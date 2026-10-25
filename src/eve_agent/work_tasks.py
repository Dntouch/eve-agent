from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from .memory import redact_sensitive
from .search import fts_query
from .provider_schemas import work_task_operations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value, label: str, maximum: int, *, required: bool = False, multiline: bool = False) -> str | None:
    if value is None and not required:
        return None
    raw = str(value or "")
    text = redact_sensitive(raw.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                            if multiline else re.sub(r"\s+", " ", raw).strip())
    if not text.strip():
        text = ""
    if required and not text:
        raise ValueError(f"{label} darf nicht leer sein")
    if len(text) > maximum:
        raise ValueError(f"{label} darf höchstens {maximum} Zeichen lang sein")
    return text or None


class WorkTaskStore:
    """Persistence for non-scheduled work lists and work items."""

    def __init__(self, database):
        self.database = database

    def create_list(self, name: str, description: str | None = None, *, metadata: dict | None = None) -> dict:
        identifier, now = str(uuid.uuid4()), _now()
        clean_name = _clean_text(name, "Listenname", 120, required=True)
        clean_description = _clean_text(description, "Beschreibung", 2000, multiline=True)
        with self.database.connect() as connection:
            deleted = connection.execute(
                "SELECT id FROM work_task_lists WHERE name=? COLLATE NOCASE AND status='deleted'",
                (clean_name,),
            ).fetchone()
            if deleted is not None:
                identifier = deleted["id"]
                connection.execute(
                    """UPDATE work_task_lists
                       SET name=?, description=?, status='active', created_at=?, updated_at=?, metadata_json=?
                       WHERE id=? AND status='deleted'""",
                    (clean_name, clean_description, now, now,
                     json.dumps(metadata or {}, ensure_ascii=False), identifier),
                )
            else:
                try:
                    connection.execute(
                        """INSERT INTO work_task_lists
                           (id, name, description, created_at, updated_at, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (identifier, clean_name, clean_description, now, now,
                         json.dumps(metadata or {}, ensure_ascii=False)),
                    )
                except Exception as exc:
                    if "UNIQUE constraint failed" in str(exc):
                        raise ValueError("Eine Arbeitsliste mit diesem Namen existiert bereits") from exc
                    raise
        return self.get_list(identifier)

    def create_list_with_items(
        self, name: str, items: list[dict], description: str | None = None,
        *, metadata: dict | None = None, context_link: dict | None = None,
    ) -> dict:
        """Create a new list and its initial items in one transaction."""
        identifier, now = str(uuid.uuid4()), _now()
        clean_name = _clean_text(name, "Listenname", 120, required=True)
        clean_description = _clean_text(description, "Beschreibung", 2000, multiline=True)
        prepared = self._prepare_items(items)
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM work_task_lists WHERE name=? COLLATE NOCASE AND status='active'",
                (clean_name,),
            ).fetchone()
            if existing is not None:
                raise ValueError("Eine Arbeitsliste mit diesem Namen existiert bereits")
            deleted = connection.execute(
                "SELECT id FROM work_task_lists WHERE name=? COLLATE NOCASE AND status='deleted'",
                (clean_name,),
            ).fetchone()
            if deleted is not None:
                identifier = deleted["id"]
                connection.execute(
                    """UPDATE work_task_lists
                       SET name=?, description=?, status='active', created_at=?, updated_at=?, metadata_json=?
                       WHERE id=? AND status='deleted'""",
                    (clean_name, clean_description, now, now,
                     json.dumps(metadata or {}, ensure_ascii=False), identifier),
                )
            else:
                connection.execute(
                    """INSERT INTO work_task_lists
                       (id, name, description, created_at, updated_at, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (identifier, clean_name, clean_description, now, now,
                     json.dumps(metadata or {}, ensure_ascii=False)),
                )
            result = self._insert_items(
                connection, identifier, clean_name, prepared, context_link=context_link,
            )
        return result

    def list_lists(self, *, include_archived: bool = False, limit: int | None = None) -> list[dict]:
        where = "status!='deleted'" if include_archived else "status='active'"
        sql = f"""SELECT l.*, count(CASE WHEN w.status='open' THEN 1 END) AS open_count
                    FROM work_task_lists l LEFT JOIN work_items w ON w.list_id=l.id
                    WHERE l.{where} GROUP BY l.id ORDER BY l.name COLLATE NOCASE"""
        parameters = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (max(int(limit), 1),)
        with self.database.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._list_dict(row) for row in rows]

    def get_list(self, list_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_task_lists WHERE id=? AND status!='deleted'", (str(list_id),)
            ).fetchone()
        if row is None:
            raise KeyError("Arbeitsliste wurde nicht gefunden")
        return self._list_dict(row)

    def delete_list(self, list_id: str) -> dict:
        current = self.get_list(list_id)
        now = _now()
        with self.database.connect() as connection:
            item_rows = connection.execute(
                "SELECT id FROM work_items WHERE list_id=? AND status!='deleted'", (str(list_id),)
            ).fetchall()
            for row in item_rows:
                self._event(connection, row["id"], "deleted", {"reason": "list_deleted"})
                connection.execute(
                    "DELETE FROM work_item_context_links WHERE work_item_id=?", (row["id"],)
                )
            connection.execute(
                "UPDATE work_items SET status='deleted', updated_at=? WHERE list_id=? AND status!='deleted'",
                (now, str(list_id)),
            )
            connection.execute(
                "UPDATE work_task_lists SET status='deleted', updated_at=? WHERE id=? AND status!='deleted'",
                (now, str(list_id)),
            )
        return {"id": current["id"], "name": current["name"], "deleted_items": len(item_rows)}

    def create_item(
        self, list_id: str, title: str, description: str | None = None, *,
        status: str = "open", metadata: dict | None = None,
        context_link: dict | None = None,
    ) -> dict:
        if status not in {"open", "completed"}:
            raise ValueError("Ungültiger Aufgabenstatus")
        self.get_list(list_id)
        identifier, now = str(uuid.uuid4()), _now()
        completed_at = now if status == "completed" else None
        with self.database.connect() as connection:
            position = connection.execute(
                "SELECT coalesce(max(position), -1) + 1 FROM work_items WHERE list_id=? AND status=?",
                (str(list_id), status),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO work_items
                   (id, list_id, title, description, status, created_at, updated_at,
                    completed_at, metadata_json, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, str(list_id), _clean_text(title, "Aufgabentitel", 240, required=True),
                 _clean_text(description, "Beschreibung", 5000, multiline=True), status, now, now, completed_at,
                 json.dumps(metadata or {}, ensure_ascii=False), position),
            )
            self._event(connection, identifier, "created", {"status": status})
            if context_link:
                self._insert_context_link(connection, identifier, **context_link)
        return self.get_item(identifier)

    def create_items(self, list_id: str, items: list[dict], *, context_link: dict | None = None) -> dict:
        """Create several open items atomically and skip title duplicates."""
        prepared = self._prepare_items(items)
        with self.database.connect() as connection:
            task_list = connection.execute(
                "SELECT id, name FROM work_task_lists WHERE id=? AND status='active'",
                (str(list_id),),
            ).fetchone()
            if task_list is None:
                raise KeyError("Arbeitsliste wurde nicht gefunden")
            return self._insert_items(
                connection, str(list_id), task_list["name"], prepared,
                context_link=context_link,
            )

    @staticmethod
    def _prepare_items(items: list[dict]) -> list[dict]:
        if not isinstance(items, list) or not 1 <= len(items) <= 25:
            raise ValueError("Es müssen zwischen 1 und 25 Arbeitsaufgaben angegeben werden")
        prepared: list[dict] = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {"title", "description"}:
                raise ValueError("Jede Arbeitsaufgabe benötigt Titel und optional Beschreibung")
            prepared.append({
                "title": _clean_text(item.get("title"), "Aufgabentitel", 240, required=True),
                "description": _clean_text(item.get("description"), "Beschreibung", 5000, multiline=True),
            })
        return prepared

    def _insert_items(
        self, connection, list_id: str, list_name: str, prepared: list[dict],
        *, context_link: dict | None = None,
    ) -> dict:
        created_ids: list[str] = []
        results: list[dict] = []
        existing = {
            str(row["title"]).casefold(): {"id": row["id"], "title": row["title"]}
            for row in connection.execute(
                "SELECT id, title FROM work_items WHERE list_id=? AND status!='deleted'",
                (str(list_id),),
            )
        }
        position = int(connection.execute(
            "SELECT coalesce(max(position), -1) + 1 FROM work_items WHERE list_id=? AND status='open'",
            (str(list_id),),
        ).fetchone()[0])
        now = _now()
        for item in prepared:
            key = str(item["title"]).casefold()
            duplicate = existing.get(key)
            if duplicate is not None:
                results.append({**duplicate, "status": "already_exists"})
                continue
            identifier = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO work_items
                   (id, list_id, title, description, status, created_at, updated_at,
                    completed_at, metadata_json, position)
                   VALUES (?, ?, ?, ?, 'open', ?, ?, NULL, '{}', ?)""",
                (identifier, str(list_id), item["title"], item["description"], now, now, position),
            )
            self._event(connection, identifier, "created", {"status": "open", "batch": True})
            if context_link:
                self._insert_context_link(connection, identifier, **context_link)
            result = {"id": identifier, "title": item["title"], "status": "created"}
            results.append(result)
            existing[key] = result
            created_ids.append(identifier)
            position += 1
        return {
            "list_id": str(list_id), "list_name": str(list_name), "items": results,
            "created_count": len(created_ids),
            "existing_count": len(results) - len(created_ids),
        }

    def list_items(
        self, *, list_id: str | None = None, status: str | None = "open", limit: int | None = None,
    ) -> list[dict]:
        clauses, params = ["w.status!='deleted'", "l.status!='deleted'"], []
        if list_id is not None:
            self.get_list(list_id)
            clauses.append("w.list_id=?")
            params.append(str(list_id))
        if status is not None:
            if status not in {"open", "completed"}:
                raise ValueError("Ungültiger Aufgabenstatus")
            clauses.append("w.status=?")
            params.append(status)
        sql = f"""SELECT w.*, l.name AS list_name FROM work_items w
                    JOIN work_task_lists l ON l.id=w.list_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY l.name COLLATE NOCASE,
                             CASE w.status WHEN 'open' THEN 0 ELSE 1 END,
                             w.position, w.updated_at DESC, w.id"""
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(int(limit), 1))
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            links = self._context_links(connection, [row["id"] for row in rows])
        return [self._item_dict(row, links.get(row["id"], [])) for row in rows]

    def get_item(self, item_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT w.*, l.name AS list_name FROM work_items w
                   JOIN work_task_lists l ON l.id=w.list_id
                   WHERE w.id=? AND w.status!='deleted' AND l.status!='deleted'""",
                (str(item_id),),
            ).fetchone()
            links = self._context_links(connection, [str(item_id)]) if row is not None else {}
        if row is None:
            raise KeyError("Arbeitsaufgabe wurde nicht gefunden")
        return self._item_dict(row, links.get(str(item_id), []))

    def update_item(self, item_id: str, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("Änderungen müssen ein Objekt sein")
        allowed = {"list_id", "title", "description", "status", "metadata"}
        if not changes or set(changes) - allowed:
            raise ValueError("Unbekannte oder leere Aufgabenänderung")
        current = self.get_item(item_id)
        list_id = str(changes.get("list_id", current["list_id"]))
        if "list_id" in changes:
            self.get_list(list_id)
        title = _clean_text(changes.get("title", current["title"]), "Aufgabentitel", 240, required=True)
        description = _clean_text(changes.get("description", current["description"]), "Beschreibung", 5000, multiline=True)
        status = str(changes.get("status", current["status"])).casefold()
        if status not in {"open", "completed"}:
            raise ValueError("Ungültiger Aufgabenstatus")
        metadata = changes.get("metadata", current["metadata"])
        if not isinstance(metadata, dict):
            raise ValueError("Metadaten müssen ein Objekt sein")
        now = _now()
        completed_at = current["completed_at"]
        if status == "completed" and current["status"] != "completed":
            completed_at = now
        elif status == "open":
            completed_at = None
        changed = {
            key: value for key, value in {
                "list_id": list_id, "title": title, "description": description, "status": status,
            }.items() if value != current.get(key)
        }
        with self.database.connect() as connection:
            position = current["position"]
            if list_id != current["list_id"] or status != current["status"]:
                position = connection.execute(
                    """SELECT coalesce(max(position), -1) + 1 FROM work_items
                       WHERE list_id=? AND status=? AND status!='deleted' AND id!=?""",
                    (list_id, status, str(item_id)),
                ).fetchone()[0]
            connection.execute(
                """UPDATE work_items SET list_id=?, title=?, description=?, status=?,
                   updated_at=?, completed_at=?, metadata_json=?, position=?
                   WHERE id=? AND status!='deleted'""",
                (list_id, title, description, status, now, completed_at,
                 json.dumps(metadata, ensure_ascii=False), position, str(item_id)),
            )
            if changed or metadata != current["metadata"]:
                event = "completed" if status == "completed" and current["status"] != status else (
                    "reopened" if status == "open" and current["status"] != status else "updated"
                )
                self._event(connection, str(item_id), event, changed)
        return self.get_item(item_id)

    def complete_item(self, item_id: str) -> dict:
        return self.update_item(item_id, {"status": "completed"})

    def reopen_item(self, item_id: str) -> dict:
        return self.update_item(item_id, {"status": "open"})

    def delete_item(self, item_id: str) -> dict:
        current = self.get_item(item_id)
        now = _now()
        with self.database.connect() as connection:
            self._event(connection, str(item_id), "deleted", {"previous_status": current["status"]})
            connection.execute(
                "DELETE FROM work_item_context_links WHERE work_item_id=?", (str(item_id),)
            )
            connection.execute(
                "UPDATE work_items SET status='deleted', updated_at=? WHERE id=? AND status!='deleted'",
                (now, str(item_id)),
            )
        return {"id": current["id"], "title": current["title"], "list_name": current["list_name"]}

    def move_item(self, item_id: str, target_list_id: str, target_position: int) -> dict:
        if isinstance(target_position, bool) or not isinstance(target_position, int):
            raise ValueError("Zielposition muss eine ganze Zahl sein")
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT w.id, w.list_id, w.title, w.status FROM work_items w
                   JOIN work_task_lists l ON l.id=w.list_id
                   WHERE w.id=? AND w.status!='deleted' AND l.status='active'""",
                (str(item_id),),
            ).fetchone()
            if current is None:
                raise KeyError("Arbeitsaufgabe wurde nicht gefunden")
            if current["status"] != "open":
                raise ValueError("Nur offene Arbeitsaufgaben können sortiert werden")
            target_list = connection.execute(
                "SELECT id FROM work_task_lists WHERE id=? AND status='active'", (str(target_list_id),)
            ).fetchone()
            if target_list is None:
                raise KeyError("Ziel-Arbeitsliste wurde nicht gefunden")

            source_ids = [row["id"] for row in connection.execute(
                """SELECT id FROM work_items WHERE list_id=? AND status='open' AND id!=?
                   ORDER BY position, updated_at DESC, id""",
                (current["list_id"], str(item_id)),
            )]
            if str(target_list_id) == current["list_id"]:
                target_ids = source_ids
            else:
                target_ids = [row["id"] for row in connection.execute(
                    """SELECT id FROM work_items WHERE list_id=? AND status='open' AND id!=?
                       ORDER BY position, updated_at DESC, id""",
                    (str(target_list_id), str(item_id)),
                )]
            if target_position < 0 or target_position > len(target_ids):
                raise ValueError("Zielposition liegt außerhalb der Arbeitsliste")
            target_ids.insert(target_position, str(item_id))

            if str(target_list_id) != current["list_id"]:
                for position, sibling_id in enumerate(source_ids):
                    connection.execute("UPDATE work_items SET position=? WHERE id=?", (position, sibling_id))
            for position, sibling_id in enumerate(target_ids):
                if sibling_id == str(item_id):
                    connection.execute(
                        "UPDATE work_items SET list_id=?, position=?, updated_at=? WHERE id=?",
                        (str(target_list_id), position, now, sibling_id),
                    )
                else:
                    connection.execute("UPDATE work_items SET position=? WHERE id=?", (position, sibling_id))
            self._event(connection, str(item_id), "moved", {
                "from_list_id": current["list_id"], "to_list_id": str(target_list_id),
                "position": target_position,
            })
        return self.get_item(item_id)

    def search_items(self, query: str, *, status: str | None = None,
                     limit: int | None = None) -> list[dict]:
        clauses = ["work_items_fts MATCH ?", "w.status!='deleted'", "l.status!='deleted'"]
        params: list[object] = [fts_query(query)]
        if status is not None:
            if status not in {"open", "completed"}:
                raise ValueError("Ungültiger Aufgabenstatus")
            clauses.append("w.status=?")
            params.append(status)
        sql = f"""SELECT w.*, l.name AS list_name, bm25(work_items_fts) AS rank
                    FROM work_items_fts JOIN work_items w ON w.id=work_items_fts.work_item_id
                    JOIN work_task_lists l ON l.id=w.list_id
                    WHERE {' AND '.join(clauses)} ORDER BY rank, w.updated_at DESC"""
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(int(limit), 1))
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            links = self._context_links(connection, [row["id"] for row in rows])
        return [self._item_dict(row, links.get(row["id"], [])) for row in rows]

    def add_context_link(
        self, item_id: str, conversation_id: str, *, start_message_id: str | None = None,
        end_message_id: str | None = None, label: str | None = None, source: str = "manual",
    ) -> dict:
        with self.database.connect() as connection:
            identifier = self._insert_context_link(
                connection, str(item_id), conversation_id=str(conversation_id),
                start_message_id=start_message_id, end_message_id=end_message_id,
                label=label, source=source,
            )
            links = self._context_links(connection, [str(item_id)])
        return next(link for link in links[str(item_id)] if link["id"] == identifier)

    def remove_context_link(self, item_id: str, link_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM work_item_context_links WHERE id=? AND work_item_id=?",
                (str(link_id), str(item_id)),
            )
        if cursor.rowcount != 1:
            raise KeyError("Kontextverknüpfung wurde nicht gefunden")
        return True

    def items_for_conversation(self, conversation_id: str) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT w.*, l.name AS list_name FROM work_item_context_links x
                   JOIN work_items w ON w.id=x.work_item_id
                   JOIN work_task_lists l ON l.id=w.list_id
                   WHERE x.conversation_id=? AND w.status!='deleted' AND l.status!='deleted'
                   ORDER BY w.updated_at DESC, w.id""",
                (str(conversation_id),),
            ).fetchall()
            links = self._context_links(connection, [row["id"] for row in rows])
        return [self._item_dict(row, links.get(row["id"], [])) for row in rows]

    def add_conversation_context(
        self, item_id: str, conversation_id: str, *, scope: str = "current_turn",
        count: int | None = None, label: str | None = None,
    ) -> dict:
        """Resolve an explicit structural scope and append its link to an existing item."""
        if scope == "conversation":
            return self.add_context_link(
                item_id, conversation_id, label=label, source="assistant",
            )
        if scope not in {"current_turn", "last_messages", "last_turns"}:
            raise ValueError("Ungültige Kontextgranularität")
        requested = 1 if scope == "current_turn" else count
        if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= 50:
            raise ValueError("Die Kontextanzahl muss zwischen 1 und 50 liegen")
        with self.database.connect() as connection:
            conversation = connection.execute(
                "SELECT id FROM conversations WHERE id=? AND status!='deleted'", (str(conversation_id),)
            ).fetchone()
            if conversation is None:
                raise KeyError("Konversation wurde nicht gefunden")
            if scope == "last_messages":
                rows = connection.execute(
                    """SELECT id, ordinal FROM messages WHERE conversation_id=?
                       ORDER BY ordinal DESC LIMIT ?""",
                    (str(conversation_id), requested),
                ).fetchall()
            else:
                turn_rows = connection.execute(
                    """SELECT t.id, max(m.ordinal) AS last_ordinal FROM turns t
                       JOIN messages m ON m.turn_id=t.id
                       WHERE t.conversation_id=? GROUP BY t.id
                       ORDER BY last_ordinal DESC, t.id DESC LIMIT ?""",
                    (str(conversation_id), requested),
                ).fetchall()
                turn_ids = [row["id"] for row in turn_rows]
                if not turn_ids:
                    rows = connection.execute(
                        """SELECT id, ordinal FROM messages WHERE conversation_id=?
                           ORDER BY ordinal DESC LIMIT 1""",
                        (str(conversation_id),),
                    ).fetchall()
                else:
                    placeholders = ",".join("?" for _ in turn_ids)
                    rows = connection.execute(
                        f"""SELECT id, ordinal FROM messages WHERE conversation_id=?
                            AND turn_id IN ({placeholders}) ORDER BY ordinal DESC""",
                        [str(conversation_id), *turn_ids],
                    ).fetchall()
        if not rows:
            raise ValueError("Die Konversation enthält noch keinen verknüpfbaren Kontext")
        ordered = sorted(rows, key=lambda row: int(row["ordinal"]))
        start_message_id = ordered[0]["id"]
        end_message_id = ordered[-1]["id"] if len(ordered) > 1 else None
        return self.add_context_link(
            item_id, conversation_id, start_message_id=start_message_id,
            end_message_id=end_message_id, label=label, source="assistant",
        )

    @staticmethod
    def _insert_context_link(
        connection, item_id: str, *, conversation_id: str,
        start_message_id: str | None = None, end_message_id: str | None = None,
        label: str | None = None, source: str = "manual",
    ) -> str:
        if source not in {"manual", "task_creation", "assistant"}:
            raise ValueError("Ungültige Quelle der Kontextverknüpfung")
        task = connection.execute(
            "SELECT id FROM work_items WHERE id=? AND status!='deleted'", (str(item_id),)
        ).fetchone()
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id=? AND status!='deleted'", (str(conversation_id),)
        ).fetchone()
        if task is None:
            raise KeyError("Arbeitsaufgabe wurde nicht gefunden")
        if conversation is None:
            raise KeyError("Konversation wurde nicht gefunden")
        if end_message_id and not start_message_id:
            raise ValueError("Ein Bereich benötigt eine Startnachricht")
        ordinals: list[int] = []
        for message_id in (start_message_id, end_message_id):
            if not message_id:
                continue
            message = connection.execute(
                "SELECT conversation_id, ordinal FROM messages WHERE id=?", (str(message_id),)
            ).fetchone()
            if message is None or message["conversation_id"] != str(conversation_id):
                raise ValueError("Die referenzierte Nachricht gehört nicht zur Konversation")
            ordinals.append(int(message["ordinal"]))
        if len(ordinals) == 2 and ordinals[1] < ordinals[0]:
            raise ValueError("Das Ende des Kontextbereichs liegt vor seinem Anfang")
        clean_label = _clean_text(label, "Kontextlabel", 120)
        existing = connection.execute(
            """SELECT id FROM work_item_context_links WHERE work_item_id=? AND conversation_id=?
               AND start_message_id IS ? AND end_message_id IS ?""",
            (str(item_id), str(conversation_id), start_message_id, end_message_id),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        identifier = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO work_item_context_links
               (id, work_item_id, conversation_id, start_message_id, end_message_id,
                label, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (identifier, str(item_id), str(conversation_id), start_message_id, end_message_id,
             clean_label, source, _now()),
        )
        return identifier

    @staticmethod
    def _context_links(connection, item_ids: list[str]) -> dict[str, list[dict]]:
        result = {str(item_id): [] for item_id in item_ids}
        if not item_ids:
            return result
        placeholders = ",".join("?" for _ in item_ids)
        rows = connection.execute(
            f"""SELECT x.*, c.title AS conversation_title,
                       sm.ordinal AS start_ordinal, em.ordinal AS end_ordinal
                FROM work_item_context_links x
                JOIN conversations c ON c.id=x.conversation_id AND c.status!='deleted'
                LEFT JOIN messages sm ON sm.id=x.start_message_id
                LEFT JOIN messages em ON em.id=x.end_message_id
                WHERE x.work_item_id IN ({placeholders})
                ORDER BY x.created_at, x.id""",
            [str(item_id) for item_id in item_ids],
        ).fetchall()
        for row in rows:
            result[row["work_item_id"]].append({
                "id": row["id"], "work_item_id": row["work_item_id"],
                "conversation_id": row["conversation_id"],
                "conversation_title": row["conversation_title"],
                "start_message_id": row["start_message_id"], "end_message_id": row["end_message_id"],
                "start_ordinal": row["start_ordinal"], "end_ordinal": row["end_ordinal"],
                "label": row["label"], "source": row["source"], "created_at": row["created_at"],
            })
        return result

    def events(self, item_id: str, *, limit: int | None = None) -> list[dict]:
        self.get_item(item_id)
        suffix = ""
        parameters: list[object] = [str(item_id)]
        if limit is not None:
            suffix = " LIMIT ?"
            parameters.append(max(0, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id, event_type, changes_json, created_at FROM work_item_events
                   WHERE work_item_id=? ORDER BY id DESC""" + suffix,
                parameters,
            ).fetchall()
        return [{"id": row["id"], "event_type": row["event_type"],
                 "changes": json.loads(row["changes_json"]), "created_at": row["created_at"]} for row in rows]

    @staticmethod
    def _event(connection, item_id: str, event_type: str, changes: dict) -> None:
        connection.execute(
            "INSERT INTO work_item_events(work_item_id, event_type, changes_json, created_at) VALUES (?, ?, ?, ?)",
            (item_id, event_type, json.dumps(changes, ensure_ascii=False), _now()),
        )

    @staticmethod
    def _list_dict(row) -> dict:
        result = {"id": row["id"], "name": row["name"], "description": row["description"],
                  "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
                  "metadata": json.loads(row["metadata_json"])}
        if "open_count" in row.keys():
            result["open_count"] = int(row["open_count"])
        return result

    @staticmethod
    def _item_dict(row, context_links: list[dict] | None = None) -> dict:
        result = {"id": row["id"], "list_id": row["list_id"], "title": row["title"],
                  "description": row["description"], "status": row["status"],
                  "position": int(row["position"]),
                  "created_at": row["created_at"], "updated_at": row["updated_at"],
                  "completed_at": row["completed_at"], "metadata": json.loads(row["metadata_json"])}
        result["context_links"] = context_links or []
        if "list_name" in row.keys():
            result["list_name"] = row["list_name"]
        return result


class WorkTaskCapability:
    """Model-planned boundary for work-list operations; the store remains semantic-free."""

    OPERATIONS = {
        "create_list", "create_list_with_items", "list_lists", "create_item", "create_items", "list_items", "get_item",
        "update_item", "complete_item", "reopen_item", "delete_item", "delete_list",
        "search_items", "add_context_link", "clarify",
    }

    OPERATION_DESCRIPTIONS = {
        "create_list": "Eine neue leere Aufgabenliste anlegen.",
        "create_list_with_items": (
            "Eine neue Aufgabenliste zusammen mit allen ausdrücklich genannten Aufgaben oder "
            "Teilaufgaben atomar anlegen."
        ),
        "list_lists": "Bestehende Aufgabenlisten und ihre Anzahlen anzeigen.",
        "delete_list": "Delete one existing published work list and all work items contained in it.",
        "create_item": "Eine neue Aufgabe zu einer bestehenden Aufgabenliste hinzufügen.",
        "create_items": (
            "Mehrere ausdrücklich genannte Aufgaben oder Teilaufgaben atomar zu einer bestehenden "
            "Aufgabenliste hinzufügen."
        ),
        "list_items": "Den aktuellen Inhalt und Aufgaben einer veröffentlichten Aufgabenliste anzeigen.",
        "search_items": "Find existing work items before reading or changing one by ID.",
        "add_context_link": (
            "Append explicitly requested chat context to one existing work item found by "
            "search_items; never create or replace a work item and never infer a larger semantic "
            "range."
        ),
        "get_item": "Read one existing item found by search_items.",
        "update_item": "Change fields of one existing item found by search_items; never use to add a new item.",
        "complete_item": "Mark one existing item found by search_items as completed.",
        "reopen_item": "Reopen one completed item found by search_items.",
        "delete_item": "Delete one existing item found by search_items.",
    }

    MUTATION_RESULT_IDS = {
        "create_list_with_items": lambda result: [
            item["id"] for item in result["items"] if item["status"] == "created"
        ],
        "create_item": lambda result: [result["id"]],
        "create_items": lambda result: [
            item["id"] for item in result["items"] if item["status"] == "created"
        ],
        "update_item": lambda result: [result["id"]],
        "complete_item": lambda result: [result["id"]],
        "reopen_item": lambda result: [result["id"]],
    }

    def __init__(self, store: WorkTaskStore, llm):
        self.store, self.llm = store, llm
        self._mutated_item_ids: list[str] = []
        self._conversation_items: dict[str, list[str]] = {}

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [
            RuntimeSelfDescription(
                "work_tasks.read", "tasks.read",
                "Ich kann Arbeitsaufgaben und Aufgabenlisten suchen und anzeigen.",
                "WorkTaskCapability", "list_lists,list_items,search_items,get_item",
            ),
            RuntimeSelfDescription(
                "work_tasks.write", "tasks.write",
                "Ich kann Arbeitsaufgaben und Aufgabenlisten erstellen und verändern.",
                "WorkTaskCapability",
                "create_list,create_item,create_items,update_item,complete_item,reopen_item,delete_item,delete_list",
            ),
            RuntimeSelfDescription(
                "work_tasks.context", "tasks.context",
                "Ich kann Arbeitsaufgaben mit Chat-Kontext verknüpfen.",
                "WorkTaskCapability", "add_context_link",
            ),
        ]

    def has_active_context(self, conversation_id: str | None) -> bool:
        return bool(conversation_id and self._conversation_items.get(str(conversation_id)))

    def minimal_contract(self, conversation_id: str | None = None, discoveries: list[dict] | None = None) -> dict:
        return {
            "description": "Arbeitslisten und Arbeitsaufgaben lesen, erstellen und verändern.",
            "operations": work_task_operations(self.OPERATION_DESCRIPTIONS),
            "lists": [{"id": item["id"], "name": item["name"],
                       "open_count": item.get("open_count", 0)}
                      for item in self.store.list_lists(include_archived=False)],
            "discoveries": list(discoveries or []),
            "active_items": self._active_items(conversation_id),
            "recent_message_references": self._message_references(conversation_id),
        }

    def execute_operation(self, operation: str, arguments: dict, *, conversation_id: str | None = None,
                          discoveries: list[dict] | None = None) -> dict:
        self._mutated_item_ids = []
        discoveries = discoveries if discoveries is not None else []
        context = self.minimal_contract(conversation_id, discoveries)
        if operation not in self.OPERATIONS or operation == "clarify" or not isinstance(arguments, dict):
            raise ValueError("Nicht veröffentlichte Arbeitslisten-Operation")
        if operation == "search_items":
            results = self.store.search_items(
                str(arguments.get("query", "")), status=arguments.get("status"),
            )
            published = [self._published_item(item) for item in results]
            discoveries.append({"query": arguments.get("query"), "items": published})
            return {"answer": "" if results else "Ich habe keine passende Arbeitsaufgabe gefunden.",
                    "result": published, "discoveries": discoveries, "needs_selection": bool(results)}
        result = self._execute(operation, arguments, context, conversation_id=conversation_id)
        extractor = self.MUTATION_RESULT_IDS.get(operation)
        if extractor is not None:
            self._mutated_item_ids.extend(item_id for item_id in extractor(result) if item_id not in self._mutated_item_ids)
            if conversation_id and self._mutated_item_ids:
                self._conversation_items[str(conversation_id)] = list(self._mutated_item_ids)
        elif operation == "get_item" and conversation_id:
            self._conversation_items[str(conversation_id)] = [str(result["id"])]
        return {"answer": self._answer(operation, result), "result": result, "discoveries": discoveries}

    def _message_references(self, conversation_id: str | None) -> list[dict]:
        if not conversation_id:
            return []
        with self.store.database.connect() as connection:
            rows = connection.execute(
                """SELECT id, role, ordinal, turn_id FROM messages
                   WHERE conversation_id=? ORDER BY ordinal DESC""",
                (str(conversation_id),),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def _active_items(self, conversation_id: str | None) -> list[dict]:
        result = []
        for item_id in self._conversation_items.get(str(conversation_id), []) if conversation_id else []:
            try:
                result.append(self._published_item(self.store.get_item(item_id)))
            except KeyError:
                continue
        return result

    @staticmethod
    def _published_item(item: dict) -> dict:
        """Expose stable selection fields without task bodies or relation payloads."""
        return {
            "id": item["id"], "list_id": item["list_id"], "list_name": item.get("list_name"),
            "title": item["title"], "status": item["status"],
            "has_description": bool(item.get("description")),
        }

    def attach_mutation_provenance(self, conversation_id: str, user_message_id: str) -> list[dict]:
        """Attach one persisted triggering user message to every successfully mutated item."""
        item_ids, self._mutated_item_ids = self._mutated_item_ids, []
        return [
            self.store.add_context_link(
                item_id, conversation_id, start_message_id=user_message_id, source="assistant",
            )
            for item_id in item_ids
        ]

    def _execute(
        self, operation: str, arguments: dict, context: dict, *, conversation_id: str | None = None,
    ):
        list_ids = {item["id"] for item in context["lists"]}
        def published_list_id(*, required: bool = True):
            supplied_id = arguments.get("list_id")
            if supplied_id is not None and str(supplied_id) in list_ids:
                return str(supplied_id)
            supplied_name = str(arguments.get("list_name") or "").strip().casefold()
            if supplied_name:
                matches = [
                    item["id"] for item in context["lists"]
                    if str(item.get("name") or "").strip().casefold() == supplied_name
                ]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    raise ValueError("Der veröffentlichte Listenname ist nicht eindeutig")
            if required:
                raise ValueError("Die Arbeitsliste wurde nicht veröffentlicht")
            if supplied_id is not None or supplied_name:
                raise ValueError("Die Arbeitsliste wurde nicht veröffentlicht")
            return None
        discovery_items = context["discoveries"][-1].get("items", []) if context["discoveries"] else []
        discovered_ids = {item["id"] for item in discovery_items}
        active_ids = {item["id"] for item in context.get("active_items", [])}
        item_ids = discovered_ids | active_ids
        if operation == "create_list":
            return self.store.create_list(arguments.get("name", ""), arguments.get("description"))
        if operation == "create_list_with_items":
            return self.store.create_list_with_items(
                arguments.get("name", ""), arguments.get("items"), arguments.get("description"),
            )
        if operation == "list_lists":
            return self.store.list_lists()
        if operation == "delete_list":
            list_id = published_list_id()
            return self.store.delete_list(list_id)
        if operation == "create_item":
            list_id = published_list_id()
            return self.store.create_item(
                list_id, arguments.get("title", ""), arguments.get("description"),
            )
        if operation == "create_items":
            list_id = published_list_id()
            return self.store.create_items(list_id, arguments.get("items"))
        if operation == "list_items":
            list_id = published_list_id(required=False)
            return self.store.list_items(list_id=list_id, status=arguments.get("status", "open"))
        item_id = str(arguments.get("item_id", ""))
        if item_id not in item_ids:
            raise ValueError("Die Arbeitsaufgabe wurde nicht eindeutig über die Suche veröffentlicht")
        if operation == "get_item":
            return self.store.get_item(item_id)
        if operation in {"add_context_link", "update_item", "complete_item", "reopen_item", "delete_item"}:
            target_origin = str(arguments.get("target_origin", ""))
            valid_discovery = (
                target_origin in {"", "current_discovery"} and item_id in discovered_ids
                and (
                    len(discovery_items) == 1
                    or str(arguments.get("target_resolution", "")) == "exact"
                )
            )
            valid_active = (
                target_origin == "active_context" and len(active_ids) == 1
                and item_id in active_ids
            )
            if not (valid_discovery or valid_active):
                raise ValueError("Die Zielaufgabe ist für diese Mutation nicht eindeutig bestimmt")
        if operation == "add_context_link":
            if not conversation_id:
                raise ValueError("Es ist keine aktuelle Conversation verfügbar")
            return self.store.add_conversation_context(
                item_id, conversation_id, scope=str(arguments.get("scope", "current_turn")),
                count=arguments.get("count"), label=arguments.get("label"),
            )
        if operation == "complete_item":
            return self.store.complete_item(item_id)
        if operation == "reopen_item":
            return self.store.reopen_item(item_id)
        if operation == "delete_item":
            return self.store.delete_item(item_id)
        if operation == "update_item":
            changes = arguments.get("changes", {})
            description_message_id = arguments.get("description_message_id")
            if description_message_id is not None:
                if not conversation_id:
                    raise ValueError("Es ist keine aktuelle Conversation verfügbar")
                with self.store.database.connect() as connection:
                    message = connection.execute(
                        """SELECT content FROM messages WHERE id=? AND conversation_id=?
                           AND role='assistant'""",
                        (str(description_message_id), str(conversation_id)),
                    ).fetchone()
                if message is None:
                    raise ValueError("Die referenzierte Beschreibungsnachricht wurde nicht veröffentlicht")
                if not isinstance(changes, dict):
                    raise ValueError("Änderungen müssen ein Objekt sein")
                changes = {**changes, "description": message["content"]}
            if "list_id" in changes and str(changes["list_id"]) not in list_ids:
                raise ValueError("Die Ziel-Arbeitsliste wurde nicht veröffentlicht")
            return self.store.update_item(item_id, changes)
        raise ValueError("Arbeitslisten-Operation ist nicht ausführbar")

    @staticmethod
    def _answer(operation: str, result) -> str:
        if operation == "create_list":
            return f"Die Arbeitsliste „{result['name']}“ ist angelegt."
        if operation == "create_list_with_items":
            return WorkTaskCapability._answer("create_items", result)
        if operation == "list_lists":
            return "Arbeitslisten: " + ("; ".join(f"{x['name']} ({x.get('open_count', 0)} offen)" for x in result) if result else "keine") + "."
        if operation == "delete_list":
            return f"Die Arbeitsliste „{result['name']}“ wurde gelöscht."
        if operation == "create_item":
            return f"„{result['title']}“ steht jetzt auf der Liste „{result['list_name']}“."
        if operation == "create_items":
            lines = [
                f"{index}. {item['title']}"
                + (" (bereits vorhanden)" if item["status"] == "already_exists" else "")
                for index, item in enumerate(result["items"], 1)
            ]
            summary = f"{result['created_count']} Arbeitsaufgaben wurden auf der Liste „{result['list_name']}“ angelegt"
            if result["existing_count"]:
                summary += f"; {result['existing_count']} waren bereits vorhanden"
            return summary + ":\n" + "\n".join(lines)
        if operation == "list_items":
            if not result:
                return "Es gibt keine offenen Arbeitsaufgaben."
            return (
                f"{len(result)} offene Arbeitsaufgaben: "
                + "; ".join(f"{x['title']} [{x['list_name']}]" for x in result)
                + "."
            )
        if operation == "complete_item":
            return f"„{result['title']}“ ist als erledigt markiert."
        if operation == "reopen_item":
            return f"„{result['title']}“ ist wieder offen."
        if operation == "delete_item":
            return f"„{result['title']}“ wurde aus der Arbeitsliste gelöscht."
        if operation == "update_item":
            return f"„{result['title']}“ wurde aktualisiert."
        if operation == "add_context_link":
            return "Der Chat-Kontext ist jetzt mit der Arbeitsaufgabe verknüpft."
        return f"„{result['title']}“ ist {result['status']} und gehört zu „{result['list_name']}“."
