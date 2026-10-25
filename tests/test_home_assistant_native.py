import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from eve_agent.home_assistant import HomeAssistant


class Headers:
    def __init__(self, content_type="application/json"):
        self.content_type = content_type

    def get(self, name, default=""):
        return self.content_type if name == "Content-Type" else default


class Response:
    status = 200

    def __init__(self, body=b'{"ok":true}', content_type="application/json"):
        self.body = body
        self.headers = Headers(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


class HomeAssistantNativeTest(unittest.TestCase):
    def provider(self):
        return HomeAssistant(
            {"url": "http://homeassistant.local:8123", "token": "secret"}, Path("."),
        )

    def test_contract_contains_only_native_transports(self):
        operations = self.provider().native_contract()["operations"]
        self.assertEqual({"http_request", "websocket_command"}, set(operations))
        self.assertNotIn("execute_actions", str(operations))
        self.assertNotIn("upsert_automation", str(operations))
        self.assertNotIn("intended_effect", str(operations))
        self.assertIn("/api/services/{domain}/{service}", operations["http_request"]["purpose"])
        self.assertIn('"type":"call_service"', operations["websocket_command"]["purpose"])
        self.assertIn("never the WebSocket command type", operations["websocket_command"]["purpose"])

    def test_http_request_passes_provider_path_query_and_body_unchanged(self):
        provider = self.provider()
        with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            result = provider.execute_native_operation("http_request", {
                "method": "POST", "path": "/api/services/light/turn_off",
                "query": {"return_response": True},
                "body": {"entity_id": "light.flur"},
            })
        request = urlopen.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertEqual(
            "http://homeassistant.local:8123/api/services/light/turn_off?return_response=True",
            request.full_url,
        )
        self.assertEqual({"entity_id": "light.flur"}, json.loads(request.data))
        self.assertEqual(True, result["response"]["body"]["ok"])
        self.assertNotIn("secret", json.dumps(result))

    def test_http_provider_error_is_returned_without_generic_reconstruction(self):
        error = HTTPError(
            "http://homeassistant.local:8123/api/config/automation/config/test",
            400, "Bad Request", Headers(), io.BytesIO(b'{"message":"required key missing"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = self.provider().execute_native_operation("http_request", {
                "method": "POST", "path": "/api/config/automation/config/test",
                "body": {"alias": "test"},
            })
        self.assertEqual("failed", result["status"])
        self.assertEqual(400, result["response"]["status"])
        self.assertEqual("required key missing", result["response"]["body"]["message"])

    def test_large_provider_error_is_not_cut_at_an_arbitrary_error_boundary(self):
        detail = "provider detail " * 22_000
        error = HTTPError(
            "http://homeassistant.local:8123/api/test", 400, "Bad Request", Headers(),
            io.BytesIO(json.dumps({"message": detail}).encode()),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = self.provider().execute_native_operation("http_request", {
                "method": "GET", "path": "/api/test",
            })
        self.assertEqual(detail, result["response"]["body"]["message"])

    def test_response_larger_than_transport_safety_boundary_is_rejected_explicitly(self):
        oversized = b"x" * (12 * 1024 * 1024 + 1)
        with patch("urllib.request.urlopen", return_value=Response(oversized, "text/plain")):
            with self.assertRaisesRegex(RuntimeError, "12 MiB"):
                self.provider().execute_native_operation("http_request", {
                    "method": "GET", "path": "/api/test",
                })

    def test_websocket_adds_only_authentication_and_transport_id(self):
        connection = Mock()
        connection.recv.side_effect = [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True, "result": {"ok": True}}),
        ]
        command = {"type": "config/entity_registry/list"}
        with patch.dict(sys.modules, {
            "websocket": SimpleNamespace(create_connection=Mock(return_value=connection)),
        }):
            result = self.provider().execute_native_operation(
                "websocket_command", {"command": command},
            )
        sent = [json.loads(call.args[0]) for call in connection.send.call_args_list]
        self.assertEqual({"type": "auth", "access_token": "secret"}, sent[0])
        self.assertEqual({"id": 1, **command}, sent[1])
        self.assertEqual(command, result["request"]["command"])
        self.assertNotIn("secret", json.dumps(result))

    def test_websocket_replaces_model_transport_id(self):
        connection = Mock()
        connection.recv.side_effect = [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True, "result": {"ok": True}}),
        ]
        command = {"id": 999, "type": "fixture/read", "value": "kept"}
        with patch.dict(sys.modules, {
            "websocket": SimpleNamespace(create_connection=Mock(return_value=connection)),
        }):
            result = self.provider().execute_native_operation(
                "websocket_command", {"command": command},
            )
        sent = [json.loads(call.args[0]) for call in connection.send.call_args_list]
        self.assertEqual({"id": 1, "type": "fixture/read", "value": "kept"}, sent[1])
        self.assertEqual(
            {"type": "fixture/read", "value": "kept"}, result["request"]["command"],
        )


if __name__ == "__main__":
    unittest.main()
