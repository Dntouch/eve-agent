"""Protocol-contract checks for the shared-server connectivity probe."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import tempfile

spec = importlib.util.spec_from_file_location(
    "shared_probe", Path(__file__).resolve().parents[1] / "scripts/probe_codex_shared_chat.py")
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)

launcher_spec = importlib.util.spec_from_file_location(
    "shared_launcher", Path(__file__).resolve().parents[1] / "scripts/start_codex_shared_chat.py")
launcher = importlib.util.module_from_spec(launcher_spec)
launcher_spec.loader.exec_module(launcher)


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/list":
            return {"data": [{"id": "existing"}]}
        if method == "project/list":
            return {"data": [{"id": "eve-project", "roots": [{"path": "/tmp"}]}]}
        if method == "thread/start":
            return {"thread": {"id": "test-chat"}}
        return {}

    def send(self, message):
        self.calls.append((message["method"], {}))


class ProbeTests(unittest.TestCase):
    def test_desktop_and_proxy_share_the_same_socket(self):
        plan = launcher.launch_plan("/tmp/eve-chat-test")
        self.assertEqual(plan["desktop_env"]["CODEX_APP_SERVER_WS_URL"],
                         "ws+unix://localhost" + plan["socket"] + ":/rpc")
        self.assertEqual(plan["server"][-3:],
                         ["app-server", "--listen", "unix://" + plan["socket"]])
        self.assertNotIn("daemon", plan["server"])

    def test_existing_socket_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = launcher.launch_plan(directory)
            socket = Path(plan["socket"])
            socket.parent.mkdir()
            socket.touch()
            with patch.object(launcher.subprocess, "Popen") as popen:
                with self.assertRaises(RuntimeError):
                    launcher.start_server(plan)
                popen.assert_not_called()
            self.assertTrue(socket.exists())

    def test_failed_server_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Mock()
            child.poll.return_value = 1
            child.returncode = 1
            with patch.object(launcher.subprocess, "Popen", return_value=child):
                with patch.object(launcher, "stop_child") as stop:
                    with self.assertRaises(RuntimeError):
                        launcher.start_server(launcher.launch_plan(directory))
                    stop.assert_called_once_with(child)

    def test_ambiguous_socket_url_is_rejected(self):
        with self.assertRaises(ValueError):
            launcher.launch_plan("/tmp/eve:chat")

    def test_default_probe_only_reads_after_handshake(self):
        client = FakeClient()
        result = probe_module.probe(client, "/tmp")
        self.assertEqual([c[0] for c in client.calls],
                         ["initialize", "initialized", "thread/list"])
        self.assertTrue(client.calls[0][1]["capabilities"]["experimentalApi"])
        self.assertTrue(result["connected"])
        self.assertFalse(result["desktop_visibility_verified"])

    def test_explicit_creation_is_persistent_read_only_and_starts_no_turn(self):
        client = FakeClient()
        result = probe_module.probe(client, "/tmp", True)
        calls = dict(client.calls)
        self.assertFalse(calls["thread/start"]["ephemeral"])
        self.assertEqual(calls["thread/start"]["projectId"], "eve-project")
        self.assertEqual(calls["thread/start"]["sandbox"], "read-only")
        self.assertNotIn("turn/start", calls)
        self.assertEqual(calls["thread/name/set"]["threadId"], result["thread_id"])
        self.assertFalse(result["desktop_visibility_verified"])

    def test_missing_project_does_not_create_unassigned_chat(self):
        class WithoutProject(FakeClient):
            def request(self, method, params):
                if method == "project/list":
                    self.calls.append((method, params))
                    return {"data": []}
                return super().request(method, params)
        client = WithoutProject()
        with self.assertRaises(probe_module.ProtocolError):
            probe_module.probe(client, "/tmp", True)
        self.assertNotIn("thread/start", dict(client.calls))

    def test_connection_error_does_not_trigger_creation_or_fallback(self):
        class Unavailable(FakeClient):
            def request(self, method, params):
                raise probe_module.ProtocolError("unavailable")
        client = Unavailable()
        with self.assertRaises(probe_module.ProtocolError):
            probe_module.probe(client, "/tmp", True)
        self.assertEqual(client.calls, [])
