import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.request
import urllib.error

from eve_agent.assist_api import AssistAPI
from eve_agent.assist_events import AssistEventInbox
from eve_agent.visual import VisualServer


class AssistEventsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.inbox = AssistEventInbox(self.path)
        self.payload = {"event_id": "motion-1", "event_type": "motion_detected",
                        "data": {"area": "  Flur\n", "nested": [False, 2, None]}}

    def test_event_is_durable_and_duplicate_id_is_idempotent(self):
        self.assertFalse(self.inbox.receive(self.payload)["duplicate"])
        restored = AssistEventInbox(self.path)
        self.assertTrue(restored.receive(self.payload)["duplicate"])
        events = restored.read()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"], self.payload["data"])
        self.assertEqual(events[0]["event_type"], "motion_detected")
        self.assertEqual(restored.read(after=events[0]["sequence"])["events"], [])
        with self.assertRaises(ValueError):
            restored.receive({**self.payload, "data": {"different": True}})

    def test_invalid_events_are_rejected_without_storage(self):
        for payload in ({}, {**self.payload, "data": []},
                        {**self.payload, "event_type": " "},
                        {**self.payload, "data": {"value": float("nan")}},
                        {**self.payload, "data": {"value": "x" * 65536}}):
            with self.assertRaises(ValueError):
                self.inbox.receive(payload)
        self.assertEqual(self.inbox.read()["events"], [])

    def test_authenticated_http_event_round_trip_without_chat_or_audio(self):
        transcriber, speaker, conversations, message = Mock(), Mock(), Mock(), Mock()
        transcriber.config = speaker.config = {"language": "de"}
        api = AssistAPI(transcriber, speaker, conversations, message, event_inbox=self.inbox)
        self.assertTrue(api.info()["events"])
        server = VisualServer(Path(self.temp.name), Mock(), "127.0.0.1", 0,
                              assist_handler=api, assist_token="test-token")
        self.addCleanup(server.stop)
        server.start()
        base = f"http://127.0.0.1:{server.port}/api/assist/events"
        def request(data=None, authorized=True, suffix=""):
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers["Authorization"] = "Bearer test-token"
            return urllib.request.urlopen(urllib.request.Request(base + suffix, data=data, headers=headers), timeout=3)
        for data in (None, json.dumps(self.payload).encode()):
            with self.assertRaises(urllib.error.HTTPError) as error:
                request(data, authorized=False)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
        self.assertEqual(self.inbox.read()["events"], [])
        for duplicate in (False, True):
            with request(json.dumps(self.payload).encode()) as response:
                self.assertEqual(response.status, 202)
                self.assertEqual(json.load(response), {"accepted": True, "event_id": "motion-1", "duplicate": duplicate})
        with request() as response:
            self.assertEqual(len(json.load(response)["events"]), 1)
        with request(suffix="?after=1") as response:
            self.assertEqual(json.load(response)["events"], [])
        with self.assertRaises(urllib.error.HTTPError) as error:
            request(b"x" * 65537)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            request(suffix="?limit=101")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        conversations.create.assert_not_called()
        message.assert_not_called()
        transcriber.transcribe.assert_not_called()
        speaker.synthesize.assert_not_called()

    def test_exact_grouping_keeps_all_receipts_and_newer_events_after_ack(self):
        for n in range(100):
            self.inbox.receive({**self.payload, "event_id": str(n)})
        self.inbox.receive({**self.payload, "event_id": "different", "data": {"area": "Flur"}})
        page = self.inbox.groups()
        self.assertEqual((page["pending_count"], page["pending_groups"], page["total_count"]), (101, 2, 101))
        group = next(g for g in page["groups"] if g["count"] == 100)
        self.assertEqual(self.inbox.groups()["pending_count"], 101)
        self.inbox.receive({**self.payload, "event_id": "later"})
        self.inbox.acknowledge(group["group_id"], group["through_sequence"])
        self.assertEqual(self.inbox.groups()["pending_count"], 2)
        self.assertEqual(AssistEventInbox(self.path).groups()["pending_count"], 2)
        self.assertEqual(self.inbox.groups()["total_count"], 102)
        with self.assertRaises(ValueError):
            self.inbox.acknowledge(group["group_id"], 101)

    def test_parallel_receipts_are_not_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: self.inbox.receive({**self.payload, "event_id": str(n)}), range(100)))
        self.assertEqual(self.inbox.groups()["groups"][0]["count"], 100)

    def test_brainwatch_event_route_is_authenticated_and_read_only(self):
        self.inbox.receive(self.payload)
        handler = Mock(side_effect=lambda op, identifier, query: self.inbox.groups())
        server = VisualServer(Path(self.temp.name), Mock(), "127.0.0.1", 0,
                              brainwatch_handler=handler, access_token="browser-token")
        self.addCleanup(server.stop)
        server.start()
        url = f"http://127.0.0.1:{server.port}/api/brainwatch/assist-events"
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url, timeout=3)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with urllib.request.urlopen(urllib.request.Request(url, headers={"X-EVE-Token": "browser-token"}), timeout=3) as response:
            self.assertEqual(json.load(response)["pending_count"], 1)
        handler.assert_called_once_with("assist_events", None, {})
        self.assertEqual(self.inbox.groups()["pending_count"], 1)

    def test_event_is_received_while_conversation_is_waiting(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        def conversation(text, images, identifier):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test conversation timed out")
            return {"answer": "reply", "conversation_id": identifier, "turn_id": "turn"}
        transcriber, speaker = Mock(config={"language": "de"}), Mock(config={"language": "de"})
        api = AssistAPI(transcriber, speaker, Mock(), conversation, event_inbox=self.inbox)
        server = VisualServer(Path(self.temp.name), Mock(), "127.0.0.1", 0,
                              assist_handler=api, assist_token="test-token")
        self.addCleanup(server.stop)
        server.start()
        def post(path, data):
            request = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/assist/{path}",
                data=json.dumps(data).encode(), headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=4) as response:
                return json.load(response)
        with ThreadPoolExecutor(max_workers=1) as pool:
            turn = pool.submit(post, "conversation", {"text": "chat", "images": [], "conversation_id": "chat-id"})
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(post("events", self.payload)["accepted"])
                self.assertFalse(turn.done())
                self.assertEqual(self.inbox.groups()["pending_count"], 1)
            finally:
                release.set()
            self.assertEqual(turn.result()["answer"], "reply")
        speaker.synthesize.assert_not_called()
