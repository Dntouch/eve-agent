import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eve_agent.backend_turns import TurnCancelled
from eve_agent.bot_activity import BotActivity, report_runtime_activity, tool_activity
from eve_agent.llm import OpenAICompatibleLLM
from eve_agent.minimal import NativeToolRuntime
from eve_agent.transport_access import transport_access


class BotActivityTest(unittest.TestCase):
    def test_actual_buffered_model_and_tool_boundaries_report_phases(self):
        tracker, phases, events = BotActivity(), [], []
        def activity(event):
            events.append(event)
            phases.append(tracker.update(event))
        llm = OpenAICompatibleLLM({'base_url': 'http://fixture.invalid/v1', 'model': 'fixture'})
        runtime = NativeToolRuntime(SimpleNamespace())
        response = {'choices': [{'message': {'content': 'Antwort'}, 'finish_reason': 'stop'}]}
        with transport_access({}, activity=activity):
            report_runtime_activity('model_start')
            result, _ = runtime._execute_direct('calculator', 'evaluate', {'expression': '1+2'}, {}, [])
            self.assertEqual(result['result'], 3)
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                self.assertEqual(llm.request_tool_turn([{'role': 'user', 'content': 'PRIVATE'}], [], None)['content'], 'Antwort')
        self.assertEqual(phases, ['THINKING', 'TOOL_USE', 'THINKING', 'THINKING', 'WRITING'])
        self.assertNotIn('PRIVATE', json.dumps(events))
        self.assertNotIn('calculator', json.dumps(events))
        self.assertEqual(tracker.tools, {})

    def test_stream_reasoning_is_thinking_and_content_starts_writing_once(self):
        for tools in (True, False):
            with self.subTest(tools=tools):
                llm = OpenAICompatibleLLM({'base_url': 'http://fixture.invalid/v1', 'model': 'fixture'})
                events = []
                def lines(events=events):
                    yield b'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE THOUGHTS"}}]}\n'
                    self.assertEqual([e['kind'] for e in events], ['model_start'])
                    yield b'data: {"choices":[{"delta":{"content":"Antwort"}}]}\n'
                    yield b'data: {"choices":[{"delta":{"content":"text"},"finish_reason":"stop"}]}\n'
                    yield b'data: [DONE]\n'
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.__iter__ = Mock(side_effect=lines)
                with transport_access({}, activity=events.append), llm.stream_answers(lambda _: None), patch('urllib.request.urlopen', return_value=response):
                    if tools:
                        llm.request_tool_turn([{'role': 'user', 'content': 'PRIVATE'}], [], None)
                    else:
                        llm._request([{'role': 'user', 'content': 'PRIVATE'}], None, 0, role='answer')
                self.assertEqual(events, [{'kind': 'model_start'}, {'kind': 'model_writing'}])

    def test_web_search_and_fetch_are_research_and_tool_errors_always_end(self):
        tracker, phases = BotActivity(), []
        web = Mock()
        runtime = NativeToolRuntime(SimpleNamespace(web=web, _presentation_resources=[]))
        for operation in ('search', 'fetch'):
            for error in (None, RuntimeError('PRIVATE'), TurnCancelled('cancelled')):
                with self.subTest(operation=operation, error=error):
                    phases.clear()
                    web.execute_native_operation.side_effect = error
                    web.execute_native_operation.return_value = {'sources': [], 'resources': []}
                    with transport_access({}, activity=lambda e: phases.append(tracker.update(e))):
                        if error:
                            with self.assertRaises(type(error)):
                                runtime._execute_direct('web', operation, {}, {}, [])
                        else:
                            runtime._execute_direct('web', operation, {}, {}, [])
                    self.assertEqual(phases, ['WEB_RESEARCH', 'THINKING'])
                    self.assertEqual(tracker.tools, {})

    def test_overlapping_web_tools_keep_precedence_until_the_last_web_tool_ends(self):
        tracker = BotActivity()
        self.assertEqual(tracker.update({'kind': 'tool_start', 'tool_id': 'ordinary'}), 'TOOL_USE')
        for identifier in ('web1', 'web2'):
            self.assertEqual(tracker.update({'kind': 'tool_start', 'tool_id': identifier, 'web': True}), 'WEB_RESEARCH')
        self.assertEqual(tracker.update({'kind': 'tool_end', 'tool_id': 'web1'}), 'WEB_RESEARCH')
        self.assertEqual(tracker.update({'kind': 'tool_end', 'tool_id': 'web1'}), 'WEB_RESEARCH')
        self.assertEqual(tracker.update({'kind': 'model_writing'}), 'WEB_RESEARCH')
        self.assertEqual(tracker.update({'kind': 'tool_end', 'tool_id': 'web2'}), 'TOOL_USE')
        self.assertEqual(tracker.update({'kind': 'tool_end', 'tool_id': 'ordinary'}), 'WRITING')

    def test_concurrent_tool_scopes_are_request_local_and_callbacks_are_best_effort(self):
        tracker, other = BotActivity(), BotActivity()
        barrier = threading.Barrier(4)
        def work():
            with tool_activity('web'):
                barrier.wait(timeout=2)
                self.assertEqual(tracker.update({}), 'WEB_RESEARCH')
                self.assertEqual(other.update({}), 'THINKING')
                barrier.wait(timeout=2)
        with transport_access({}, activity=tracker.update), ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(copy_context().run, work) for _ in range(3)]
            barrier.wait(timeout=2)
            barrier.wait(timeout=2)
            for future in futures:
                future.result(timeout=2)
        self.assertEqual(tracker.update({}), 'THINKING')
        with transport_access({}, activity=Mock(side_effect=RuntimeError('optional status failure'))):
            result, _ = NativeToolRuntime(SimpleNamespace())._execute_direct('calculator', 'evaluate', {'expression': '2*3'}, {}, [])
            self.assertEqual(result['result'], 6)


if __name__ == '__main__':
    unittest.main()
