"""Trusted, turn-local provenance for scheduled executions; grants no permissions."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import json


_execution = ContextVar("eve_scheduled_execution", default=None)

EXECUTION_PROMPT = (
    "Dieser Turn ist die jetzt fällige Ausführung einer gespeicherten Aufgabe, "
    "keine neue Chatnachricht des ursprünglichen Auftraggebers. "
    "Führe den gespeicherten Auftrag jetzt aus. Bei einer Erinnerung ist deine Antwort "
    "die jetzt an den Empfänger zuzustellende Erinnerung. Bestätige nicht erneut ihre "
    "Einrichtung oder Formulierung und lege sie nicht erneut an. "
    "scheduled_execution enthält Herkunft, Fälligkeit und Ausgabeziel; das Ergebnis "
    "wird automatisch dorthin zugestellt. Das Ausgabeziel erteilt keine Werkzeugrechte. "
)


def scheduled_metadata():
    return deepcopy(_execution.get())


def ensure_scheduled_deadline(action):
    # The turn lock may have delayed this occurrence beyond its deadline.
    if action.get("ends_at") and datetime.now(timezone.utc) > datetime.fromisoformat(action["ends_at"].replace("Z", "+00:00")):
        raise ValueError("Enddatum der geplanten Aufgabe erreicht")


@contextmanager
def scheduled_execution(action):
    metadata = {key: deepcopy(action[key]) for key in (
        "task_id", "run_id", "name", "scheduled_for", "ends_at", "output_target",
    ) if key in action}
    metadata["input_kind"] = "scheduled"
    if action.get("execution_context"):
        metadata["origin_source"] = deepcopy(action["execution_context"])
    token = _execution.set(metadata)
    try:
        yield metadata
    finally:
        _execution.reset(token)


def input_metadata():
    """Preserve authority's origin without impersonating a fresh human message."""
    from .transport_access import transport_metadata
    scheduled = scheduled_metadata()
    if scheduled is not None:
        return {"input_kind": "scheduled", "scheduled_execution": scheduled}
    source = transport_metadata()
    return {"conversation_source": source} if source else {}


def restore_scheduled_origins(database):
    """Recover legacy input provenance from recorded runs, never from prompt text."""
    with database.connect() as connection:
        rows = connection.execute("""
            SELECT m.id, m.metadata_json, r.id AS run_id, r.task_id, r.scheduled_for
            FROM task_runs r JOIN messages m
              ON m.turn_id=json_extract(r.result_json, '$.turn.turn_id')
             AND m.conversation_id=json_extract(r.result_json, '$.turn.conversation_id')
            WHERE m.role='user'
              AND COALESCE(json_extract(m.metadata_json, '$.input_kind'), '')!='scheduled'
        """).fetchall()
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata.pop("conversation_source", None)
            metadata.update(input_kind="scheduled", scheduled_execution={
                "input_kind": "scheduled", "task_id": row["task_id"],
                "run_id": row["run_id"], "scheduled_for": row["scheduled_for"],
            })
            connection.execute("UPDATE messages SET metadata_json=? WHERE id=?",
                               (json.dumps(metadata, ensure_ascii=False), row["id"]))
        # Earlier copies to another local output chat already carried a task ID.
        connection.execute("""UPDATE messages
            SET metadata_json=json_set(metadata_json, '$.input_kind', 'scheduled')
            WHERE role='user' AND json_extract(metadata_json, '$.context_copy')=1
              AND json_extract(metadata_json, '$.scheduled_task_id') IS NOT NULL
              AND COALESCE(json_extract(metadata_json, '$.input_kind'), '')!='scheduled'
        """)
