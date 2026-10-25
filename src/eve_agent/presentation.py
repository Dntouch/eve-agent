from __future__ import annotations

import json
import base64
import binascii
import math
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


COMPONENT_TYPES = {
    "text", "markdown", "image", "video", "metric", "progress", "badge",
    "list", "table", "chart", "divider", "container",
}
LAYOUTS = {"vertical", "horizontal", "grid"}
MAX_DEPTH = 8
MAX_COMPONENTS = 256
MAX_INLINE_MEDIA_BYTES = 12 * 1024 * 1024
MAX_INLINE_MEDIA_CHARACTERS = 4 * math.ceil(MAX_INLINE_MEDIA_BYTES / 3) + 128


class PresentationStore:
    """Validated, source-agnostic presentation state shared with the UI."""

    def __init__(self, runtime_dir: Path):
        self.path = runtime_dir / "presentation.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "presentation.manage", "presentation.manage",
            "Ich kann strukturierte Präsentationen erstellen, aktualisieren und schließen.",
            "PresentationStore", "create,update,close",
        )]

    def read(self) -> dict[str, Any]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {"active": False, "revision": 0}
            except (OSError, ValueError):
                return {"active": False, "revision": 0}

    def create(self, presentation: dict[str, Any]) -> dict[str, Any]:
        document = validate_presentation(presentation)
        with self._lock:
            previous = self.read()
            payload = {
                "active": True,
                "id": uuid.uuid4().hex,
                "revision": int(previous.get("revision", 0)) + 1,
                "updated_at": time.time(),
                "presentation": document,
            }
            self._write(payload)
            return deepcopy(payload)

    def update(self, presentation_id: str, presentation: dict[str, Any]) -> dict[str, Any]:
        document = validate_presentation(presentation)
        with self._lock:
            current = self.read()
            if not current.get("active") or current.get("id") != presentation_id:
                raise KeyError("Präsentation wurde nicht gefunden")
            current.update(
                revision=int(current.get("revision", 0)) + 1,
                updated_at=time.time(),
                presentation=document,
            )
            self._write(current)
            return deepcopy(current)

    def close(self, presentation_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = self.read()
            if presentation_id is not None and current.get("id") != presentation_id:
                raise KeyError("Präsentation wurde nicht gefunden")
            payload = {
                "active": False,
                "revision": int(current.get("revision", 0)) + 1,
                "updated_at": time.time(),
            }
            self._write(payload)
            return deepcopy(payload)

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(command, dict):
            raise ValueError("Präsentationsbefehl muss ein Objekt sein")
        action = command.get("action")
        if action == "create":
            return self.create(command.get("presentation"))
        if action == "update":
            return self.update(str(command.get("id", "")), command.get("presentation"))
        if action == "close":
            identifier = command.get("id")
            return self.close(str(identifier) if identifier is not None else None)
        raise ValueError("Unbekannte Präsentationsaktion")

    def execute_if_revision(self, command: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        """Atomically reject a command planned against an obsolete screen state."""
        with self._lock:
            current = self.read()
            if int(current.get("revision", 0)) != int(expected_revision):
                raise RuntimeError("Präsentationszustand wurde durch einen neueren Turn geändert")
            return self.execute(command)

    def client_state(self) -> dict[str, Any]:
        """Return presentation JSON with inline media exposed as short URLs."""
        state = self.read()
        if not state.get("active") or not isinstance(state.get("presentation"), dict):
            return state
        public = deepcopy(state)
        revision = int(public.get("revision", 0))

        def expose(components: list[dict[str, Any]], prefix: str = "") -> None:
            for index, component in enumerate(components):
                path = f"{prefix}.{index}" if prefix else str(index)
                content = component.get("content")
                if component.get("type") in {"image", "video"} and _inline_media(content):
                    component["content"] = f"/api/presentation/resource/{revision}/{path}"
                if component.get("type") == "container":
                    expose(component.get("components", []), path)

        expose(public["presentation"]["components"])
        return public

    def read_resource(self, revision: int, component_path: str) -> tuple[str, bytes]:
        state = self.read()
        if not state.get("active") or int(state.get("revision", -1)) != revision:
            raise KeyError("Präsentationsressource wurde nicht gefunden")
        component: Any = {"components": state["presentation"]["components"]}
        try:
            for part in component_path.split("."):
                if not part.isdigit():
                    raise KeyError
                component = component["components"][int(part)]
        except (KeyError, IndexError, TypeError):
            raise KeyError("Präsentationsressource wurde nicht gefunden") from None
        media = _inline_media(component.get("content")) if isinstance(component, dict) else None
        if component.get("type") not in {"image", "video"} or media is None:
            raise KeyError("Präsentationsressource wurde nicht gefunden")
        mime, encoded = media
        try:
            return mime, base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Präsentationsressource ist ungültig") from exc

    def _write(self, payload: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)


def validate_presentation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("presentation muss ein Objekt sein")
    unknown = set(value) - {"title", "layout", "components"}
    if unknown:
        raise ValueError(f"Unbekannte Presentation-Felder: {', '.join(sorted(unknown))}")
    title = value.get("title", "")
    layout = value.get("layout", "vertical")
    components = value.get("components")
    if not isinstance(title, str) or len(title) > 200:
        raise ValueError("title muss Text mit höchstens 200 Zeichen sein")
    if layout not in LAYOUTS:
        raise ValueError("Unbekanntes Presentation-Layout")
    counter = [0]
    validated = _components(components, 0, counter)
    return {"title": title, "layout": layout, "components": validated}


def _components(value: Any, depth: int, counter: list[int]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("components muss eine Liste sein")
    if depth > MAX_DEPTH:
        raise ValueError("Komponenten sind zu tief verschachtelt")
    result = []
    for component in value:
        counter[0] += 1
        if counter[0] > MAX_COMPONENTS:
            raise ValueError("Präsentation enthält zu viele Komponenten")
        result.append(_component(component, depth, counter))
    return result


def _inline_media(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"data:((?:image|video)/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)", value)
    return (match.group(1), match.group(2)) if match else None


def _list_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int, float)) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def _validate_list_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("list.items muss eine Liste sein")
    for index, item in enumerate(value):
        if _list_scalar(item):
            continue
        if not isinstance(item, dict):
            raise ValueError(f"list.items[{index}] muss ein einfacher Wert oder ein label/value-Objekt sein")
        if set(item) != {"label", "value"}:
            raise ValueError(f"list.items[{index}] muss genau label und value enthalten")
        if not isinstance(item["label"], str) or len(item["label"]) > 100_000:
            raise ValueError(f"list.items[{index}].label muss Text sein")
        if not _list_scalar(item["value"]):
            raise ValueError(f"list.items[{index}].value muss ein einfacher Wert sein")
    return deepcopy(value)


def _component(value: Any, depth: int, counter: list[int]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Komponente muss ein Objekt sein")
    kind = value.get("type")
    if kind not in COMPONENT_TYPES:
        raise ValueError(f"Unbekannter Komponententyp: {kind}")
    allowed = {"type", "label", "content", "value", "items", "columns", "rows", "data", "layout", "components"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unbekannte Komponentenfelder: {', '.join(sorted(unknown))}")
    result = deepcopy(value)
    for key in ("label", "content"):
        max_length = (
            MAX_INLINE_MEDIA_CHARACTERS
            if key == "content" and kind in {"image", "video"}
            else 100_000
        )
        if key in result and (not isinstance(result[key], str) or len(result[key]) > max_length):
            raise ValueError(f"{key} muss Text sein")
    if kind in {"image", "video"}:
        media = _inline_media(result.get("content"))
        if media is not None:
            encoded = media[1]
            padding = len(encoded) - len(encoded.rstrip("="))
            decoded_size = len(encoded) * 3 // 4 - padding
            if decoded_size > MAX_INLINE_MEDIA_BYTES:
                raise ValueError("Präsentationsmedium überschreitet die zulässige Providergröße")
    if kind == "progress":
        progress = result.get("value")
        if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not 0 <= progress <= 100:
            raise ValueError("progress.value muss zwischen 0 und 100 liegen")
    if kind in {"image", "video"} and not isinstance(result.get("content"), str):
        raise ValueError(f"{kind}.content muss eine Ressourcenadresse sein")
    if kind == "container":
        if result.get("layout", "vertical") not in LAYOUTS:
            raise ValueError("Unbekanntes Container-Layout")
        result["layout"] = result.get("layout", "vertical")
        result["components"] = _components(result.get("components"), depth + 1, counter)
    elif "components" in result:
        raise ValueError("components ist nur für container erlaubt")
    if kind == "list":
        result["items"] = _validate_list_items(result.get("items"))
    if kind == "table" and not isinstance(result.get("rows"), list):
        raise ValueError("table.rows muss eine Liste sein")
    if kind == "chart" and not isinstance(result.get("data"), list):
        raise ValueError("chart.data muss eine Liste sein")
    return result
