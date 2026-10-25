import io
import json
import tempfile
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from eve_agent.backend_turns import TurnCancelled
from eve_agent.llm import LocalLLMError, OpenAICompatibleLLM
from eve_agent.llm_context_telemetry import LLMContextTelemetry
from eve_agent.memory_runtime_telemetry import MemoryRuntimeRecorder, validate_event
from eve_agent.provenance import PlanningProvenance
from eve_agent.storage import EveDatabase


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class StreamResponse:
    status = 200

    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.lines)


class CapturingRecorder:
    def __init__(self, *, enabled=True, fail=False):
        self.enabled = enabled
        self.fail = fail
        self.batches = []
        self.diagnostics = []
        self.lock = threading.Lock()

    def record_trace_events(self, events, **kwargs):
        if self.fail:
            raise RuntimeError("write failed with token=super-secret")
        for event in events:
            validate_event(event)
        with self.lock:
            self.batches.append((list(events), dict(kwargs)))
        return [{"id": str(index)} for index, _event in enumerate(events)]

    def _diagnose(self, operation, exc):
        with self.lock:
            self.diagnostics.append((operation, type(exc).__name__))


class Cancellation:
    def __init__(self):
        self.cancelled = False

    def checkpoint(self):
        if self.cancelled:
            raise TurnCancelled("cancelled")


class LLMContextTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.recorder = CapturingRecorder()
        self.llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1/v1", "model": "test-model",
        })
        self.llm.memory_context_telemetry = LLMContextTelemetry(self.recorder)

    @staticmethod
    def response(content="ok"):
        return Response(json.dumps({
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        }).encode())

    @staticmethod
    def claims(count=1, prefix="claim"):
        return [
            {"claim_id": f"{prefix}-{index}", "compiler_evaluation_id": f"eval-{index}"}
            for index in range(count)
        ]

    def invoke(self, messages, *, claims=None, blocks=None, request=None,
               provenance=None, role="minimal_semantic"):
        provenance = provenance or PlanningProvenance.create("trace-test")
        request = request or self.response()
        with self.llm.logical_call() as call_id:
            sidecar = self.llm.memory_context_telemetry.assemble(
                messages=messages,
                blocks=blocks or ([{"message_index": 0, "claims": claims}] if claims else []),
                trace_id=provenance.trace_id,
                planner_round_id=provenance.planner_round_id,
                llm_call_id=call_id,
                consumer=role,
            )
            with self.llm.causal_provenance(provenance), self.llm.memory_context(sidecar):
                with patch("urllib.request.urlopen", return_value=request):
                    result = self.llm._request(messages, 20, 0, role=role)
        return result, call_id, sidecar

    def events(self):
        return [event for batch, _kwargs in self.recorder.batches for event in batch]

    def test_call_without_claims_records_only_transport_and_changes_no_payload(self):
        messages = [{"role": "user", "content": "Hallo"}]
        original = json.loads(json.dumps(messages))
        opened = []

        def urlopen(request, timeout=None):
            opened.append(json.loads(request.data))
            return self.response()

        provenance = PlanningProvenance.create("trace-empty")
        with self.llm.causal_provenance(provenance), patch(
            "urllib.request.urlopen", side_effect=urlopen,
        ):
            self.assertEqual("ok", self.llm._request(messages, 20, 0, role="answer"))
        self.assertEqual(original, messages)
        self.assertEqual(messages, opened[0]["messages"])
        self.assertEqual(["llm_transport_result"], [item["event_kind"] for item in self.events()])
        self.assertNotIn("claim_id", json.dumps(opened))

    def test_multiple_claims_and_blocks_cross_all_three_boundaries(self):
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Memory block one"},
            {"role": "user", "content": "Memory block two"},
        ]
        original = json.loads(json.dumps(messages))
        blocks = [
            {"message_index": 1, "claims": self.claims(2, "first")},
            {"message_index": 2, "claims": self.claims(1, "second")},
        ]
        _result, call_id, sidecar = self.invoke(messages, blocks=blocks)
        events = self.events()
        kinds = [item["event_kind"] for item in events]
        for kind in (
            "claim_added_to_prompt_context", "claim_received_by_llm_client",
            "claim_serialized_for_transport",
        ):
            self.assertEqual(3, kinds.count(kind))
        self.assertEqual(1, kinds.count("llm_transport_result"))
        claim_events = [item for item in events if item.get("claim_id")]
        self.assertEqual({sidecar.context_manifest_digest}, {
            item["context_manifest_digest"] for item in claim_events
        })
        self.assertEqual({call_id}, {item["llm_call_id"] for item in events})
        self.assertEqual(original, messages)
        encoded = json.dumps(events)
        self.assertNotIn("Memory block", encoded)
        self.assertNotIn("System", encoded)

    def test_all_context_blocks_and_claims_are_recorded_without_hidden_caps(self):
        messages = [
            {"role": "user", "content": f"block-{index}"}
            for index in range(20)
        ]
        blocks = [
            {"message_index": index, "claims": self.claims(5, f"block{index}")}
            for index in range(20)
        ]

        _result, _call_id, sidecar = self.invoke(messages, blocks=blocks)

        self.assertEqual(20, len(sidecar.blocks))
        self.assertEqual(100, sum(len(block.claims) for block in sidecar.blocks))
        events = self.events()
        for kind in (
            "claim_added_to_prompt_context", "claim_received_by_llm_client",
            "claim_serialized_for_transport",
        ):
            self.assertEqual(100, sum(item["event_kind"] == kind for item in events))

    def test_replaced_or_removed_context_block_has_no_claim_events(self):
        for replacement in (
            [{"role": "user", "content": "replacement"}],
            [],
        ):
            with self.subTest(replacement=replacement):
                self.recorder.batches.clear()
                messages = [{"role": "user", "content": "original memory"}]
                provenance = PlanningProvenance.create("trace-replaced")
                with self.llm.logical_call() as call_id:
                    sidecar = self.llm.memory_context_telemetry.assemble(
                        messages=messages,
                        blocks=[{"message_index": 0, "claims": self.claims()}],
                        trace_id=provenance.trace_id,
                        planner_round_id=provenance.planner_round_id,
                        llm_call_id=call_id,
                        consumer="minimal_semantic",
                    )
                    messages[:] = replacement
                    with self.llm.causal_provenance(provenance), self.llm.memory_context(sidecar):
                        with patch("urllib.request.urlopen", return_value=self.response()):
                            self.llm._request(messages, 20, 0, role="minimal_semantic")
                self.assertEqual(
                    ["llm_transport_result"],
                    [item["event_kind"] for item in self.events()],
                )

    def test_retry_keeps_call_id_and_uses_new_attempt_identity(self):
        messages = [{"role": "user", "content": "memory"}]
        provenance = PlanningProvenance.create("trace-retry")
        with self.llm.logical_call() as call_id:
            sidecar = self.llm.memory_context_telemetry.assemble(
                messages=messages,
                blocks=[{"message_index": 0, "claims": self.claims()}],
                trace_id=provenance.trace_id,
                planner_round_id=provenance.planner_round_id,
                llm_call_id=call_id,
                consumer="minimal_semantic",
            )
            with self.llm.causal_provenance(provenance), self.llm.memory_context(sidecar):
                with patch("urllib.request.urlopen", side_effect=TimeoutError("late")):
                    with self.assertRaises(LocalLLMError):
                        self.llm._request(messages, 20, 0, role="minimal_semantic")
                with patch("urllib.request.urlopen", return_value=self.response()):
                    self.llm._request(messages, 20, 0, role="minimal_semantic")
        events = self.events()
        transport = [item for item in events if item["event_kind"] in {
            "transport_failed", "llm_transport_result",
        }]
        self.assertEqual(["transport_failed", "llm_transport_result"], [
            item["event_kind"] for item in transport
        ])
        self.assertEqual([1, 2], [item["attempt_no"] for item in transport])
        self.assertEqual({call_id}, {item["llm_call_id"] for item in transport})
        self.assertEqual(2, len({item["attempt_id"] for item in transport}))
        self.assertEqual(1, sum(
            item["event_kind"] == "claim_added_to_prompt_context" for item in events
        ))

    def test_serialization_failure_is_visible_without_transport_or_provider_call(self):
        messages = [{"role": "user", "content": {"not-json"}}]
        provenance = PlanningProvenance.create("trace-serialization")
        opened = []
        with self.llm.logical_call() as call_id:
            sidecar = self.llm.memory_context_telemetry.assemble(
                messages=messages,
                blocks=[{"message_index": 0, "claims": self.claims()}],
                trace_id=provenance.trace_id,
                planner_round_id=provenance.planner_round_id,
                llm_call_id=call_id,
                consumer="minimal_semantic",
            )
            with self.llm.causal_provenance(provenance), self.llm.memory_context(sidecar):
                with patch("urllib.request.urlopen", side_effect=lambda *a, **k: opened.append(a)):
                    with self.assertRaises(TypeError):
                        self.llm._request(messages, 20, 0, role="minimal_semantic")
        self.assertEqual([], opened)
        kinds = [item["event_kind"] for item in self.events()]
        self.assertIn("claim_added_to_prompt_context", kinds)
        self.assertIn("claim_received_by_llm_client", kinds)
        self.assertNotIn("claim_serialized_for_transport", kinds)
        self.assertEqual("transport_failed", kinds[-1])
        self.assertEqual({
            "serialized": False, "transport_started": False,
            "response_received": False, "timed_out": False, "cancelled": False,
        }, self.events()[-1]["details"]["metrics"])

    def test_http_error_is_result_and_timeout_is_failed_transport(self):
        messages = [{"role": "user", "content": "plain"}]
        error = urllib.error.HTTPError(
            "http://local", 413, "too large", {}, io.BytesIO(b'{"error":"large"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LocalLLMError):
                self.llm._request(messages, 20, 0)
        http_event = self.events()[-1]
        self.assertEqual("llm_transport_result", http_event["event_kind"])
        self.assertEqual(413, http_event["details"]["http_status"])
        self.recorder.batches.clear()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            with self.assertRaises(LocalLLMError):
                self.llm._request(messages, 20, 0)
        self.assertEqual("transport_failed", self.events()[-1]["event_kind"])
        self.assertTrue(self.events()[-1]["details"]["metrics"]["serialized"])
        self.assertTrue(self.events()[-1]["details"]["metrics"]["transport_started"])
        self.assertFalse(self.events()[-1]["details"]["metrics"]["response_received"])

    def test_streaming_success_and_user_cancellation_are_distinct(self):
        success = StreamResponse([
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n',
            "data: [DONE]\n",
        ])
        with patch("urllib.request.urlopen", return_value=success):
            self.assertEqual("ok", self.llm._request_stream(
                [{"role": "user", "content": "stream"}], 20, 0, lambda _chunk: None,
            ))
        self.assertEqual("success", self.events()[-1]["outcome_status"])
        self.recorder.batches.clear()
        cancellation = Cancellation()

        def cancel(_chunk):
            cancellation.cancelled = True

        interrupted = StreamResponse([
            'data: {"choices":[{"delta":{"content":"first"}}]}\n',
            'data: {"choices":[{"delta":{"content":"second"}}]}\n',
        ])
        with self.llm.cancellable(cancellation), patch(
            "urllib.request.urlopen", return_value=interrupted,
        ):
            with self.assertRaises(TurnCancelled):
                self.llm._request_stream(
                    [{"role": "user", "content": "stream"}], 20, 0, cancel,
                )
        event = self.events()[-1]
        self.assertEqual("llm_transport_result", event["event_kind"])
        self.assertEqual("cancelled", event["event_status"])

    def test_disabled_and_failed_recorder_are_fail_open(self):
        self.recorder.enabled = False
        with patch("urllib.request.urlopen", return_value=self.response()):
            self.assertEqual("ok", self.llm._request([], 20, 0))
        self.assertEqual([], self.recorder.batches)
        failing = CapturingRecorder(fail=True)
        self.llm.memory_context_telemetry = LLMContextTelemetry(failing)
        with patch("urllib.request.urlopen", return_value=self.response()):
            self.assertEqual("ok", self.llm._request([], 20, 0))
        self.assertTrue(failing.diagnostics)

    def test_parallel_contexts_keep_claims_and_calls_isolated(self):
        barrier = threading.Barrier(2)

        def worker(index):
            messages = [{"role": "user", "content": f"memory-{index}"}]
            provenance = PlanningProvenance.create(f"trace-{index}")
            with self.llm.logical_call() as call_id:
                sidecar = self.llm.memory_context_telemetry.assemble(
                    messages=messages,
                    blocks=[{"message_index": 0, "claims": self.claims(1, f"claim{index}")}],
                    trace_id=provenance.trace_id,
                    planner_round_id=provenance.planner_round_id,
                    llm_call_id=call_id,
                    consumer="minimal_semantic",
                )
                with self.llm.causal_provenance(provenance), self.llm.memory_context(sidecar):
                    barrier.wait()
                    self.llm._request(messages, 20, 0, role="minimal_semantic")
            return call_id

        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: self.response()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                call_ids = list(pool.map(worker, range(2)))
        for batch, _kwargs in self.recorder.batches:
            claims = {item.get("claim_id") for item in batch if item.get("claim_id")}
            calls = {item["llm_call_id"] for item in batch}
            self.assertEqual(1, len(claims))
            self.assertEqual(1, len(calls))
        self.assertEqual(2, len(set(call_ids)))

    def test_events_are_persisted_in_one_batch_without_text_or_used_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            database = EveDatabase(Path(directory) / "eve.db", lifecycle_audit=False)
            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                        verification_policy,created_at,updated_at)
                       VALUES ('claim-0','opaque_fact','test','one','Private text','{}',
                               'active','stable',datetime('now'),datetime('now'))"""
                )
            recorder = MemoryRuntimeRecorder(database, enabled=True)
            self.llm.memory_context_telemetry = LLMContextTelemetry(recorder)
            self.invoke([{"role": "user", "content": "Private text"}], claims=self.claims())
            with database.connect() as connection:
                rows = connection.execute(
                    "SELECT event_kind,details_json FROM memory_runtime_events ORDER BY occurred_at,id"
                ).fetchall()
            self.assertEqual(4, len(rows))
            encoded = json.dumps([tuple(row) for row in rows])
            self.assertNotIn("Private text", encoded)
            self.assertNotIn("used", encoded)


if __name__ == "__main__":
    unittest.main()
