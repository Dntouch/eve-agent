from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


VALID_STATES = {"idle", "listening", "thinking", "speaking", "error"}


class StateBus:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.runtime_dir, 0o700)
        except OSError:
            pass
        self.path = runtime_dir / "state.json"
        self._lock = threading.Lock()
        self.set("idle")

    def set(self, state: str, detail: str = "") -> None:
        if state not in VALID_STATES and not state.startswith(("tool:", "memory:")):
            raise ValueError(f"unknown state: {state}")
        payload = {"state": state, "detail": detail, "updated_at": time.time()}
        tmp = self.path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)

    def read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"state": "error", "detail": "state bus unavailable"}
