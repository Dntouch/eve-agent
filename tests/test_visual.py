import base64
import json
import socket
import ssl
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from eve_agent.visual import EveHTTPServer, VisualServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeBus:
    def __init__(self):
        self.state = {"state": "idle", "detail": ""}

    def read(self):
        return dict(self.state)

    def set(self, state, detail=""):
        self.state = {"state": state, "detail": detail}


class VisualServerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def make_server(self, **kwargs):
        try:
            server = VisualServer(
                Path(self.temp_dir.name),
                FakeBus(),
                "127.0.0.1",
                0,
                **kwargs,
            )
        except PermissionError as exc:
            self.skipTest(f"Lokale Sockets sind in dieser Sandbox gesperrt: {exc}")
        self.addCleanup(server.stop)
        return server

    @staticmethod
    def request_json(server, path, *, data=None, timeout=2, headers=None, method=None):
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            f"{server.scheme}://127.0.0.1:{server.port}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        last_error = None
        for _ in range(20):
            try:
                context = ssl._create_unverified_context() if server.scheme == "https" else None
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return response.status, dict(response.headers), json.load(response)
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(.01)
        raise last_error

    def test_health_endpoints_and_dynamic_port(self):
        server = self.make_server(readiness_handler=lambda: {"ready": True, "component": "eve"})
        self.assertNotEqual(server.port, 0)
        server.start()

        status, headers, payload = self.request_json(server, "/health/live")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})
        self.assertEqual(headers["Cache-Control"], "no-store")

        status, _, payload = self.request_json(server, "/health/ready")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["component"], "eve")

    def test_backend_stream_emits_reasoning_separately_before_answer(self):
        snapshot = {
            "turn_id": "turn-reasoning",
            "conversation_id": "conversation-1",
            "status": "completed",
            "version": 3,
            "cancellable": False,
            "cancel_requested": False,
            "reasoning": "Memory und Provider prüfen …",
            "answer": "Die Kamera wurde gefunden.",
            "response": {"answer": "Die Kamera wurde gefunden."},
            "audio_segments": [],
        }
        server = self.make_server(
            backend_message_snapshot_handler=lambda _turn_id, _version=0: dict(snapshot),
        )
        server.start()
        request = urllib.request.Request(
            f"{server.scheme}://127.0.0.1:{server.port}/api/message/stream/turn-reasoning",
        )
        context = ssl._create_unverified_context() if server.scheme == "https" else None
        with urllib.request.urlopen(request, timeout=2, context=context) as response:
            events = [json.loads(line) for line in response if line.strip()]

        event_types = [event["type"] for event in events]
        self.assertLess(event_types.index("reasoning_delta"), event_types.index("delta"))
        reasoning = next(event for event in events if event["type"] == "reasoning_delta")
        answer = next(event for event in events if event["type"] == "delta")
        self.assertEqual("Memory und Provider prüfen …", reasoning["content"])
        self.assertEqual("Die Kamera wurde gefunden.", answer["content"])

    def test_backend_stream_promotes_identical_answer_preview_without_duplicate_delta(self):
        snapshot = {
            "turn_id": "turn-preview",
            "conversation_id": "conversation-1",
            "status": "completed",
            "version": 4,
            "cancellable": False,
            "cancel_requested": False,
            "reasoning": "",
            "answer_preview": "Früh sichtbare Antwort.",
            "answer": "Früh sichtbare Antwort.",
            "response": {"answer": "Früh sichtbare Antwort."},
            "audio_segments": [],
        }
        server = self.make_server(
            backend_message_snapshot_handler=lambda _turn_id, _version=0: dict(snapshot),
        )
        server.start()
        request = urllib.request.Request(
            f"{server.scheme}://127.0.0.1:{server.port}/api/message/stream/turn-preview",
        )
        context = ssl._create_unverified_context() if server.scheme == "https" else None
        with urllib.request.urlopen(request, timeout=2, context=context) as response:
            events = [json.loads(line) for line in response if line.strip()]

        event_types = [event["type"] for event in events]
        self.assertIn("preview_delta", event_types)
        self.assertIn("preview_commit", event_types)
        self.assertNotIn("delta", event_types)
        preview = next(event for event in events if event["type"] == "preview_delta")
        self.assertEqual("Früh sichtbare Antwort.", preview["content"])

    def test_backend_stream_promotes_prefix_and_never_republishes_committed_preview(self):
        for coalesced in (True, False):
            with self.subTest(coalesced=coalesced):
                prefix, tail = "Erste Zeile.\n", "Letzte Zeile."
                final = prefix + tail
                common = {"turn_id": "turn-prefix", "conversation_id": "conversation-1",
                          "cancellable": False, "cancel_requested": False, "reasoning": "",
                          "audio_segments": [], "answer_preview_generation": 0}
                first = {**common, "version": 1, "status": "running",
                         "answer_preview": prefix, "answer": prefix, "response": None}
                last = {**common, "version": 2, "status": "completed",
                        "answer_preview": prefix if coalesced else final,
                        "answer": final, "response": {"answer": final}}
                server = self.make_server(backend_message_snapshot_handler=
                    lambda _id, version=0: dict(last if coalesced or version else first))
                server.start()
                context = ssl._create_unverified_context() if server.scheme == "https" else None
                with urllib.request.urlopen(
                    f"{server.scheme}://127.0.0.1:{server.port}/api/message/stream/turn-prefix",
                    timeout=2, context=context,
                ) as response:
                    events = [json.loads(line) for line in response if line.strip()]
                visible = ""
                for event in events:
                    if event["type"] == "preview_reset":
                        visible = ""
                    elif event["type"] in {"preview_delta", "delta"}:
                        visible += event["content"]
                self.assertEqual(final, visible)
                self.assertEqual(1, sum(e["type"] == "preview_commit" for e in events))

    def test_backend_stream_resets_preview_generation_even_when_prefix_matches(self):
        common = {
            "turn_id": "turn-preview-reset", "conversation_id": "conversation-1",
            "cancellable": True, "cancel_requested": False, "reasoning": "",
            "answer": "", "response": None, "audio_segments": [],
        }
        snapshots = {
            0: {**common, "status": "running", "version": 1,
                "answer_preview": "Ich", "answer_preview_generation": 0},
            1: {**common, "status": "running", "version": 2,
                "answer_preview": "Ich prüfe", "answer_preview_generation": 1},
            2: {**common, "status": "completed", "version": 3,
                "cancellable": False, "answer_preview": "Ich prüfe",
                "answer_preview_generation": 1, "answer": "Ich prüfe",
                "response": {"answer": "Ich prüfe"}},
        }
        server = self.make_server(
            backend_message_snapshot_handler=lambda _turn_id, version=0: dict(
                snapshots.get(version, snapshots[2])
            ),
        )
        server.start()
        request = urllib.request.Request(
            f"{server.scheme}://127.0.0.1:{server.port}/api/message/stream/turn-preview-reset",
        )
        context = ssl._create_unverified_context() if server.scheme == "https" else None
        with urllib.request.urlopen(request, timeout=2, context=context) as response:
            events = [json.loads(line) for line in response if line.strip()]

        event_types = [event["type"] for event in events]
        self.assertLess(event_types.index("preview_delta"), event_types.index("preview_reset"))
        self.assertEqual(2, event_types.count("preview_delta"))
        self.assertIn("preview_commit", event_types)

    def test_not_ready_returns_503_without_internal_exception(self):
        server = self.make_server(readiness_handler=lambda: False)
        server.start()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/health/ready")
        self.assertEqual(caught.exception.code, 503)
        payload = json.loads(caught.exception.read())
        caught.exception.close()
        self.assertEqual(payload, {"status": "not_ready"})

    def test_request_limit_returns_429_and_retry_after(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_message(text, images):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test handler timed out")
            return {"answer": text}

        server = self.make_server(
            message_handler=slow_message,
            max_connections=4,
            max_concurrent_requests=1,
        )
        server.start()
        body = json.dumps({"text": "eins", "images": []}).encode()
        first_result = []

        def first_request():
            first_result.append(self.request_json(server, "/api/message", data=body))

        first = threading.Thread(target=first_request)
        first.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request_json(server, "/api/message", data=body)
            self.assertEqual(caught.exception.code, 429)
            self.assertEqual(caught.exception.headers["Retry-After"], "1")
            caught.exception.close()
        finally:
            release.set()
            first.join(2)
        self.assertFalse(first.is_alive())
        self.assertEqual(first_result[0][0], 200)

    def test_invalid_message_is_400_and_releases_request_slot(self):
        server = self.make_server(
            message_handler=lambda text, images: {"answer": text},
            max_concurrent_requests=1,
        )
        server.start()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/message", data=b"{}")
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

        valid = json.dumps({"text": "danach", "images": []}).encode()
        status, _, payload = self.request_json(server, "/api/message", data=valid)
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "danach")

    def test_message_forwards_optional_conversation_id(self):
        received = []
        server = self.make_server(
            message_handler=lambda text, images, conversation_id: (
                received.append((text, conversation_id)) or {"answer": text, "conversation_id": conversation_id}
            )
        )
        server.start()
        body = json.dumps({"text": "Hallo", "images": [], "conversation_id": "conversation-1"}).encode()
        status, _, payload = self.request_json(server, "/api/message", data=body)
        self.assertEqual(status, 200)
        self.assertEqual(received, [("Hallo", "conversation-1")])
        self.assertEqual(payload["conversation_id"], "conversation-1")

    def test_conversation_rest_routes_are_forwarded(self):
        calls = []

        def conversations(method, conversation_id, payload, query):
            calls.append((method, conversation_id, payload, query))
            if method == "POST":
                return 201, {"conversation": {"id": "new"}}
            if method == "DELETE":
                return 200, {"deleted": True}
            return 200, {"conversation": {"id": conversation_id}, "conversations": []}

        server = self.make_server(conversation_handler=conversations)
        server.start()
        status, _, _ = self.request_json(server, "/api/conversations?limit=10")
        self.assertEqual(status, 200)
        status, _, payload = self.request_json(
            server, "/api/conversations", data=json.dumps({"title": "Neu"}).encode()
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["conversation"]["id"], "new")
        status, _, _ = self.request_json(
            server, "/api/conversations/abc", data=json.dumps({"title": "Umbenannt"}).encode(), method="PATCH"
        )
        self.assertEqual(status, 200)
        status, _, payload = self.request_json(server, "/api/conversations/abc", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(payload["deleted"])
        self.assertEqual([call[0] for call in calls], ["GET", "POST", "PATCH", "DELETE"])

    def test_training_package_routes_forward_query_and_json_without_side_effects(self):
        calls = []

        def training_packages(method, payload, query):
            calls.append((method, payload, query))
            return 200, {"method": method, "ok": True}

        server = self.make_server(training_package_handler=training_packages)
        server.start()
        status, _, result = self.request_json(
            server,
            "/api/training-packages?action=export&provider=home_assistant&kind=language",
        )
        self.assertEqual(200, status)
        self.assertEqual("GET", result["method"])
        body = json.dumps({"action": "preview", "package": {"provider": "home_assistant"}}).encode()
        status, _, result = self.request_json(server, "/api/training-packages", data=body)
        self.assertEqual(200, status)
        self.assertEqual("POST", result["method"])
        self.assertEqual("export", calls[0][2]["action"][0])
        self.assertEqual("preview", calls[1][1]["action"])

    def test_task_rest_routes_are_forwarded(self):
        calls = []

        def tasks(method, task_id, payload, query):
            calls.append((method, task_id, payload, query))
            if method == "DELETE":
                return 200, {"deleted": True}
            return 200, {"task": {"id": task_id}, "tasks": []}

        server = self.make_server(task_handler=tasks)
        server.start()
        status, _, _ = self.request_json(server, "/api/tasks?limit=10")
        self.assertEqual(status, 200)
        status, _, payload = self.request_json(
            server, "/api/tasks/task-1", data=json.dumps({"status": "paused"}).encode(), method="PATCH"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["id"], "task-1")
        status, _, payload = self.request_json(server, "/api/tasks/task-1", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(payload["deleted"])
        self.assertEqual([call[0] for call in calls], ["GET", "PATCH", "DELETE"])

    def test_home_assistant_inventory_route_is_post_only_and_forwarded(self):
        calls = []
        server = self.make_server(
            home_assistant_inventory_handler=lambda: (
                calls.append("scan") or (200, {"inventory": {"counts": {"total": 3}}})
            )
        )
        server.start()
        status, _, payload = self.request_json(
            server, "/api/home-assistant/inventory", data=b"", method="POST"
        )
        self.assertEqual(200, status)
        self.assertEqual(3, payload["inventory"]["counts"]["total"])
        self.assertEqual(["scan"], calls)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/home-assistant/inventory")
        self.assertEqual(404, caught.exception.code)
        caught.exception.close()

    def test_home_assistant_policy_route_reads_and_updates_memory_policy(self):
        calls = []

        def policy(method, payload):
            calls.append((method, payload))
            return 200, {
                "policy": {"excluded_areas": payload.get("excluded_areas", ["Carport"])},
                "areas": [],
            }

        server = self.make_server(home_assistant_policy_handler=policy)
        server.start()
        status, _, payload = self.request_json(server, "/api/home-assistant/policy")
        self.assertEqual(200, status)
        self.assertEqual(["Carport"], payload["policy"]["excluded_areas"])
        body = json.dumps({"excluded_areas": ["Garage"]}).encode()
        status, _, payload = self.request_json(
            server, "/api/home-assistant/policy", data=body, method="PATCH",
        )
        self.assertEqual(200, status)
        self.assertEqual(["Garage"], payload["policy"]["excluded_areas"])
        self.assertEqual([("GET", {}), ("PATCH", {"excluded_areas": ["Garage"]})], calls)

    def test_presentation_lifecycle_routes_are_forwarded(self):
        calls = []

        def presentations(method, payload):
            calls.append((method, payload))
            return (201 if method == "POST" else 200), {"active": method != "DELETE", "revision": len(calls)}

        server = self.make_server(presentation_handler=presentations)
        server.start()
        status, _, payload = self.request_json(server, "/api/presentation")
        self.assertEqual((status, payload["active"]), (200, True))
        status, _, _ = self.request_json(server, "/api/presentation", data=json.dumps({"presentation": {}}).encode())
        self.assertEqual(status, 201)
        status, _, _ = self.request_json(server, "/api/presentation", data=json.dumps({"id": "p1"}).encode(), method="PATCH")
        self.assertEqual(status, 200)
        status, _, payload = self.request_json(server, "/api/presentation", method="DELETE")
        self.assertFalse(payload["active"])
        self.assertEqual([call[0] for call in calls], ["GET", "POST", "PATCH", "DELETE"])

    def test_presentation_binary_resource_is_served_with_media_type(self):
        server = self.make_server(
            presentation_resource_handler=lambda revision, path: ("image/jpeg", b"\xff\xd8\xfftest")
        )
        server.start()
        request = urllib.request.Request(
            f"{server.scheme}://127.0.0.1:{server.port}/api/presentation/resource/7/0"
        )
        context = ssl._create_unverified_context() if server.scheme == "https" else None
        try:
            with urllib.request.urlopen(request, timeout=2, context=context) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertEqual(response.read(), b"\xff\xd8\xfftest")
        except urllib.error.URLError as exc:
            self.skipTest(f"Lokale Sockets sind in dieser Sandbox gesperrt: {exc}")

    def test_config_get_and_patch_are_narrowly_forwarded(self):
        calls = []

        def config(method, payload):
            calls.append((method, payload))
            return 200, {"sections": [], "runtime_effect": "restart"}

        server = self.make_server(config_handler=config)
        server.start()
        status, _, payload = self.request_json(server, "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(payload["runtime_effect"], "restart")
        status, _, _ = self.request_json(
            server, "/api/config", data=json.dumps({"values": {"llm.model": "new"}}).encode(), method="PATCH"
        )
        self.assertEqual(status, 200)
        self.assertEqual(calls, [("GET", {}), ("PATCH", {"values": {"llm.model": "new"}})])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/config", method="DELETE")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_telemetry_endpoint_is_read_only(self):
        server = self.make_server(telemetry_handler=lambda query: {"turns": [], "query": query})
        server.start()
        status, _, payload = self.request_json(server, "/api/telemetry?conversation_id=abc")
        self.assertEqual(status, 200)
        self.assertEqual(payload["query"]["conversation_id"], ["abc"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/telemetry", data=b"{}")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_brainwatch_endpoints_are_read_only_and_allowlisted(self):
        calls = []

        def inspect(operation, node_id, query):
            calls.append((operation, node_id, query))
            return {"focus": node_id, "nodes": [], "edges": [], "page": {"has_more": False, "next_cursor": None}}

        server = self.make_server(brainwatch_handler=inspect)
        server.start()
        self.assertEqual(200, self.request_json(server, "/api/brainwatch/search?q=EVE")[0])
        self.assertEqual(200, self.request_json(server, "/api/brainwatch/nodes/memory%3Aabc")[0])
        self.assertEqual(200, self.request_json(server, "/api/brainwatch/nodes/turn%3Aabc/neighbors?limit=30")[0])
        self.assertEqual(["search", "node", "neighbors"], [call[0] for call in calls])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/brainwatch/search", data=b"{}", method="POST")
        self.assertEqual(404, caught.exception.code)
        caught.exception.close()

    def test_conversation_learning_status_and_controls_are_brainwatch_routes(self):
        calls = []

        def inspect(operation, node_id, query):
            calls.append((operation, node_id, query))
            return {"status": "paused" if query.get("action") == "pause" else "waiting"}

        server = self.make_server(brainwatch_handler=inspect)
        server.start()
        status, _, payload = self.request_json(server, "/api/brainwatch/conversation-learning")
        self.assertEqual(200, status)
        self.assertEqual("waiting", payload["status"])
        status, _, payload = self.request_json(
            server, "/api/brainwatch/conversation-learning",
            data=json.dumps({"action": "pause"}).encode(), method="POST",
        )
        self.assertEqual(200, status)
        self.assertEqual("paused", payload["status"])
        self.assertEqual(
            ["conversation_learning_status", "conversation_learning_control"],
            [item[0] for item in calls],
        )
        self.assertEqual("pause", calls[1][2]["action"])

    def test_learning_review_route_accepts_turn_and_note_and_rejects_invalid_shape(self):
        calls = []
        server = self.make_server(brainwatch_handler=lambda *args: (calls.append(args), {'status': 'reviewed'})[1])
        server.start()
        for action in ['review', 'reopen_review']:
            status, _, _ = self.request_json(server, '/api/brainwatch/conversation-learning',
                data=json.dumps({'action': action, 'turn_id': 'failed-turn', 'note': 'Beleg geprüft'}).encode(), method='POST')
            self.assertEqual(200, status)
            self.assertEqual('failed-turn', calls[-1][2]['turn_id'])
        for value in [{'action': 'review'}, {'action': 'review', 'turn_id': ''}, {'action': 'review', 'turn_id': 'x', 'note': 5}, {'action': 'pause', 'turn_id': 'x'}]:
            with self.subTest(value=value), self.assertRaises(urllib.error.HTTPError) as error:
                self.request_json(server, '/api/brainwatch/conversation-learning', data=json.dumps(value).encode(), method='POST')
            self.assertEqual(400, error.exception.code)
            error.exception.close()

    def test_working_memory_graph_route_dispatches_read_only_projection(self):
        calls = []
        server = self.make_server(brainwatch_handler=lambda *args: calls.append(args) or {'nodes': []})
        server.start()
        self.assertEqual(200, self.request_json(server, '/api/brainwatch/memory/graph/working')[0])
        self.assertEqual(calls, [('working_memory_graph', None, {})])

    def test_memory_explorer_routes_are_read_only_and_preserve_claim_ids(self):
        calls = []

        def inspect(operation, claim_id, query):
            calls.append((operation, claim_id, query))
            return {"ok": True}

        server = self.make_server(brainwatch_handler=inspect)
        server.start()
        paths = (
            "/api/brainwatch/memory/events?event_kind=compiler_retrieved&fidelity=derived_link",
            "/api/brainwatch/memory/graph?node_limit=100&edge_limit=200",
            "/api/brainwatch/memory/graph/relations?limit=200&cursor=relation-a",
            "/api/brainwatch/memory/claims?limit=20&lifecycle=active",
            "/api/brainwatch/memory/claims/claim-a",
            "/api/brainwatch/memory/claims/claim-a/evidence?limit=10",
            "/api/brainwatch/memory/claims/claim-a/relations?relation_type=supersedes",
            "/api/brainwatch/memory/claims/claim-a/turns?origin_class=observation_turn",
            "/api/brainwatch/memory/claims/claim-a/runtime-events?category=actions",
            "/api/brainwatch/memory/runtime-events?trace_id=trace-a&sort=desc",
            "/api/brainwatch/memory/runtime-events/event-a",
            "/api/brainwatch/turns/turn-a/memory?consumer=planner",
            "/api/brainwatch/turns/turn-a/runtime-events?proof_level=action_result",
            "/api/brainwatch/turns/turn-a/runtime-events/live?tail=true",
        )
        for path in paths:
            self.assertEqual(200, self.request_json(server, path)[0])
        self.assertEqual(
            ["memory_events", "memory_graph", "memory_graph_relations", "memory_claims", "memory_claim", "memory_evidence", "memory_relations",
             "memory_claim_turns", "memory_claim_runtime", "memory_runtime_events",
             "memory_runtime_event", "turn_memory", "turn_runtime", "turn_runtime_live"],
            [item[0] for item in calls],
        )
        self.assertEqual(
            [None, None, None, None, "claim-a", "claim-a", "claim-a", "claim-a", "claim-a", None,
             "event-a", "turn-a", "turn-a", "turn-a"],
            [item[1] for item in calls],
        )
        self.assertEqual(["derived_link"], calls[0][2]["fidelity"])
        self.assertEqual(["100"], calls[1][2]["node_limit"])
        self.assertEqual(["relation-a"], calls[2][2]["cursor"])
        self.assertEqual(["active"], calls[3][2]["lifecycle"])
        self.assertEqual(["observation_turn"], calls[7][2]["origin_class"])
        self.assertEqual(["actions"], calls[8][2]["category"])
        self.assertEqual(["trace-a"], calls[9][2]["trace_id"])
        self.assertEqual(["planner"], calls[11][2]["consumer"])
        self.assertEqual(["action_result"], calls[12][2]["proof_level"])
        self.assertEqual(["true"], calls[13][2]["tail"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/brainwatch/memory/claims/claim-a", data=b"{}")
        self.assertEqual(404, caught.exception.code)
        caught.exception.close()

    def test_memory_explorer_requires_brainwatch_access_token(self):
        calls = []
        server = self.make_server(
            access_token="memory-secret",
            brainwatch_handler=lambda *args: calls.append(args) or {"items": []},
        )
        server.start()
        paths = ("/api/brainwatch/memory/events", "/api/brainwatch/memory/graph",
                 "/api/brainwatch/memory/graph/working",
                 "/api/brainwatch/memory/graph/relations", "/api/brainwatch/memory/claims",
                 "/api/brainwatch/memory/runtime-events",
                 "/api/brainwatch/memory/runtime-events/event-a",
                 "/api/brainwatch/turns/turn-a/memory",
                 "/api/brainwatch/turns/turn-a/runtime-events",
                 "/api/brainwatch/turns/turn-a/runtime-events/live")
        for path in paths:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request_json(server, path)
            self.assertEqual(401, caught.exception.code)
            caught.exception.close()
        self.assertEqual([], calls)
        self.assertEqual(200, self.request_json(
            server, paths[1], headers={"X-EVE-Token": "memory-secret"},
        )[0])

    def test_action_feedback_route_is_narrow_authenticated_and_supports_undo(self):
        calls = []
        def feedback(conversation_id, message_id, decision, explanation=None):
            calls.append((conversation_id, message_id, decision, explanation))
            return {'decision': None if decision == 'undo' else decision,
                    'can_undo': decision != 'undo', 'explanation': explanation}
        server = self.make_server(semantic_feedback_handler=feedback)
        server.start()
        generic = '/api/conversations/conversation-1/messages/message-2/feedback'
        status, _, payload = self.request_json(server, generic, data=b'{"decision":"correct"}')
        self.assertEqual((200, 'correct'), (status, payload['feedback']['decision']))
        calls.clear()
        path = '/api/conversations/conversation-1/messages/message-2/semantic-feedback'
        status, _, payload = self.request_json(
            server, path, data=json.dumps({
                'decision': 'incorrect', 'explanation': 'Das Bild fehlte.',
            }).encode())
        self.assertEqual((status, payload['feedback']['decision']), (200, 'incorrect'))
        self.assertEqual('Das Bild fehlte.', payload['feedback']['explanation'])
        status, _, payload = self.request_json(
            server, path, data=json.dumps({'decision': 'undo'}).encode())
        self.assertEqual((status, payload['feedback']['can_undo']), (200, False))
        self.assertEqual(calls, [
            ('conversation-1', 'message-2', 'incorrect', 'Das Bild fehlte.'),
            ('conversation-1', 'message-2', 'undo', None),
        ])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request_json(server, path, data=b'[]')
        self.assertEqual(error.exception.code, 409)
        error.exception.close()

        protected = self.make_server(
            access_token='feedback-secret', semantic_feedback_handler=feedback)
        protected.start()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request_json(protected, path, data=b'{"decision":"incorrect"}')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_semantic_brainwatch_routes_and_explicit_rejection(self):
        calls = []
        def inspect(operation, claim_id, query):
            calls.append((operation, claim_id, query))
            return {"ok": True}
        server = self.make_server(brainwatch_handler=inspect)
        server.start()
        for path in ("/api/brainwatch/semantic-summary", "/api/brainwatch/semantic-composition",
                     "/api/brainwatch/semantic-links?limit=1", "/api/brainwatch/semantic-links/claim-1?cursor=2"):
            self.assertEqual(self.request_json(server, path)[0], 200)
        self.assertEqual([c[0] for c in calls],
                         ["semantic_summary", "semantic_composition", "semantic_list", "semantic_detail"])
        for path in ("/api/brainwatch/semantic-actions?limit=2", "/api/brainwatch/semantic-actions/group-1?cursor=2&evidence_cursor=3"):
            self.assertEqual(self.request_json(server, path)[0], 200)
        self.assertEqual([c[0] for c in calls[-2:]], ["semantic_actions", "semantic_action"])
        self.assertEqual(calls[-1][1], "group-1")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request_json(server, "/api/brainwatch/semantic-actions/group-1/reject", data=b"{}")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_dynamic_semantics_brainwatch_read_correct_and_undo_routes(self):
        calls = []
        def inspect(operation, item_id, payload):
            calls.append((operation, item_id, payload)); return {'ok': True}
        server = self.make_server(brainwatch_handler=inspect); server.start()
        self.assertEqual(self.request_json(server, '/api/brainwatch/semantic-similarity')[0], 200)
        relation = json.dumps({'left':'Licht','right':'nicht','polarity':'negative'}).encode()
        self.assertEqual(self.request_json(server, '/api/brainwatch/semantic-similarity/relations', data=relation)[0], 200)
        recognition = json.dumps({'input_formulation':'Wohnzimmer nicht aus','learned_claim_id':'claim-1','polarity':'negative'}).encode()
        self.assertEqual(self.request_json(server, '/api/brainwatch/semantic-similarity/recognitions', data=recognition)[0], 200)
        self.assertEqual(self.request_json(server, '/api/brainwatch/semantic-similarity/relations/relation-1/undo', data=b'{"confirmed":true}')[0], 200)
        self.assertEqual([item[0] for item in calls], [
            'semantic_similarity', 'semantic_similarity_relation',
            'semantic_similarity_recognition', 'semantic_similarity_undo'])
        self.assertEqual(calls[-1][1], 'relation-1')
        body = json.dumps({"claim_id": "claim-1", "confirmed": True}).encode()
        self.assertEqual(self.request_json(server, "/api/brainwatch/semantic-links/claim-1/reject", data=body)[0], 200)
        self.assertEqual(calls[-1], ("semantic_reject", "claim-1", {"claim_id": "claim-1", "confirmed": True}))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request_json(server, "/api/brainwatch/semantic-links/claim-1/reject", data=b"not-json")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_semantic_brainwatch_requires_existing_access_token(self):
        calls = []
        server = self.make_server(access_token="test-secret", brainwatch_handler=lambda *args: calls.append(args) or {})
        server.start()
        for path, body in (("/api/brainwatch/semantic-summary", None),
                           ("/api/brainwatch/semantic-composition", None),
                           ("/api/brainwatch/semantic-actions", None),
                           ("/api/brainwatch/semantic-actions/group-1", None),
                           ("/api/brainwatch/semantic-links/claim-1/reject", b'{"claim_id":"claim-1","confirmed":true}')):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request_json(server, path, data=body)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
        self.assertEqual(calls, [])
        self.assertEqual(self.request_json(server, "/api/brainwatch/semantic-summary", headers={"X-EVE-Token":"test-secret"})[0], 200)

    def test_turn_result_endpoint_returns_correlated_followup(self):
        server = self.make_server(turn_result_handler=lambda turn_id: {
            "turn_id": turn_id,
            "status": "complete",
            "presentation": {"status": "success", "revision": 4},
            "audio": {"status": "success", "audio_wav_base64": "UklGRg=="},
        })
        server.start()
        status, _, payload = self.request_json(server, "/api/turn-results/turn-42")
        self.assertEqual(status, 200)
        self.assertEqual(payload["turn_id"], "turn-42")
        self.assertEqual(payload["presentation"]["revision"], 4)

    def test_stop_is_idempotent_and_closes_socket(self):
        server = self.make_server()
        server.start()
        self.request_json(server, "/health/live")
        server.stop()
        server.stop()
        self.assertEqual(server.server.fileno(), -1)
        self.assertFalse(server._thread.is_alive())

    def test_stalled_raw_tls_client_does_not_block_valid_health_request(self):
        certificate = PROJECT_ROOT / "certs" / "eve-lan.crt"
        key = PROJECT_ROOT / "certs" / "eve-lan.key"
        if not certificate.exists() or not key.exists():
            self.skipTest("Lokales Testzertifikat fehlt")
        server = self.make_server(tls_cert=certificate, tls_key=key)
        server.start()
        raw_client = socket.create_connection(("127.0.0.1", server.port), timeout=1)
        try:
            status, _, payload = self.request_json(server, "/health/live")
        finally:
            raw_client.close()
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_tls_origin_must_use_https_even_for_the_same_host(self):
        certificate = PROJECT_ROOT / "certs" / "eve-lan.crt"
        key = PROJECT_ROOT / "certs" / "eve-lan.key"
        if not certificate.exists() or not key.exists():
            self.skipTest("Lokales Testzertifikat fehlt")
        server = self.make_server(
            tls_cert=certificate,
            tls_key=key,
            message_handler=lambda text, images: {"answer": text},
        )
        server.start()
        body = json.dumps({"text": "Hallo", "images": []}).encode()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/message",
                data=body,
                headers={"Origin": f"http://127.0.0.1:{server.port}"},
            )
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

        status, _, payload = self.request_json(
            server,
            "/api/message",
            data=body,
            headers={"Origin": f"https://127.0.0.1:{server.port}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "Hallo")

    def test_post_rejects_cross_origin_before_invoking_handler(self):
        handler = mock.Mock(return_value={"answer": "should not run"})
        server = self.make_server(message_handler=handler)
        server.start()
        body = json.dumps({"text": "öffne die Tür", "images": []}).encode()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/message",
                data=body,
                headers={"Origin": "https://attacker.invalid"},
            )
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(caught.exception.headers["X-Content-Type-Options"], "nosniff")
        caught.exception.close()
        handler.assert_not_called()

        # Matching a forged Host to the hostile Origin must not turn DNS
        # rebinding into a same-origin Home-Assistant control channel.
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/message",
                data=body,
                headers={
                    "Host": "attacker.invalid",
                    "Origin": "http://attacker.invalid",
                },
            )
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        handler.assert_not_called()

    def test_same_origin_post_is_accepted(self):
        server = self.make_server(message_handler=lambda text, images: {"answer": text})
        server.start()
        body = json.dumps({"text": "Hallo", "images": []}).encode()
        status, _, payload = self.request_json(
            server,
            "/api/message",
            data=body,
            headers={"Origin": f"http://127.0.0.1:{server.port}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "Hallo")

    def test_configured_lan_hostname_is_accepted(self):
        server = self.make_server(
            message_handler=lambda text, images: {"answer": text},
            allowed_hosts=["eve.lan"],
        )
        server.start()
        body = json.dumps({"text": "Hallo", "images": []}).encode()
        status, _, payload = self.request_json(
            server,
            "/api/message",
            data=body,
            headers={"Host": "eve.lan", "Origin": "http://eve.lan"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "Hallo")

    def test_notification_poll_is_post_only_and_cross_site_get_cannot_consume(self):
        notifications = mock.Mock(return_value={"notifications": [{"message": "Test"}]})
        server = self.make_server(notification_handler=notifications)
        server.start()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/notifications",
                headers={"Sec-Fetch-Site": "cross-site"},
            )
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        notifications.assert_not_called()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/notifications",
                headers={"Referer": "https://attacker.invalid/page"},
            )
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        notifications.assert_not_called()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(server, "/api/notifications")
        self.assertEqual(caught.exception.code, 405)
        self.assertEqual(caught.exception.headers["Allow"], "POST")
        caught.exception.close()
        notifications.assert_not_called()

        status, _, payload = self.request_json(
            server,
            "/api/notifications",
            method="POST",
            headers={"Origin": f"http://127.0.0.1:{server.port}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["notifications"][0]["message"], "Test")
        notifications.assert_called_once_with()

    def test_message_requires_json_content_type(self):
        handler = mock.Mock(return_value={"answer": "should not run"})
        server = self.make_server(message_handler=handler)
        server.start()
        body = json.dumps({"text": "Hallo", "images": []}).encode()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/message",
                data=body,
                headers={"Content-Type": "text/plain"},
            )
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        handler.assert_not_called()

    def test_message_accepts_only_bounded_base64_raster_screenshots(self):
        handler = mock.Mock(return_value={"answer": "ok"})
        server = self.make_server(message_handler=handler)
        server.start()

        invalid_images = [
            "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode(),
            "data:image/png;base64,not-valid-***",
            "data:image/png;base64," + base64.b64encode(b"not a png").decode(),
        ]
        for image in invalid_images:
            with self.subTest(image=image[:30]), self.assertRaises(urllib.error.HTTPError) as caught:
                body = json.dumps({"text": "", "images": [image]}).encode()
                self.request_json(server, "/api/message", data=body)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()

        valid_png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        body = json.dumps({"text": "", "images": [valid_png]}).encode()
        status, _, payload = self.request_json(server, "/api/message", data=body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "ok")
        handler.assert_called_once_with("", [valid_png])

    def test_message_rejects_image_above_per_image_limit(self):
        handler = mock.Mock(return_value={"answer": "should not run"})
        server = self.make_server(message_handler=handler)
        server.start()
        oversized_png = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nX"
        ).decode()
        body = json.dumps({"text": "", "images": [oversized_png]}).encode()

        with mock.patch("eve_agent.visual.MAX_IMAGE_BYTES", 8), self.assertRaises(
            urllib.error.HTTPError
        ) as caught:
            self.request_json(server, "/api/message", data=body)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        handler.assert_not_called()

    def test_turn_rejects_unknown_audio_content_type_without_temp_file(self):
        handler = mock.Mock(return_value={"answer": "should not run"})
        server = self.make_server(turn_handler=handler)
        server.start()

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request_json(
                server,
                "/api/turn",
                data=b"not audio",
                headers={"Content-Type": "application/octet-stream"},
            )
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        handler.assert_not_called()

    def test_turn_uses_suffix_matching_browser_audio_type(self):
        seen_suffixes = []

        def turn_handler(audio_path):
            seen_suffixes.append(audio_path.suffix)
            return {"answer": "ok"}

        server = self.make_server(turn_handler=turn_handler)
        server.start()
        status, _, payload = self.request_json(
            server,
            "/api/turn",
            data=b"fake mp4 audio",
            headers={"Content-Type": "audio/mp4; codecs=mp4a.40.2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "ok")
        self.assertEqual(seen_suffixes, [".m4a"])

    def test_stop_before_start_closes_socket_without_waiting(self):
        server = self.make_server()
        started = time.monotonic()
        server.stop()
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(server.server.fileno(), -1)

    def test_expected_tls_disconnect_does_not_delegate_to_traceback_logger(self):
        server = object.__new__(EveHTTPServer)
        with mock.patch.object(ThreadingHTTPServer, "handle_error") as parent_handler:
            try:
                raise ssl.SSLError("browser closed handshake")
            except ssl.SSLError:
                server.handle_error(None, ("127.0.0.1", 1))
        parent_handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
