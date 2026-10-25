from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .memory import redact_sensitive


_GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:secret|credential|cookie|session[_\s-]?id)\b\s*[\"']?\s*[:=]\s*)"
    r"(?:bearer\s+)?(?:[\"'][^\"']*[\"']|[^\s,;}\]]+)"
)
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
_MAX_FIELD_CHARS = 8_000


def _redact(value: str) -> str:
    """Redact diagnostic text without ever persisting the original value."""

    cleaned = redact_sensitive(str(value))
    cleaned = _GENERIC_SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", cleaned)
    cleaned = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", cleaned)
    return cleaned[:_MAX_FIELD_CHARS]


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {_redact(str(key)): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact(str(value))


class DiagnosticJournal:
    """Small private JSONL journal for operational diagnostics.

    Records are kept in chronological order. ``recent`` returns the selected
    tail in that same order, which makes it suitable as bounded diagnostic
    context for a maintenance request.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_records: int = 200,
        filename: str = "diagnostics.jsonl",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        if Path(filename).name != filename:
            raise ValueError("filename must not contain a directory")

        self.root = Path(root)
        self.path = self.root / filename
        self.max_records = int(max_records)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()

        self._ensure_private_storage()
        # Scrub and bound legacy content before it can be read back. Invalid
        # lines are deliberately discarded instead of entering Nova context.
        with self._lock:
            self._rewrite(self._read_records()[-self.max_records :])

    def _ensure_private_storage(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        if self.path.is_symlink():
            raise ValueError("diagnostic journal must not be a symbolic link")
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _read_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return records
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                records.append(_sanitize(item))
        return records

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        self._ensure_private_storage()
        descriptor, temporary_name = tempfile.mkstemp(prefix=".diagnostics-", suffix=".tmp", dir=self.root)
        temporary = Path(temporary_name)
        try:
            os.chmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                for record in records[-self.max_records :]:
                    output.write(json.dumps(_sanitize(record), ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def record(
        self,
        component: str,
        operation: str,
        status: str,
        message: str,
        *,
        exception: BaseException | str | None = None,
        route: str | None = None,
        correlation: str | None = None,
    ) -> dict[str, Any]:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        entry: dict[str, Any] = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "component": _redact(component),
            "operation": _redact(operation),
            "status": _redact(status),
            "message": _redact(message),
        }
        if exception is not None:
            if isinstance(exception, BaseException):
                entry["exception"] = {
                    "type": type(exception).__name__,
                    "message": _redact(str(exception)),
                    "traceback": _redact("".join(traceback.format_exception(exception))),
                }
            else:
                entry["exception"] = {"type": "Error", "message": _redact(exception)}
        if route is not None:
            entry["route"] = _redact(route)
        if correlation is not None:
            entry["correlation"] = _redact(correlation)

        with self._lock:
            records = self._read_records()
            records.append(entry)
            self._rewrite(records[-self.max_records :])
        return dict(entry)

    def recent(self, limit: int = 20, *, component: str | None = None) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        with self._lock:
            records = self._read_records()
        if component is not None:
            wanted = _redact(component).casefold()
            records = [record for record in records if str(record.get("component", "")).casefold() == wanted]
        return records[-min(int(limit), self.max_records) :]
