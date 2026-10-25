"""Real MCP discovery and negative-result tests, never simulated UI success."""
from pathlib import Path
import unittest

from eve_agent.wayland_computer import WaylandComputerCapability
from eve_agent.minimal import NativeToolRuntime

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / '.venv-wayland-mcp/bin/python').exists(), 'isolated Wayland MCP not installed')
class WaylandMcpIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.provider = WaylandComputerCapability({}, ROOT)
        self.addCleanup(self.provider.close_all)

    def test_actual_tool_discovery_and_original_schemas_reach_model(self):
        contract = self.provider.native_contract()
        self.assertNotIn('error', contract)
        self.assertIn('execute_action', contract['operations'])
        runtime = NativeToolRuntime.__new__(NativeToolRuntime)
        tools, bindings = runtime._native_tools({'wayland_computer': contract})
        for tool in tools:
            binding = bindings[tool['function']['name']]
            native = self.provider.tools[binding['operation']]
            self.assertEqual(native['inputSchema'], tool['function']['parameters'])
            self.assertEqual(native['description'], tool['function']['description'])
        self.assertEqual(len(self.provider.tools), len(tools))

    def test_actual_environment_result_is_preserved(self):
        result = self.provider.execute_native_operation('describe_environment', {})
        self.assertEqual('completed', result['status'], result)
        self.assertTrue(result['result']['structuredContent']['success'])

    def test_real_native_error_is_not_labelled_completed(self):
        # No UI input: the actual server rejects the nonexistent operation.
        result = self.provider.execute_native_operation('execute_action', {'action': 'nonexistent-test-action'})
        self.assertEqual('failed', result['status'], result)
        self.assertFalse(result['result']['structuredContent']['success'])

    def test_invalid_schema_does_not_execute(self):
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):
            self.provider.execute_native_operation('move_mouse', {'x': 'invalid', 'y': 1})

    def test_engine_dispatch_executes_actual_wayland_operation(self):
        from types import SimpleNamespace
        from eve_agent.dialog import Route
        runtime = NativeToolRuntime.__new__(NativeToolRuntime)
        runtime.agent = SimpleNamespace(wayland_computer=self.provider, _presentation_resources=[])
        result, route = runtime._execute_direct('wayland_computer', 'describe_environment', {}, {}, [])
        self.assertEqual(Route.COMPUTER, route)
        self.assertEqual('completed', result['status'], result)
        self.assertTrue(result['result']['structuredContent']['success'])
