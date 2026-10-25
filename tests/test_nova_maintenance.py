import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from eve_agent.nova_maintenance import (
    MaintenanceLevel,
    NovaMaintenance,
)


def _result(**overrides):
    payload = {
        "status": "completed",
        "root_cause_found": True,
        "error_description": "Die Ursache liegt in sample.py.",
        "changes": ["Fehlerbehandlung korrigiert"],
        "changed_files": ["von-nova-behauptet.txt"],
        "tests": {"status": "passed", "summary": "Alle fokussierten Tests bestanden."},
        "remaining_risks": [],
        "next_action": "Vorschlag prüfen.",
        "restart_or_deployment_required": True,
    }
    payload.update(overrides)
    return payload


class _Runner:
    def __init__(self, result=None, mutate=None, returncode=0):
        self.result = result or _result()
        self.mutate = mutate
        self.returncode = returncode
        self.calls = []
        self.auth_home_during_call = None
        self.auth_home_existed_during_call = False

    @staticmethod
    def workspace(argv):
        for index, item in enumerate(argv[:-2]):
            if item in {"--bind", "--ro-bind"} and argv[index + 2] == "/var/mnt":
                return Path(argv[index + 1])
        # Direct, explicitly non-isolated mode.
        if "-C" in argv:
            return Path(argv[argv.index("-C") + 1])
        raise AssertionError("workspace mount not found")

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append((argv, kwargs))
        for index, item in enumerate(argv[:-2]):
            if item == "--bind" and argv[index + 2] == "/var/opt":
                self.auth_home_during_call = Path(argv[index + 1])
                self.auth_home_existed_during_call = (self.auth_home_during_call / "auth.json").is_file()
        if self.mutate:
            self.mutate(self.workspace(argv))
        return subprocess.CompletedProcess(
            argv,
            self.returncode,
            stdout=json.dumps(self.result, ensure_ascii=False),
            stderr="runner stderr" if self.returncode else "",
        )


class _Diagnostics:
    def __init__(self):
        self.records = []

    def recent(self, limit=20):
        return [{"component": "voice", "message": "Authorization: Bearer super-secret-token-value"}][-limit:]

    def record(self, component, operation, status, message, **kwargs):
        self.records.append((component, operation, status, message, kwargs))


class _Verifier:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(
            argv,
            self.returncode,
            stdout="verification output",
            stderr="failed verification" if self.returncode else "",
        )


class NovaMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "eve"
        self.root.mkdir()
        (self.root / "src" / "eve_agent").mkdir(parents=True)
        (self.root / "src" / "eve_agent" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text("# test\n", encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "notes.md").write_text("notes\n", encoding="utf-8")
        (self.root / "web").mkdir()
        (self.root / "web" / "index.html").write_text("<p>EVE</p>\n", encoding="utf-8")
        (self.root / "README.md").write_text("EVE\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\nname='eve'\n", encoding="utf-8")
        (self.root / "eve.json").write_text('{"token":"must-not-leak"}\n', encoding="utf-8")
        (self.root / "secrets").mkdir()
        (self.root / "secrets" / "home-assistant.token").write_text("must-not-leak\n", encoding="utf-8")
        (self.root / "memory").mkdir()
        (self.root / "memory" / "facts.md").write_text("private memory\n", encoding="utf-8")
        (self.root / "certs").mkdir()
        (self.root / "certs" / "eve.key").write_text("private key\n", encoding="utf-8")

        self.fake_home = Path(self.temporary.name) / "home"
        (self.fake_home / ".codex").mkdir(parents=True)
        (self.fake_home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
        (self.fake_home / ".codex" / "installation_id").write_text("test-id", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def maintenance(self, runner, verifier=None, system_snapshot_provider=None, **config):
        defaults = {
            "enabled": True,
            "command": "codex",
            "bwrap_command": "/usr/bin/bwrap",
            "require_process_isolation": True,
            "api_token": "must-not-leak",
        }
        defaults.update(config)
        return NovaMaintenance(
            self.root,
            defaults,
            diagnostics=_Diagnostics(),
            runner=runner,
            verifier=verifier or _Verifier(),
            system_config={"home_assistant": {"token": "system-secret", "url": "http://ha.local"}},
            system_snapshot_provider=system_snapshot_provider,
        )

    def run_with_home(self, maintenance, text, images=None):
        level = "development" if "repariere" in text.casefold() else "diagnosis"
        with mock.patch("eve_agent.nova_maintenance.Path.home", return_value=self.fake_home):
            return maintenance.execute_operation(
                "run", {"instruction": text, "level": level},
                history=[{"role": "user", "content": "Fehler von eben"}], images=images or [],
            )



    def test_diagnosis_uses_read_only_codex_and_bubblewrap_boundary(self):
        runner = _Runner()
        maintenance = self.maintenance(runner)
        answer = self.run_with_home(maintenance, "Nova, diagnostiziere den Fehler von eben")

        self.assertIn("Diagnose abgeschlossen", answer)
        argv, kwargs = runner.calls[0]
        self.assertEqual("/usr/bin/bwrap", argv[0])
        for option in ("--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--cap-drop"):
            self.assertIn(option, argv)
        self.assertIn("ALL", argv)
        self.assertIn("--tmpfs", argv)
        self.assertIn(str(self.root.resolve()), argv)
        self.assertIn("/var/empty", argv)
        self.assertIn("/run", argv)
        self.assertIn("/tmp", argv)
        self.assertIn("--proc", argv)
        self.assertIn("--dev", argv)
        separator = argv.index("--")
        codex = argv[separator + 1 :]
        self.assertEqual("exec", codex[5])
        for required in (
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--output-schema",
            "-o",
        ):
            self.assertIn(required, codex)
        self.assertLess(codex.index("-a"), codex.index("exec"))
        self.assertLess(codex.index("-s"), codex.index("exec"))
        self.assertEqual("never", codex[codex.index("-a") + 1])
        self.assertEqual("read-only", codex[codex.index("-s") + 1])
        self.assertEqual("/var/mnt", codex[codex.index("-C") + 1])
        self.assertNotIn(str(self.root), codex)
        self.assertIs(False, kwargs["shell"])
        self.assertEqual(Path("/"), kwargs["cwd"])
        self.assertNotIn("must-not-leak", kwargs["input"])
        self.assertTrue(runner.auth_home_existed_during_call)
        self.assertFalse(runner.auth_home_during_call.exists())
        self.assertIn("/var/opt", argv)

    def test_snapshot_and_context_exclude_private_live_data(self):
        (self.root / "src" / "eve_agent" / "__pycache__").mkdir()
        (self.root / "src" / "eve_agent" / "__pycache__" / "sample.cpython-313.pyc").write_bytes(b"compiled")
        (self.root / "web" / "stale.pyc").write_bytes(b"compiled")
        runner = _Runner()
        maintenance = self.maintenance(runner)
        self.run_with_home(maintenance, "Nova, diagnostiziere den Fehler von eben")
        workspace = self.root / "runtime" / "nova" / maintenance.last_job_id / "workspace"

        self.assertTrue((workspace / "src" / "eve_agent" / "sample.py").is_file())
        self.assertTrue((workspace / "README.md").is_file())
        for forbidden in ("eve.json", "secrets", "memory", "runtime", "certs", "voices"):
            self.assertFalse((workspace / forbidden).exists(), forbidden)
        self.assertFalse((workspace / "src" / "eve_agent" / "__pycache__").exists())
        self.assertFalse((workspace / "web" / "stale.pyc").exists())
        context = json.loads((workspace / ".nova" / "context.json").read_text(encoding="utf-8"))
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("system-secret", serialized)
        self.assertNotIn("super-secret-token-value", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertEqual("eve_agent", context["component"])

    def test_context_contains_fresh_redacted_read_only_system_snapshot(self):
        calls = []

        def snapshot_provider():
            calls.append(True)
            return {
                "connected": True,
                "entities": [{
                    "entity_id": "lock.haustuer",
                    "state": "locked",
                    "attributes": {"friendly_name": "Haustür", "supported_features": 1},
                }],
                "services": [{"domain": "lock", "service": "open", "fields": ["code"]}],
                "api_token": "must-not-leak",
            }

        runner = _Runner()
        maintenance = self.maintenance(runner, system_snapshot_provider=snapshot_provider)
        self.run_with_home(maintenance, "Nova, prüfe die Home-Assistant-Anbindung")
        workspace = self.root / "runtime" / "nova" / maintenance.last_job_id / "workspace"
        context = json.loads((workspace / ".nova" / "context.json").read_text(encoding="utf-8"))

        self.assertEqual([True], calls)
        self.assertTrue(context["live_system"]["available"])
        home = context["live_system"]["home_assistant"]
        self.assertEqual(1, home["entities"][0]["attributes"]["supported_features"])
        self.assertEqual("open", home["services"][0]["service"])
        self.assertEqual("[REDACTED]", home["api_token"])
        self.assertNotIn("must-not-leak", json.dumps(context, ensure_ascii=False))

    def test_development_changes_only_staging_and_uses_actual_diff(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")

        runner = _Runner(mutate=mutate)
        verifier = _Verifier()
        maintenance = self.maintenance(runner, verifier=verifier)
        answer = self.run_with_home(maintenance, "Nova, repariere sample.py, aber starte nichts neu")

        self.assertEqual("VALUE = 1\n", (self.root / "src" / "eve_agent" / "sample.py").read_text(encoding="utf-8"))
        self.assertTrue(maintenance.has_pending())
        self.assertEqual(["src/eve_agent/sample.py"], maintenance.last_result["changed_files"])
        self.assertNotIn("von-nova-behauptet.txt", maintenance.last_result["changed_files"])
        self.assertNotIn(maintenance.last_job_id, answer)
        self.assertIn("noch nichts geändert", answer)
        _, kwargs = runner.calls[0]
        self.assertIn("workspace-write", runner.calls[0][0])
        self.assertIs(False, kwargs["shell"])
        self.assertEqual(1, len(verifier.calls))
        verification_argv, verification_kwargs = verifier.calls[0]
        self.assertIn("--unshare-net", verification_argv)
        self.assertIn("--unshare-pid", verification_argv)
        self.assertIn(str(self.root.resolve()), verification_argv)
        self.assertIn("/var/mnt", verification_argv)
        self.assertNotIn("auth.json", " ".join(verification_argv))
        self.assertIs(False, verification_kwargs["shell"])

    def test_generated_python_cache_does_not_abort_or_enter_activation_diff(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
            cache = workspace / "src" / "eve_agent" / "__pycache__"
            cache.mkdir()
            (cache / "__init__.cpython-314.pyc").write_bytes(b"generated bytecode")

        runner = _Runner(mutate=mutate)
        maintenance = self.maintenance(runner)
        answer = self.run_with_home(maintenance, "Nova, repariere sample.py")

        self.assertIn("getesteten Vorschlag", answer)
        self.assertTrue(maintenance.has_pending())
        self.assertEqual(["src/eve_agent/sample.py"], maintenance.last_result["changed_files"])
        self.assertNotIn("__pycache__", str(maintenance.last_result["changed_files"]))
        argv, _kwargs = runner.calls[0]
        self.assertIn("PYTHONDONTWRITEBYTECODE", argv)

    def test_explicit_confirmation_applies_atomically_but_never_restarts(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")

        maintenance = self.maintenance(_Runner(mutate=mutate))
        self.run_with_home(maintenance, "Nova, repariere sample.py")
        description = maintenance.pending_description()
        self.assertNotIn(maintenance.last_job_id, description)
        self.assertNotIn("Prüfsumme", description)
        self.assertIn("‚Ja‘", description)

        wrong = maintenance.confirm_pending("nova-19990101T000000Z-deadbeef")
        self.assertIn("nichts aktiviert", wrong)
        self.assertTrue(maintenance.has_pending())
        self.assertEqual("VALUE = 1\n", (self.root / "src" / "eve_agent" / "sample.py").read_text(encoding="utf-8"))

        answer = maintenance.confirm_pending(maintenance._pending.job_id)

        self.assertEqual("VALUE = 2\n", (self.root / "src" / "eve_agent" / "sample.py").read_text(encoding="utf-8"))
        self.assertFalse(maintenance.has_pending())
        self.assertIn("wurde aktiviert", answer)
        self.assertNotIn(maintenance.last_job_id, answer)
        self.assertIn("nicht neu gestartet", answer)
        backup = self.root / "runtime" / "nova" / maintenance.last_job_id / "backups" / "src" / "eve_agent" / "sample.py"
        self.assertEqual("VALUE = 1\n", backup.read_text(encoding="utf-8"))

    def test_staging_tamper_or_live_drift_blocks_activation(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")

        maintenance = self.maintenance(_Runner(mutate=mutate))
        self.run_with_home(maintenance, "Nova, repariere sample.py")
        staged = self.root / "runtime" / "nova" / maintenance.last_job_id / "workspace" / "src" / "eve_agent" / "sample.py"
        staged.write_text("VALUE = 999\n", encoding="utf-8")
        answer = maintenance.confirm_pending(maintenance._pending.job_id)
        self.assertIn("nicht aktiviert", answer)
        self.assertEqual("VALUE = 1\n", (self.root / "src" / "eve_agent" / "sample.py").read_text(encoding="utf-8"))

        maintenance = self.maintenance(_Runner(mutate=mutate))
        self.run_with_home(maintenance, "Nova, repariere sample.py")
        (self.root / "src" / "eve_agent" / "sample.py").write_text("VALUE = 3\n", encoding="utf-8")
        answer = maintenance.confirm_pending(maintenance._pending.job_id)
        self.assertIn("nicht aktiviert", answer)
        self.assertEqual("VALUE = 3\n", (self.root / "src" / "eve_agent" / "sample.py").read_text(encoding="utf-8"))

    def test_symlinked_live_parent_blocks_activation_outside_project(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")

        maintenance = self.maintenance(_Runner(mutate=mutate))
        self.run_with_home(maintenance, "Nova, repariere sample.py")
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "sample.py").write_text("OUTSIDE = 1\n", encoding="utf-8")
        original = self.root / "src" / "eve_agent"
        original.rename(self.root / "src" / "eve_agent-original")
        original.symlink_to(outside, target_is_directory=True)

        answer = maintenance.confirm_pending(maintenance._pending.job_id)

        self.assertIn("nicht aktiviert", answer)
        self.assertEqual("OUTSIDE = 1\n", (outside / "sample.py").read_text(encoding="utf-8"))

    def test_failed_tests_and_deletions_never_create_pending_activation(self):
        def mutate(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")

        maintenance = self.maintenance(_Runner(mutate=mutate), verifier=_Verifier(returncode=1))
        answer = self.run_with_home(maintenance, "Nova, repariere sample.py")
        self.assertFalse(maintenance.has_pending())
        self.assertIn("keine Aktivierung", answer)

        def delete(workspace):
            (workspace / "src" / "eve_agent" / "sample.py").unlink()

        maintenance = self.maintenance(_Runner(mutate=delete))
        answer = self.run_with_home(maintenance, "Nova, repariere sample.py")
        self.assertFalse(maintenance.has_pending())
        self.assertIn("Löschungen", answer)

    def test_screenshot_data_url_is_bounded_staged_and_passed_with_i(self):
        # Only the signature is needed here; Nova does not decode image pixels.
        image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nminimal").decode("ascii")
        runner = _Runner()
        maintenance = self.maintenance(runner)
        self.run_with_home(maintenance, "Nova, prüfe den UI-Fehler", [image, "/etc/passwd"])
        argv = runner.calls[0][0]
        separator = argv.index("--")
        codex = argv[separator + 1 :]
        self.assertEqual(1, codex.count("-i"))
        image_path = codex[codex.index("-i") + 1]
        self.assertTrue(image_path.startswith("/var/mnt/.nova/images/"))
        self.assertNotIn("/etc/passwd", codex)

    def test_invalid_or_failed_structured_result_fails_closed(self):
        runner = _Runner(result={"status": "completed"})
        maintenance = self.maintenance(runner)
        answer = self.run_with_home(maintenance, "Nova, repariere sample.py")
        self.assertFalse(maintenance.has_pending())
        self.assertEqual("failed", maintenance.last_result["status"])
        self.assertIn("nichts geändert", answer)

        runner = _Runner(returncode=9)
        maintenance = self.maintenance(runner)
        answer = self.run_with_home(maintenance, "Nova, diagnostiziere dich")
        self.assertIn("Fehlercode 9", answer)
        self.assertFalse(maintenance.has_pending())

        def quota_runner(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 9, stdout="", stderr="You've hit your usage limit")

        maintenance = self.maintenance(quota_runner)
        answer = self.run_with_home(maintenance, "Nova, diagnostiziere dich")
        self.assertIn("Nutzungskontingent", answer)
        self.assertIn("nichts geändert", answer)
        self.assertFalse(maintenance.has_pending())

        wrong_types = _result(changes=[123], error_description=456)
        maintenance = self.maintenance(_Runner(result=wrong_types))
        answer = self.run_with_home(maintenance, "Nova, diagnostiziere dich")
        self.assertIn("ungültige Textfelder", answer)
        self.assertEqual("failed", maintenance.last_result["status"])

    def test_missing_required_isolation_fails_closed(self):
        runner = _Runner()
        maintenance = self.maintenance(runner, bwrap_command="missing-bwrap")
        # Injected runners intentionally accept a synthetic executable so the
        # argv can be tested. The real resolver must still fail closed.
        maintenance._injected_runner = False
        with mock.patch(
            "eve_agent.nova_maintenance.shutil.which",
            side_effect=lambda command, **kwargs: "/usr/bin/codex" if command == "codex" else None,
        ), mock.patch(
            "eve_agent.nova_maintenance.Path.home", return_value=self.fake_home
        ):
            answer = maintenance.execute_operation(
                "run", {"instruction": "Prüfe die Prozessisolation", "level": "diagnosis"},
                history=[], images=[],
            )
        self.assertIn("Prozessisolation", answer)
        self.assertEqual([], runner.calls)


    def test_shared_chat_executes_corrected_request_in_existing_isolation(self):
        runner = _Runner()
        maintenance = self.maintenance(runner, transport="shared_chat")
        observed = []

        class Chat:
            thread_id = "visible-chat"
            state = {"title": "EVE Auftrag"}
            def __init__(self, *args, **kwargs):
                pass
            def run(self, instruction, execute):
                report = execute("Stefans korrigierter Auftrag")
                job = next(maintenance.jobs_root.iterdir())
                context = json.loads((job / "workspace/.nova/context.json").read_text())
                observed.append(context["request"])
                return report

        with mock.patch("eve_agent.nova_maintenance.SharedChatJob", Chat):
            answer = self.run_with_home(maintenance, "Prüfe den Auftrag")
        self.assertEqual(observed, ["Stefans korrigierter Auftrag"])
        self.assertIn("visible-chat", answer)
        self.assertEqual(maintenance.last_chat_id, "visible-chat")
        self.assertIn("--unshare-pid", runner.calls[0][0])
        self.assertFalse(maintenance.has_pending())

    def test_failed_shared_chat_never_falls_back_to_invisible_worker(self):
        from eve_agent.codex_chat import ProtocolError
        runner = _Runner()
        maintenance = self.maintenance(runner, transport="shared_chat")
        with mock.patch("eve_agent.nova_maintenance.SharedChatJob") as chat:
            chat.return_value.thread_id = None
            chat.return_value.run.side_effect = ProtocolError("Socket unavailable")
            answer = self.run_with_home(maintenance, "Prüfe den Auftrag")
        self.assertEqual(runner.calls, [])
        self.assertIn("Socket unavailable", answer)
        self.assertFalse(maintenance.has_pending())


if __name__ == "__main__":
    unittest.main()
