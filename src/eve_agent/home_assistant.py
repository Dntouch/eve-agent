"""Thin native transport for a configured Home Assistant instance.

Home Assistant owns entity identities, services, automation schemas, validation
and provider errors.  This adapter only authenticates native REST/WebSocket
requests, applies technical transport bounds, redacts returned secrets and
publishes provider facts for the optional read-only Memory inventory.
"""
from __future__ import annotations

import base64
import contextvars
import copy
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from .memory import redact_sensitive


class ProviderEntityNotFound(ValueError):
    """Compatibility name for a native provider entity error."""


class ProviderServiceNotFound(ValueError):
    """Compatibility name for a native provider service error."""


def _safe(value):
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return value


class HomeAssistant:
    def __init__(self, config: dict, root: Path, aliases=None):
        self.base_url = str(config.get("url") or "").rstrip("/")
        self.token = str(config.get("token") or "").strip()
        self.timeout = int(config.get("timeout_seconds", 12))
        self.share_coordinates_with_web = config.get("share_coordinates_with_web") is True
        self.last_domain: str | None = None
        self.last_entities: list[str] = []
        self.last_target_focus: list[dict] = []
        self.telemetry = None
        self._entity_namespace_cache: tuple[float, tuple[str, ...]] | None = None
        self._turn_cancellation = contextvars.ContextVar(
            "eve_home_assistant_turn_cancellation", default=None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    @contextmanager
    def cancellable(self, cancellation):
        token = self._turn_cancellation.set(cancellation)
        try:
            yield
        finally:
            self._turn_cancellation.reset(token)

    def _cancel_checkpoint(self) -> None:
        cancellation = self._turn_cancellation.get()
        if cancellation is not None:
            cancellation.checkpoint()

    def semantic_provider_identity(self) -> dict:
        return {"provider": "home_assistant", "endpoint": self.base_url}

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "home_assistant.native", "home_assistant.native",
            "Ich kann die native REST- und WebSocket-API des verbundenen Home Assistant verwenden.",
            "HomeAssistant", "http_request,websocket_command",
        )]

    def native_contract(self) -> dict:
        return {
            "description": (
                "Native Home Assistant REST and WebSocket transport. Use Home Assistant paths and "
                "command payloads unchanged; Home Assistant responses and errors are authoritative. "
                "Image responses are passed to the active model as native image input."
            ),
            "operations": {
                "http_request": {
                    "effect": "read|write",
                    "purpose": (
                        "Send one native Home Assistant REST request. Use the real /api path. "
                        "Read one entity with GET /api/states/{entity_id}; inspect available "
                        "services with GET /api/services; invoke a service with POST "
                        "/api/services/{domain}/{service} and its native JSON body, for example "
                        "{\"entity_id\":\"light.example\"}. Home Assistant validates the request. "
                        "A response with an image/* content type is attached to the next model turn "
                        "as native image input."
                    ),
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "method": {"type": "string", "pattern": "^[A-Z]{3,16}$"},
                            "path": {"type": "string", "pattern": "^/api(?:/|$)"},
                            "query": {
                                "type": "object",
                                "additionalProperties": {
                                    "type": ["string", "number", "integer", "boolean", "null"],
                                },
                            },
                            "body": {},
                        },
                        "required": ["method", "path"],
                    },
                },
                "websocket_command": {
                    "effect": "read|write",
                    "purpose": (
                        "Send one native Home Assistant WebSocket API command. The command.type "
                        "must be a real WebSocket command type. To invoke a service use "
                        "{\"type\":\"call_service\",\"domain\":\"light\","
                        "\"service\":\"turn_on\",\"target\":{\"entity_id\":\"light.example\"},"
                        "\"service_data\":{}}; a service name such as light.turn_on is never the "
                        "WebSocket command type. EVE adds only authentication and the transport id."
                    ),
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "command": {
                                "type": "object", "minProperties": 1,
                                "properties": {"type": {"type": "string", "minLength": 1}},
                                "required": ["type"], "additionalProperties": True,
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
        }

    def execute_native_operation(self, operation: str, parameters: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Home Assistant is not configured")
        if not isinstance(parameters, dict):
            raise ValueError("Home Assistant parameters must be an object")
        if operation == "http_request":
            return self._native_http_request(parameters)
        if operation == "websocket_command":
            return self._native_websocket_command(parameters.get("command"))
        raise ValueError("Unknown native Home Assistant transport operation")

    def native_semantic_execution(self, operation, parameters, result):
        """Project an actual service transport into the existing experience format.

        This reads protocol fields, never user wording or intended outcome. An
        accepted request is not by itself a semantic success declaration.
        """
        if not isinstance(result, dict) or result.get("status") != "completed":
            return None
        if operation == "http_request":
            parts = str(parameters.get("path", "")).split("/")
            if (parameters.get("method", "").upper() != "POST" or len(parts) != 5
                    or parts[1:3] != ["api", "services"] or not all(parts[3:])):
                return None
            domain, service = parts[3:]
            data = parameters.get("body")
        elif operation == "websocket_command":
            command = parameters.get("command") or {}
            if not isinstance(command, dict) or command.get("type") != "call_service":
                return None
            domain, service = command.get("domain"), command.get("service")
            data = copy.deepcopy(command.get("service_data") or {})
            target = command.get("target") or {}
            if not isinstance(data, dict) or not isinstance(target, dict):
                return None
            if target.get("entity_id") is not None:
                if "entity_id" in data and data["entity_id"] != target["entity_id"]:
                    return None
                data["entity_id"] = target["entity_id"]
            if set(target) - {"entity_id"}:
                return None
        else:
            return None
        if not domain or not service or not isinstance(data, dict):
            return None
        # Area/device targeting needs a separately evidenced expansion. Do not
        # infer targets from returned changed states or arbitrary identifier strings.
        if set(data) & {"area_id", "device_id"}:
            return None
        targets = data.get("entity_id")
        targets = [targets] if isinstance(targets, str) else targets
        if not isinstance(targets, list) or not targets or any(not isinstance(t, str) or not t for t in targets):
            return None
        fields = {key: copy.deepcopy(value) for key, value in data.items() if key != "entity_id"}
        return {"provider": self.semantic_provider_identity(), "effect": "write", "actions": [
            {"type": "call_service", "entity_id": target, "service": f"{domain}.{service}",
             "parameters": copy.deepcopy(fields)} for target in targets]}

    @staticmethod
    def _decode_body(raw: bytes, content_type: str):
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        if content_type.casefold() == "application/json" or text[:1] in "[{":
            try:
                return _safe(json.loads(text))
            except json.JSONDecodeError:
                pass
        return redact_sensitive(text)

    def _native_http_request(self, parameters: dict) -> dict:
        method = str(parameters.get("method") or "").upper()
        path = str(parameters.get("path") or "")
        if not re.fullmatch(r"[A-Z]{3,16}", method):
            raise ValueError("Invalid HTTP method")
        if not path.startswith("/api/") and path != "/api":
            raise ValueError("Home Assistant path must stay below /api")
        if "?" in path or "#" in path or "\\" in path:
            raise ValueError("Put query values in the query object")
        query = parameters.get("query") or {}
        if not isinstance(query, dict) or any(
                isinstance(value, (dict, list, tuple, set)) for value in query.values()):
            raise ValueError("HTTP query must contain scalar values")
        encoded_query = urllib.parse.urlencode({
            str(key): value for key, value in query.items() if value is not None
        })
        url = self.base_url + path + (("?" + encoded_query) if encoded_query else "")
        has_body = "body" in parameters
        body = json.dumps(parameters.get("body"), ensure_ascii=False).encode("utf-8") if has_body else None
        request = urllib.request.Request(
            url, method=method, data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, image/*;q=0.9, text/plain;q=0.8, */*;q=0.1",
            },
        )
        self._cancel_checkpoint()
        maximum = 12 * 1024 * 1024
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(maximum + 1)
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip()
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(maximum + 1)
                status = int(exc.code)
                content_type = str(exc.headers.get("Content-Type", "")).split(";", 1)[0].strip()
            finally:
                exc.close()
        except OSError as exc:
            raise RuntimeError(f"Home Assistant is unreachable: {exc}") from exc
        if len(raw) > maximum:
            raise RuntimeError("Home Assistant response exceeds 12 MiB")
        result = {
            "status": "completed" if 200 <= status < 300 else "failed",
            "request": {"method": method, "path": path, "query": _safe(query)},
            "response": {"status": status, "content_type": content_type},
        }
        if raw and content_type.casefold().startswith("image/"):
            result["response"]["body"] = {"kind": "binary", "bytes": len(raw)}
            result["resources"] = [{
                "type": "image",
                "content": f"data:{content_type};base64," + base64.b64encode(raw).decode("ascii"),
                "operation": "http_request", "provider_path": path,
            }]
        else:
            result["response"]["body"] = self._decode_body(raw, content_type)
        return result

    def _native_websocket_command(self, command) -> dict:
        if not isinstance(command, dict) or not isinstance(command.get("type"), str):
            raise ValueError("Home Assistant WebSocket command must contain a type")
        if "access_token" in command:
            raise ValueError("EVE owns WebSocket authentication")
        # The provider protocol requires a client-owned correlation id. It is
        # transport metadata rather than model intent, so accept a model frame
        # with an id but replace that value with EVE's own correlation id.
        command = {key: value for key, value in command.items() if key != "id"}
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("websocket-client is required for Home Assistant") from exc
        connection = websocket.create_connection(
            re.sub(r"^http", "ws", self.base_url) + "/api/websocket",
            timeout=self.timeout,
        )
        try:
            hello = json.loads(connection.recv())
            if hello.get("type") != "auth_required":
                raise RuntimeError("Home Assistant WebSocket authentication did not start")
            connection.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(connection.recv())
            if auth.get("type") == "auth_invalid":
                raise PermissionError("Home Assistant denied WebSocket authentication")
            if auth.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant WebSocket authentication failed")
            payload = {"id": 1, **copy.deepcopy(command)}
            connection.send(json.dumps(payload, ensure_ascii=False))
            response = json.loads(connection.recv())
            if response.get("id") != 1:
                raise RuntimeError("Home Assistant returned an unrelated WebSocket response")
            return {
                "status": "completed" if response.get("success", True) else "failed",
                "request": {"command": _safe(command)}, "response": _safe(response),
            }
        finally:
            connection.close()

    def _api(self, method: str, path: str, payload=None):
        parameters = {"method": method, "path": path}
        if payload is not None:
            parameters["body"] = payload
        result = self._native_http_request(parameters)
        if result["status"] != "completed":
            response = result["response"]
            raise RuntimeError(
                f"Home Assistant HTTP {response['status']}: {response.get('body')}"
            )
        return result["response"].get("body")

    def _catalog(self) -> dict[str, dict]:
        states = self._api("GET", "/api/states")
        if not isinstance(states, list):
            raise RuntimeError("Home Assistant returned no state list")
        return {
            str(item.get("entity_id")): item for item in states
            if isinstance(item, dict) and "." in str(item.get("entity_id") or "")
        }

    def _service_catalog(self) -> dict[str, dict]:
        services = self._api("GET", "/api/services")
        if not isinstance(services, list):
            raise RuntimeError("Home Assistant returned no service catalog")
        result = {}
        for domain_item in services:
            if not isinstance(domain_item, dict):
                continue
            domain = str(domain_item.get("domain") or "")
            for name, definition in (domain_item.get("services") or {}).items():
                if domain and isinstance(name, str) and isinstance(definition, dict):
                    result[f"{domain}.{name}"] = definition
        return result

    def available_entity_namespaces(self, *, max_age_seconds=30.0) -> list[str]:
        now = time.monotonic()
        if self._entity_namespace_cache and now - self._entity_namespace_cache[0] <= max_age_seconds:
            return list(self._entity_namespace_cache[1])
        namespaces = tuple(sorted({item.partition(".")[0] for item in self._catalog()}))
        self._entity_namespace_cache = (now, namespaces)
        return list(namespaces)

    def _area_map(self, entity_ids: list[str]) -> dict[str, str]:
        if not entity_ids:
            return {}
        template = (
            "{% set ns = namespace(items=[]) %}"
            f"{{% for entity_id in {json.dumps(entity_ids, ensure_ascii=False)} %}}"
            "{% set ns.items = ns.items + [{'entity_id': entity_id, 'area': area_name(entity_id)}] %}"
            "{% endfor %}{{ ns.items | tojson }}"
        )
        try:
            values = self._api("POST", "/api/template", {"template": template})
            return {
                str(item["entity_id"]): str(item["area"])
                for item in values if isinstance(item, dict) and item.get("area")
            }
        except Exception:
            return {}

    def inventory_catalog(self) -> dict:
        """Copy provider-published structure for the explicit read-only inventory."""
        catalog = self._catalog()
        services = self._service_catalog()
        areas = self._area_map(list(catalog))
        entities = []
        for entity_id, item in catalog.items():
            attributes = item.get("attributes") if isinstance(item, dict) else {}
            attributes = attributes if isinstance(attributes, dict) else {}
            domain = entity_id.partition(".")[0]
            published = sorted(name for name in services if name.startswith(domain + "."))
            entities.append({
                "entity_id": entity_id,
                "name": attributes.get("friendly_name") or entity_id,
                "area": areas.get(entity_id),
                "device_class": attributes.get("device_class"),
                "unit": attributes.get("unit_of_measurement"),
                "state_class": attributes.get("state_class"),
                "supported_features": attributes.get("supported_features"),
                "services": published,
                "service_fields": {
                    name: sorted((services[name].get("fields") or {})) for name in published
                },
                "properties": sorted(str(name) for name in attributes if isinstance(name, str)),
                "members": list(attributes.get("entity_id"))
                    if isinstance(attributes.get("entity_id"), list) else [],
                "state": item.get("state"),
            })
        return {"entities": _safe(entities)}

    def diagnostic_snapshot(self) -> dict:
        snapshot = {"connected": self.configured, "entities": [], "services": [], "errors": []}
        try:
            snapshot["entities"] = list(self.inventory_catalog()["entities"])
        except Exception as exc:
            snapshot["errors"].append(f"inventory: {type(exc).__name__}")
        return snapshot
