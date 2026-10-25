"""Authenticated Chatto transport, conversation binding and child lifecycle."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import secrets
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from .transport_access import transport_access, PUBLIC_CAPABILITIES
from .memory import redact_sensitive


class ChattoAPI:
    def __init__(self, config, conversations, message_handler, learning_activity=None):
        self.config, self.conversations, self.message_handler = config, conversations, message_handler
        self.learning_activity = learning_activity

    def configure(self, config):
        self.config = deepcopy(config)

    def _context(self, payload, config=None):
        config = self.config if config is None else config
        if not config["enabled"]:
            raise PermissionError("Chatto is disabled")
        context = payload.get("context")
        if not isinstance(context, dict):
            raise ValueError("Chatto context is required")
        clean = {}
        for key in ("server_url", "bot_id", "owner_id", "room_id", "room_kind", "sender_id", "message_id"):
            value = context.get(key)
            if not isinstance(value, str) or not value or len(value) > 2048:
                raise ValueError("Invalid Chatto context: " + key)
            clean[key] = value
        if clean["server_url"] != config["server_url"]:
            raise PermissionError("Chatto server does not match configuration")
        clean["sender_name"] = str(context.get("sender_name") or "")[:128]
        clean["room_name"] = str(context.get("room_name") or "")[:128]
        clean["transport"] = "chatto"
        if clean["room_kind"] == "dm":
            if clean["owner_id"] != config["owner_user_id"]:
                raise PermissionError("Chatto owner does not match configuration")
            if clean["sender_id"] == clean["owner_id"]:
                if not config["owner_dm_enabled"]:
                    raise PermissionError("Owner DMs are disabled")
                clean["access_profile"] = "owner_dm"
            elif config.get("member_dm_enabled", False) and clean["sender_id"] != clean["bot_id"]:
                clean["access_profile"] = "member_dm"
            else:
                raise PermissionError("Member DMs are disabled")
        elif clean["room_kind"] == "channel" and clean["room_id"] in config["channel_ids"]:
            clean["access_profile"] = "public_channel"
        else:
            raise PermissionError("Chatto room is not enabled")
        return clean

    @staticmethod
    def _scope(context):
        # One conversation per room/profile; everyone in the channel shares its history.
        keys = ("server_url", "bot_id", "room_id", "access_profile")
        if context["access_profile"] == "member_dm":
            keys += ("sender_id",)
        return {key: context[key] for key in keys}

    def create_conversation(self, payload):
        context = self._context(payload)
        conversation = self.conversations.create(
            "Chatto · " + ((context["sender_name"] if context["room_kind"] == "dm" else context["room_name"])
                          or context["sender_name"] or context["room_id"]),
            source="chatto",
        )
        with self.conversations.database.connect() as connection:
            connection.execute("UPDATE conversations SET metadata_json=? WHERE id=?",
                               (json.dumps({"chatto_scope": self._scope(context)}), conversation["id"]))
        return {"conversation_id": conversation["id"]}

    def conversation(self, payload):
        config = self.config
        context = self._context(payload, config)
        text, identifier = payload.get("text"), payload.get("conversation_id")
        images = payload.get("images", [])
        if not isinstance(images, list) or len(images) > 4 or any(not isinstance(image, str) for image in images):
            raise ValueError("Invalid Chatto images")
        if not isinstance(text, str) or (not text.strip() and not images) or len(text) > 32000:
            raise ValueError("Invalid Chatto message")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Chatto conversation ID is required")
        self._require_bound_conversation(identifier, context)
        with transport_access(context, public=context["access_profile"] != "owner_dm",
                              allowed_capabilities=(PUBLIC_CAPABILITIES if context["access_profile"] == "member_dm"
                                                    else config["channel_capabilities"])):
            result = self.message_handler(text, images, identifier)
        return {**{key: result[key] for key in ("answer", "conversation_id", "turn_id")},
                "resources": [
                    {"type": "image", "content": resource["content"]}
                    for resource in result.get("resources", [])
                    if resource.get("type") == "image" and isinstance(resource.get("content"), str)
                    and resource["content"].startswith("data:image/")
                ]}

    def _require_bound_conversation(self, identifier, context):
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Chatto conversation ID is required")
        self.conversations.get(identifier)
        with self.conversations.database.connect() as connection:
            row = connection.execute("SELECT metadata_json FROM conversations WHERE id=?", (identifier,)).fetchone()
        metadata = json.loads(row[0] or "{}")
        if metadata.get("chatto_scope") != self._scope(context):
            raise PermissionError("Conversation belongs to another Chatto room or access profile")

    def observe(self, payload):
        config = self.config
        context = self._context(payload, config)
        if context["room_kind"] != "channel" or context["room_id"] not in config.get("channel_learning_ids", []):
            raise PermissionError("Silent channel learning is disabled")
        text, identifier = payload.get("text"), payload.get("conversation_id")
        if not isinstance(text, str) or not text.strip() or len(text) > 32000:
            raise ValueError("Invalid Chatto observation")
        self._require_bound_conversation(identifier, context)
        identity = json.dumps([context[key] for key in
                               ("server_url", "bot_id", "room_id", "message_id")])
        turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "chatto-observation:" + identity))
        message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, turn_id + ":user"))
        now = datetime.now(timezone.utc).isoformat()
        with self.conversations.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT id FROM turns WHERE id=?", (turn_id,)).fetchone()
            if not exists:
                ordinal = connection.execute(
                    "SELECT COALESCE(MAX(ordinal),-1)+1 FROM messages WHERE conversation_id=?",
                    (identifier,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO turns(id,conversation_id,created_at,completed_at) VALUES (?,?,?,?)",
                    (turn_id, identifier, now, now),
                )
                connection.execute(
                    "INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at,metadata_json,turn_id) "
                    "VALUES (?,?,'user',?,?,?,?,?)",
                    (message_id, identifier, redact_sensitive(text), ordinal, now,
                     json.dumps({"conversation_source": context, "observation_only": True}), turn_id),
                )
                connection.execute("UPDATE turns SET user_message_id=? WHERE id=?", (message_id, turn_id))
                connection.execute(
                    "INSERT INTO memory_learning_jobs(turn_id,status,accepted_at,updated_at) VALUES (?,'pending',?,?)",
                    (turn_id, now, now),
                )
                connection.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, identifier))
        if self.learning_activity and not exists:
            self.learning_activity()
        return {"conversation_id": identifier, "turn_id": turn_id, "status": "observed"}


class ChattoProcess:
    def __init__(self, root, config):
        self.root, self.config = Path(root), deepcopy(config)
        self.directory = Path(config["paths"]["runtime"]) / "chatto"
        self.process = None
        self.log = None
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_path = self.directory / "bridge-token"
        try:
            with token_path.open("x") as stream:
                stream.write(secrets.token_urlsafe(32))
            token_path.chmod(0o600)
        except FileExistsError:
            pass
        self.token = token_path.read_text().strip()
        if not self.token:
            raise ValueError("Empty Chatto bridge token")

    def start(self):
        if not self.config["chatto"]["enabled"]:
            return
        self._write_config()
        env = dict(os.environ, EVE_CHATTO_CONFIG=str(self.directory / "effective-config.json"), EVE_CHATTO_BOT_KEY=self.config["chatto"]["api_key"])
        self.log = (self.directory / "bot.log").open("a")
        try:
            self.process = subprocess.Popen(
                [self.config["chatto"]["node_executable"], str(self.root / "scripts/chatto-bot.mjs")],
                cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
            )
        except OSError:
            self.log.close()
            self.log = None
            raise

    def _write_config(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = self.directory / "effective-config.json"
        exported = {key: self.config[key] for key in ("chatto", "visual", "paths")}
        exported["chatto"] = {key: value for key, value in self.config["chatto"].items() if key != "api_key"}
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(exported))
        temporary.chmod(0o600)
        temporary.replace(config_path)

    def configure(self, effective):
        previous = self.config["chatto"]
        current = deepcopy(effective["chatto"])
        if current == previous:
            return
        reconnect = any(current[key] != previous[key] for key in (
            "enabled", "server_url", "api_key", "node_executable", "owner_user_id", "presence_enabled",
        ))
        if reconnect:
            self.close()
        self.config = {**self.config, "chatto": current}
        self._write_config()
        if reconnect:
            self.start()

    def status(self):
        if not self.config["chatto"]["enabled"]:
            return {"state": "disabled"}
        if not self.process or self.process.poll() is not None:
            return {"state": "stopped"}
        try:
            return json.loads((self.directory / "status.json").read_text())
        except (OSError, ValueError):
            return {"state": "starting"}

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self.log:
            self.log.close()
            self.log = None
