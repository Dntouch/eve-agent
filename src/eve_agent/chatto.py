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
import threading

from .transport_access import transport_access, PUBLIC_CAPABILITIES, update_transport_metadata, transport_metadata
from .memory import redact_sensitive


class ChattoAPI:
    def __init__(self, config, conversations, message_handler, learning_activity=None):
        self.config, self.conversations, self.message_handler = config, conversations, message_handler
        self.learning_activity = learning_activity
        self.scheduler = None
        self.output_rooms = []
        self.activities = {}
        self.activity_lock = threading.RLock()

    def output_targets(self):
        context = transport_metadata()
        # Public callers can address only their verified current room/thread.
        if context and context.get("access_profile") != "owner_dm":
            return []
        with self.conversations.database.connect() as connection:
            local_rows = connection.execute("SELECT id,title FROM conversations WHERE source!='chatto' AND status!='deleted'").fetchall()
        local_targets = [{"id": "eve:conversation:" + row["id"], "name": "EVE · " + row["title"],
                          "transport": "eve", "conversation_id": row["id"]} for row in local_rows]
        if not self.config.get("enabled"):
            return local_targets
        targets = local_targets + [{"id": "chatto:room:" + room["id"], "name": "Chatto · " + room["name"],
                    "transport": "chatto", "server_url": self.config["server_url"],
                    "room_id": room["id"], "room_kind": "channel"}
                   for room in self.output_rooms if room["id"] in self.config["channel_ids"]]
        with self.conversations.database.connect() as connection:
            rows = connection.execute("SELECT id,title,metadata_json FROM conversations WHERE source='chatto' AND status!='deleted'").fetchall()
        for row in rows:
            scope = json.loads(row["metadata_json"] or "{}").get("chatto_scope", {})
            if scope.get("server_url") != self.config["server_url"]:
                continue
            if scope.get("access_profile") == "public_channel" and scope.get("room_id") not in self.config["channel_ids"]:
                continue
            if scope.get("access_profile") == "owner_dm" and not self.config.get("owner_dm_enabled"):
                continue
            if scope.get("access_profile") == "member_dm" and not self.config.get("member_dm_enabled"):
                continue
            targets.append({**scope, "id": "chatto:conversation:" + row["id"], "name": row["title"],
                            "transport": "chatto", "conversation_id": row["id"]})
        return targets

    def deliveries(self, payload):
        if self.scheduler is None:
            return {"deliveries": []}
        return {"deliveries": self.scheduler.claim_deliveries()}

    def delivery_ack(self, payload):
        self.scheduler.acknowledge_delivery(payload["id"], payload["status"], payload.get("error"))
        return {"ok": True}

    def register_output_rooms(self, payload):
        rooms = payload.get("rooms")
        if not isinstance(rooms, list) or len(rooms) > 10000:
            raise ValueError("Invalid rooms")
        self.output_rooms = [{"id": room["id"], "name": room["name"]} for room in rooms
                             if isinstance(room.get("id"), str) and isinstance(room.get("name"), str)]
        return {"ok": True}

    def scheduled_access(self, context):
        clean = self._context({"context": context})
        if context.get("mcp_session_id"):
            clean["mcp_session_id"] = context["mcp_session_id"]
        allowed = (PUBLIC_CAPABILITIES if clean["access_profile"] == "member_dm"
                   else self.config["channel_capabilities"])
        return transport_access(clean, public=clean["access_profile"] != "owner_dm", allowed_capabilities=allowed)

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
        thread_root = context.get("thread_root_id", "")
        if not isinstance(thread_root, str) or len(thread_root) > 2048:
            raise ValueError("Invalid Chatto thread root")
        if thread_root:
            clean["thread_root_id"] = thread_root
            clean["project_reference"] = self._project_reference(clean)
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
    def _project_reference(context):
        identity = json.dumps([context[key] for key in
                              ("server_url", "bot_id", "room_id", "thread_root_id")])
        return "EVE-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "chatto-project:" + identity))

    @staticmethod
    def _scope(context):
        # One conversation per room/profile; everyone in the channel shares its history.
        keys = ("server_url", "bot_id", "room_id", "access_profile")
        if context["access_profile"] == "member_dm":
            keys += ("sender_id",)
        scope = {key: context[key] for key in keys}
        if context.get("thread_root_id"):
            scope["thread_root_id"] = context["thread_root_id"]
        return scope

    def create_conversation(self, payload):
        context = self._context(payload)
        if context.get("thread_root_id"):
            with self.conversations.database.connect() as connection:
                rows = connection.execute("SELECT id,metadata_json FROM conversations WHERE source='chatto' AND status!='deleted' "
                    "AND json_extract(metadata_json,'$.chatto_scope.thread_root_id')=?", (context["thread_root_id"],)).fetchall()
            for row in rows:
                if json.loads(row["metadata_json"] or "{}").get("chatto_scope") == self._scope(context):
                    return {"conversation_id": row["id"], "project_reference": context["project_reference"]}
        conversation = self.conversations.create(
            "Chatto · " + ((context.get("project_reference")) or (context["sender_name"] if context["room_kind"] == "dm" else context["room_name"])
                          or context["sender_name"] or context["room_id"]),
            source="chatto",
        )
        with self.conversations.database.connect() as connection:
            connection.execute("UPDATE conversations SET metadata_json=? WHERE id=?",
                               (json.dumps({"chatto_scope": self._scope(context)}), conversation["id"]))
        return {"conversation_id": conversation["id"],
                **({"project_reference": context["project_reference"]} if context.get("project_reference") else {})}

    def activity(self, payload):
        context = self._context(payload)
        self._require_bound_conversation(payload.get("conversation_id"), context)
        key = (payload["conversation_id"], context["message_id"])
        with self.activity_lock:
            return deepcopy(self.activities.get(key, {"state": "unknown"}))

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
        original_thread = context.get("thread_root_id")
        with self.conversations.database.connect() as connection:
            metadata = json.loads(connection.execute("SELECT metadata_json FROM conversations WHERE id=?", (identifier,)).fetchone()[0] or "{}")
        if metadata.get("mcp_session_id"):
            context["mcp_session_id"] = metadata["mcp_session_id"]
        activity_key = (identifier, context["message_id"])
        progress = {"state": "working", "thread_root_id": original_thread or ""}
        with self.activity_lock:
            if len(self.activities) >= 256:
                completed = next((key for key, item in self.activities.items() if item["state"] != "working"), None)
                if completed is not None:
                    self.activities.pop(completed)
            self.activities[activity_key] = progress
        branch_identifier = None
        def activity(event):
            nonlocal branch_identifier
            if event.get("reply_mode") == "thread" and not context.get("thread_root_id"):
                context["thread_root_id"] = context["message_id"]
                context["project_reference"] = self._project_reference(context)
                context["mcp_session_id"] = context["project_reference"]
                update_transport_metadata({key: context[key] for key in
                                           ("thread_root_id", "project_reference", "mcp_session_id")})
            if not original_thread and context.get("thread_root_id") and branch_identifier is None:
                branch_identifier = self.create_conversation({"context": context})["conversation_id"]
                with self.conversations.database.connect() as connection:
                    branch_metadata = {"chatto_scope": self._scope(context), "mcp_session_id": context["mcp_session_id"],
                                       "origin_conversation_id": identifier, "origin_message_id": context["message_id"]}
                    connection.execute("UPDATE conversations SET metadata_json=? WHERE id=?",
                                       (json.dumps(branch_metadata), branch_identifier))
            with self.activity_lock:
                progress.update({"integration": event.get("integration", ""),
                                 "thread_root_id": context.get("thread_root_id", "")})
        try:
            with transport_access(context, public=context["access_profile"] != "owner_dm", activity=activity,
                                  allowed_capabilities=(PUBLIC_CAPABILITIES if context["access_profile"] == "member_dm"
                                                        else config["channel_capabilities"])):
                result = self.message_handler(text, images, identifier)
        except BaseException:
            with self.activity_lock:
                progress["state"] = "failed"
            raise
        response_identifier = identifier
        if not original_thread and context.get("thread_root_id"):
            response_identifier = branch_identifier
            with self.conversations.database.connect() as connection:
                metadata = {"chatto_scope": self._scope(context), "mcp_session_id": context["mcp_session_id"],
                            "origin_conversation_id": identifier, "origin_turn_id": result.get("turn_id")}
                connection.execute("UPDATE conversations SET metadata_json=? WHERE id=?",
                                   (json.dumps(metadata), response_identifier))
            _, copied_answer = self.conversations.append_turn(response_identifier, text, result["answer"],
                user_metadata={"conversation_source": context, "context_copy": True, "origin_turn_id": result.get("turn_id")},
                assistant_metadata={"context_copy": True, "origin_turn_id": result.get("turn_id")},
                user_attachments=[{"type":"image", "content": image} for image in images],
                assistant_attachments=[r for r in result.get("resources", []) if r.get("type") == "image"])
            artifacts = list(result.get("artifacts", []))
            for resource in result.get("resources", []):
                if resource.get("type") == "file" and isinstance(resource.get("content"), str):
                    header, separator, encoded = resource["content"].partition(";base64,")
                    if separator and header.startswith("data:"):
                        artifacts.append({"filename": resource.get("filename") or "eve-download.bin",
                                          "mime": header[5:], "base64": encoded})
            if artifacts:
                self.conversations.store_artifacts(response_identifier, copied_answer["id"], artifacts)
        with self.activity_lock:
            progress["state"] = "completed"
        answer = result["answer"]
        if context.get("thread_root_id") == context["message_id"]:
            answer = f"Auftrag: {context['project_reference']}\n\n{answer}"
        return {**{key: result[key] for key in ("conversation_id", "turn_id")}, "conversation_id": response_identifier, "answer": answer,
                "thread_root_id": context.get("thread_root_id", ""),
                **({"project_reference": context["project_reference"]} if context.get("project_reference") else {}),
                "resources": [
                    {key: resource[key] for key in ("type", "content", "filename", "media_type") if key in resource}
                    for resource in result.get("resources", [])
                    if resource.get("type") in {"image", "file"} and isinstance(resource.get("content"), str)
                    and (resource["content"].startswith("data:image/") if resource.get("type") == "image" else resource["content"].startswith("data:"))
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
