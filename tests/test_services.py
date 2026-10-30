import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from copy import deepcopy
from types import SimpleNamespace
from urllib.error import URLError

from eve_agent.config import DEFAULTS
from eve_agent.services import ServiceManager, runtime_status


class ServiceManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = ServiceManager(self.root, self.root / "eve.json")
        self.cfg = deepcopy(DEFAULTS)
        self.cfg["web"]["enabled"] = True
        self.cfg["llm"].update(base_url="http://127.0.0.1:8813/v1", model="model")
        self.cfg["paths"]["database"] = str(self.root / "missing.db")

    def test_service_health_checks_real_results_instead_of_container_running_flag(self):
        with mock.patch.object(self.manager, "_container", return_value={"running": True}), mock.patch(
            "eve_agent.services.request_json", side_effect=URLError("connection refused")):
            row = self.manager._http_service(self.cfg, "search")
        self.assertEqual("error", row["status"])
        self.assertIn("restart", row["actions"])
        with mock.patch.object(self.manager, "_container", return_value=None), mock.patch(
            "eve_agent.services.request_json", side_effect=[{"engines": []}, {"results": []}]):
            row = self.manager._http_service(self.cfg, "search")
        self.assertEqual("warning", row["status"])
        self.assertEqual([], row["actions"])

    def test_wrong_model_and_failed_engines_do_not_show_green(self):
        with mock.patch.object(self.manager, "_container", return_value=None), mock.patch(
            "eve_agent.services.request_json", return_value={"data": [{"id": "different-model"}]}):
            self.assertEqual("warning", self.manager._http_service(self.cfg, "llm")["status"])
        with mock.patch.object(self.manager, "_container", return_value=None), mock.patch(
            "eve_agent.services.request_json", side_effect=[{"engines": []}, {"results": [{"url": "https://example.org"}], "unresponsive_engines": [["engine", "timeout"]]}]):
            self.assertEqual("warning", self.manager._http_service(self.cfg, "search")["status"])

    def test_monitor_does_not_query_external_search_engines_on_every_poll(self):
        with mock.patch.object(self.manager, "_container", return_value=None), mock.patch(
            "eve_agent.services.request_json", side_effect=[{"engines": []}, {"results": [{"url": "https://example.org"}]}, {"engines": []}]) as request:
            first = self.manager._http_service(self.cfg, "search")
            second = self.manager._http_service(self.cfg, "search")
        self.assertEqual("healthy", first["status"])
        self.assertEqual("healthy", second["status"])
        self.assertEqual(1, sum("/search?" in call.args[0] for call in request.call_args_list))

    def test_container_control_requires_local_endpoint_and_matching_published_port(self):
        container = {"HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9999"}]}}, "State": {"Running": True}}
        process = SimpleNamespace(returncode=0, stdout=json.dumps([container]))
        with mock.patch("eve_agent.services.shutil.which", return_value="/bin/podman"), mock.patch(
            "eve_agent.services.subprocess.run", return_value=process) as run:
            self.assertIsNone(self.manager._container(self.cfg, "search"))
            container["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostPort"] = "8888"
            process.stdout = json.dumps([container])
            self.assertEqual("eve-search-", self.manager._container(self.cfg, "search")["name"][:11])
            run.reset_mock()
            self.cfg["web"]["searxng_url"] = "http://remote.example.org:8888"
            self.assertIsNone(self.manager._container(self.cfg, "search"))
            run.assert_not_called()

    def test_action_validation_and_serialization(self):
        for payload in ({"service": "eve; touch /tmp/evil", "action": "start"},
                        {"service": "eve", "action": "shell"},
                        {"service": "eve", "action": "start", "command": "x"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.manager.action(payload)
        with mock.patch("eve_agent.services.threading.Thread") as thread:
            status, _ = self.manager.action({"service": "search", "action": "restart"})
            self.assertEqual(202, status)
            self.assertEqual(409, self.manager.action({"service": "eve", "action": "stop"})[0])
            self.assertEqual(1, thread.call_count)

    def test_host_network_container_requires_matching_explicit_port(self):
        container = {"HostConfig": {"NetworkMode": "host"}, "State": {"Running": True},
                     "Config": {"Env": ["PORT=8813", "HOST=0.0.0.0"]}}
        process = SimpleNamespace(returncode=0, stdout=json.dumps([container]))
        with mock.patch("eve_agent.services.shutil.which", return_value="/bin/podman"), mock.patch(
            "eve_agent.services.subprocess.run", return_value=process):
            self.assertEqual("eve-strata", self.manager._container(self.cfg, "llm")["name"])
            self.cfg["llm"]["base_url"] = "http://127.0.0.1:8814/v1"
            self.assertIsNone(self.manager._container(self.cfg, "llm"))

    def test_external_container_cannot_be_started_and_failure_is_recorded(self):
        self.manager._operation = {"service": "search", "action": "start", "status": "running"}
        with mock.patch("eve_agent.services.load_config", return_value=(self.root, self.cfg)), mock.patch.object(
            self.manager, "_container", return_value=None), mock.patch.object(self.manager, "_command") as command, mock.patch.object(self.manager, "refresh"):
            self.manager._perform("search", "start")
        command.assert_not_called()
        self.assertEqual("failed", self.manager.snapshot()["operation"]["status"])
        receipt = json.loads((self.manager.runtime / "actions.jsonl").read_text())
        self.assertEqual("failed", receipt["status"])

    def test_restart_uses_fixed_argv_and_does_not_stop_unrelated_services(self):
        self.manager._operation = {"service": "search", "action": "restart", "status": "running"}
        with mock.patch("eve_agent.services.load_config", return_value=(self.root, self.cfg)), mock.patch.object(
            self.manager, "_container", return_value={"engine": "/bin/podman", "name": "eve-searxng"}), mock.patch.object(
            self.manager, "_command") as command, mock.patch.object(self.manager, "refresh"):
            self.manager._perform("search", "restart")
        command.assert_called_once_with(["/bin/podman", "restart", "--time", "5", "eve-searxng"])
        self.assertEqual("completed", self.manager.snapshot()["operation"]["status"])

    def test_runtime_tool_registration_and_last_bad_call_are_distinct_from_backend_health(self):
        with mock.patch("eve_agent.services.request_json", return_value={"web_registered": True,
            "last_web_call": {"invalid_function": True, "operation": "web", "at": "2026-10-30T08:42:00Z"},
            "chatto": {"state": "ready"}}):
            web, chatto = self.manager._runtime_rows(self.cfg)
        self.assertEqual("warning", web["status"])
        self.assertIn("keine verweigerte Berechtigung", web["detail"])
        self.assertEqual("healthy", chatto["status"])
        status = runtime_status(SimpleNamespace(web=object()), SimpleNamespace(status=lambda: {"state": "ready"}), self.cfg)
        self.assertTrue(status["web_registered"])
        self.assertFalse((self.root / "missing.db").exists())

    def test_snapshot_reads_never_block_on_health_requests_and_are_copies(self):
        self.manager._snapshot = {"services": [{"id": "eve", "status": "healthy"}]}
        data = self.manager.snapshot()
        data["services"][0]["status"] = "error"
        self.assertEqual("healthy", self.manager.snapshot()["services"][0]["status"])


if __name__ == "__main__":
    unittest.main()
