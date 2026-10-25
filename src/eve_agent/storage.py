from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .memory import redact_sensitive


SCHEMA_VERSION = 23
_SECRET_JSON_KEY = re.compile(r"^(?:token|access_token|api[_-]?key|authorization|password|secret)$", re.I)
_MEMORY_V2_IMPORT_NAMESPACE = uuid.UUID("8233c6ee-7d27-4ed6-b88f-e16706f33bfd")
_RUNTIME_SELF_KNOWLEDGE_WRITER = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value, *, key: str = ""):
    """Redact strings in structured diagnostic data without changing its shape."""
    if _SECRET_JSON_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _safe_json(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_sensitive(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive(str(value))


def _memory_v2_import_id(record_type: str, legacy_memory_id: str) -> str:
    """Return a stable ID so the legacy import never depends on random UUIDs."""
    return str(uuid.uuid5(_MEMORY_V2_IMPORT_NAMESPACE, f"{record_type}:{legacy_memory_id}"))


def _safe_legacy_metadata(raw: str) -> tuple[str, bool, dict]:
    """Redact structured legacy metadata while retaining invalid JSON opaquely."""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        cleaned = redact_sensitive(str(raw or ""))
        return json.dumps({"opaque_legacy_json": cleaned}, ensure_ascii=False), cleaned != str(raw or ""), {}
    safe = _safe_json(parsed)
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    original = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    redacted = encoded != original
    # Preserve the original JSON representation when no security redaction was
    # required.  This keeps whitespace/order as part of the legacy artifact.
    preserved = encoded if redacted else str(raw or "{}")
    return preserved, redacted, safe if isinstance(safe, dict) else {}


class EveDatabase:
    """Versioned local persistence shared by conversations, memory and tasks."""

    def __init__(self, path: Path, *, lifecycle_audit: bool = True,
                 lifecycle_max_detail_bytes: int = 4096):
        self.path = path
        self.lifecycle_audit_enabled = bool(lifecycle_audit)
        self.lifecycle_max_detail_bytes = int(lifecycle_max_detail_bytes)
        self._lifecycle_audit_ready = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._initialize()
        self._lifecycle_audit_ready = True

    @contextmanager
    def connect(self, *, lifecycle_audit: bool = True) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            audit = (
                self._lifecycle_audit_ready and self.lifecycle_audit_enabled and lifecycle_audit
            )
            if audit:
                from .memory_lifecycle import install_connection_audit
                install_connection_audit(connection)
                # Installing connection-local TEMP objects must not leave an
                # implicit transaction open before callers use BEGIN IMMEDIATE.
                connection.commit()
            yield connection
            if audit:
                from .memory_lifecycle import MemoryLifecycleWriter
                MemoryLifecycleWriter(
                    self, max_detail_bytes=self.lifecycle_max_detail_bytes,
                ).flush(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"EVE-Datenbankversion {version} ist neuer als die unterstützte Version {SCHEMA_VERSION}"
            )
        if version == 0:
            with self.connect() as connection:
                self._create_v1(connection)
                self._migrate_v1_to_v2(connection)
                self._migrate_v2_to_v3(connection)
                self._migrate_v3_to_v4(connection)
                self._migrate_v4_to_v5(connection)
                self._migrate_v5_to_v6(connection)
                self._migrate_v6_to_v7(connection)
                self._migrate_v7_to_v8(connection)
                self._migrate_v8_to_v9(connection)
                self._migrate_v9_to_v10(connection)
                self._migrate_v10_to_v11(connection)
                self._migrate_v11_to_v12(connection)
                self._migrate_v12_to_v13(connection)
                self._migrate_v13_to_v14(connection)
                self._migrate_v14_to_v15(connection)
                self._migrate_v15_to_v16(connection)
                self._migrate_v16_to_v17(connection)
                self._migrate_v17_to_v18(connection)
                self._migrate_v18_to_v19(connection)
                self._migrate_v19_to_v20(connection)
                self._migrate_v20_to_v21(connection)
                self._migrate_v21_to_v22(connection)
                self._migrate_v22_to_v23(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version < SCHEMA_VERSION:
            self._backup_before_migration(version, SCHEMA_VERSION)
        while version < SCHEMA_VERSION:
            migration = self._migrations().get(version)
            if migration is None:
                raise RuntimeError(f"Keine Datenbankmigration für Schema-Version {version} vorhanden")
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                migration(connection)
                connection.execute(f"PRAGMA user_version = {version + 1}")
            version += 1
        with self.connect() as connection:
            for name in (
                "protect_runtime_claim_insert", "protect_runtime_claim_update", "protect_runtime_claim_delete",
                "protect_runtime_evidence_insert", "protect_runtime_evidence_update",
                "protect_runtime_evidence_delete", "protect_runtime_relation_insert",
                "protect_runtime_relation_update", "protect_runtime_relation_delete",
            ):
                connection.execute(f"DROP TRIGGER IF EXISTS {name}")
        self._protect_files()

    @staticmethod
    def assert_runtime_self_knowledge_writable(
        connection: sqlite3.Connection, *, claim_ids=(), proposed_claim=None, writer=None,
    ) -> None:
        """Reject non-runtime writers before they mutate runtime-owned memory."""
        if writer is _RUNTIME_SELF_KNOWLEDGE_WRITER:
            return
        proposed_claim = proposed_claim or {}
        payload = proposed_claim.get("payload") or {}
        if (
            proposed_claim.get("scope") == "provider:runtime"
            and payload.get("runtime_self_knowledge") is True
        ):
            raise PermissionError("runtime self-knowledge is runtime-sync owned")
        ids = tuple(dict.fromkeys(str(item) for item in claim_ids if item))
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        owned = connection.execute(
            f"""SELECT id FROM memory_claims WHERE id IN ({placeholders})
                AND scope='provider:runtime'
                AND json_extract(payload_json,'$.runtime_self_knowledge')=1 LIMIT 1""",
            ids,
        ).fetchone()
        if owned:
            raise PermissionError("runtime self-knowledge is runtime-sync owned")

    def _backup_before_migration(self, source_version: int, target_version: int) -> Path:
        """Create a consistent SQLite backup, including committed WAL content."""
        backup_root = self.path.parent / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(backup_root, 0o700)
        except OSError:
            pass
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = backup_root / (
            f"{self.path.stem}-schema-v{source_version}-to-v{target_version}-{stamp}-{uuid.uuid4().hex[:8]}.db"
        )
        source = sqlite3.connect(self.path, timeout=5)
        target = sqlite3.connect(destination)
        try:
            source.execute("PRAGMA busy_timeout = 5000")
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
        return destination

    @classmethod
    def _migrations(cls):
        return {
            1: cls._migrate_v1_to_v2, 2: cls._migrate_v2_to_v3,
            3: cls._migrate_v3_to_v4, 4: cls._migrate_v4_to_v5,
            5: cls._migrate_v5_to_v6, 6: cls._migrate_v6_to_v7,
            7: cls._migrate_v7_to_v8, 8: cls._migrate_v8_to_v9,
            9: cls._migrate_v9_to_v10,
            10: cls._migrate_v10_to_v11,
            11: cls._migrate_v11_to_v12,
            12: cls._migrate_v12_to_v13,
            13: cls._migrate_v13_to_v14,
            14: cls._migrate_v14_to_v15,
            15: cls._migrate_v15_to_v16,
            16: cls._migrate_v16_to_v17,
            17: cls._migrate_v17_to_v18,
            18: cls._migrate_v18_to_v19,
            19: cls._migrate_v19_to_v20,
            20: cls._migrate_v20_to_v21,
            21: cls._migrate_v21_to_v22,
            22: cls._migrate_v22_to_v23,
        }

    @staticmethod
    def _create_v1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'deleted')),
                source TEXT NOT NULL DEFAULT 'eve',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'text',
                ordinal INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (conversation_id, ordinal)
            );
            CREATE INDEX messages_conversation_created
                ON messages(conversation_id, ordinal);

            CREATE TABLE memory_items (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('candidate', 'active', 'superseded', 'deleted')),
                confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
                source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
                source_ref TEXT,
                valid_from TEXT,
                valid_until TEXT,
                embedding BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX memory_items_active_category
                ON memory_items(status, category);

            CREATE TABLE scheduled_tasks (
                id TEXT PRIMARY KEY,
                conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('draft', 'active', 'paused', 'completed', 'failed', 'deleted')),
                schedule_type TEXT NOT NULL,
                schedule_json TEXT NOT NULL,
                action_json TEXT NOT NULL,
                next_run_at TEXT,
                timezone TEXT NOT NULL DEFAULT 'local',
                risk_level TEXT NOT NULL DEFAULT 'low'
                    CHECK (risk_level IN ('low', 'normal', 'elevated', 'high', 'forbidden')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX scheduled_tasks_due
                ON scheduled_tasks(status, next_run_at);

            CREATE TABLE task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                status TEXT NOT NULL
                    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')),
                scheduled_for TEXT,
                started_at TEXT,
                finished_at TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                result_json TEXT,
                error_text TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE approvals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                task_id TEXT REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                action_json TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
                requested_at TEXT NOT NULL,
                decided_at TEXT,
                expires_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                task_id TEXT REFERENCES scheduled_tasks(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX audit_events_created ON audit_events(created_at);

            """
        )

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        statements = (
            """CREATE TABLE work_task_lists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'deleted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE work_items (
                id TEXT PRIMARY KEY,
                list_id TEXT NOT NULL REFERENCES work_task_lists(id) ON DELETE RESTRICT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'completed', 'deleted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )""",
            "CREATE INDEX work_items_list_status ON work_items(list_id, status, updated_at)",
            """CREATE TABLE work_item_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                changes_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX work_item_events_item_created ON work_item_events(work_item_id, created_at)",
            """CREATE VIRTUAL TABLE conversation_messages_fts USING fts5(
                message_id UNINDEXED, conversation_id UNINDEXED, role UNINDEXED,
                created_at UNINDEXED, content, tokenize='unicode61 remove_diacritics 2'
            )""",
            """CREATE VIRTUAL TABLE memory_items_fts USING fts5(
                memory_id UNINDEXED, category UNINDEXED, content,
                tokenize='unicode61 remove_diacritics 2'
            )""",
            """CREATE VIRTUAL TABLE work_items_fts USING fts5(
                work_item_id UNINDEXED, list_id UNINDEXED, title, description,
                tokenize='unicode61 remove_diacritics 2'
            )""",
            """CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
                INSERT INTO conversation_messages_fts(message_id, conversation_id, role, created_at, content)
                VALUES (new.id, new.conversation_id, new.role, new.created_at, new.content);
            END""",
            """CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages BEGIN
                DELETE FROM conversation_messages_fts WHERE message_id=old.id;
                INSERT INTO conversation_messages_fts(message_id, conversation_id, role, created_at, content)
                VALUES (new.id, new.conversation_id, new.role, new.created_at, new.content);
            END""",
            """CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
                DELETE FROM conversation_messages_fts WHERE message_id=old.id;
            END""",
            """CREATE TRIGGER memory_fts_insert AFTER INSERT ON memory_items BEGIN
                INSERT INTO memory_items_fts(memory_id, category, content)
                VALUES (new.id, new.category, new.content);
            END""",
            """CREATE TRIGGER memory_fts_update AFTER UPDATE ON memory_items BEGIN
                DELETE FROM memory_items_fts WHERE memory_id=old.id;
                INSERT INTO memory_items_fts(memory_id, category, content)
                VALUES (new.id, new.category, new.content);
            END""",
            """CREATE TRIGGER memory_fts_delete AFTER DELETE ON memory_items BEGIN
                DELETE FROM memory_items_fts WHERE memory_id=old.id;
            END""",
            """CREATE TRIGGER work_items_fts_insert AFTER INSERT ON work_items BEGIN
                INSERT INTO work_items_fts(work_item_id, list_id, title, description)
                VALUES (new.id, new.list_id, new.title, coalesce(new.description, ''));
            END""",
            """CREATE TRIGGER work_items_fts_update AFTER UPDATE ON work_items BEGIN
                DELETE FROM work_items_fts WHERE work_item_id=old.id;
                INSERT INTO work_items_fts(work_item_id, list_id, title, description)
                VALUES (new.id, new.list_id, new.title, coalesce(new.description, ''));
            END""",
            """CREATE TRIGGER work_items_fts_delete AFTER DELETE ON work_items BEGIN
                DELETE FROM work_items_fts WHERE work_item_id=old.id;
            END""",
            """INSERT INTO conversation_messages_fts(message_id, conversation_id, role, created_at, content)
                SELECT id, conversation_id, role, created_at, content FROM messages""",
            """INSERT INTO memory_items_fts(memory_id, category, content)
                SELECT id, category, content FROM memory_items""",
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE work_items ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """WITH ranked AS (
                   SELECT id, row_number() OVER (
                       PARTITION BY list_id, status ORDER BY updated_at DESC, id
                   ) - 1 AS ordinal
                   FROM work_items WHERE status!='deleted'
               )
               UPDATE work_items SET position=(
                   SELECT ordinal FROM ranked WHERE ranked.id=work_items.id
               ) WHERE id IN (SELECT id FROM ranked)"""
        )
        connection.execute(
            "CREATE INDEX work_items_list_status_position ON work_items(list_id, status, position, id)"
        )

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE conversation_assets (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                media_type TEXT NOT NULL,
                filename TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(message_id, ordinal)
            );
            CREATE INDEX conversation_assets_conversation
                ON conversation_assets(conversation_id, message_id, ordinal);

            CREATE TABLE conversation_tool_events (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                tool TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(message_id, ordinal)
            );
            CREATE INDEX conversation_tool_events_conversation
                ON conversation_tool_events(conversation_id, message_id, ordinal);
            """
        )

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE visual_asset_index (
                asset_id TEXT PRIMARY KEY REFERENCES conversation_assets(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                embedding BLOB,
                created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE visual_asset_index_fts USING fts5(
                asset_id UNINDEXED, description, content='visual_asset_index', content_rowid='rowid'
            );
            CREATE TRIGGER visual_asset_fts_insert AFTER INSERT ON visual_asset_index BEGIN
                INSERT INTO visual_asset_index_fts(rowid, asset_id, description)
                VALUES (new.rowid, new.asset_id, new.description);
            END;
            CREATE TRIGGER visual_asset_fts_delete AFTER DELETE ON visual_asset_index BEGIN
                INSERT INTO visual_asset_index_fts(visual_asset_index_fts, rowid, asset_id, description)
                VALUES ('delete', old.rowid, old.asset_id, old.description);
            END;
            CREATE TRIGGER visual_asset_fts_update AFTER UPDATE ON visual_asset_index BEGIN
                INSERT INTO visual_asset_index_fts(visual_asset_index_fts, rowid, asset_id, description)
                VALUES ('delete', old.rowid, old.asset_id, old.description);
                INSERT INTO visual_asset_index_fts(rowid, asset_id, description)
                VALUES (new.rowid, new.asset_id, new.description);
            END;
            INSERT INTO visual_asset_index(asset_id, description, source, embedding, created_at)
            SELECT a.id,
                   'Quelle: ' || CASE WHEN m.role='user' THEN 'user' ELSE 'assistant' END ||
                   ' | Conversation: ' || c.title || ' | Zeitpunkt: ' || a.created_at ||
                   ' | Nachrichtenkontext: ' || m.content ||
                   CASE WHEN m.role='user' THEN COALESCE(
                       ' | Antwort-/Vision-Kontext: ' || (
                           SELECT following.content FROM messages following
                           WHERE following.conversation_id=m.conversation_id
                             AND following.ordinal=m.ordinal+1 AND following.role='assistant'
                       ), '') ELSE '' END,
                   CASE WHEN m.role='user' THEN 'user'
                        ELSE COALESCE(json_extract(m.metadata_json, '$.route'), 'assistant') END,
                   NULL, a.created_at
            FROM conversation_assets a
            JOIN messages m ON m.id=a.message_id
            JOIN conversations c ON c.id=a.conversation_id
            WHERE a.media_type LIKE 'image/%' AND c.status!='deleted';
            """
        )

    @staticmethod
    def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE turns (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_message_id TEXT UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
                assistant_message_id TEXT UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
                knowledge_flow_json TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE INDEX turns_conversation_created
                ON turns(conversation_id, created_at, id);

            ALTER TABLE messages ADD COLUMN turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL;
            CREATE INDEX messages_turn_id ON messages(turn_id);

            CREATE TABLE turn_memory_retrievals (
                turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                memory_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                method TEXT NOT NULL,
                score REAL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (turn_id, memory_id)
            );
            CREATE INDEX turn_memory_retrievals_memory
                ON turn_memory_retrievals(memory_id, retrieved_at, turn_id);
            """
        )

    @staticmethod
    def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
        connection.execute("DROP TABLE IF EXISTS legacy_imports")

    @staticmethod
    def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
        """Remove data imported from the retired Markdown memory stores."""
        connection.execute(
            """DELETE FROM memory_items
               WHERE json_extract(metadata_json, '$.legacy_source') IN
                     ('memory/facts.md', 'memory/home-assistant.md')"""
        )

    @staticmethod
    def _migrate_v8_to_v9(connection: sqlite3.Connection) -> None:
        """Create the inactive Memory-v2 foundation and import legacy rows."""
        statements = (
            """CREATE TABLE memory_claims (
                id TEXT PRIMARY KEY,
                claim_kind TEXT NOT NULL
                    CHECK (claim_kind IN ('opaque_fact', 'provider_binding', 'alias')),
                scope TEXT NOT NULL CHECK (length(trim(scope)) > 0),
                canonical_key TEXT NOT NULL CHECK (length(trim(canonical_key)) > 0),
                slot_key TEXT,
                display_text TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
                lifecycle TEXT NOT NULL
                    CHECK (lifecycle IN ('candidate', 'active', 'retired', 'invalid')),
                valid_from TEXT,
                valid_until TEXT,
                verification_policy TEXT NOT NULL
                    CHECK (verification_policy IN ('stable', 'configuration', 'dynamic', 'unknown')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (scope, claim_kind, canonical_key)
            )""",
            "CREATE INDEX memory_claims_lifecycle_kind ON memory_claims(lifecycle, claim_kind)",
            "CREATE INDEX memory_claims_scope_slot ON memory_claims(scope, slot_key)",
            """CREATE TABLE memory_observations (
                id TEXT PRIMARY KEY,
                source_role TEXT NOT NULL
                    CHECK (source_role IN ('user','assistant','system','tool','provider','external','legacy','unknown')),
                source_type TEXT NOT NULL
                    CHECK (source_type IN ('user_message','turn','tool_event','provider_result','external','legacy_import')),
                message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
                turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
                tool_event_id TEXT REFERENCES conversation_tool_events(id) ON DELETE SET NULL,
                external_ref TEXT,
                excerpt TEXT,
                structured_value_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(structured_value_json)),
                observed_at TEXT NOT NULL,
                scope TEXT NOT NULL CHECK (length(trim(scope)) > 0),
                metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX memory_observations_message ON memory_observations(message_id)",
            "CREATE INDEX memory_observations_turn ON memory_observations(turn_id)",
            "CREATE INDEX memory_observations_tool ON memory_observations(tool_event_id)",
            """CREATE TABLE memory_evidence (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                observation_id TEXT REFERENCES memory_observations(id) ON DELETE RESTRICT,
                stance TEXT NOT NULL CHECK (stance IN ('supports', 'contradicts')),
                evidence_type TEXT NOT NULL CHECK (length(trim(evidence_type)) > 0),
                source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
                source_turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
                tool_event_id TEXT REFERENCES conversation_tool_events(id) ON DELETE SET NULL,
                source_ref TEXT,
                excerpt TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
                observed_at TEXT NOT NULL,
                effective_from TEXT,
                effective_until TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (claim_id, observation_id, evidence_type)
            )""",
            "CREATE INDEX memory_evidence_claim_created ON memory_evidence(claim_id, created_at)",
            "CREATE INDEX memory_evidence_observation ON memory_evidence(observation_id)",
            """CREATE TABLE memory_relations (
                id TEXT PRIMARY KEY,
                from_claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                to_claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL
                    CHECK (relation_type IN ('supersedes', 'contradicts', 'refines')),
                evidence_id TEXT REFERENCES memory_evidence(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                CHECK (from_claim_id <> to_claim_id),
                UNIQUE (from_claim_id, to_claim_id, relation_type)
            )""",
            "CREATE INDEX memory_relations_to_claim ON memory_relations(to_claim_id, relation_type)",
            """CREATE TABLE memory_learning_decisions (
                id TEXT PRIMARY KEY,
                observation_id TEXT REFERENCES memory_observations(id) ON DELETE RESTRICT,
                decision_type TEXT NOT NULL CHECK (decision_type IN (
                    'legacy_import','no_persist','create_candidate','create_active',
                    'append_supporting_evidence','append_contradicting_evidence',
                    'create_competing_claim','supersede_claim','refine_claim'
                )),
                method TEXT NOT NULL CHECK (length(trim(method)) > 0),
                policy_version TEXT,
                model_version TEXT,
                rationale TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
                uncertainty REAL CHECK (uncertainty IS NULL OR (uncertainty >= 0 AND uncertainty <= 1)),
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX memory_learning_decisions_observation ON memory_learning_decisions(observation_id)",
            """CREATE TABLE memory_learning_decision_claims (
                decision_id TEXT NOT NULL REFERENCES memory_learning_decisions(id) ON DELETE CASCADE,
                claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                PRIMARY KEY (decision_id, claim_id)
            )""",
            """CREATE TABLE memory_legacy_mappings (
                legacy_memory_id TEXT PRIMARY KEY REFERENCES memory_items(id) ON DELETE RESTRICT,
                claim_id TEXT NOT NULL UNIQUE REFERENCES memory_claims(id) ON DELETE CASCADE,
                observation_id TEXT NOT NULL UNIQUE REFERENCES memory_observations(id) ON DELETE RESTRICT,
                evidence_id TEXT NOT NULL UNIQUE REFERENCES memory_evidence(id) ON DELETE CASCADE,
                decision_id TEXT NOT NULL UNIQUE REFERENCES memory_learning_decisions(id) ON DELETE CASCADE,
                legacy_category TEXT NOT NULL,
                legacy_status TEXT NOT NULL,
                legacy_confidence REAL NOT NULL,
                legacy_source_message_id TEXT,
                legacy_source_ref TEXT,
                legacy_valid_from TEXT,
                legacy_valid_until TEXT,
                legacy_created_at TEXT NOT NULL,
                legacy_updated_at TEXT NOT NULL,
                legacy_metadata_json TEXT NOT NULL CHECK (json_valid(legacy_metadata_json)),
                legacy_embedding BLOB,
                redaction_applied INTEGER NOT NULL DEFAULT 0 CHECK (redaction_applied IN (0,1)),
                imported_at TEXT NOT NULL
            )""",
            "CREATE INDEX memory_legacy_mappings_claim ON memory_legacy_mappings(claim_id)",
        )
        for statement in statements:
            # The schema version normally prevents a second execution.  IF NOT
            # EXISTS additionally keeps recovery/idempotency checks harmless
            # when the structures already exist but user_version was restored.
            if statement.startswith("CREATE TABLE "):
                statement = statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
            elif statement.startswith("CREATE INDEX "):
                statement = statement.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
            connection.execute(statement)
        EveDatabase._import_legacy_memory_v2(connection)

    @staticmethod
    def _import_legacy_memory_v2(connection: sqlite3.Connection) -> None:
        """Losslessly map each legacy row without semantic inference or dual-write."""
        lifecycle_map = {
            "active": "active", "candidate": "candidate",
            "superseded": "retired", "deleted": "retired",
        }
        imported_at = _now()
        rows = connection.execute("SELECT * FROM memory_items ORDER BY created_at, id").fetchall()
        for row in rows:
            legacy_id = str(row["id"])
            if connection.execute(
                "SELECT 1 FROM memory_legacy_mappings WHERE legacy_memory_id=?", (legacy_id,)
            ).fetchone():
                continue
            claim_id = _memory_v2_import_id("claim", legacy_id)
            observation_id = _memory_v2_import_id("observation", legacy_id)
            evidence_id = _memory_v2_import_id("evidence", legacy_id)
            decision_id = _memory_v2_import_id("decision", legacy_id)
            safe_metadata_json, metadata_redacted, metadata = _safe_legacy_metadata(row["metadata_json"])
            original_content = str(row["content"])
            display_text = redact_sensitive(original_content)
            source_ref = redact_sensitive(str(row["source_ref"])) if row["source_ref"] is not None else None
            content_redacted = display_text != original_content
            source_redacted = source_ref != row["source_ref"]
            category = str(row["category"])
            structured_binding = (
                category == "provider_binding"
                and all(isinstance(metadata.get(key), str) and metadata[key].strip()
                        for key in ("provider", "subject", "property", "entity_id"))
            )
            if structured_binding:
                claim_kind = "provider_binding"
                verification_policy = "configuration"
                slot_key = "provider_binding:" + ":".join(
                    str(metadata[key]).strip().casefold()
                    for key in ("provider", "subject", "property")
                )
                payload = {
                    "provider": metadata["provider"], "subject": metadata["subject"],
                    "property": metadata["property"], "external_reference": metadata["entity_id"],
                    "scope": None,
                }
            elif category == "device_alias":
                claim_kind, verification_policy, slot_key = "alias", "configuration", None
                payload = {"opaque_legacy_category": category}
            else:
                claim_kind, verification_policy, slot_key = "opaque_fact", "unknown", None
                payload = {"opaque_legacy_category": category}
            payload["legacy_memory_id"] = legacy_id
            payload["legacy_memory_key"] = metadata.get("memory_key")
            scope = "legacy:unknown"
            source_message_id = row["source_message_id"]
            observation_value = {
                "legacy_memory_id": legacy_id,
                "content_location": "memory_claims.display_text",
                "source_message_semantics": "historical_creation_context_only",
            }
            evidence_payload = {
                "meaning": "imported_from_existing_memory_row_only",
                "not_verification": True,
                "legacy_confidence": row["confidence"],
            }
            decision_metadata = {
                "meaning": "lossless_schema_migration_only",
                "capture_policy_replayed": False,
            }
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                    valid_from,valid_until,verification_policy,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (claim_id, claim_kind, scope, f"legacy:{legacy_id}", slot_key, display_text,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), lifecycle_map[str(row["status"])],
                 row["valid_from"], row["valid_until"], verification_policy,
                 row["created_at"], row["updated_at"]),
            )
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,message_id,external_ref,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'legacy','legacy_import',?,?,?,?,?,?,?)""",
                (observation_id, source_message_id, source_ref,
                 json.dumps(observation_value, ensure_ascii=False, sort_keys=True),
                 row["created_at"], scope,
                 json.dumps({"legacy_category": category}, ensure_ascii=False, sort_keys=True), imported_at),
            )
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_message_id,source_ref,
                    payload_json,observed_at,effective_from,effective_until,created_at)
                   VALUES (?,?,?,'supports','legacy_import',?,?,?,?,?,?,?)""",
                (evidence_id, claim_id, observation_id, source_message_id, source_ref,
                 json.dumps(evidence_payload, ensure_ascii=False, sort_keys=True), row["created_at"],
                 row["valid_from"], row["valid_until"], imported_at),
            )
            connection.execute(
                """INSERT INTO memory_learning_decisions
                   (id,observation_id,decision_type,method,rationale,metadata_json,created_at)
                   VALUES (?,?,'legacy_import','schema_migration',?,?,?)""",
                (decision_id, observation_id,
                 "Bestehenden Legacy-Datensatz ohne neue fachliche Bewertung abgebildet.",
                 json.dumps(decision_metadata, ensure_ascii=False, sort_keys=True), imported_at),
            )
            connection.execute(
                "INSERT INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)",
                (decision_id, claim_id),
            )
            connection.execute(
                """INSERT INTO memory_legacy_mappings
                   (legacy_memory_id,claim_id,observation_id,evidence_id,decision_id,
                    legacy_category,legacy_status,legacy_confidence,legacy_source_message_id,
                    legacy_source_ref,legacy_valid_from,legacy_valid_until,legacy_created_at,
                    legacy_updated_at,legacy_metadata_json,legacy_embedding,redaction_applied,imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (legacy_id, claim_id, observation_id, evidence_id, decision_id, category,
                 row["status"], row["confidence"], source_message_id, source_ref,
                 row["valid_from"], row["valid_until"], row["created_at"], row["updated_at"],
                 safe_metadata_json, row["embedding"],
                 int(metadata_redacted or content_redacted or source_redacted), imported_at),
            )

    @staticmethod
    def _migrate_v9_to_v10(connection: sqlite3.Connection) -> None:
        """Add isolated Phase-2 shadow-learning audit structures."""
        statements = (
            """CREATE TABLE memory_shadow_learning_decisions (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                primary_observation_id TEXT NOT NULL
                    REFERENCES memory_observations(id) ON DELETE RESTRICT,
                mode TEXT NOT NULL DEFAULT 'shadow' CHECK (mode='shadow'),
                decision_type TEXT NOT NULL CHECK (decision_type IN (
                    'no_persist','create_active','create_candidate',
                    'append_supporting_evidence','append_contradicting_evidence',
                    'create_competing_claim','supersede_claim','refine_claim',
                    'undetermined','shadow_error'
                )),
                memory_worthy INTEGER CHECK (memory_worthy IS NULL OR memory_worthy IN (0,1)),
                proposed_claim_kind TEXT CHECK (
                    proposed_claim_kind IS NULL OR
                    proposed_claim_kind IN ('opaque_fact','provider_binding','alias')
                ),
                proposed_scope TEXT,
                proposed_canonical_key TEXT,
                proposed_slot_key TEXT,
                proposed_lifecycle TEXT CHECK (
                    proposed_lifecycle IS NULL OR
                    proposed_lifecycle IN ('candidate','active','retired','invalid')
                ),
                proposed_payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(proposed_payload_json)),
                proposed_evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(proposed_evidence_json)),
                matched_claims_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(matched_claims_json)),
                proposed_relations_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(proposed_relations_json)),
                valid_from TEXT,
                valid_until TEXT,
                method TEXT NOT NULL CHECK (method IN ('deterministic','llm','hybrid')),
                policy_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model_version TEXT NOT NULL DEFAULT '',
                uncertainty REAL CHECK (uncertainty IS NULL OR (uncertainty>=0 AND uncertainty<=1)),
                reason_code TEXT NOT NULL,
                clarification_recommended INTEGER NOT NULL DEFAULT 0
                    CHECK (clarification_recommended IN (0,1)),
                legacy_comparison TEXT NOT NULL CHECK (legacy_comparison IN (
                    'legacy_stored_v2_no_persist','legacy_missed_v2_persist',
                    'both_persist','both_no_persist','different_integration','not_compared'
                )),
                metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
                created_at TEXT NOT NULL,
                UNIQUE (turn_id, policy_version, prompt_version, model_version)
            )""",
            """CREATE TABLE memory_shadow_decision_observations (
                decision_id TEXT NOT NULL REFERENCES memory_shadow_learning_decisions(id) ON DELETE CASCADE,
                observation_id TEXT NOT NULL REFERENCES memory_observations(id) ON DELETE RESTRICT,
                evidence_eligible INTEGER NOT NULL CHECK (evidence_eligible IN (0,1)),
                role TEXT NOT NULL CHECK (role IN ('trigger','support','contradict','context')),
                PRIMARY KEY (decision_id, observation_id)
            )""",
            "CREATE INDEX memory_shadow_decisions_turn ON memory_shadow_learning_decisions(turn_id,created_at)",
            "CREATE INDEX memory_shadow_decisions_type ON memory_shadow_learning_decisions(decision_type,created_at)",
        )
        for statement in statements:
            if statement.startswith("CREATE TABLE "):
                statement = statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
            elif statement.startswith("CREATE INDEX "):
                statement = statement.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
            connection.execute(statement)

    @staticmethod
    def _migrate_v10_to_v11(connection: sqlite3.Connection) -> None:
        """Add rebuildable retrieval and read-only Phase-3 compiler audit data."""
        connection.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_claims_fts USING fts5(
                claim_id UNINDEXED, display_text, structured_terms,
                tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TRIGGER IF NOT EXISTS memory_claims_fts_insert AFTER INSERT ON memory_claims BEGIN
                INSERT INTO memory_claims_fts(claim_id,display_text,structured_terms)
                VALUES (new.id,new.display_text,new.canonical_key || ' ' || COALESCE(new.slot_key,'') || ' ' || new.payload_json);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_claims_fts_update AFTER UPDATE ON memory_claims BEGIN
                DELETE FROM memory_claims_fts WHERE claim_id=old.id;
                INSERT INTO memory_claims_fts(claim_id,display_text,structured_terms)
                VALUES (new.id,new.display_text,new.canonical_key || ' ' || COALESCE(new.slot_key,'') || ' ' || new.payload_json);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_claims_fts_delete AFTER DELETE ON memory_claims BEGIN
                DELETE FROM memory_claims_fts WHERE claim_id=old.id;
            END;
            CREATE TABLE IF NOT EXISTS memory_compiler_evaluations (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                consumer TEXT NOT NULL CHECK (consumer IN ('planner','answer','audit')),
                compiler_version TEXT NOT NULL,
                retrieval_version TEXT NOT NULL,
                eligibility_version TEXT NOT NULL,
                projection_version TEXT NOT NULL,
                budget_version TEXT NOT NULL,
                claim_snapshot TEXT NOT NULL,
                config_snapshot TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('would_present','empty','cancelled','error')),
                token_budget INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                token_method TEXT NOT NULL,
                required_overflow INTEGER NOT NULL DEFAULT 0 CHECK (required_overflow IN (0,1)),
                candidate_count INTEGER NOT NULL DEFAULT 0,
                eligible_count INTEGER NOT NULL DEFAULT 0,
                presented_count INTEGER NOT NULL DEFAULT 0,
                legacy_count INTEGER NOT NULL DEFAULT 0,
                legacy_token_count INTEGER NOT NULL DEFAULT 0,
                legacy_overlap_count INTEGER NOT NULL DEFAULT 0,
                rendered_view TEXT NOT NULL DEFAULT '',
                metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
                created_at TEXT NOT NULL,
                UNIQUE(turn_id,consumer,compiler_version,claim_snapshot,config_snapshot)
            );
            CREATE INDEX IF NOT EXISTS memory_compiler_evaluations_turn
                ON memory_compiler_evaluations(turn_id,consumer,created_at);
            CREATE TABLE IF NOT EXISTS memory_compiler_claim_audit (
                evaluation_id TEXT NOT NULL REFERENCES memory_compiler_evaluations(id) ON DELETE CASCADE,
                claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                stage TEXT NOT NULL CHECK (stage IN ('retrieved','eligible','would_present','rejected','cancelled','error')),
                method TEXT NOT NULL,
                reason TEXT NOT NULL,
                requirement_class TEXT CHECK (requirement_class IS NULL OR requirement_class IN ('required','useful','optional')),
                token_cost INTEGER,
                rank_score REAL,
                PRIMARY KEY(evaluation_id,claim_id,stage,reason)
            );
            CREATE INDEX IF NOT EXISTS memory_compiler_claim_audit_claim
                ON memory_compiler_claim_audit(claim_id,stage);
            """
        )
        connection.execute("DELETE FROM memory_claims_fts")
        rows = connection.execute(
            "SELECT id,display_text,canonical_key,slot_key,payload_json FROM memory_claims ORDER BY id"
        ).fetchall()
        connection.executemany(
            "INSERT INTO memory_claims_fts(claim_id,display_text,structured_terms) VALUES (?,?,?)",
            [(row["id"], row["display_text"], " ".join(filter(None, (
                row["canonical_key"], row["slot_key"], row["payload_json"],
            )))) for row in rows],
        )

    @staticmethod
    def _migrate_v11_to_v12(connection: sqlite3.Connection) -> None:
        """Add the atomic Phase-4 cutover, productive jobs and compact usage audit."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_learning_jobs (
                turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ('pending','running','applied','no_persist','failed')),
                decision_id TEXT REFERENCES memory_learning_decisions(id) ON DELETE SET NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                error_class TEXT,
                accepted_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS memory_learning_jobs_status
                ON memory_learning_jobs(status,accepted_at);
            CREATE TABLE IF NOT EXISTS memory_cutover_events (
                id TEXT PRIMARY KEY,
                previous_mode TEXT NOT NULL,
                new_mode TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                git_reference TEXT,
                backup_reference TEXT NOT NULL,
                learning_version TEXT NOT NULL,
                compiler_version TEXT NOT NULL,
                delta_imported INTEGER NOT NULL,
                delta_existing INTEGER NOT NULL,
                counts_json TEXT NOT NULL CHECK (json_valid(counts_json)),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_runtime_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                memory_backend TEXT NOT NULL CHECK (memory_backend IN ('legacy','v2')),
                legacy_writes_enabled INTEGER NOT NULL CHECK (legacy_writes_enabled IN (0,1)),
                legacy_productive_reads_enabled INTEGER NOT NULL CHECK (legacy_productive_reads_enabled IN (0,1)),
                last_cutover_at TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO memory_runtime_state
                (singleton,memory_backend,legacy_writes_enabled,legacy_productive_reads_enabled,updated_at)
                VALUES (1,'legacy',1,1,datetime('now'));
            CREATE TABLE IF NOT EXISTS memory_compiler_usage (
                turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                consumer TEXT NOT NULL CHECK (consumer IN ('planner','answer')),
                claim_id TEXT NOT NULL REFERENCES memory_claims(id) ON DELETE CASCADE,
                usage TEXT NOT NULL CHECK (usage IN ('presented','used')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (turn_id,consumer,claim_id,usage)
            );
            """
        )

    @staticmethod
    def _migrate_v12_to_v13(connection: sqlite3.Connection) -> None:
        """Add isolated, dry-run-only Memory-v2 maintenance audit data."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_maintenance_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
                snapshot_hash TEXT NOT NULL,
                analyzer_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_ms REAL,
                active_claims INTEGER NOT NULL DEFAULT 0,
                historical_claims INTEGER NOT NULL DEFAULT 0,
                relations_checked INTEGER NOT NULL DEFAULT 0,
                finding_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(summary_json)),
                warnings_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(warnings_json)),
                error_class TEXT
            );
            CREATE INDEX IF NOT EXISTS memory_maintenance_runs_started
                ON memory_maintenance_runs(started_at DESC);
            CREATE TABLE IF NOT EXISTS memory_maintenance_findings (
                id TEXT PRIMARY KEY,
                finding_key TEXT NOT NULL UNIQUE,
                problem_class TEXT NOT NULL CHECK (problem_class IN (
                    'possible_duplicate','potential_contradiction','consolidation_candidate',
                    'suspicious_history','orphaned_data'
                )),
                category TEXT NOT NULL,
                affected_claim_ids_json TEXT NOT NULL CHECK (json_valid(affected_claim_ids_json)),
                rationale TEXT NOT NULL,
                proposed_action TEXT NOT NULL CHECK (proposed_action IN (
                    'keep','review','merge','supersede','repair_relation','archive','delete_candidate'
                )),
                confidence TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
                evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_maintenance_run_findings (
                run_id TEXT NOT NULL REFERENCES memory_maintenance_runs(id) ON DELETE CASCADE,
                finding_id TEXT NOT NULL REFERENCES memory_maintenance_findings(id) ON DELETE RESTRICT,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (run_id, finding_id)
            );
            CREATE INDEX IF NOT EXISTS memory_maintenance_run_findings_finding
                ON memory_maintenance_run_findings(finding_id, run_id);
            """
        )

    @staticmethod
    def _migrate_v13_to_v14(connection: sqlite3.Connection) -> None:
        """Finish the upgrade path before Memory becomes the only runtime."""
        EveDatabase._import_legacy_memory_v2(connection)
        legacy = int(connection.execute("SELECT count(*) FROM memory_items").fetchone()[0])
        mapped = int(connection.execute("SELECT count(*) FROM memory_legacy_mappings").fetchone()[0])
        if legacy != mapped:
            raise RuntimeError("Historische Memory-Daten konnten nicht vollständig übernommen werden")
        connection.execute(
            """UPDATE memory_runtime_state SET memory_backend='v2',legacy_writes_enabled=0,
               legacy_productive_reads_enabled=0,updated_at=? WHERE singleton=1""",
            (_now(),),
        )

    @staticmethod
    def _migrate_v14_to_v15(connection: sqlite3.Connection) -> None:
        """Add durable, metadata-only links from work items to chat context."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS work_item_context_links (
                id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                start_message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
                end_message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
                label TEXT,
                source TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('manual','task_creation','assistant')),
                created_at TEXT NOT NULL,
                CHECK (end_message_id IS NULL OR start_message_id IS NOT NULL),
                UNIQUE (work_item_id, conversation_id, start_message_id, end_message_id)
            );
            CREATE INDEX IF NOT EXISTS work_item_context_links_item
                ON work_item_context_links(work_item_id, created_at, id);
            CREATE INDEX IF NOT EXISTS work_item_context_links_conversation
                ON work_item_context_links(conversation_id, created_at, id);
            """
        )

    @staticmethod
    def _migrate_v15_to_v16(connection: sqlite3.Connection) -> None:
        """Persist bounded differential evidence beside Semantic Links in Memory V2."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_differential_experiences (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL UNIQUE REFERENCES memory_claims(id) ON DELETE CASCADE,
                provider_key TEXT NOT NULL,
                context_key TEXT NOT NULL,
                context_json TEXT NOT NULL CHECK (json_valid(context_json)),
                shape_key TEXT NOT NULL,
                utterance TEXT NOT NULL,
                tokens_json TEXT NOT NULL CHECK (json_valid(tokens_json)),
                plan_json TEXT NOT NULL CHECK (json_valid(plan_json)),
                action_key TEXT NOT NULL,
                provenance_root TEXT,
                state TEXT NOT NULL CHECK (state IN ('eligible','ineligible','invalid')),
                reason TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_exp_partition
                ON semantic_differential_experiences(provider_key,context_key,shape_key,state);
            CREATE INDEX IF NOT EXISTS semantic_diff_exp_root
                ON semantic_differential_experiences(provenance_root,state);
            CREATE INDEX IF NOT EXISTS semantic_diff_exp_action
                ON semantic_differential_experiences(action_key,state);

            CREATE TABLE IF NOT EXISTS semantic_differential_features (
                experience_id TEXT NOT NULL REFERENCES semantic_differential_experiences(id) ON DELETE CASCADE,
                feature TEXT NOT NULL,
                spans_json TEXT NOT NULL CHECK (json_valid(spans_json)),
                PRIMARY KEY (experience_id,feature)
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_feature_lookup
                ON semantic_differential_features(feature,experience_id);

            CREATE TABLE IF NOT EXISTS semantic_differential_fields (
                experience_id TEXT NOT NULL REFERENCES semantic_differential_experiences(id) ON DELETE CASCADE,
                field_path TEXT NOT NULL,
                value_json TEXT NOT NULL CHECK (json_valid(value_json)),
                other_signature TEXT NOT NULL,
                PRIMARY KEY (experience_id,field_path)
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_field_lookup
                ON semantic_differential_fields(field_path,value_json,experience_id);
            CREATE INDEX IF NOT EXISTS semantic_diff_contrast_lookup
                ON semantic_differential_fields(field_path,other_signature,value_json);

            CREATE TABLE IF NOT EXISTS semantic_differential_hypotheses (
                id TEXT PRIMARY KEY,
                hypothesis_key TEXT NOT NULL UNIQUE,
                provider_key TEXT NOT NULL,
                context_key TEXT NOT NULL,
                shape_key TEXT NOT NULL,
                feature TEXT NOT NULL,
                field_path TEXT NOT NULL,
                value_json TEXT NOT NULL CHECK (json_valid(value_json)),
                status TEXT NOT NULL CHECK (status IN ('candidate','released','blocked','retired','truncated')),
                support_roots INTEGER NOT NULL,
                counterexamples INTEGER NOT NULL,
                nuisance_values INTEGER NOT NULL,
                contrast_count INTEGER NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_hyp_lookup
                ON semantic_differential_hypotheses(provider_key,context_key,shape_key,status,feature);
            CREATE INDEX IF NOT EXISTS semantic_diff_hyp_field
                ON semantic_differential_hypotheses(field_path,value_json,status);

            CREATE TABLE IF NOT EXISTS semantic_differential_hypothesis_versions (
                hypothesis_id TEXT NOT NULL REFERENCES semantic_differential_hypotheses(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (hypothesis_id,version)
            );
            CREATE TABLE IF NOT EXISTS semantic_differential_dependencies (
                hypothesis_id TEXT NOT NULL REFERENCES semantic_differential_hypotheses(id) ON DELETE CASCADE,
                experience_id TEXT NOT NULL REFERENCES semantic_differential_experiences(id) ON DELETE CASCADE,
                provenance_root TEXT,
                stance TEXT NOT NULL CHECK (stance IN ('support','counter','contrast')),
                PRIMARY KEY (hypothesis_id,experience_id,stance)
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_dependency_exp
                ON semantic_differential_dependencies(experience_id,hypothesis_id);

            CREATE TABLE IF NOT EXISTS semantic_differential_evaluations (
                id TEXT PRIMARY KEY,
                input_text TEXT NOT NULL,
                provider_key TEXT NOT NULL,
                context_json TEXT NOT NULL CHECK (json_valid(context_json)),
                mode TEXT NOT NULL CHECK (mode IN ('active','shadow','disabled')),
                status TEXT NOT NULL,
                candidate_plan_json TEXT CHECK (candidate_plan_json IS NULL OR json_valid(candidate_plan_json)),
                hypothesis_ids_json TEXT NOT NULL CHECK (json_valid(hypothesis_ids_json)),
                details_json TEXT NOT NULL CHECK (json_valid(details_json)),
                duration_ms REAL NOT NULL,
                candidate_count INTEGER NOT NULL,
                config_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS semantic_diff_eval_created
                ON semantic_differential_evaluations(created_at DESC,id);
            """
        )

    @staticmethod
    def _migrate_v16_to_v17(connection: sqlite3.Connection) -> None:
        """Add the isolated, append-only Memory runtime telemetry contract."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_runtime_traces (
                id TEXT PRIMARY KEY
                    CHECK (length(trim(id)) BETWEEN 1 AND 256),
                conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                started_at TEXT NOT NULL CHECK (length(trim(started_at)) > 0),
                telemetry_version TEXT NOT NULL
                    CHECK (telemetry_version = 'memory-runtime-events-v1')
            );
            CREATE INDEX IF NOT EXISTS memory_runtime_traces_conversation_started
                ON memory_runtime_traces(conversation_id, started_at, id)
                WHERE conversation_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS memory_runtime_events (
                id TEXT PRIMARY KEY CHECK (length(trim(id)) BETWEEN 1 AND 256),
                trace_id TEXT NOT NULL
                    REFERENCES memory_runtime_traces(id) ON DELETE RESTRICT,
                event_kind TEXT NOT NULL CHECK (event_kind IN (
                    'trace_started','operation_started','operation_completed',
                    'operation_aborted','telemetry_persist_failed','transport_failed',
                    'llm_transport_result','claim_retrieved','claim_eligible',
                    'claim_selected_for_view','claim_returned_to_consumer',
                    'relation_traversed_for_retrieval',
                    'claim_added_to_prompt_context','claim_received_by_llm_client',
                    'claim_serialized_for_transport','claim_query_started','claim_resolved',
                    'claim_technical_verification','claim_bound_to_plan','alias_read_for_stt',
                    'claim_bound_to_action','action_dispatch_attempted_with_claim',
                    'action_provider_response_with_claim','action_verification_with_claim',
                    'action_completed_with_claim','relation_bound_to_plan',
                    'claim_lifecycle_changed'
                )),
                occurred_at TEXT NOT NULL CHECK (length(trim(occurred_at)) > 0),
                recorded_at TEXT NOT NULL CHECK (length(trim(recorded_at)) > 0),
                operation_id TEXT NOT NULL CHECK (length(trim(operation_id)) BETWEEN 1 AND 256),
                parent_event_id TEXT REFERENCES memory_runtime_events(id) ON DELETE RESTRICT,
                turn_id TEXT,
                planner_round_id TEXT,
                plan_id TEXT,
                llm_call_id TEXT,
                attempt_id TEXT,
                attempt_no INTEGER,
                consumer TEXT,
                action_id TEXT,
                action_index INTEGER CHECK (action_index IS NULL OR action_index >= 0),
                tool_event_id TEXT,
                compiler_evaluation_id TEXT,
                claim_id TEXT REFERENCES memory_claims(id) ON DELETE RESTRICT,
                relation_id TEXT REFERENCES memory_relations(id) ON DELETE RESTRICT,
                learning_decision_id TEXT
                    REFERENCES memory_learning_decisions(id) ON DELETE RESTRICT,
                producer TEXT NOT NULL CHECK (length(trim(producer)) BETWEEN 1 AND 256),
                proof_level TEXT NOT NULL CHECK (proof_level IN (
                    'trace_boundary','operation_boundary','compiler_evaluation',
                    'assembled_context','client_boundary','transport_payload','transport_result',
                    'deterministic_resolution','provider_verification','validated_binding',
                    'dispatch_boundary','provider_response','verification_result','action_result',
                    'relation_traversal','consumer_boundary','atomic_lifecycle','telemetry_boundary'
                )),
                event_status TEXT NOT NULL
                    CHECK (event_status IN ('started','completed','failed','cancelled','rejected')),
                outcome_status TEXT CHECK (outcome_status IS NULL OR outcome_status IN (
                    'success','failed','partial','outcome_uncertain','cancelled','skipped',
                    'acknowledged','denied','error','not_available'
                )),
                verification_status TEXT CHECK (
                    verification_status IS NULL OR verification_status IN (
                        'verified','contradictory','in_progress','inconclusive',
                        'not_available','cancelled','error','not_applicable'
                    )
                ),
                provider TEXT,
                target_resource_id TEXT,
                state_before TEXT,
                state_after TEXT,
                reason_code TEXT,
                context_block_id TEXT,
                context_manifest_digest TEXT CHECK (
                    context_manifest_digest IS NULL OR (
                        length(context_manifest_digest) = 64
                        AND context_manifest_digest NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                ordinal INTEGER CHECK (ordinal IS NULL OR ordinal >= 0),
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (
                    json_valid(details_json)
                    AND json_type(details_json) = 'object'
                    AND length(CAST(details_json AS BLOB)) <= 16384
                ),
                dedupe_key TEXT NOT NULL UNIQUE CHECK (
                    length(dedupe_key) = 64 AND dedupe_key NOT GLOB '*[^0-9a-f]*'
                ),
                record_digest TEXT NOT NULL CHECK (
                    length(record_digest) = 64 AND record_digest NOT GLOB '*[^0-9a-f]*'
                ),
                CHECK (parent_event_id IS NULL OR parent_event_id <> id),
                CHECK ((attempt_id IS NULL AND attempt_no IS NULL)
                       OR (attempt_id IS NOT NULL AND attempt_no >= 1)),
                CHECK (
                    (event_kind IN (
                        'claim_retrieved','claim_eligible','claim_selected_for_view',
                        'claim_returned_to_consumer',
                        'claim_added_to_prompt_context','claim_received_by_llm_client',
                        'claim_serialized_for_transport','claim_resolved',
                        'claim_technical_verification','claim_bound_to_plan','alias_read_for_stt',
                        'claim_bound_to_action','action_dispatch_attempted_with_claim',
                        'action_provider_response_with_claim','action_verification_with_claim',
                        'action_completed_with_claim','claim_lifecycle_changed'
                    ) AND claim_id IS NOT NULL AND relation_id IS NULL)
                    OR
                    (event_kind IN (
                        'relation_traversed_for_retrieval','relation_bound_to_plan'
                    ) AND relation_id IS NOT NULL AND claim_id IS NULL)
                    OR
                    (event_kind IN (
                        'trace_started','operation_started','operation_completed',
                        'operation_aborted','telemetry_persist_failed','transport_failed',
                        'llm_transport_result','claim_query_started'
                    ) AND claim_id IS NULL AND relation_id IS NULL)
                ),
                CHECK (event_kind <> 'claim_lifecycle_changed'
                       OR (state_after IS NOT NULL AND reason_code IS NOT NULL
                           AND (state_before IS NULL OR state_before <> state_after))),
                CHECK (event_kind NOT IN (
                           'claim_technical_verification','claim_bound_to_action',
                           'action_dispatch_attempted_with_claim',
                           'action_provider_response_with_claim',
                           'action_verification_with_claim','action_completed_with_claim'
                       ) OR (provider IS NOT NULL AND target_resource_id IS NOT NULL)),
                CHECK (event_kind NOT IN (
                           'claim_bound_to_action','action_dispatch_attempted_with_claim',
                           'action_provider_response_with_claim',
                           'action_verification_with_claim','action_completed_with_claim'
                       ) OR (planner_round_id IS NOT NULL AND plan_id IS NOT NULL
                             AND action_id IS NOT NULL AND action_index IS NOT NULL))
            );
            CREATE INDEX IF NOT EXISTS memory_runtime_events_trace_time
                ON memory_runtime_events(trace_id, occurred_at, id);
            CREATE INDEX IF NOT EXISTS memory_runtime_events_turn_kind
                ON memory_runtime_events(turn_id, event_kind, occurred_at, id)
                WHERE turn_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_claim_time
                ON memory_runtime_events(claim_id, occurred_at, id, turn_id)
                WHERE claim_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_relation_time
                ON memory_runtime_events(relation_id, occurred_at, id, turn_id)
                WHERE relation_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_llm_attempt
                ON memory_runtime_events(llm_call_id, attempt_no, occurred_at, id)
                WHERE llm_call_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_action_time
                ON memory_runtime_events(action_id, occurred_at, id)
                WHERE action_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_evaluation
                ON memory_runtime_events(compiler_evaluation_id, claim_id, event_kind)
                WHERE compiler_evaluation_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS memory_runtime_events_operation_status
                ON memory_runtime_events(operation_id, event_status, occurred_at, id);

            CREATE TRIGGER IF NOT EXISTS memory_runtime_traces_no_update
            BEFORE UPDATE ON memory_runtime_traces BEGIN
                SELECT RAISE(ABORT, 'memory runtime traces are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS memory_runtime_traces_no_delete
            BEFORE DELETE ON memory_runtime_traces BEGIN
                SELECT RAISE(ABORT, 'memory runtime traces are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS memory_runtime_events_no_update
            BEFORE UPDATE ON memory_runtime_events BEGIN
                SELECT RAISE(ABORT, 'memory runtime events are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS memory_runtime_events_no_delete
            BEFORE DELETE ON memory_runtime_events BEGIN
                SELECT RAISE(ABORT, 'memory runtime events are append-only');
            END;
            """
        )

    @staticmethod
    def _migrate_v17_to_v18(connection: sqlite3.Connection) -> None:
        """Add a typed consumer-return boundary without reinterpreting selection."""
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_runtime_events'"
        ).fetchone()
        if row is None:
            raise RuntimeError("Memory-Runtime-Ereignistabelle fehlt")
        original_sql = str(row[0])
        if ("claim_returned_to_consumer" in original_sql
                and "consumer_boundary" in original_sql):
            return

        for name in (
            "memory_runtime_events_no_update", "memory_runtime_events_no_delete",
            "memory_runtime_events_trace_time", "memory_runtime_events_turn_kind",
            "memory_runtime_events_claim_time", "memory_runtime_events_relation_time",
            "memory_runtime_events_llm_attempt", "memory_runtime_events_action_time",
            "memory_runtime_events_evaluation", "memory_runtime_events_operation_status",
        ):
            kind = "TRIGGER" if "no_" in name else "INDEX"
            connection.execute(f"DROP {kind} IF EXISTS {name}")

        connection.execute(
            "ALTER TABLE memory_runtime_events RENAME TO memory_runtime_events_v17"
        )
        migrated_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_runtime_events_v17'"
        ).fetchone()[0]
        migrated_sql = str(migrated_sql).replace(
            '"memory_runtime_events_v17"', 'memory_runtime_events'
        ).replace(
            "'claim_selected_for_view'",
            "'claim_selected_for_view','claim_returned_to_consumer'",
        ).replace(
            "'relation_traversal','atomic_lifecycle'",
            "'relation_traversal','consumer_boundary','atomic_lifecycle'",
        )
        connection.execute(migrated_sql)
        columns = [
            str(item[1]) for item in connection.execute(
                "PRAGMA table_info(memory_runtime_events_v17)"
            ).fetchall()
        ]
        names = ",".join(columns)
        connection.execute(
            f"INSERT INTO memory_runtime_events({names}) SELECT {names} FROM memory_runtime_events_v17"
        )
        connection.execute("DROP TABLE memory_runtime_events_v17")
        statements = (
            "CREATE INDEX memory_runtime_events_trace_time "
            "ON memory_runtime_events(trace_id, occurred_at, id)",
            "CREATE INDEX memory_runtime_events_turn_kind "
            "ON memory_runtime_events(turn_id, event_kind, occurred_at, id) "
            "WHERE turn_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_claim_time "
            "ON memory_runtime_events(claim_id, occurred_at, id, turn_id) "
            "WHERE claim_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_relation_time "
            "ON memory_runtime_events(relation_id, occurred_at, id, turn_id) "
            "WHERE relation_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_llm_attempt "
            "ON memory_runtime_events(llm_call_id, attempt_no, occurred_at, id) "
            "WHERE llm_call_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_action_time "
            "ON memory_runtime_events(action_id, occurred_at, id) "
            "WHERE action_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_evaluation "
            "ON memory_runtime_events(compiler_evaluation_id, claim_id, event_kind) "
            "WHERE compiler_evaluation_id IS NOT NULL",
            "CREATE INDEX memory_runtime_events_operation_status "
            "ON memory_runtime_events(operation_id, event_status, occurred_at, id)",
            """CREATE TRIGGER memory_runtime_events_no_update
               BEFORE UPDATE ON memory_runtime_events BEGIN
                   SELECT RAISE(ABORT, 'memory runtime events are append-only');
               END""",
            """CREATE TRIGGER memory_runtime_events_no_delete
               BEFORE DELETE ON memory_runtime_events BEGIN
                   SELECT RAISE(ABORT, 'memory runtime events are append-only');
               END""",
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _migrate_v18_to_v19(connection: sqlite3.Connection) -> None:
        """Persist the interruptible conversation-learning scheduler state."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_learning_runtime (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                status TEXT NOT NULL CHECK (
                    status IN ('waiting','running','paused','completed','failed','disabled')
                ),
                pause_requested INTEGER NOT NULL DEFAULT 0 CHECK (pause_requested IN (0,1)),
                current_batch_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(current_batch_json)),
                last_activity_at TEXT,
                last_started_at TEXT,
                last_completed_at TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO conversation_learning_runtime
                (singleton,status,pause_requested,current_batch_json,updated_at)
                VALUES (1,'waiting',0,'[]',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            UPDATE memory_learning_jobs
               SET status='pending',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
             WHERE status='running';
            """
        )

    @staticmethod
    def _migrate_v19_to_v20(connection):
        from .working_memory import SCHEMA
        for statement in SCHEMA:
            connection.execute(statement)

    @staticmethod
    def _migrate_v20_to_v21(connection):
        connection.execute("CREATE INDEX IF NOT EXISTS memory_work_events_turn ON memory_work_events(turn_id)")

    @staticmethod
    def _migrate_v21_to_v22(connection):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(memory_workspaces)')}
        if 'retention_class' not in columns:
            connection.execute(
                "ALTER TABLE memory_workspaces ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'standard' "
                "CHECK(retention_class IN ('standard','temporary_learning'))"
            )
        if 'pinned' not in columns:
            connection.execute(
                'ALTER TABLE memory_workspaces ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0 '
                'CHECK(pinned IN (0,1))'
            )
        if 'last_accessed_at' not in columns:
            connection.execute('ALTER TABLE memory_workspaces ADD COLUMN last_accessed_at TEXT')
            connection.execute('UPDATE memory_workspaces SET last_accessed_at=updated_at WHERE last_accessed_at IS NULL')
        from .working_memory import SCHEMA
        for statement in SCHEMA:
            connection.execute(statement)

    @staticmethod
    def _migrate_v22_to_v23(connection):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(memory_learning_jobs)')}
        if 'reviewed_at' not in columns:
            connection.execute("ALTER TABLE memory_learning_jobs ADD COLUMN reviewed_at TEXT")
        if 'review_note' not in columns:
            connection.execute("ALTER TABLE memory_learning_jobs ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")

    def import_legacy_memory_delta(self) -> dict[str, int]:
        """Idempotently import all as-yet unmapped Legacy rows in one transaction."""
        # Historical import is migration provenance, not a current lifecycle
        # decision.  It must never manufacture contemporary runtime events.
        with self.connect(lifecycle_audit=False) as connection:
            legacy = int(connection.execute("SELECT count(*) FROM memory_items").fetchone()[0])
            before = int(connection.execute("SELECT count(*) FROM memory_legacy_mappings").fetchone()[0])
            self._import_legacy_memory_v2(connection)
            after = int(connection.execute("SELECT count(*) FROM memory_legacy_mappings").fetchone()[0])
        return {"legacy": legacy, "existing": before, "imported": after - before, "mapped": after}

    def _protect_files(self) -> None:
        for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if path.exists():
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass


class MemoryV2AuditStore:
    """Read-only inspection surface for the inactive Phase-1 data model."""

    def __init__(self, database: EveDatabase):
        self.database = database

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        for key in tuple(item):
            if key.endswith("_json") and isinstance(item[key], str):
                try:
                    item[key.removesuffix("_json")] = json.loads(item.pop(key))
                except ValueError:
                    pass
        return item

    def list_claims(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM memory_claims
                   ORDER BY created_at, id LIMIT ? OFFSET ?""",
                (min(max(int(limit), 1), 500), max(int(offset), 0)),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def claim(self, claim_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM memory_claims WHERE id=?", (str(claim_id),)).fetchone()
            if row is None:
                raise KeyError("Memory-v2-Claim wurde nicht gefunden")
            evidence_rows = connection.execute(
                "SELECT * FROM memory_evidence WHERE claim_id=? ORDER BY created_at,id", (str(claim_id),)
            ).fetchall()
            observations = []
            for evidence in evidence_rows:
                if evidence["observation_id"]:
                    observation = connection.execute(
                        "SELECT * FROM memory_observations WHERE id=?", (evidence["observation_id"],)
                    ).fetchone()
                    if observation:
                        observations.append(self._decode(observation))
            mapping = connection.execute(
                """SELECT legacy_memory_id,claim_id,observation_id,evidence_id,decision_id,
                          legacy_category,legacy_status,legacy_confidence,legacy_source_message_id,
                          legacy_source_ref,legacy_valid_from,legacy_valid_until,legacy_created_at,
                          legacy_updated_at,legacy_metadata_json,redaction_applied,imported_at,
                          length(legacy_embedding) AS legacy_embedding_bytes
                   FROM memory_legacy_mappings WHERE claim_id=?""", (str(claim_id),)
            ).fetchone()
        return {
            "claim": self._decode(row),
            "evidence": [self._decode(item) for item in evidence_rows],
            "observations": observations,
            "legacy_mapping": self._decode(mapping),
        }

    def resolve_legacy_id(self, legacy_memory_id: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT legacy_memory_id,claim_id,observation_id,evidence_id,decision_id,imported_at
                   FROM memory_legacy_mappings WHERE legacy_memory_id=?""", (str(legacy_memory_id),)
            ).fetchone()
        return self._decode(row)

    def provider_bindings(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                          verification_policy,created_at,updated_at
                   FROM memory_claims WHERE claim_kind='provider_binding'
                   ORDER BY created_at,id"""
            ).fetchall()
        return [self._decode(row) for row in rows]

    def relations(self, claim_id: str | None = None) -> list[dict]:
        with self.database.connect() as connection:
            if claim_id is None:
                rows = connection.execute("SELECT * FROM memory_relations ORDER BY created_at,id").fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM memory_relations
                       WHERE from_claim_id=? OR to_claim_id=? ORDER BY created_at,id""",
                    (str(claim_id), str(claim_id)),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def integrity(self) -> dict:
        with self.database.connect() as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
        return {"integrity": integrity, "foreign_key_violations": foreign_keys}

    def migration_summary(self) -> dict:
        with self.database.connect() as connection:
            count = lambda table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            counts = {
                key: count(table) for key, table in (
                    ("legacy_items", "memory_items"), ("claims", "memory_claims"),
                    ("observations", "memory_observations"), ("evidence", "memory_evidence"),
                    ("import_decisions", "memory_learning_decisions"), ("relations", "memory_relations"),
                )
            }
            lifecycle = dict(connection.execute(
                "SELECT lifecycle,count(*) FROM memory_claims GROUP BY lifecycle ORDER BY lifecycle"
            ).fetchall())
            kinds = dict(connection.execute(
                "SELECT claim_kind,count(*) FROM memory_claims GROUP BY claim_kind ORDER BY claim_kind"
            ).fetchall())
            provenance = dict(connection.execute(
                """SELECT CASE WHEN legacy_source_message_id IS NULL THEN 'without_source_message_id'
                                ELSE 'with_source_message_id' END, count(*)
                   FROM memory_legacy_mappings GROUP BY 1 ORDER BY 1"""
            ).fetchall())
            redactions = int(connection.execute(
                "SELECT count(*) FROM memory_legacy_mappings WHERE redaction_applied=1"
            ).fetchone()[0])
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        return {
            **counts,
            "structured_provider_bindings": kinds.get("provider_binding", 0),
            "opaque_legacy_claims": kinds.get("opaque_fact", 0),
            "claim_lifecycle": lifecycle,
            "claim_kinds": kinds,
            "provenance": provenance,
            "redacted_imports": redactions,
            "integrity": integrity,
            "foreign_key_violations": foreign_key_violations,
            "legacy_production_path": "unchanged",
        }

    def losslessness_issues(self) -> list[str]:
        """Return structural mismatches without exposing memory contents."""
        lifecycle_map = {"active": "active", "candidate": "candidate", "superseded": "retired", "deleted": "retired"}
        issues: list[str] = []
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT i.*,m.*,c.display_text,c.lifecycle,c.valid_from AS claim_valid_from,
                          c.valid_until AS claim_valid_until,c.created_at AS claim_created_at,
                          c.updated_at AS claim_updated_at,o.source_type,o.source_role,
                          e.evidence_type,d.decision_type
                   FROM memory_items i
                   LEFT JOIN memory_legacy_mappings m ON m.legacy_memory_id=i.id
                   LEFT JOIN memory_claims c ON c.id=m.claim_id
                   LEFT JOIN memory_observations o ON o.id=m.observation_id
                   LEFT JOIN memory_evidence e ON e.id=m.evidence_id
                   LEFT JOIN memory_learning_decisions d ON d.id=m.decision_id
                   ORDER BY i.id"""
            ).fetchall()
        for row in rows:
            identifier = str(row["id"])
            if row["claim_id"] is None:
                issues.append(f"{identifier}:missing_mapping")
                continue
            comparisons = (
                (row["category"], row["legacy_category"], "category"),
                (row["status"], row["legacy_status"], "status"),
                (row["confidence"], row["legacy_confidence"], "confidence"),
                (row["source_message_id"], row["legacy_source_message_id"], "source_message_id"),
                (row["valid_from"], row["claim_valid_from"], "valid_from"),
                (row["valid_until"], row["claim_valid_until"], "valid_until"),
                (row["created_at"], row["claim_created_at"], "created_at"),
                (row["updated_at"], row["claim_updated_at"], "updated_at"),
                (row["embedding"], row["legacy_embedding"], "embedding"),
                (lifecycle_map[row["status"]], row["lifecycle"], "lifecycle"),
                (redact_sensitive(str(row["content"])), row["display_text"], "content"),
            )
            for expected, actual, field in comparisons:
                if expected != actual:
                    issues.append(f"{identifier}:{field}")
            safe_metadata, _redacted, _parsed = _safe_legacy_metadata(row["metadata_json"])
            if safe_metadata != row["legacy_metadata_json"]:
                issues.append(f"{identifier}:metadata_json")
            expected_source_ref = (
                redact_sensitive(str(row["source_ref"])) if row["source_ref"] is not None else None
            )
            if expected_source_ref != row["legacy_source_ref"]:
                issues.append(f"{identifier}:source_ref")
            if (row["source_type"], row["source_role"], row["evidence_type"], row["decision_type"]) != (
                "legacy_import", "legacy", "legacy_import", "legacy_import"
            ):
                issues.append(f"{identifier}:audit_chain")
        return issues


class ConversationStore:
    """Persistence API for resumable conversations and their messages."""

    def __init__(self, database: EveDatabase):
        self.database = database
        self.asset_root = database.path.parent / "conversation-assets"
        self.asset_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.asset_root, 0o700)
        except OSError:
            pass

    def create(self, title: str = "Neue Unterhaltung", *, source: str = "eve") -> dict:
        conversation_id = str(uuid.uuid4())
        now = _now()
        clean_title = self._clean_title(title)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO conversations(id, title, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (conversation_id, clean_title, source, now, now),
            )
        return self.get(conversation_id)

    def record_user_interaction(self, conversation_id: str, timestamp: float) -> None:
        """Persist input-arrival time without treating later processing as activity."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM conversations WHERE id=? AND status!='deleted'",
                (str(conversation_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Konversation wurde nicht gefunden")
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata["last_user_interaction_at"] = float(timestamp)
            connection.execute(
                "UPDATE conversations SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), str(conversation_id)),
            )

    def conversation_state(self, conversation_id: str) -> dict:
        """Return persisted, conversation-scoped runtime state."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM conversations WHERE id=? AND status!='deleted'",
                (str(conversation_id),),
            ).fetchone()
        if row is None:
            raise KeyError("Konversation wurde nicht gefunden")
        metadata = json.loads(row["metadata_json"] or "{}")
        state = metadata.get("operational_state", {})
        return dict(state) if isinstance(state, dict) else {}

    def set_conversation_state(self, conversation_id: str, state: dict) -> None:
        """Persist runtime state without turning it into long-term memory."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM conversations WHERE id=? AND status!='deleted'",
                (str(conversation_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Konversation wurde nicht gefunden")
            metadata = json.loads(row["metadata_json"] or "{}")
            if state:
                metadata["operational_state"] = state
            else:
                metadata.pop("operational_state", None)
            connection.execute(
                "UPDATE conversations SET metadata_json=?, updated_at=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), _now(), str(conversation_id)),
            )

    def last_user_interaction(self, conversation_id: str) -> float | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM conversations WHERE id=? AND status!='deleted'",
                (str(conversation_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Konversation wurde nicht gefunden")
            value = json.loads(row["metadata_json"] or "{}").get("last_user_interaction_at")
            if isinstance(value, (int, float)):
                return float(value)
            # Conversations created before lifecycle timestamps existed remain
            # usable without a migration or parallel session store. Their last
            # persisted user message is the best existing input-time evidence;
            # the next real turn replaces it with the exact arrival timestamp.
            legacy = connection.execute(
                """SELECT created_at FROM messages
                   WHERE conversation_id=? AND role='user'
                   ORDER BY ordinal DESC LIMIT 1""",
                (str(conversation_id),),
            ).fetchone()
        if legacy is None:
            return None
        try:
            return datetime.fromisoformat(str(legacy["created_at"])).timestamp()
        except ValueError:
            return None

    def has_messages(self, conversation_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id=? AND status!='deleted'",
                (str(conversation_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Konversation wurde nicht gefunden")
            message = connection.execute(
                "SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1",
                (str(conversation_id),),
            ).fetchone()
        return message is not None

    def get(self, conversation_id: str, *, include_deleted: bool = False) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (str(conversation_id),)
            ).fetchone()
        if row is None or (row["status"] == "deleted" and not include_deleted):
            raise KeyError("Konversation wurde nicht gefunden")
        return self._conversation_dict(row)

    def list(self, *, limit: int = 50, offset: int = 0,
             include_member_dms: bool = True, include_owner_dms: bool = True,
             include_chatto_channels: bool = True) -> list[dict]:
        limit = min(max(int(limit), 1), 100)
        offset = max(int(offset), 0)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT c.*, COUNT(m.id) AS message_count
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.status != 'deleted'
                     AND (? OR c.source != 'chatto' OR
                          COALESCE(json_extract(c.metadata_json, '$.chatto_scope.access_profile'), '') != 'member_dm')
                     AND (? OR c.source != 'chatto' OR
                          COALESCE(json_extract(c.metadata_json, '$.chatto_scope.access_profile'), '') != 'owner_dm')
                     AND (? OR c.source != 'chatto' OR
                          COALESCE(json_extract(c.metadata_json, '$.chatto_scope.access_profile'), '') != 'public_channel')
                   GROUP BY c.id
                   ORDER BY c.updated_at DESC, c.id DESC
                   LIMIT ? OFFSET ?""",
                (include_member_dms, include_owner_dms, include_chatto_channels, limit, offset),
            ).fetchall()
        return [self._conversation_dict(row) for row in rows]

    def rename(self, conversation_id: str, title: str) -> dict:
        clean_title = self._clean_title(title)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE conversations SET title = ?, updated_at = ?
                   WHERE id = ? AND status != 'deleted'""",
                (clean_title, _now(), str(conversation_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError("Konversation wurde nicht gefunden")
        return self.get(conversation_id)

    def delete(self, conversation_id: str) -> None:
        paths: list[Path] = []
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT filename FROM conversation_assets WHERE conversation_id=?",
                (str(conversation_id),),
            ).fetchall()
            paths = [self.asset_root / str(row["filename"]) for row in rows]
            cursor = connection.execute(
                """UPDATE conversations SET status = 'deleted', updated_at = ?
                   WHERE id = ? AND status != 'deleted'""",
                (_now(), str(conversation_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError("Konversation wurde nicht gefunden")
            connection.execute(
                "DELETE FROM work_item_context_links WHERE conversation_id=?", (str(conversation_id),)
            )
            connection.execute(
                "DELETE FROM conversation_assets WHERE conversation_id=?", (str(conversation_id),)
            )
            connection.execute(
                "DELETE FROM conversation_tool_events WHERE conversation_id=?", (str(conversation_id),)
            )
        for path in paths:
            path.unlink(missing_ok=True)

    def messages(self, conversation_id: str, *, limit: int | None = 100,
                 before: int | None = None) -> dict:
        self.get(conversation_id)
        if limit is None:
            with self.database.connect() as connection:
                limit = max(1, int(connection.execute(
                    "SELECT count(*) FROM messages WHERE conversation_id=?",
                    (str(conversation_id),),
                ).fetchone()[0]))
        else:
            limit = max(int(limit), 1)
        params: list[object] = [str(conversation_id)]
        before_clause = ""
        if before is not None:
            before_clause = " AND ordinal < ?"
            params.append(max(int(before), 0))
        params.append(limit + 1)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM messages
                    WHERE conversation_id = ?{before_clause}
                    ORDER BY ordinal DESC LIMIT ?""",
                params,
            ).fetchall()
            message_ids = [str(row["id"]) for row in rows]
            assets: dict[str, list[dict]] = {}
            events: dict[str, list[dict]] = {}
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                for item in connection.execute(
                    f"SELECT * FROM conversation_assets WHERE message_id IN ({placeholders}) "
                    "ORDER BY message_id, ordinal", message_ids,
                ).fetchall():
                    assets.setdefault(str(item["message_id"]), []).append(self._asset_dict(item))
                for item in connection.execute(
                    f"SELECT * FROM conversation_tool_events WHERE message_id IN ({placeholders}) "
                    "ORDER BY message_id, ordinal", message_ids,
                ).fetchall():
                    events.setdefault(str(item["message_id"]), []).append(self._tool_event_dict(item))
        has_more = len(rows) > limit
        selected = list(reversed(rows[:limit]))
        messages = []
        for row in selected:
            message = self._message_dict(row)
            message["attachments"] = assets.get(message["id"], [])
            message["tool_events"] = events.get(message["id"], [])
            messages.append(message)
        return {"messages": messages, "has_more": has_more}

    def record_failure(self, conversation_id: str, report: dict) -> None:
        self.get(conversation_id)
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM audit_events WHERE conversation_id=? AND event_type='turn_failure' "
                "AND json_extract(details_json,'$.turn_id')=?",
                (conversation_id, report["turn_id"]),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) "
                    "VALUES (?,'turn_failure','runtime',?,?,?)",
                    (conversation_id, report["reason"], json.dumps(_safe_json(report), ensure_ascii=False), report["created_at"]),
                )
                connection.execute("UPDATE conversations SET updated_at=? WHERE id=?",
                                   (report["created_at"], conversation_id))

    def record_retry(self, conversation_id: str, turn_id: str, source_turn_id: str, correction: str) -> None:
        self.get(conversation_id)
        with self.database.connect() as connection:
            source = connection.execute(
                "SELECT 1 FROM audit_events WHERE conversation_id=? AND event_type='turn_failure' "
                "AND json_extract(details_json,'$.turn_id')=?", (conversation_id, source_turn_id),
            ).fetchone()
            if source is None:
                raise ValueError("Fehlversuch gehört nicht zu dieser Unterhaltung")
            connection.execute(
                "INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) "
                "VALUES (?,'turn_retry','user','Korrigierter Wiederholungsversuch',?,?)",
                (conversation_id, json.dumps({"turn_id":turn_id,"source_turn_id":source_turn_id,
                                              "correction":redact_sensitive(correction)}, ensure_ascii=False), _now()),
            )

    def answer_feedback(self, conversation_id, message_id, decision, explanation=None):
        """Persist a user's answer rating without confirming factual claims."""
        if decision not in {'correct', 'incorrect', 'undo'}:
            raise ValueError('Bewertung muss correct, incorrect oder undo sein')
        if explanation is not None and not isinstance(explanation, str):
            raise ValueError('Die Erklärung muss Text sein')
        explanation = redact_sensitive((explanation or '').strip()) or None
        if explanation and decision != 'incorrect':
            raise ValueError('Eine Erklärung gehört zu einer negativen Bewertung')
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM messages WHERE id=? AND conversation_id=? AND role='assistant'",
                            (message_id, conversation_id)).fetchone()
            if row is None:
                raise KeyError(message_id)
            metadata = json.loads(row['metadata_json'] or '{}')
            if metadata.get('semantic_feedback'):
                raise ValueError('Die vorhandene Aktionsbewertung muss über ihre ursprüngliche Verknüpfung geändert werden')
            current = metadata.get('answer_feedback')
            if decision == 'undo':
                updated = None
                metadata.pop('answer_feedback', None)
            elif current and current.get('decision') == decision and current.get('explanation') == explanation:
                return {**current, 'can_undo': True}
            else:
                updated = {'status': 'active', 'decision': decision, 'created_at': _now()}
                if explanation:
                    updated['explanation'] = explanation
                metadata['answer_feedback'] = updated
            if current != updated:
                c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                          (json.dumps(metadata, ensure_ascii=False), message_id))
                c.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                    "VALUES (?,'answer_feedback','user',?,?,?)", (conversation_id,
                    'Antwortbewertung zurückgenommen' if updated is None else 'Antwort bewertet',
                    json.dumps({'assistant_message_id': message_id, 'turn_id': row['turn_id'],
                        'previous_feedback': current, 'feedback': updated}, ensure_ascii=False), _now()))
        return {**(updated or {'decision': None}), 'can_undo': updated is not None}

    def failures(self, conversation_id: str) -> list[dict]:
        self.get(conversation_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT details_json FROM audit_events WHERE conversation_id=? "
                "AND event_type='turn_failure' ORDER BY id", (conversation_id,),
            ).fetchall()
        from .turn_failures import normalize_failure_report
        from .working_memory import WorkingMemoryStore
        reports = [normalize_failure_report(json.loads(row[0])) for row in rows]
        for report in reports:
            work = report.get("working_memory") or {}
            if "execution_observation" in report or not work.get("workspace_id") or not work.get("work_turn_id"):
                continue
            with self.database.connect(lifecycle_audit=False) as connection:
                own_turn = connection.execute(
                    "SELECT 1 FROM memory_work_turns WHERE id=? AND workspace_id=? AND conversation_id=?",
                    (work["work_turn_id"], work["workspace_id"], conversation_id),
                ).fetchone()
            if own_turn:
                report["execution_observation"] = WorkingMemoryStore(self.database).activity(
                    work["workspace_id"], turn_id=work["work_turn_id"],
                )
        return reports

    def store_message_reasoning(
        self, conversation_id: str, message_id: str, reasoning: str,
    ) -> dict:
        """Attach redacted provider reasoning to one persisted assistant message."""
        clean = redact_sensitive(str(reasoning or "")).strip()
        if not clean:
            raise ValueError("Gedankengang ist leer")
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT metadata_json FROM messages
                   WHERE id=? AND conversation_id=? AND role='assistant'""",
                (str(message_id), str(conversation_id)),
            ).fetchone()
            if row is None:
                raise KeyError("Assistentenantwort wurde nicht gefunden")
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata["reasoning"] = clean
            connection.execute(
                "UPDATE messages SET metadata_json=? WHERE id=? AND conversation_id=?",
                (json.dumps(metadata, ensure_ascii=False), str(message_id), str(conversation_id)),
            )
        return {"message_id": str(message_id), "reasoning": clean}

    def recent_history(self, conversation_id: str, *, limit: int | None = None) -> list[dict]:
        page = self.messages(conversation_id, limit=limit)
        history = []
        for item in page["messages"]:
            content = item["content"]
            if item.get("attachments"):
                references = ", ".join(
                    f"asset:{asset['id']} ({asset['media_type']})" for asset in item["attachments"]
                )
                content += f"\n[Historische Conversation-Anhänge: {references}]"
            if item.get("tool_events"):
                summaries = "; ".join(
                    f"{event['tool']} {event['status']}: {event['summary']}"
                    for event in item["tool_events"]
                )
                content += (
                    "\n[Historische Tool-Ereignisse – nur vergangener Gesprächskontext, "
                    f"kein aktueller Providerzustand: {summaries}]"
                )
            source = item.get("metadata", {}).get("conversation_source")
            history.append({"role": item["role"], "content": content,
                            **({"conversation_source": source} if source else {})})
        return history

    def append_turn(
        self,
        conversation_id: str,
        user: str,
        assistant: str,
        *,
        user_metadata: dict | None = None,
        assistant_metadata: dict | None = None,
        user_attachments: list[dict] | None = None,
        assistant_attachments: list[dict] | None = None,
        tool_events: list[dict] | None = None,
        turn_id: str | None = None,
        knowledge_flow: dict | None = None,
        source_memory_ids: list[str] | None = None,
        memory_retrievals: list[dict] | None = None,
    ) -> tuple[dict, dict]:
        now = _now()
        prepared: list[tuple[dict, bytes]] = []
        for role, attachments in (("user", user_attachments or []), ("assistant", assistant_attachments or [])):
            for ordinal, attachment in enumerate(attachments):
                item = self._prepare_asset(attachment, role=role, ordinal=ordinal)
                if item:
                    prepared.append(item)
        written: list[Path] = []
        try:
            for item, body in prepared:
                path = self.asset_root / item["filename"]
                path.write_bytes(body)
                os.chmod(path, 0o600)
                written.append(path)
            with self.database.connect() as connection:
                conversation = connection.execute(
                "SELECT title FROM conversations WHERE id = ? AND status != 'deleted'",
                (str(conversation_id),),
            ).fetchone()
                if conversation is None:
                    raise KeyError("Konversation wurde nicht gefunden")
                ordinal = int(connection.execute(
                "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM messages WHERE conversation_id = ?",
                (str(conversation_id),),
            ).fetchone()[0])
                user_id, assistant_id = str(uuid.uuid4()), str(uuid.uuid4())
                if turn_id:
                    connection.execute(
                        """INSERT INTO turns
                           (id,conversation_id,knowledge_flow_json,created_at,completed_at)
                           VALUES (?,?,?,?,?)""",
                        (str(turn_id), str(conversation_id),
                         json.dumps(_safe_json(knowledge_flow), ensure_ascii=False)
                         if isinstance(knowledge_flow, dict) else None,
                         now, now),
                    )
                connection.execute(
                    """INSERT INTO messages
                   (id, conversation_id, role, content, ordinal, created_at, metadata_json, turn_id)
                   VALUES (?, ?, 'user', ?, ?, ?, ?, ?)""",
                (user_id, str(conversation_id), redact_sensitive(user), ordinal, now,
                 json.dumps(user_metadata or {}, ensure_ascii=False), str(turn_id) if turn_id else None),
            )
                connection.execute(
                    """INSERT INTO messages
                   (id, conversation_id, role, content, ordinal, created_at, metadata_json, turn_id)
                   VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)""",
                (assistant_id, str(conversation_id), redact_sensitive(assistant), ordinal + 1, now,
                 json.dumps(assistant_metadata or {}, ensure_ascii=False), str(turn_id) if turn_id else None),
            )
                if turn_id:
                    connection.execute(
                        "UPDATE turns SET user_message_id=?, assistant_message_id=? WHERE id=?",
                        (user_id, assistant_id, str(turn_id)),
                    )
                    for position, retrieval in enumerate(memory_retrievals or []):
                        memory_id = retrieval.get("memory_id") if isinstance(retrieval, dict) else None
                        if not memory_id:
                            continue
                        connection.execute(
                            """INSERT INTO turn_memory_retrievals
                               (turn_id,memory_id,position,method,score,retrieved_at)
                               VALUES (?,?,?,?,?,?)""",
                            (str(turn_id), str(memory_id), position,
                             str(retrieval.get("method") or "unknown"),
                             float(retrieval["score"]) if retrieval.get("score") is not None else None,
                             now),
                        )
                    for memory_id in source_memory_ids or []:
                        connection.execute(
                            """UPDATE memory_items SET source_message_id=?
                               WHERE id=? AND source_message_id IS NULL""",
                            (user_id, str(memory_id)),
                        )
                for item, _body in prepared:
                    message_id = user_id if item["role"] == "user" else assistant_id
                    connection.execute(
                        """INSERT INTO conversation_assets
                           (id,conversation_id,message_id,media_type,filename,byte_size,sha256,ordinal,created_at,metadata_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (item["id"], str(conversation_id), message_id, item["media_type"], item["filename"],
                         item["byte_size"], item["sha256"], item["ordinal"], now,
                         json.dumps(item["metadata"], ensure_ascii=False)),
                    )
                    if item["media_type"].startswith("image/"):
                        source = str(item["metadata"].get("source") or item["role"])
                        description = self._visual_description(
                            user, assistant, str(conversation["title"]), source,
                            item["metadata"].get("description"), now,
                        )
                        connection.execute(
                            """INSERT INTO visual_asset_index
                               (asset_id,description,source,embedding,created_at)
                               VALUES (?,?,?,?,?)""",
                            (item["id"], description, source, self._visual_embedding(description), now),
                        )
                for event_ordinal, event in enumerate(tool_events or []):
                    event_input = dict(event.get("input") or {})
                    event_identifier = str(event.get("id") or uuid.uuid4())
                    working_reference = event.get("working_memory")
                    if isinstance(working_reference, dict):
                        event_input["working_memory"] = working_reference
                    if isinstance(event.get("provenance"), dict):
                        event_input["technical_provenance"] = event["provenance"]
                    connection.execute(
                        """INSERT INTO conversation_tool_events
                           (id,conversation_id,message_id,ordinal,tool,status,summary,input_json,result_json,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (event_identifier, str(conversation_id), assistant_id, event_ordinal,
                         str(event.get("tool", "unknown"))[:80], str(event.get("status", "completed"))[:40],
                         redact_sensitive(str(event.get("summary", "")))[:1000],
                         json.dumps(event_input, ensure_ascii=False),
                         json.dumps(event.get("result") or {}, ensure_ascii=False), now),
                    )
                    if isinstance(working_reference, dict):
                        connection.execute("UPDATE memory_observations SET tool_event_id=? WHERE id=? AND scope=?",
                            (event_identifier, working_reference.get("observation_id"),
                             "workspace:" + str(working_reference.get("workspace_id"))))
                working = (assistant_metadata or {}).get("working_memory")
                if turn_id and isinstance(working, dict):
                    connection.execute("UPDATE memory_observations SET turn_id=? WHERE id IN ("
                        "SELECT o.observation_id FROM memory_work_objects o JOIN memory_work_events e ON e.object_id=o.id "
                        "WHERE e.turn_id=? AND e.workspace_id=?)",
                        (str(turn_id), working.get("work_turn_id"), working.get("workspace_id")))
                title = conversation["title"]
                if title == "Neue Unterhaltung":
                    title = self._title_from_message(user)
                connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, str(conversation_id)),
            )
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise
        self.database._protect_files()
        return (
            {"id": user_id, "role": "user", "content": redact_sensitive(user), "ordinal": ordinal,
             "created_at": now, "turn_id": str(turn_id) if turn_id else None},
            {"id": assistant_id, "role": "assistant", "content": redact_sensitive(assistant),
             "ordinal": ordinal + 1, "created_at": now, "turn_id": str(turn_id) if turn_id else None},
        )

    def turn_lineage(self, turn_id: str) -> dict:
        """Read one persisted turn and its recorded retrieval lineage."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM turns WHERE id=?", (str(turn_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Turn wurde nicht gefunden")
            retrievals = connection.execute(
                """SELECT r.memory_id,r.position,r.method,r.score,r.retrieved_at
                   FROM turn_memory_retrievals r WHERE r.turn_id=? ORDER BY r.position""",
                (str(turn_id),),
            ).fetchall()
        return {
            "id": row["id"], "conversation_id": row["conversation_id"],
            "user_message_id": row["user_message_id"],
            "assistant_message_id": row["assistant_message_id"],
            "knowledge_flow": json.loads(row["knowledge_flow_json"]) if row["knowledge_flow_json"] else None,
            "created_at": row["created_at"], "completed_at": row["completed_at"],
            "memory_retrievals": [dict(item) for item in retrievals],
        }

    def _prepare_asset(self, attachment: dict, *, role: str, ordinal: int):
        content = attachment.get("content") if isinstance(attachment, dict) else None
        if not isinstance(content, str) or not content.startswith("data:"):
            return None
        match = re.fullmatch(r"data:([a-z0-9.+-]+/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\r\n]+)", content, re.I)
        if not match:
            return None
        media_type = match.group(1).casefold()
        allowed_documents = {
            "text/plain", "text/markdown", "text/csv", "application/json",
            "application/yaml", "application/pdf", "application/xml",
        }
        if not (media_type.startswith("image/") or media_type.startswith("video/") or media_type in allowed_documents):
            return None
        try:
            body = base64.b64decode(match.group(2), validate=True)
        except ValueError:
            return None
        if not body or len(body) > 20 * 1024 * 1024:
            return None
        asset_id = str(uuid.uuid4())
        requested_name = Path(str(attachment.get("filename") or "")).name
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
                  "text/plain": ".txt", "text/markdown": ".md", "text/csv": ".csv",
                  "application/json": ".json", "application/yaml": ".yaml",
                  "application/pdf": ".pdf", "application/xml": ".xml"}.get(media_type, ".bin")
        item = {
            "id": asset_id, "role": role, "media_type": media_type,
            "filename": asset_id + suffix, "byte_size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "ordinal": ordinal,
            "metadata": {
                "type": attachment.get("type", "image"),
                "source": attachment.get("source", role),
                "description": attachment.get("description"),
                "display_name": requested_name or None,
                **{
                    key: attachment[key] for key in (
                        "action_index", "operation", "entity_id",
                        "result_status", "result_reference",
                    ) if key in attachment
                },
            },
        }
        return item, body

    def read_asset(self, asset_id: str) -> tuple[str, bytes]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT a.* FROM conversation_assets a JOIN conversations c ON c.id=a.conversation_id
                   WHERE a.id=? AND c.status!='deleted'""", (str(asset_id),),
            ).fetchone()
        if row is None:
            raise KeyError("Conversation-Asset wurde nicht gefunden")
        path = self.asset_root / str(row["filename"])
        return str(row["media_type"]), path.read_bytes()

    def asset_details(self, asset_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT a.id, a.conversation_id, a.message_id, a.media_type, a.created_at,
                          v.description, v.source, c.title AS conversation_title
                   FROM conversation_assets a
                   JOIN conversations c ON c.id=a.conversation_id
                   LEFT JOIN visual_asset_index v ON v.asset_id=a.id
                   WHERE a.id=? AND c.status!='deleted'""", (str(asset_id),),
            ).fetchone()
        if row is None:
            raise KeyError("Conversation-Asset wurde nicht gefunden")
        result = dict(row)
        result["asset_id"] = result.pop("id")
        return result

    @staticmethod
    def _visual_description(user: str, assistant: str, title: str, source: str,
                            explicit: object, created_at: str) -> str:
        parts = [
            str(explicit or "").strip(), f"Quelle: {source}", f"Conversation: {title}",
            f"Zeitpunkt: {created_at}", f"Benutzerkontext: {redact_sensitive(user)}",
            f"Antwort-/Vision-Kontext: {redact_sensitive(assistant)}",
        ]
        return " | ".join(re.sub(r"\s+", " ", part)[:800] for part in parts if part)[:2400]

    @staticmethod
    def _visual_embedding(text: str) -> bytes:
        # Reuse the deterministic local semantic representation used by Memory.
        from .memory import lexical_vector
        return json.dumps(lexical_vector(text), separators=(",", ":")).encode()

    def store_artifacts(self, conversation_id: str, message_id: str, artifacts: list[dict]) -> list[dict]:
        stored = []
        for artifact in artifacts:
            encoded = artifact.get("base64") if isinstance(artifact, dict) else None
            if not isinstance(encoded, str):
                continue
            try:
                body = base64.b64decode(encoded, validate=True)
            except ValueError:
                continue
            if not body or len(body) > 20 * 1024 * 1024:
                continue
            media_type = str(artifact.get("mime") or "application/octet-stream").casefold()
            display_name = Path(str(artifact.get("filename") or "eve-download.bin")).name
            asset_id = str(uuid.uuid4())
            suffix = Path(display_name).suffix[:12] or ".bin"
            filename = asset_id + suffix
            path = self.asset_root / filename
            path.write_bytes(body)
            os.chmod(path, 0o600)
            try:
                with self.database.connect() as connection:
                    ordinal = int(connection.execute(
                        "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM conversation_assets WHERE message_id=?",
                        (str(message_id),),
                    ).fetchone()[0])
                    connection.execute(
                        """INSERT INTO conversation_assets
                           (id,conversation_id,message_id,media_type,filename,byte_size,sha256,ordinal,created_at,metadata_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (asset_id, str(conversation_id), str(message_id), media_type, filename, len(body),
                         hashlib.sha256(body).hexdigest(), ordinal, _now(),
                         json.dumps({"type": "attachment", "display_name": display_name}, ensure_ascii=False)),
                    )
                    if media_type.startswith("image/"):
                        context = connection.execute(
                            """SELECT m.content, c.title FROM messages m JOIN conversations c
                               ON c.id=m.conversation_id WHERE m.id=? AND c.id=?""",
                            (str(message_id), str(conversation_id)),
                        ).fetchone()
                        description = self._visual_description(
                            str(context["content"] if context else ""), "",
                            str(context["title"] if context else ""), "generated",
                            display_name, _now(),
                        )
                        connection.execute(
                            """INSERT INTO visual_asset_index
                               (asset_id,description,source,embedding,created_at) VALUES (?,?,?,?,?)""",
                            (asset_id, description, "generated", self._visual_embedding(description), _now()),
                        )
            except Exception:
                path.unlink(missing_ok=True)
                raise
            stored.append({"id": asset_id, "url": f"/api/conversation-assets/{asset_id}"})
        return stored

    @staticmethod
    def _asset_dict(row: sqlite3.Row) -> dict:
        metadata = json.loads(row["metadata_json"])
        return {
            "id": row["id"], "media_type": row["media_type"], "byte_size": row["byte_size"],
            "sha256": row["sha256"], "ordinal": row["ordinal"],
            "url": f"/api/conversation-assets/{row['id']}", "metadata": metadata,
            "filename": metadata.get("display_name"),
        }

    @staticmethod
    def _tool_event_dict(row: sqlite3.Row) -> dict:
        result = {
            "id": row["id"], "ordinal": row["ordinal"], "tool": row["tool"],
            "status": row["status"], "summary": row["summary"],
            "input": json.loads(row["input_json"]), "result": json.loads(row["result_json"]),
            "created_at": row["created_at"], "historical": True,
        }
        provenance = result["input"].get("technical_provenance")
        if isinstance(provenance, dict):
            result["provenance"] = provenance
        return result

    @staticmethod
    def _clean_title(title: str) -> str:
        clean = re.sub(r"\s+", " ", str(title)).strip()
        if not clean:
            raise ValueError("Titel darf nicht leer sein")
        if len(clean) > 120:
            raise ValueError("Titel darf höchstens 120 Zeichen lang sein")
        return clean

    @staticmethod
    def _title_from_message(message: str) -> str:
        clean = re.sub(r"\s+", " ", redact_sensitive(message)).strip()
        return (clean[:77].rstrip() + "…") if len(clean) > 78 else (clean or "Neue Unterhaltung")

    @staticmethod
    def _conversation_dict(row: sqlite3.Row) -> dict:
        result = {
            "id": row["id"], "title": row["title"], "status": row["status"],
            "source": row["source"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        if "message_count" in row.keys():
            result["message_count"] = int(row["message_count"])
        return result

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "conversation_id": row["conversation_id"], "role": row["role"],
            "content": row["content"], "kind": row["kind"], "ordinal": row["ordinal"],
            "created_at": row["created_at"], "metadata": json.loads(row["metadata_json"]),
            "turn_id": row["turn_id"],
        }
