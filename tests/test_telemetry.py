import json
import threading
import unittest

from eve_agent.telemetry import TurnTelemetry


class TurnTelemetryTest(unittest.TestCase):
    def test_trace_is_bounded_hierarchical_and_secret_redacted(self):
        telemetry = TurnTelemetry(limit=2)
        for index in range(3):
            telemetry.start(conversation_id="conversation-1", input_kind="text")
            telemetry.event(
                "minimal", "decision", duration_ms=12,
                details={"decision": "discover", "capability": "home_assistant"},
            )
            telemetry.event("home_assistant", "execute", duration_ms=20, details={
                "entity_id": "light.test", "token": "never-visible", "result": "ok",
            })
            telemetry.llm_call({"model": "qwen", "prompt_tokens": 10, "completion_tokens": 5})
            telemetry.route("home")
            telemetry.finish(details={"index": index})
        snapshot = telemetry.snapshot("conversation-1")
        serialized = json.dumps(snapshot)
        self.assertEqual(len(snapshot["turns"]), 2)
        self.assertNotIn("never-visible", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertTrue(snapshot["observability_only"])
        self.assertEqual(snapshot["turns"][0]["summary"]["usage"]["prompt_tokens"], 10)

    def test_observation_does_not_return_decisions_or_modify_inputs(self):
        telemetry = TurnTelemetry()
        original = {"service_data": {"brightness": 42}}
        telemetry.start(conversation_id=None, input_kind="voice")
        result = telemetry.event("home_assistant", "call", details=original)
        telemetry.finish()
        self.assertIsNone(result)
        self.assertEqual(original, {"service_data": {"brightness": 42}})

    def test_knowledge_flow_is_passive_structured_and_redacted(self):
        telemetry = TurnTelemetry()
        flow = {
            "version": 1,
            "stages": [{
                "kind": "web", "status": "sources_found", "label": "Web",
                "summary": "1 Quelle", "details": {"queries": ["test"], "token": "secret"},
            }],
        }
        telemetry.start(conversation_id="flow", input_kind="text")
        result = telemetry.knowledge_flow(flow)
        telemetry.finish()

        stored = telemetry.snapshot("flow")["turns"][0]["knowledge_flow"]
        self.assertIsNone(result)
        self.assertEqual("web", stored["stages"][0]["kind"])
        self.assertEqual("[REDACTED]", stored["stages"][0]["details"]["token"])
        self.assertEqual("secret", flow["stages"][0]["details"]["token"])

    def test_session_lifecycle_updates_turn_conversation_and_is_observability_only(self):
        telemetry = TurnTelemetry()
        telemetry.start(conversation_id="old", input_kind="text")
        telemetry.session_lifecycle(
            conversation_id="new", idle_time_seconds=301.5,
            configured_session_timeout_seconds=300,
            new_session=True, reason="inactivity",
        )
        telemetry.finish()

        turn = telemetry.snapshot()["turns"][0]
        self.assertEqual("new", turn["conversation_id"])
        lifecycle = turn["steps"][0]
        self.assertEqual("conversation", lifecycle["component"])
        self.assertTrue(lifecycle["details"]["new_session"])
        self.assertEqual("inactivity", lifecycle["details"]["reason"])

    def test_events_and_llm_calls_have_relative_timeline_bounds(self):
        telemetry = TurnTelemetry()
        telemetry.start(conversation_id=None, input_kind="text")
        start_ms = telemetry.elapsed_ms()
        telemetry.event("context", "prepare", duration_ms=1.5, start_ms=start_ms)
        telemetry.llm_call({"model": "qwen", "duration_ms": 2.0, "role": "planner"})
        telemetry.finish()

        turn = telemetry.snapshot()["turns"][0]
        step = turn["steps"][0]
        self.assertLessEqual(step["start_ms"], step["end_ms"])
        self.assertLessEqual(turn["llm_calls"][0]["start_ms"], turn["llm_calls"][0]["end_ms"])

    def test_new_requests_on_reused_worker_persist_while_previous_trace_is_active(self):
        import tempfile
        from pathlib import Path
        from eve_agent.storage import ConversationStore, EveDatabase

        telemetry = TurnTelemetry()
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(EveDatabase(Path(tmp) / "eve.db"))
            conversation = store.create()["id"]
            ids = []
            for backend_id in ("backend-first", "backend-second", None):
                current = telemetry.start(
                    conversation_id=conversation, input_kind="text",
                    turn_id=backend_id, new_turn=True,
                )
                ids.append(current)
                # browser_response and NativeToolRuntime join this request.
                self.assertEqual(current, telemetry.start(
                    conversation_id=conversation, input_kind="text",
                ))
                store.append_turn(conversation, "question", "answer", turn_id=current)
            self.assertEqual(3, len(set(ids)))
            self.assertEqual(["backend-first", "backend-second"], ids[:2])
            # Delayed completion must remain correlated with the old request.
            with telemetry.bind(ids[0]):
                telemetry.event("presentation", "complete")
                telemetry.finish()
            self.assertEqual(ids[-1], telemetry.active_id())
            self.assertEqual(6, len(store.messages(conversation)["messages"]))
            turns = {t["id"]: t for t in telemetry.snapshot()["turns"]}
            self.assertEqual("success", turns[ids[0]]["status"])
            self.assertEqual([], turns[ids[-1]]["steps"])

    def test_explicit_backend_id_does_not_join_another_active_request(self):
        telemetry = TurnTelemetry()
        telemetry.start(conversation_id="chat", input_kind="text", turn_id="first")
        self.assertEqual("second", telemetry.start(
            conversation_id="chat", input_kind="text", turn_id="second",
        ))

    def test_overlapping_threads_keep_turn_events_correlated(self):
        telemetry = TurnTelemetry()
        first = telemetry.start(conversation_id="a", input_kind="text")
        second_ready = threading.Event()

        def second_turn():
            second = telemetry.start(conversation_id="b", input_kind="text")
            telemetry.event("test", "second")
            telemetry.finish()
            second_ready.second_id = second
            second_ready.set()

        thread = threading.Thread(target=second_turn)
        thread.start()
        self.assertTrue(second_ready.wait(1))
        telemetry.event("test", "first")
        telemetry.finish()
        thread.join(1)

        turns = {turn["id"]: turn for turn in telemetry.snapshot()["turns"]}
        self.assertEqual(turns[first]["steps"][0]["operation"], "first")
        self.assertEqual(turns[second_ready.second_id]["steps"][0]["operation"], "second")


if __name__ == "__main__":
    unittest.main()
