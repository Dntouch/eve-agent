import io
import json
import unittest
import urllib.error
import unittest.mock

from eve_agent.llm import (
    LocalLLMError,
    LocalLLMOutputLimitError,
    OpenAICompatibleLLM,
    UNIFIED_PRESENTATION_MARKER,
)
from eve_agent.telemetry import TurnTelemetry
from tests.ha_contract_fixtures import provider_plan


class StreamingResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def __iter__(self): return iter(self.lines)


class CapturingLLM(OpenAICompatibleLLM):
    def __init__(self):
        super().__init__({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        self.messages = None

    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        return json.dumps(provider_plan(clarification="Welches Gerät meinst du?"))


class NovaDecisionLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        return '{"decision":"approve","confidence":0.91}'


class TurnPlannerLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        return (
            '{"tool":"home_assistant","confidence":0.95,"context_required":false,'
            '"requested_aspect":"aktueller Eingangszustand","required_evidence":"aktueller Sensorzustand",'
            '"contract_match":true,'
            '"evidence_basis":"get_state liefert Zustandsdaten"}'
        )


class RejectingTurnPlannerLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        return (
            '{"tool":"network","confidence":0.91,"context_required":false,'
            '"requested_aspect":"interne Hardwareeigenschaft","required_evidence":"direkte Hardwareinventur",'
            '"contract_match":false,'
            '"evidence_basis":"Netzwerkvertrag liefert dafür keine direkte Evidenz"}'
        )


class CapabilityResolverLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        return (
            '{"decision":"authorize","authorized_tool":"web",'
            '"provider_resolution_required":false,"clarification":"","reason":"Vertrag passt"}'
        )


class ConfigurableCapabilityResolverLLM(CapturingLLM):
    def __init__(self, response):
        super().__init__()
        self.response = response

    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        return json.dumps(self.response, ensure_ascii=False)


class PresentationDecisionLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        return '{"action":"none"}'


class WebPlannerLLM(CapturingLLM):
    def __init__(self, response):
        super().__init__()
        self.response = response

    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        return self.response


class CameraHomePlannerLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        self.request_kwargs = kwargs
        schema = kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {})
        choices = schema.get("properties", {}).get("actions", {}).get("items", {}).get("oneOf", [])
        camera = next((v for v in choices if v.get("properties", {}).get("type", {}).get("const") == "get_camera_snapshot"), None)
        actions = [{"type":"get_camera_snapshot","entity_id":"camera.haustuer"}] if camera else []
        return json.dumps(provider_plan(actions))


class RepairingWorkTaskLLM(CapturingLLM):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.calls.append((messages, max_tokens, kwargs))
        return '{"operation":"create_items","arguments":{"items":['


class RetryingWorkTaskLLM(CapturingLLM):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.calls.append(messages)
        if len(self.calls) < 3:
            return '{"operation":"update_item","arguments":{"item_id":"task-1" "changes":{}}}'
        return '{"operation":"update_item","arguments":{"item_id":"task-1","description_message_id":"message-1","changes":{}}}'


class NoisyWorkTaskLLM(CapturingLLM):
    def _request(self, messages, max_tokens, temperature, **kwargs):
        self.messages = messages
        return (
            'Vorläufig: {"operation":"update_item","arguments":{"item_id":"broken" "changes":{}}}\n'
            'Korrektur: {"operation":"clarify","arguments":{},'
            '"clarification":"Welche Beschreibung soll ich verwenden?"}\nDanach nichts ausführen.'
        )


class SpeechPerspectiveTest(unittest.TestCase):
    def test_configured_temperature_reaches_text_and_tool_transports(self):
        messages = [{"role": "user", "content": "Hallo"}]
        for configured in (None, 0.0, 1.0):
            for streaming in (False, True):
                for tools in (False, True):
                    with self.subTest(temperature=configured, streaming=streaming, tools=tools):
                        llm = OpenAICompatibleLLM({
                            "base_url": "http://127.0.0.1:1/v1", "model": "test",
                            "temperature": configured,
                        })
                        if streaming:
                            response = StreamingResponse([
                                'data: {"choices":[{"delta":{"content":"Hallo"},"finish_reason":"stop"}]}\n',
                                'data: [DONE]\n',
                            ])
                        else:
                            response = io.BytesIO(json.dumps({"choices": [{
                                "message": {"role": "assistant", "content": "Hallo"},
                                "finish_reason": "stop",
                            }]}).encode())
                        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
                            with llm.stream_answers((lambda _: None) if streaming else None):
                                if tools:
                                    llm.request_tool_turn(messages, [], None, 0.3)
                                else:
                                    llm._request(messages, None, 0.3, role="answer")
                        payload = json.loads(opened.call_args.args[0].data)
                        self.assertEqual(configured if configured is not None else 0.3, payload["temperature"])
                        self.assertEqual(streaming, payload["stream"])

    def test_learning_stream_preserves_context_error_for_work_memory_fallback(self):
        from eve_agent.llm import LocalLLMStreamError
        llm = OpenAICompatibleLLM({'base_url': 'http://localhost:1/v1', 'model': 'test'})
        events = ['data: ' + json.dumps({'error': {
            'type': 'exceed_context_size_error', 'message': 'context size exceeded'}}) + '\n']
        with unittest.mock.patch('urllib.request.urlopen', return_value=StreamingResponse(events)):
            with self.assertRaises(LocalLLMStreamError) as error:
                llm.analyze_conversation_learning([{'turn_id': 'one'}])
        self.assertEqual(error.exception.provider_code, 'exceed_context_size_error')

    def test_learning_stream_preserves_output_limit_and_partial_response(self):
        llm = OpenAICompatibleLLM({'base_url': 'http://localhost:1/v1', 'model': 'test'})
        events = ['data: {"choices":[{"delta":{"content":"{\\\"turns\\\":"},"finish_reason":"length"}]}\n',
                  'data: [DONE]\n']
        with unittest.mock.patch('urllib.request.urlopen', return_value=StreamingResponse(events)):
            with self.assertRaises(LocalLLMOutputLimitError) as error:
                llm.analyze_conversation_learning([{'turn_id': 'one'}])
        self.assertEqual(error.exception.partial_response, '{"turns":')

    def test_empty_learning_stream_records_completed_response(self):
        from eve_agent.llm import EmptyModelResponseError
        llm = OpenAICompatibleLLM({'base_url': 'http://localhost:1/v1', 'model': 'test'})
        events = ['data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n', 'data: [DONE]\n']
        with unittest.mock.patch('urllib.request.urlopen', return_value=StreamingResponse(events)):
            with self.assertRaises(EmptyModelResponseError) as error:
                llm.analyze_conversation_learning([{'turn_id': 'one'}])
        self.assertTrue(error.exception.response_evidence['stream_done'])
        self.assertEqual(error.exception.response_evidence['finish_reason'], 'stop')






    def test_visible_answer_stream_assembles_chunks_and_records_ttft(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        telemetry = TurnTelemetry()
        llm.telemetry = telemetry
        telemetry.start(conversation_id="c", input_kind="text")
        events = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
            'data: {"choices":[{"delta":{"content":"   "}}]}\n',
            'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n',
            'data: {"choices":[{"delta":{"content":" Welt"}}]}\n',
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n',
            'data: [DONE]\n',
        ]
        received = []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with llm.stream_answers(received.append):
                answer = llm.complete([{"role": "user", "content": "Hi"}])
        telemetry.finish()
        self.assertEqual("   Hallo Welt", answer)
        self.assertEqual(answer, "".join(received))
        call = telemetry.snapshot("c")["turns"][0]["llm_calls"][0]
        self.assertTrue(call["streaming"])
        self.assertIsNotNone(call["ttft_ms"])
        self.assertIsNotNone(call["generation_ms"])
        self.assertEqual(2, call["completion_tokens"])
        self.assertEqual("visible_generation_fallback", call["tokens_per_second_basis"])

    def test_provider_reasoning_stream_is_separate_from_visible_answer(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            'data: {"choices":[{"delta":{"reasoning_content":"Ich prüfe "}}]}\n',
            'data: {"choices":[{"delta":{"reasoning_content":"das Memory."}}]}\n',
            'data: {"choices":[{"delta":{"content":"Gefunden."}}]}\n',
            'data: [DONE]\n',
        ]
        visible, reasoning = [], []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with llm.stream_reasoning(reasoning.append), llm.stream_answers(visible.append):
                answer = llm.complete([{"role": "user", "content": "Suche"}])
        self.assertEqual("Gefunden.", answer)
        self.assertEqual(["Gefunden."], visible)
        self.assertEqual("Ich prüfe das Memory.", "".join(reasoning))

    def test_native_stream_preserves_server_error_instead_of_empty_response(self):
        from eve_agent.llm import LocalLLMStreamError
        llm = OpenAICompatibleLLM({"base_url": "http://localhost:1/v1", "model": "test"})
        events = ['data: ' + json.dumps({"error": {"type": "exceed_context_size_error", "message": "request exceeds the available context size"}}) + '\n']
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)), llm.stream_reasoning(lambda _: None):
            with self.assertRaises(LocalLLMStreamError) as error:
                llm.request_tool_turn([{"role":"user","content":"test"}], [], None)
        self.assertEqual("exceed_context_size_error", error.exception.provider_code)
        self.assertIn("context size", str(error.exception))

    def test_empty_native_stream_records_finish_and_done_before_raising(self):
        llm = OpenAICompatibleLLM({"base_url": "http://localhost:1/v1", "model": "test"})
        telemetry = TurnTelemetry()
        llm.telemetry = telemetry
        telemetry.start(conversation_id=None, input_kind="text")
        events = ['data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n', 'data: [DONE]\n']
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)), llm.stream_reasoning(lambda _: None):
            with self.assertRaises(LocalLLMError):
                llm.request_tool_turn([{"role":"user","content":"test"}], [], None)
        call=telemetry.snapshot()["turns"][0]["llm_calls"][-1]
        self.assertEqual("stop",call["finish_reason"])
        self.assertTrue(call["stream_done"])
        self.assertEqual(1,call["stream_event_count"])
        self.assertEqual(0,call["content_chars"])

    def test_native_stream_reads_json_error_returned_without_sse(self):
        from eve_agent.llm import LocalLLMStreamError
        llm=OpenAICompatibleLLM({"base_url":"http://localhost:1/v1","model":"test"})
        lines=[json.dumps({"error":{"code":"context_error","message":"too much input"}})]
        with unittest.mock.patch("urllib.request.urlopen",return_value=StreamingResponse(lines)), llm.stream_reasoning(lambda _: None):
            with self.assertRaises(LocalLLMStreamError) as error:
                llm.request_tool_turn([{"role":"user","content":"test"}],[],None)
        self.assertIn("too much input",str(error.exception))

    def test_native_tool_turn_streams_reasoning_and_reassembles_tool_call(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            'data: {"choices":[{"delta":{"reasoning":"Passenden Provider prüfen."}}]}\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            '"function":{"name":"home_assistant","arguments":"{\\"operation\\":\\"get_"}}]}}]}\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"state\\"}"}}]},"finish_reason":"tool_calls"}]}\n',
            'data: [DONE]\n',
        ]
        reasoning = []
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=StreamingResponse(events),
        ) as opened:
            with llm.stream_reasoning(reasoning.append):
                result = llm.request_tool_turn(
                    [{"role": "user", "content": "Status"}],
                    [{"type": "function", "function": {"name": "home_assistant"}}],
                    None,
                )
        self.assertEqual("Passenden Provider prüfen.", "".join(reasoning))
        self.assertEqual([{
            "id": "call_1", "name": "home_assistant",
            "arguments": {"operation": "get_state"},
        }], result["tool_calls"])
        self.assertEqual("tool_calls", result["finish_reason"])
        self.assertTrue(json.loads(opened.call_args.args[0].data)["stream"])

    def test_unfinished_empty_stream_is_not_a_completed_empty_response(self):
        from eve_agent.llm import LocalLLMStreamError
        llm = OpenAICompatibleLLM({'base_url':'http://127.0.0.1:1/v1','model':'test'})
        with unittest.mock.patch('urllib.request.urlopen', return_value=StreamingResponse([])):
            with llm.stream_answers(lambda _: None):
                with self.assertRaises(LocalLLMStreamError) as caught:
                    llm.request_tool_turn([{'role':'user','content':'Test'}], [], None)
        self.assertEqual('incomplete_stream', caught.exception.provider_code)

    def test_reasoning_only_response_is_typed_and_retains_observed_protocol_evidence(self):
        from eve_agent.llm import EmptyModelResponseError
        llm = OpenAICompatibleLLM({'base_url': 'http://127.0.0.1:1/v1', 'model': 'test'})
        events = ['data: {"choices":[{"delta":{"reasoning_content":"Checking data"}}]}\n',
                  'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n', 'data: [DONE]\n']
        with unittest.mock.patch('urllib.request.urlopen', return_value=StreamingResponse(events)):
            with llm.stream_answers(lambda _: None):
                with self.assertRaises(EmptyModelResponseError) as caught:
                    llm.request_tool_turn([{'role': 'user', 'content': 'Test'}], [], None)
        self.assertEqual({'finish_reason': 'stop', 'stream_done': True, 'reasoning_chars': 13,
                          'content_chars': 0, 'tool_calls': 0}, caught.exception.response_evidence)

    def test_native_final_answer_is_previewed_then_committed_to_answer_stream(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            'data: {"choices":[{"delta":{"content":"  Hallo "}}]}\n',
            'data: {"choices":[{"delta":{"content":"Welt  "},"finish_reason":"stop"}]}\n',
            'data: [DONE]\n',
        ]
        previews, committed, resets = [], [], []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with (
                llm.stream_answers(committed.append),
                llm.stream_tool_previews(previews.append, lambda: resets.append(True)),
            ):
                result = llm.request_tool_turn(
                    [{"role": "user", "content": "Hi"}],
                    [{"type": "function", "function": {"name": "tool"}}],
                    None,
                )
        self.assertEqual("Hallo Welt", "".join(previews))
        self.assertEqual(["Hallo Welt"], committed)
        self.assertEqual([], resets)
        self.assertEqual("Hallo Welt", result["content"])
        self.assertEqual([], result["tool_calls"])

    def test_native_tool_call_retracts_accompanying_text_preview(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            'data: {"choices":[{"delta":{"content":"Ich prüfe das."}}]}\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            '"function":{"name":"tool","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}\n',
            'data: [DONE]\n',
        ]
        previews, committed, resets = [], [], []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with (
                llm.stream_answers(committed.append),
                llm.stream_tool_previews(previews.append, lambda: resets.append(True)),
            ):
                result = llm.request_tool_turn(
                    [{"role": "user", "content": "Prüfe"}],
                    [{"type": "function", "function": {"name": "tool"}}],
                    None,
                )
        self.assertEqual("Ich prüfe das.", "".join(previews))
        self.assertEqual([True], resets)
        self.assertEqual([], committed)
        self.assertEqual("tool", result["tool_calls"][0]["name"])

    def test_unified_answer_stream_publishes_only_text_and_returns_presentation(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        llm.telemetry = TurnTelemetry()
        llm.telemetry.start(conversation_id="unified", input_kind="text")
        command = {
            "action": "create",
            "presentation": {
                "title": "Bild", "layout": "vertical",
                "components": [{"type": "image", "content": "resource:0"}],
            },
        }
        chunks = [
            "Hier ist ", "das Bild.", UNIFIED_PRESENTATION_MARKER[:8],
            UNIFIED_PRESENTATION_MARKER[8:], json.dumps(command),
            "\n</EVE_PRESENTATION>",
        ]
        events = [
            "data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n"
            for chunk in chunks
        ] + ["data: [DONE]\n"]
        visible = []
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=StreamingResponse(events),
        ) as opened:
            with llm.stream_answers(visible.append):
                result = llm.complete_unified(
                    [{"role": "user", "content": "Zeige das Bild"}],
                    {
                        "active_presentation": {"active": False, "revision": 0},
                        "available_resources": [{"reference": "resource:0", "type": "image"}],
                        "completed_capability": "home",
                    },
                )

        self.assertEqual("Hier ist das Bild.", result.answer)
        self.assertEqual(command, result.presentation)
        self.assertIsNone(result.presentation_error)
        self.assertEqual(result.answer, "".join(visible))
        self.assertNotIn("EVE_PRESENTATION", "".join(visible))
        self.assertEqual(1, opened.call_count)
        payload = json.loads(opened.call_args.args[0].data)
        self.assertTrue(payload["stream"])
        self.assertIn('\\"reference\\":\\"resource:0\\"', json.dumps(payload["messages"]))
        self.assertEqual("system", payload["messages"][0]["role"])
        self.assertNotIn("system", [item["role"] for item in payload["messages"][1:]])
        llm.telemetry.finish()
        roles = [
            item["role"]
            for item in llm.telemetry.snapshot("unified")["turns"][0]["llm_calls"]
        ]
        self.assertEqual(["unified_answer"], roles)

    def test_unified_answer_preserves_visible_text_byte_for_byte_before_marker(self):
        cases = {
            "plain": "Einfacher Text.",
            "one_trailing_newline": "Text mit Zeilenumbruch.\n",
            "multiple_trailing_newlines": "Text mit Zeilenumbrüchen.\n\n\n",
            "trailing_spaces": "Text mit Leerzeichen.   ",
            "leading_whitespace": "  \nText mit führendem Whitespace.",
            "markdown_code_block": "```python\nprint('EVE')\n```\n",
            "unicode": "Grüße 👋 – déjà vu · 你好\n",
        }
        command = {"action": "none"}
        for name, expected in cases.items():
            with self.subTest(name=name):
                llm = OpenAICompatibleLLM({
                    "base_url": "http://127.0.0.1:1/v1", "model": "test",
                })
                wire = expected + UNIFIED_PRESENTATION_MARKER + json.dumps(command)
                split_points = (1, 3, 7, len(expected) + 2, len(expected) + 9)
                chunks = []
                start = 0
                for end in split_points:
                    if start < min(end, len(wire)):
                        chunks.append(wire[start:min(end, len(wire))])
                    start = min(end, len(wire))
                if start < len(wire):
                    chunks.append(wire[start:])
                events = [
                    "data: " + json.dumps({
                        "choices": [{"delta": {"content": chunk}}],
                    }) + "\n"
                    for chunk in chunks
                ] + ["data: [DONE]\n"]
                visible = []
                with unittest.mock.patch(
                    "urllib.request.urlopen", return_value=StreamingResponse(events),
                ):
                    with llm.stream_answers(visible.append):
                        result = llm.complete_unified(
                            [{"role": "user", "content": "Antwort"}],
                            {"active_presentation": {}, "available_resources": []},
                        )
                self.assertEqual(expected, result.answer)
                self.assertEqual(expected, "".join(visible))
                self.assertEqual(command, result.presentation)

    def test_unified_answer_stream_without_trailer_preserves_exact_text(self):
        expected = "  Sichtbarer Text.  \n\n"
        events = [
            "data: " + json.dumps({
                "choices": [{"delta": {"content": expected[:5]}}],
            }) + "\n",
            "data: " + json.dumps({
                "choices": [{"delta": {"content": expected[5:]}}],
            }) + "\n",
            "data: [DONE]\n",
        ]
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1/v1", "model": "test",
        })
        visible = []
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=StreamingResponse(events),
        ):
            with llm.stream_answers(visible.append):
                result = llm.complete_unified(
                    [{"role": "user", "content": "Antwort"}],
                    {"active_presentation": {}, "available_resources": []},
                )
        self.assertEqual(expected, result.answer)
        self.assertEqual(expected, "".join(visible))
        self.assertIsNone(result.presentation)
        self.assertEqual("missing_presentation_marker", result.presentation_error)

    def test_unified_answer_keeps_text_when_structured_trailer_is_incomplete(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "Text bleibt sichtbar."}}]}) + "\n",
            "data: " + json.dumps({"choices": [{"delta": {"content": UNIFIED_PRESENTATION_MARKER}}]}) + "\n",
            "data: " + json.dumps({"choices": [{"delta": {"content": '{"action":"create"'}}]}) + "\n",
            "data: [DONE]\n",
        ]
        visible = []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with llm.stream_answers(visible.append):
                result = llm.complete_unified(
                    [{"role": "user", "content": "Antwort"}],
                    {"active_presentation": {}, "available_resources": []},
                )

        self.assertEqual("Text bleibt sichtbar.", result.answer)
        self.assertEqual(result.answer, "".join(visible))
        self.assertIsNone(result.presentation)
        self.assertEqual("invalid_presentation_json", result.presentation_error)

    def test_unified_answer_without_trailer_preserves_full_answer_without_retry(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"Nur Text"}}],"usage":{}}'
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            result = llm.complete_unified(
                [{"role": "user", "content": "Antwort"}],
                {"active_presentation": {}, "available_resources": []},
            )
        self.assertEqual("Nur Text", result.answer)
        self.assertIsNone(result.presentation)
        self.assertEqual("missing_presentation_marker", result.presentation_error)
        self.assertEqual(1, opened.call_count)

    def test_unified_answer_cancellation_after_text_never_returns_partial_presentation(self):
        class CancelBeforeTrailer:
            def __init__(self): self.checkpoints = 0
            def checkpoint(self):
                self.checkpoints += 1
                if self.checkpoints >= 2:
                    raise RuntimeError("cancelled")

        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        events = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "Sichtbarer Text."}}]}) + "\n",
            "data: " + json.dumps({"choices": [{"delta": {"content": UNIFIED_PRESENTATION_MARKER}}]}) + "\n",
            "data: " + json.dumps({"choices": [{"delta": {"content": '{"action":"none"}'}}]}) + "\n",
            "data: [DONE]\n",
        ]
        visible = []
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with llm.cancellable(CancelBeforeTrailer()), llm.stream_answers(visible.append):
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    llm.complete_unified(
                        [{"role": "user", "content": "Antwort"}],
                        {"active_presentation": {}, "available_resources": []},
                    )
        self.assertEqual("Sichtbarer Text.", "".join(visible))

    def test_meta_and_empty_chunks_do_not_finish_visible_ttft(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        received = []
        events = [
            'data: {"choices":[{"delta":{}}]}\n',
            '\n',
            'data: {"choices":[{"delta":{"content":""}}]}\n',
            'data: {"choices":[{"delta":{"content":"Antwort"}}]}\n',
            'data: [DONE]\n',
        ]
        with unittest.mock.patch("urllib.request.urlopen", return_value=StreamingResponse(events)):
            with llm.stream_answers(received.append):
                self.assertEqual("Antwort", llm.complete([]))
        self.assertEqual(["Antwort"], received)

    def test_structured_request_stays_non_streaming_inside_stream_context(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}],"usage":{}}'
        )
        captured = []
        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            with llm.stream_answers(captured.append):
                answer = llm._request([], 20, 0, role="turn_planner")
        request_payload = json.loads(opened.call_args.args[0].data)
        self.assertFalse(request_payload["stream"])
        self.assertEqual('{"ok":true}', answer)
        self.assertEqual([], captured)

    def test_non_streaming_fallback_rate_records_whole_request_basis(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        telemetry = TurnTelemetry()
        llm.telemetry = telemetry
        telemetry.start(conversation_id="rate", input_kind="text")
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"Antwort"}}],'
            b'"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}'
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            self.assertEqual("Antwort", llm._request([], 20, 0, role="minimal_semantic"))
        telemetry.finish()
        call = telemetry.snapshot("rate")["turns"][0]["llm_calls"][0]
        self.assertEqual("whole_request_fallback", call["tokens_per_second_basis"])
        self.assertIsNotNone(call["tokens_per_second"])

    def test_provider_rate_is_marked_as_provider_reported(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        telemetry = TurnTelemetry()
        llm.telemetry = telemetry
        telemetry.start(conversation_id="provider-rate", input_kind="text")
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"Antwort"}}],'
            b'"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12},'
            b'"stats":{"tokens_per_second":19.5}}'
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            self.assertEqual("Antwort", llm._request([], 20, 0, role="minimal_semantic"))
        telemetry.finish()
        call = telemetry.snapshot("provider-rate")["turns"][0]["llm_calls"][0]
        self.assertEqual("server_reported", call["tokens_per_second_basis"])
        self.assertEqual(19.5, call["tokens_per_second"])

    def test_buffered_request_reports_output_limit_with_partial_response(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps({
            "choices": [{
                "message": {"content": '{"decision":"execute","parameters":'},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }).encode())
        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(LocalLLMOutputLimitError) as caught:
                llm._request([], 20, 0, role="minimal_semantic")
        self.assertEqual("length", caught.exception.finish_reason)
        self.assertEqual(
            '{"decision":"execute","parameters":',
            caught.exception.partial_response,
        )

    def test_native_tool_turn_returns_provider_function_call(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [{
                        "id": "call-1", "type": "function",
                        "function": {"name": "clock__now", "arguments": "{}"},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        }).encode())
        tools = [{
            "type": "function",
            "function": {
                "name": "clock__now", "description": "Current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            result = llm.request_tool_turn([], tools, 128)

        self.assertEqual("clock__now", result["tool_calls"][0]["name"])
        self.assertEqual({}, result["tool_calls"][0]["arguments"])
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(tools, payload["tools"])
        self.assertEqual("auto", payload["tool_choice"])
        self.assertNotIn("parallel_tool_calls", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("chat_template_kwargs", payload)

    def test_native_tool_turn_preserves_multiple_provider_calls(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [
                        {"id": "call-1", "type": "function",
                         "function": {"name": "clock__now", "arguments": "{}"}},
                        {"id": "call-2", "type": "function",
                         "function": {"name": "calculator__evaluate",
                                      "arguments": '{"expression":"2+2"}'}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }).encode())
        tools = [{
            "type": "function",
            "function": {
                "name": "clock__now", "description": "Current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            result = llm.request_tool_turn([], tools, 128)

        self.assertEqual(["call-1", "call-2"], [call["id"] for call in result["tool_calls"]])
        self.assertEqual(
            ["clock__now", "calculator__evaluate"],
            [call["name"] for call in result["tool_calls"]],
        )

    def test_lm_studio_runtime_model_info_uses_loaded_instance_context(self):
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1234/v1", "model": "qwen-test",
        })
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps({
            "models": [{
                "key": "qwen-test", "max_context_length": 262144,
                "capabilities": {"vision": True, "trained_for_tool_use": True},
                "loaded_instances": [{
                    "id": "qwen-test",
                    "config": {"context_length": 65536, "parallel": 4},
                }],
            }],
        }).encode())

        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            info = llm.runtime_model_info(refresh=True)

        self.assertEqual(65536, info["context_length"])
        self.assertEqual(262144, info["max_context_length"])
        self.assertTrue(info["trained_for_tool_use"])
        self.assertEqual(
            "http://127.0.0.1:1234/api/v1/models",
            opened.call_args.args[0].full_url,
        )

    def test_strata_runtime_model_info_uses_published_image_modality(self):
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:8813/v1",
            "model": "qwen3.8-flash-next-iq2_xs",
        })
        native_catalogue = io.BytesIO(b'{"models":[]}')
        openai_catalogue = io.BytesIO(json.dumps({
            "object": "list",
            "data": [{
                "id": "qwen3.8-flash-next-iq2_xs",
                "meta": {"n_ctx": 32768},
                "architecture": {
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text"],
                },
            }],
        }).encode())
        health = io.BytesIO(json.dumps({
            "service": "strata", "model": "qwen3.8-flash-next-iq2_xs",
            "images": True,
        }).encode())

        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=[native_catalogue, openai_catalogue, health,
                         io.BytesIO(b'{"default_generation_settings":{"params":{"n_predict":-1}}}'),
                         io.BytesIO(b'{"defaults":{}}')],
        ) as opened:
            info = llm.runtime_model_info(refresh=True)

        self.assertEqual("strata", info["provider"])
        self.assertEqual(32768, info["context_length"])
        self.assertTrue(info["vision"])
        self.assertEqual([
            "http://127.0.0.1:8813/api/v1/models",
            "http://127.0.0.1:8813/v1/models",
            "http://127.0.0.1:8813/health",
            "http://127.0.0.1:8813/props",
            "http://127.0.0.1:8813/settings",
        ], [call.args[0].full_url for call in opened.call_args_list])

    def test_server_managed_generation_omits_eve_output_cap(self):
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1/v1", "model": "test",
            "max_tokens": 17, "use_server_limits": True,
        })
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"Antwort"}}],"usage":{}}'
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            self.assertEqual("Antwort", llm.complete([]))

        payload = json.loads(opened.call_args.args[0].data)
        self.assertNotIn("max_tokens", payload)

    def test_server_managed_limit_also_applies_to_auxiliary_model_calls(self):
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1/v1", "model": "test",
            "max_tokens": 17, "use_server_limits": True,
        })
        with unittest.mock.patch.object(
            llm, "_request", return_value='{"title":"Titel","reminder_text":"Erinnerung"}',
        ) as requested:
            llm.normalize_scheduled_task("Inhalt")
        self.assertIsNone(requested.call_args.args[1])

        with unittest.mock.patch.object(
            llm, "_request_stream", return_value=(
                '{"decision_type":"no_persist","memory_worthy":false}'
            ),
        ) as streamed:
            llm.analyze_shadow_learning({})
        self.assertIsNone(streamed.call_args.args[1])

    def test_manual_generation_limit_remains_available_as_fallback(self):
        llm = OpenAICompatibleLLM({
            "base_url": "http://127.0.0.1:1/v1", "model": "test",
            "max_tokens": 17, "use_server_limits": False,
        })
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(
            b'{"choices":[{"message":{"content":"Antwort"}}],"usage":{}}'
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response) as opened:
            self.assertEqual("Antwort", llm.complete([]))

        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(17, payload["max_tokens"])













    def test_http_error_body_is_bounded_and_available_for_diagnostics(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        body = b'{"error":{"message":"context length exceeded"}}'
        error = urllib.error.HTTPError(
            "http://127.0.0.1:1/v1/chat/completions", 400, "Bad Request", {}, io.BytesIO(body)
        )
        with unittest.mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LocalLLMError) as caught:
                llm.complete([{"role": "user", "content": "test"}])
        message = str(caught.exception)
        self.assertIn("HTTP 400", message)
        self.assertNotIn("context length exceeded", message)
        self.assertIn("context length exceeded", str(caught.exception.__cause__))

    def test_oversize_http_error_is_explicitly_marked_and_secrets_are_redacted(self):
        llm = OpenAICompatibleLLM({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        body = b"token=top-secret " + (b"x" * (1024 * 1024 + 32))
        error = urllib.error.HTTPError(
            "http://127.0.0.1:1/v1/chat/completions", 500, "Failure", {}, io.BytesIO(body)
        )
        with unittest.mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LocalLLMError) as caught:
                llm.complete([{"role": "user", "content": "test"}])
        diagnostic = str(caught.exception.__cause__)
        self.assertIn("TRUNCATED", diagnostic)
        self.assertIn("1048576-byte diagnostic safety limit", diagnostic)
        self.assertIn("token=[REDACTED]", diagnostic)
        self.assertNotIn("top-secret", diagnostic)








    def test_swapped_perspective_is_rejected(self):
        original = "Ich kann dein Licht steuern."
        self.assertFalse(OpenAICompatibleLLM._perspective_preserved(original, "Du kannst mein Licht steuern."))

    def test_same_perspective_is_accepted(self):
        original = "Ich kann dir dabei helfen."
        self.assertTrue(OpenAICompatibleLLM._perspective_preserved(original, "Ich helfe dir dabei."))

    def test_units_are_not_reinterpreted_by_python(self):
        written = "603,28 m³ und 0,13 m³/h bei 42%"
        self.assertEqual(written, OpenAICompatibleLLM.sanitize_for_speech(written))

    def test_numbers_and_clock_times_are_not_language_normalized_by_python(self):
        spoken = OpenAICompatibleLLM.sanitize_for_speech(
            "Es sind 122 Geräte. Der Termin ist um 11:12 Uhr, die Position beträgt 25 %."
        )
        self.assertEqual(
            "Es sind 122 Geräte. Der Termin ist um 11:12 Uhr, die Position beträgt 25 %.",
            spoken,
        )

    def test_product_name_is_not_rewritten_by_python(self):
        written = "Ich bin EVE und helfe dir."
        self.assertEqual(written, OpenAICompatibleLLM.sanitize_for_speech(written))
        self.assertEqual("Ich bin EVE und helfe dir.", written)














    def test_deterministic_speech_cleanup_preserves_perspective_numbers_and_negation(self):
        original = "Ich habe dein Rollo **nicht** auf 25 % gesetzt. [Quelle](https://example.test) [1]"
        spoken = OpenAICompatibleLLM.sanitize_for_speech(original)
        self.assertEqual("Ich habe dein Rollo nicht auf 25 % gesetzt. Quelle", spoken)
        self.assertIn("Ich", spoken)
        self.assertIn("dein", spoken)
        self.assertIn("nicht", spoken)
        self.assertIn("25", spoken)


if __name__ == "__main__": unittest.main()
