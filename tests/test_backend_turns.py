import threading
import time
import unittest

from eve_agent.backend_turns import BackendTurnStore, TurnCancelled


class BackendTurnStoreTest(unittest.TestCase):
    def test_response_postprocessing_remains_active_until_success_failure_or_cancellation(self):
        ready = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.set_response(turn_id, {'answer': 'Antwort'})
            ready.set()
            # The separate completion worker owns the remaining lifetime.

        store = BackendTurnStore(runner)
        self.addCleanup(store.close)
        for status in ('completed', 'failed', 'cancelled'):
            with self.subTest(status=status):
                ready.clear()
                turn_id = store.start('Lokal', [], 'local')['turn_id']
                self.assertTrue(ready.wait(2))
                self.assertTrue(store.has_active())
                store.update(turn_id, status=status)
                self.assertFalse(store.has_active())

    def test_discover_running_turn_by_conversation_without_client_marker(self):
        release = threading.Event()
        def runner(turn_id, _text, _images, _conversation_id, store):
            release.wait(2)
            store.update(turn_id, status="completed")
        store = BackendTurnStore(runner)
        self.addCleanup(store.close)
        self.addCleanup(release.set)
        self.assertFalse(store.has_active())
        turn_id = store.start("Toolcall", [], "chat-a")["turn_id"]
        self.assertTrue(store.has_active())
        self.assertEqual(turn_id, store.active_for_conversation("chat-a"))
        self.assertIsNone(store.active_for_conversation("chat-b"))
        release.set()
        self.wait_terminal(store, turn_id)
        self.assertFalse(store.has_active())
        self.assertIsNone(store.active_for_conversation("chat-a"))

    def test_reasoning_is_streamed_separately_and_never_becomes_answer(self):
        release = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append_reasoning(turn_id, "Memory prüfen …")
            release.wait(1)
            store.append(turn_id, "Antwort")

        store = BackendTurnStore(runner)
        self.addCleanup(store.close)
        turn_id = store.start("Test", [], None)["turn_id"]
        snapshot = store.snapshot(turn_id)
        for _ in range(20):
            if snapshot["reasoning"]:
                break
            snapshot = store.wait(turn_id, snapshot["version"], timeout=.1)
        self.assertEqual("Memory prüfen …", snapshot["reasoning"])
        self.assertEqual("", snapshot["answer"])
        release.set()
        for _ in range(20):
            snapshot = store.wait(turn_id, snapshot["version"], timeout=.1)
            if snapshot["answer"]:
                break
        self.assertEqual("Antwort", snapshot["answer"])
        self.assertEqual("Memory prüfen …", snapshot["reasoning"])

    def test_answer_preview_is_reversible_and_separate_from_committed_answer(self):
        release = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append_answer_preview(turn_id, "Vorläufig")
            release.wait(1)
            store.clear_answer_preview(turn_id)
            store.append(turn_id, "Endgültig")

        store = BackendTurnStore(runner)
        self.addCleanup(store.close)
        turn_id = store.start("Test", [], None)["turn_id"]
        snapshot = store.snapshot(turn_id)
        for _ in range(20):
            if snapshot["answer_preview"]:
                break
            snapshot = store.wait(turn_id, snapshot["version"], timeout=.1)
        self.assertEqual("Vorläufig", snapshot["answer_preview"])
        self.assertEqual("", snapshot["answer"])
        release.set()
        for _ in range(20):
            snapshot = store.wait(turn_id, snapshot["version"], timeout=.1)
            if snapshot["answer"]:
                break
        self.assertEqual("", snapshot["answer_preview"])
        self.assertEqual("Endgültig", snapshot["answer"])

    def wait_terminal(self, store, turn_id, timeout=2):
        deadline = time.monotonic() + timeout
        snapshot = store.snapshot(turn_id)
        while snapshot["status"] not in store.TERMINAL and time.monotonic() < deadline:
            snapshot = store.wait(turn_id, snapshot["version"], .1)
        return snapshot

    def test_turn_streams_and_completes_under_backend_ownership(self):
        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append(turn_id, "Hallo")
            store.append(turn_id, " Welt")
            store.set_response(turn_id, {"turn_id": turn_id, "answer": "Hallo Welt"})
            store.update(turn_id, status="completed", completed_at=time.time())

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "conversation-a")
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("completed", final["status"])
            self.assertEqual("Hallo Welt", final["answer"])
            self.assertEqual("conversation-a", final["conversation_id"])
            self.assertEqual(final["turn_id"], final["response"]["turn_id"])
        finally:
            store.close()

    def test_audio_segments_are_ordered_and_cancel_suppresses_late_audio(self):
        release = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.publish_audio(turn_id, "Eins. ", "MQ==")
            store.publish_audio(turn_id, "Zwei.", "Mg==")
            release.wait(1)
            store.publish_audio(turn_id, "Zu spät", "Mw==")
            store.checkpoint(turn_id)

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            turn_id = started["turn_id"]
            deadline = time.monotonic() + 1
            snapshot = store.snapshot(turn_id)
            while len(snapshot["audio_segments"]) < 2 and time.monotonic() < deadline:
                snapshot = store.wait(turn_id, snapshot["version"], .1)
            self.assertEqual([0, 1], [item["sequence"] for item in snapshot["audio_segments"]])
            store.cancel(turn_id)
            release.set()
            final = self.wait_terminal(store, turn_id)
            self.assertEqual("cancelled", final["status"])
            self.assertEqual(2, len(final["audio_segments"]))
        finally:
            release.set()
            store.close()

    def test_observer_disconnect_does_not_cancel_running_turn_and_reconnect_recovers_snapshot(self):
        release = threading.Event()
        partial_ready = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append(turn_id, "Teil")
            partial_ready.set()
            release.wait(1)
            store.append(turn_id, "antwort")
            store.update(turn_id, response={"turn_id": turn_id, "answer": "Teilantwort"})
            store.update(turn_id, status="completed", completed_at=time.time())

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "original-session")
            turn_id = started["turn_id"]
            self.assertTrue(partial_ready.wait(1))
            partial = store.snapshot(turn_id)
            # Dropping this local snapshot models an observer disappearing; the
            # worker has no dependency on it and remains running.
            self.assertEqual("running", partial["status"])
            self.assertEqual("Teil", partial["answer"])
            release.set()
            recovered = self.wait_terminal(store, turn_id)
            self.assertEqual("completed", recovered["status"])
            self.assertEqual("Teilantwort", recovered["answer"])
            self.assertEqual("original-session", recovered["conversation_id"])
        finally:
            release.set()
            store.close()

    def test_failure_has_terminal_snapshot_without_completed_response(self):
        def runner(*_args):
            raise RuntimeError("LLM kaputt")

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("failed", final["status"])
            self.assertIsNone(final["response"])
            self.assertEqual("", final["answer"])
            self.assertIn("LLM kaputt", final["error"])
            report = final["failure_report"]
            self.assertEqual(started["turn_id"], report["turn_id"])
            self.assertEqual("Hi", report["input_text"])
            self.assertEqual("c", report["conversation_id"])
            self.assertEqual("unknown", report["category"])
        finally:
            store.close()

    def test_failure_after_first_delta_preserves_committed_partial_answer(self):
        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append(turn_id, "Bereits veröffentlicht")
            raise RuntimeError("LLM-Verbindung abgebrochen")

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("failed", final["status"])
            self.assertEqual("Bereits veröffentlicht", final["answer"])
            self.assertIsNotNone(final["answer_committed_at"])
            self.assertIsNone(final["response"])
        finally:
            store.close()

    def test_final_response_cannot_replace_published_answer(self):
        def runner(turn_id, _text, _images, _conversation_id, store):
            store.append(turn_id, "Antwort A")
            store.set_response(turn_id, {"answer": "Antwort B"})

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("failed", final["status"])
            self.assertEqual("Antwort A", final["answer"])
            self.assertIsNone(final["response"])
        finally:
            store.close()

    def test_non_streaming_response_supplies_final_answer(self):
        def runner(turn_id, _text, _images, _conversation_id, store):
            store.set_response(turn_id, {"answer": "Fallback vor dem Stream"})
            store.update(turn_id, status="completed", completed_at=time.time())

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("completed", final["status"])
            self.assertEqual("Fallback vor dem Stream", final["answer"])
        finally:
            store.close()

    def test_voice_task_publishes_final_transcript_before_answer_completion(self):
        transcript_seen = threading.Event()
        release = threading.Event()

        def unused_runner(*_args):
            self.fail("normal runner must not be used")

        store = BackendTurnStore(unused_runner)
        try:
            def voice_task(turn_id, owner):
                owner.update(turn_id, transcript="Das hat EVE verstanden.")
                transcript_seen.set()
                release.wait(1)
                owner.append(turn_id, "Antwort")
                owner.update(turn_id, response={"answer": "Antwort"}, status="completed")

            started = store.start_task("voice-session", voice_task)
            self.assertTrue(transcript_seen.wait(1))
            running = store.snapshot(started["turn_id"])
            self.assertEqual("running", running["status"])
            self.assertEqual("Das hat EVE verstanden.", running["transcript"])
            self.assertEqual("", running["answer"])
            release.set()
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("completed", final["status"])
        finally:
            release.set()
            store.close()

    def test_cancel_during_stream_stops_chunks_and_is_idempotent(self):
        first_chunk = threading.Event()
        release = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            cancellation = store.cancellation(turn_id)
            store.append(turn_id, "Teil")
            first_chunk.set()
            release.wait(1)
            cancellation.checkpoint()
            store.append(turn_id, " darf nicht erscheinen")

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            self.assertTrue(first_chunk.wait(1))
            first_cancel = store.cancel(started["turn_id"])
            second_cancel = store.cancel(started["turn_id"])
            self.assertTrue(first_cancel["cancel_requested"])
            self.assertEqual(first_cancel["cancel_requested_at"], second_cancel["cancel_requested_at"])
            release.set()
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("cancelled", final["status"])
            self.assertEqual("Teil", final["answer"])
            self.assertIsNone(final["response"])
        finally:
            release.set()
            store.close()

    def test_commit_wins_race_and_late_cancel_cannot_change_completion(self):
        committed = threading.Event()
        release = threading.Event()

        def runner(turn_id, _text, _images, _conversation_id, store):
            store.begin_commit(turn_id)
            committed.set()
            release.wait(1)
            store.update(turn_id, response={"answer": "fertig"}, status="completed")

        store = BackendTurnStore(runner)
        try:
            started = store.start("Hi", [], "c")
            self.assertTrue(committed.wait(1))
            unchanged = store.cancel(started["turn_id"])
            self.assertFalse(unchanged["cancel_requested"])
            self.assertFalse(unchanged["cancellable"])
            release.set()
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("completed", final["status"])
        finally:
            release.set()
            store.close()

    def test_cancel_before_commit_prevents_persistence_boundary(self):
        store = BackendTurnStore(lambda *_: None)
        try:
            started = store.start_task("c", lambda turn_id, owner: (
                owner.cancel(turn_id), owner.begin_commit(turn_id)
            ))
            final = self.wait_terminal(store, started["turn_id"])
            self.assertEqual("cancelled", final["status"])
            self.assertIsNone(final["response"])
        finally:
            store.close()
