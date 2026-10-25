try:
    import fcntl
except ImportError:
    fcntl = None
import shutil
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from contextlib import contextmanager
from dataclasses import replace
from unittest import mock

from eve_agent import cli
from eve_agent.agent import TurnResult
from eve_agent.config import load_config as real_load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeBus:
    def __init__(self):
        self.events = []

    def set(self, state, detail=""):
        self.events.append((state, detail))

    def read(self):
        state, detail = self.events[-1] if self.events else ("idle", "")
        return {"state": state, "detail": detail}


class FakeLLM:
    def __init__(self):
        self.sanitized = []
        self.rewrites = 0
        self.model = "qwen3.5-35b-a3b"
        self.available_models = [self.model]
        self.model_checks = 0

    def sanitize_for_speech(self, text):
        self.sanitized.append(text)
        return "SICHER: " + text

    def prepare_for_speech(self, text):
        self.rewrites += 1
        return "UMGESCHRIEBEN: " + text

    def models(self):
        self.model_checks += 1
        return list(self.available_models)


class FakeMemory:
    @staticmethod
    def device_aliases():
        return {}


class FakeAgent:
    last_sources = []

    def respond(self, utterance, images=None):
        return "Ich habe das Gerät zu 75 Prozent geöffnet."

    def respond_turn(self, utterance, images=None, conversation_id=None):
        return TurnResult(
            turn_id=self.telemetry.active_id(), answer="Ich habe das Gerät zu 75 Prozent geöffnet.",
            route="chat", sources=(), resources=(), conversation_id=conversation_id,
            presentation=None,
        )


class FailingFakeAgent(FakeAgent):
    def __init__(self):
        self.diagnostics = []

    def respond_turn(self, utterance, images=None, conversation_id=None):
        raise RuntimeError("provider planning failed")

    def _diagnostic(self, *args, **kwargs):
        self.diagnostics.append((args, kwargs))


class ParallelFakeAgent(FakeAgent):
    def __init__(self, barrier):
        self.barrier = barrier

    def respond_turn(self, utterance, images=None, conversation_id=None):
        result = super().respond_turn(utterance, images, conversation_id)
        return TurnResult(
            turn_id=result.turn_id, answer=result.answer, route=result.route,
            sources=result.sources, resources=result.resources,
            conversation_id=result.conversation_id, presentation=object(),
        )

    def run_presentation(self, _work):
        self.barrier.wait(timeout=1)
        time.sleep(.05)
        return {"turn_id": self.telemetry.active_id(), "status": "success", "action": "none"}

    def _diagnostic(self, *_args, **_kwargs):
        pass


class FakeReminders:
    @staticmethod
    def pop_due(limit=None):
        return []


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text):
        self.spoken.append(text)
        return b"RIFF-test"


class ParallelFakeSpeaker(FakeSpeaker):
    def __init__(self, barrier):
        super().__init__()
        self.barrier = barrier

    def synthesize(self, text):
        self.barrier.wait(timeout=1)
        time.sleep(.05)
        return super().synthesize(text)


class OutcomeFakeAgent(ParallelFakeAgent):
    def __init__(self, fail=False):
        self.fail = fail

    def run_presentation(self, _work):
        if self.fail:
            raise ValueError("presentation failed")
        return {"turn_id": self.telemetry.active_id(), "status": "success", "action": "none"}


class OutcomeFakeSpeaker(FakeSpeaker):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    def synthesize(self, text):
        if self.fail:
            raise RuntimeError("tts failed")
        return super().synthesize(text)


class FakeVisualServer:
    instances = []

    def __init__(self, web_dir, bus, host, port, turn_handler, message_handler, *args, **kwargs):
        self.url = "https://127.0.0.1:8790/"
        self.scheme = "https"
        self.port = 8790
        self.message_handler = message_handler
        self.turn_handler = turn_handler
        self.notification_handler = kwargs.get("notification_handler")
        self.readiness_handler = kwargs.get("readiness_handler")
        self.turn_result_handler = kwargs.get("turn_result_handler")
        self.telemetry_handler = kwargs.get("telemetry_handler")
        self.home_assistant_policy_handler = kwargs.get("home_assistant_policy_handler")
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def runtime_config(root, overrides):
    """Use the validated runtime contract, including paths and optional integrations."""
    path = root / "eve.json"
    path.write_text(json.dumps(overrides), encoding="utf-8")
    return real_load_config(path, environ={})


class RuntimeTest(unittest.TestCase):
    @staticmethod
    def assert_process_gone(pid, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            except (FileNotFoundError, ProcessLookupError):
                return
            if len(stat) > 2 and stat[2] == "Z":
                return
            time.sleep(.02)
        raise AssertionError(f"Prozess {pid} läuft nach dem Shutdown weiterhin")

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_has_valid_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(PROJECT_ROOT / "run.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "eve-control.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_stack_controller_has_valid_shell_syntax_and_safe_order(self):
        controller = PROJECT_ROOT / "eve-control.sh"
        result = subprocess.run(
            ["bash", "-n", str(controller)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = controller.read_text(encoding="utf-8")
        start_body = source[source.index("start_stack()") : source.index("stop_stack()")]
        stop_body = source[source.index("stop_stack()") : source.index("status_stack()")]
        self.assertLess(start_body.index('"$STRATA_SCRIPT" start'), start_body.index('"$EVE_START_SCRIPT"'))
        self.assertLess(stop_body.index('"$EVE_STOP_SCRIPT"'), stop_body.index('"$STRATA_SCRIPT" stop'))
        self.assertIn('wait_for_health "$STRATA_HEALTH"', start_body)
        self.assertIn('wait_for_health "$EVE_READY"', start_body)
        self.assertIn('stop_container "$SEARXNG_CONTAINER"', stop_body)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "eve-control.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_stack_controller_operates_start_status_and_stop_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            events = temp_root / "events"
            strata_ready = temp_root / "strata.ready"
            eve_ready = temp_root / "eve.ready"

            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                f"  *8813*) test -e {str(strata_ready)!r} ;;\n"
                f"  *8790*) test -e {str(eve_ready)!r} ;;\n"
                "  *) exit 22 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)

            strata = temp_root / "strata"
            strata.write_text(
                "#!/usr/bin/env bash\n"
                f"echo strata-$1 >> {str(events)!r}\n"
                f"if [[ $1 == start ]]; then touch {str(strata_ready)!r}; else rm -f {str(strata_ready)!r}; fi\n",
                encoding="utf-8",
            )
            strata.chmod(0o700)
            eve_start = temp_root / "eve-start"
            eve_start.write_text(
                "#!/usr/bin/env bash\n"
                f"echo eve-start >> {str(events)!r}\n"
                f"touch {str(eve_ready)!r}\n",
                encoding="utf-8",
            )
            eve_start.chmod(0o700)
            eve_stop = temp_root / "eve-stop"
            eve_stop.write_text(
                "#!/usr/bin/env bash\n"
                f"echo eve-stop >> {str(events)!r}\n"
                f"rm -f {str(eve_ready)!r}\n",
                encoding="utf-8",
            )
            eve_stop.chmod(0o700)

            environment = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "EVE_RUNTIME_DIR": str(temp_root / "runtime"),
                "EVE_STRATA_SCRIPT": str(strata),
                "EVE_START_SCRIPT": str(eve_start),
                "EVE_STOP_SCRIPT": str(eve_stop),
                "EVE_SEARXNG_CONTAINER": "",
                "EVE_STRATA_CONTAINER": "",
                "EVE_CONTROL_NOTIFICATIONS": "0",
            }
            controller = str(PROJECT_ROOT / "eve-control.sh")
            started = subprocess.run([controller, "start"], env=environment, capture_output=True, text=True)
            status = subprocess.run([controller, "status"], env=environment, capture_output=True, text=True)
            stopped = subprocess.run([controller, "stop"], env=environment, capture_output=True, text=True)
            event_lines = events.read_text(encoding="utf-8").splitlines()

        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(event_lines, ["strata-start", "eve-start", "eve-stop", "strata-stop"])
        self.assertIn("EVE:       bereit", status.stdout)
        self.assertIn("Strata:    bereit", status.stdout)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "desktop-start.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_desktop_launcher_serializes_concurrent_starts_before_shared_files(self):
        launcher = PROJECT_ROOT / "desktop-start.sh"
        result = subprocess.run(
            ["bash", "-n", str(launcher)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = launcher.read_text(encoding="utf-8")
        lock = source.index('flock -n 8')
        spawn = source.index('nohup "$HERE/run.sh"')
        pid_write = source.index('>"$PID_FILE"')
        self.assertLess(lock, spawn)
        self.assertLess(lock, pid_write)
        self.assertIn("EVE wird bereits gestartet", source)
        self.assertIn("for _ in {1..300}", source)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "desktop-stop.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_desktop_stopper_accepts_equivalent_home_paths(self):
        stopper = PROJECT_ROOT / "desktop-stop.sh"
        result = subprocess.run(
            ["bash", "-n", str(stopper)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = stopper.read_text(encoding="utf-8")
        self.assertIn("matches_executable", source)
        self.assertIn('[[ "$argument" -ef "$expected" ]]', source)
        self.assertIn('*/outputs/eve-local-agent/.venv/bin/eve', source)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_imports_its_own_source_tree(self):
        source = (PROJECT_ROOT / "run.sh").read_text(encoding="utf-8")
        self.assertIn('export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"', source)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_rejects_a_second_instance_before_starting_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "eve.lock"
            with lock_path.open("w+") as lock:
                lock.write("999999\n")
                lock.flush()
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(
                    [str(PROJECT_ROOT / "run.sh"), "--no-tts"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                    env={**os.environ, "EVE_RUNTIME_DIR": tmp},
                )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unbekannten Prozess", result.stderr)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_recovers_legacy_empty_orphan_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            lock_path = temp_root / "eve.lock"
            config_path = temp_root / "eve.json"
            config_path.write_text(json.dumps({"text_to_speech":{"engine":"piper"}, "visual":{"host":"127.0.0.1", "port":8799}}))
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text("#!/usr/bin/env bash\nexit 22\n")
            fake_curl.chmod(0o700)
            fake_eve = temp_root / "fake-eve"
            fake_eve.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
            fake_eve.chmod(0o700)
            with lock_path.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(
                    [str(PROJECT_ROOT / "run.sh"), "--no-tts", "--config", str(config_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                    env={
                        **os.environ,
                        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                        "EVE_RUNTIME_DIR": tmp,
                        "EVE_EXECUTABLE": str(fake_eve),
                        "EVE_SKIP_AUXILIARY": "1",
                    },
                )
        self.assertNotIn("läuft bereits", result.stderr)
        self.assertIn("vor Erreichen der Bereitschaft beendet", result.stderr)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_fails_if_eve_exits_before_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            fake_eve = temp_root / "fake-eve"
            fake_eve.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
            fake_eve.chmod(0o700)
            config_path = temp_root / "eve.json"
            config_path.write_text(
                json.dumps({
                    "text_to_speech": {"engine": "piper"},
                    "visual": {"host": "127.0.0.1", "port": 8799},
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(PROJECT_ROOT / "run.sh"), "--no-tts", "--config", str(config_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                env={
                    **os.environ,
                    "EVE_EXECUTABLE": str(fake_eve),
                    "EVE_RUNTIME_DIR": str(temp_root / "runtime"),
                    "EVE_SKIP_AUXILIARY": "1",
                },
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vor Erreichen der Bereitschaft beendet", result.stderr)

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_forwards_term_and_reaps_eve_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake_curl.chmod(0o700)
            child_pid_file = temp_root / "child.pid"
            started_file = temp_root / "child.started"
            terminated_file = temp_root / "child.terminated"
            fake_eve = temp_root / "fake-eve"
            fake_eve.write_text(
                "#!/usr/bin/env bash\n"
                "echo $$ > \"$FAKE_PID_FILE\"\n"
                ": > \"$FAKE_STARTED_FILE\"\n"
                "trap ': > \"$FAKE_TERMINATED_FILE\"; exit 0' TERM INT\n"
                "while true; do sleep .05; done\n",
                encoding="utf-8",
            )
            fake_eve.chmod(0o700)
            config_path = temp_root / "eve.json"
            config_path.write_text(
                json.dumps({
                    "text_to_speech": {"engine": "piper"},
                    "visual": {"host": "127.0.0.1", "port": 8799},
                }),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "EVE_EXECUTABLE": str(fake_eve),
                "EVE_RUNTIME_DIR": str(temp_root / "runtime"),
                "EVE_SKIP_AUXILIARY": "1",
                "EVE_SHUTDOWN_GRACE_TICKS": "20",
                "FAKE_PID_FILE": str(child_pid_file),
                "FAKE_STARTED_FILE": str(started_file),
                "FAKE_TERMINATED_FILE": str(terminated_file),
            }
            process = subprocess.Popen(
                [str(PROJECT_ROOT / "run.sh"), "--no-tts", "--config", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            child_pid = None
            try:
                for _ in range(100):
                    if started_file.exists() or process.poll() is not None:
                        break
                    time.sleep(.02)
                self.assertTrue(started_file.exists(), "Fake-EVE wurde nicht gestartet")
                child_pid = int(child_pid_file.read_text(encoding="utf-8"))
                process.terminate()
                process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143)
                self.assertTrue(terminated_file.exists())
                self.assert_process_gone(child_pid)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                if child_pid is not None:
                    try:
                        os.kill(child_pid, 9)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(os.name == "posix" and fcntl is not None and shutil.which("bash") and (PROJECT_ROOT / "run.sh").exists(), "Lokaler Linux-Entwicklungslauncher ist nicht Bestandteil dieser Installation")
    def test_run_script_kills_stubborn_service_process_group_without_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake_curl.chmod(0o700)
            service_pid_file = temp_root / "service.pid"
            worker_pid_file = temp_root / "worker.pid"
            fake_eve = temp_root / "fake-eve"
            fake_eve.write_text(
                "#!/usr/bin/env bash\n"
                "trap '' TERM INT\n"
                "echo $$ > \"$FAKE_SERVICE_PID_FILE\"\n"
                "sleep 300 &\n"
                "echo $! > \"$FAKE_WORKER_PID_FILE\"\n"
                "wait\n",
                encoding="utf-8",
            )
            fake_eve.chmod(0o700)
            config_path = temp_root / "eve.json"
            config_path.write_text(
                json.dumps({
                    "text_to_speech": {"engine": "piper"},
                    "visual": {"host": "127.0.0.1", "port": 8799},
                }),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "EVE_EXECUTABLE": str(fake_eve),
                "EVE_RUNTIME_DIR": str(temp_root / "runtime"),
                "EVE_SKIP_AUXILIARY": "1",
                "EVE_SHUTDOWN_GRACE_TICKS": "3",
                "FAKE_SERVICE_PID_FILE": str(service_pid_file),
                "FAKE_WORKER_PID_FILE": str(worker_pid_file),
            }
            process = subprocess.Popen(
                [str(PROJECT_ROOT / "run.sh"), "--no-tts", "--config", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            service_pid = worker_pid = None
            try:
                for _ in range(100):
                    if worker_pid_file.exists() or process.poll() is not None:
                        break
                    time.sleep(.02)
                self.assertTrue(worker_pid_file.exists(), "Fake-Worker wurde nicht gestartet")
                service_pid = int(service_pid_file.read_text(encoding="utf-8"))
                worker_pid = int(worker_pid_file.read_text(encoding="utf-8"))
                process.terminate()
                process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143)
                self.assert_process_gone(service_pid)
                self.assert_process_gone(worker_pid)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                for pid in (service_pid, worker_pid):
                    if pid is not None:
                        try:
                            os.kill(pid, 9)
                        except ProcessLookupError:
                            pass

    def test_serve_is_noninteractive_and_uses_deterministic_speech_by_default(self):
        FakeVisualServer.instances = []
        bus, llm, speaker = FakeBus(), FakeLLM(), FakeSpeaker()
        config = {
            "audio": {},
            "speech_to_text": {},
            "text_to_speech": {"engine": "qwen3_tts"},
            "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": True},
        }
        response = {}
        readiness = []

        def exercise_browser_before_shutdown():
            readiness.append(FakeVisualServer.instances[0].readiness_handler())
            readiness.append(FakeVisualServer.instances[0].readiness_handler())
            response.update(FakeVisualServer.instances[0].message_handler("Test", []))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                completion = FakeVisualServer.instances[0].turn_result_handler(response["turn_id"])
                if completion["status"] == "complete":
                    response.update(completion["audio"])
                    break
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), FakeAgent(), FakeReminders())), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=speaker), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_browser_before_shutdown), \
             mock.patch.object(cli.webbrowser, "open") as open_browser, \
             mock.patch("builtins.input", side_effect=AssertionError("serve darf stdin nicht lesen")):
            result = cli.main(["serve"])

        self.assertEqual(result, 0)
        self.assertTrue(FakeVisualServer.instances[0].started)
        self.assertTrue(FakeVisualServer.instances[0].stopped)
        open_browser.assert_not_called()
        self.assertEqual(llm.rewrites, 0)
        self.assertEqual(llm.model_checks, 1)
        self.assertTrue(readiness[0]["ready"])
        self.assertEqual(readiness[0], readiness[1])
        self.assertEqual(len(llm.sanitized), 1)
        self.assertEqual(speaker.spoken, ["SICHER: Ich habe das Gerät zu 75 Prozent geöffnet."])
        self.assertEqual(response["answer"], "Ich habe das Gerät zu 75 Prozent geöffnet.")
        self.assertTrue(response["audio_wav_base64"])

    def test_home_assistant_policy_handler_uses_agent_provider(self):
        FakeVisualServer.instances = []
        bus, llm, speaker = FakeBus(), FakeLLM(), FakeSpeaker()
        agent = FakeAgent()
        agent.home_assistant = type("Home", (), {
            "configured": True,
            "semantic_provider_identity": lambda self: {
                "provider": "home_assistant", "endpoint": "http://ha.local",
            },
        })()

        class PolicyMemory(FakeMemory):
            def home_assistant_policy_overview(self, provider):
                return {"provider": provider, "policy": {"excluded_areas": ["Garage"]}}

        observed = {}
        config = {
            "audio": {}, "speech_to_text": {},
            "text_to_speech": {"engine": "piper"},
            "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": False},
        }

        def exercise_policy():
            handler = FakeVisualServer.instances[0].home_assistant_policy_handler
            status, payload = handler("GET", {})
            observed.update(status=status, payload=payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(
                 bus, llm, PolicyMemory(), agent, FakeReminders(),
             )), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=speaker), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_policy):
            self.assertEqual(0, cli.main(["serve", "--no-tts"]))

        self.assertEqual(200, observed["status"])
        self.assertEqual(["Garage"], observed["payload"]["policy"]["excluded_areas"])

    def test_response_stream_uses_actual_publication_not_optional_agent_tracking(self):
        from eve_agent.answer_stream import AnswerStreamMismatchError
        for mode in ("buffered", "partial", "complete", "changed", "overlong", "diagram", "artifact", "credentials", "preview"):
            with self.subTest(mode=mode):
                FakeVisualServer.instances = []
                chunks = []
                class StreamingLLM(FakeLLM):
                    @contextmanager
                    def stream_answers(self, callback):
                        self.callback = callback
                        yield
                    @contextmanager
                    def stream_tool_previews(self, callback, reset):
                        self.preview_callback = callback
                        yield
                llm = StreamingLLM()
                class Agent(FakeAgent):
                    @contextmanager
                    def published_answer_stream(self):
                        # An optional observer may not implement tracking.
                        yield []
                    def note_published_answer_delta(self, chunk):
                        pass
                    def _diagnostic(self, *args, **kwargs):
                        pass
                    def respond_turn(self, *args):
                        result = super().respond_turn(*args)
                        if mode == "diagram":
                            result = replace(result, answer="Ablauf:\n```\nLicht an\n ↓\nWarten\n```\nFertig.")
                        elif mode == "artifact":
                            result = replace(result, answer="Hier ist der Code:\n```yaml\nmode: restart\n```\nFertig.")
                        if mode in {"credentials", "preview"}:
                            from eve_agent.memory import redact_sensitive
                            raw = ("Quelle:\nhttps://example.org/" + "long-article-" * 20
                                   + "\nAuthorization: Bearer private_credential_123456789\nFertig.")
                            result = replace(result, answer=redact_sensitive(raw))
                            if mode == "preview":
                                for character in raw:
                                    llm.preview_callback(character)
                                llm.callback(raw)
                            else:
                                for character in raw:
                                    llm.callback(character)
                        if mode in {"partial", "complete", "changed", "overlong"}:
                            chunk = {"partial":result.answer[:10], "complete":result.answer,
                                     "changed":"Falscher Text", "overlong":result.answer + " extra"}[mode]
                            llm.callback(chunk)
                        return result
                agent = Agent()
                config = {"audio":{}, "speech_to_text":{}, "text_to_speech":{"engine":"piper"},
                          "visual":{"host":"127.0.0.1","port":8790,"open_browser":False}}
                def exercise():
                    handler = FakeVisualServer.instances[0].message_handler
                    if mode in {"changed","overlong"}:
                        with self.assertRaises(AnswerStreamMismatchError):
                            handler("Test", [], None, chunks.append)
                        expected = "Falscher Text" if mode == "changed" else "Ich habe das Gerät zu 75 Prozent geöffnet. extra"
                        self.assertEqual(expected, "".join(chunks))
                    else:
                        events = []
                        def publish(chunk):
                            chunks.append(chunk)
                            events.append(("answer", chunk))
                        result = handler("Test", [], None, publish,
                            on_preview=lambda chunk: events.append(("preview", chunk)))
                        self.assertEqual(result["answer"], "".join(chunks))
                        if mode == "preview":
                            first_answer = next(i for i, event in enumerate(events) if event[0] == "answer")
                            self.assertTrue(all(kind == "answer" for kind, _ in events[first_answer:]))
                            preview = "".join(chunk for kind, chunk in events if kind == "preview")
                            self.assertTrue(result["answer"].startswith(preview))
                            self.assertFalse(preview.endswith("Fertig."))
                        if mode in {"credentials", "preview"}:
                            self.assertNotIn("private_credential_123456789", "".join(chunks))
                            self.assertIn("long-article-" * 20, result["answer"])
                            self.assertIn("[REDACTED]", result["answer"])
                        else:
                            self.assertEqual(1 if mode != "partial" else 2, len(chunks))
                        if mode in {"diagram", "artifact"}:
                            self.assertIn("```", result["answer"])
                            self.assertEqual(1 if mode == "artifact" else 0, len(result["artifacts"]))
                with tempfile.TemporaryDirectory() as tmp, \
                     mock.patch.object(cli,"load_config",return_value=runtime_config(Path(tmp), config)), \
                     mock.patch.object(cli,"build",return_value=(FakeBus(),llm,FakeMemory(),agent,FakeReminders())), \
                     mock.patch.object(cli,"Recorder"), mock.patch.object(cli,"Transcriber"), \
                     mock.patch.object(cli,"Speaker",return_value=FakeSpeaker()), \
                     mock.patch.object(cli,"VisualServer",FakeVisualServer), \
                     mock.patch.object(cli,"_wait_for_service_shutdown",side_effect=exercise):
                    self.assertEqual(0,cli.main(["serve","--no-tts"]))

    def test_failed_text_turn_resets_global_state_and_records_cause(self):
        FakeVisualServer.instances = []
        bus, llm, agent = FakeBus(), FakeLLM(), FailingFakeAgent()
        config = {
            "audio": {}, "speech_to_text": {},
            "text_to_speech": {"engine": "piper"},
            "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": False},
        }
        observed = {}

        def exercise_failed_turn():
            with self.assertRaisesRegex(RuntimeError, "provider planning failed"):
                FakeVisualServer.instances[0].message_handler("Test", [])
            observed.update(bus.read())

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), agent, FakeReminders())), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=FakeSpeaker()), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_failed_turn):
            self.assertEqual(0, cli.main(["serve", "--no-tts"]))

        self.assertEqual("idle", observed["state"])
        self.assertTrue(agent.diagnostics)
        self.assertEqual(("turn", "process", "error", "Text-Turn fehlgeschlagen"), agent.diagnostics[-1][0])
        self.assertIsInstance(agent.diagnostics[-1][1]["exception"], RuntimeError)

    def test_presentation_and_tts_overlap_without_delaying_text_response(self):
        FakeVisualServer.instances = []
        barrier = threading.Barrier(2)
        bus, llm = FakeBus(), FakeLLM()
        agent = ParallelFakeAgent(barrier)
        speaker = ParallelFakeSpeaker(barrier)
        config = {
            "audio": {}, "speech_to_text": {},
            "text_to_speech": {"engine": "piper"},
            "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": False},
        }
        response = {}
        trace = {}

        def exercise_browser_before_shutdown():
            server = FakeVisualServer.instances[0]
            response.update(server.message_handler("Test", []))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                completion = server.turn_result_handler(response["turn_id"])
                if completion["status"] == "complete":
                    turns = server.telemetry_handler({})["turns"]
                    trace.update(next(turn for turn in turns if turn["id"] == response["turn_id"]))
                    return
                time.sleep(.01)
            self.fail("Parallele Nachbearbeitung wurde nicht abgeschlossen")

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), agent, FakeReminders())), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=speaker), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_browser_before_shutdown):
            self.assertEqual(0, cli.main(["serve"]))

        summary = trace["summary"]
        self.assertTrue(response["presentation_pending"])
        self.assertIn("assistant_message_id", response)
        self.assertLess(summary["text_sent_ms"], summary["presentation_ready_ms"])
        self.assertLess(summary["text_sent_ms"], summary["audio_ready_ms"])
        self.assertLess(abs(summary["presentation_start_ms"] - summary["tts_start_ms"]), 50)
        self.assertGreater(summary["postprocess_overlap_ms"], 0)
        self.assertGreaterEqual(summary["complete_ms"], summary["presentation_ready_ms"])
        self.assertGreaterEqual(summary["complete_ms"], summary["audio_ready_ms"])

    def test_parallel_post_turn_failures_are_isolated_in_all_combinations(self):
        config = {
            "audio": {}, "speech_to_text": {},
            "text_to_speech": {"engine": "piper"},
            "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": False},
        }
        for presentation_fails in (False, True):
            for tts_fails in (False, True):
                with self.subTest(presentation=presentation_fails, tts=tts_fails):
                    FakeVisualServer.instances = []
                    bus, llm = FakeBus(), FakeLLM()
                    agent = OutcomeFakeAgent(presentation_fails)
                    speaker = OutcomeFakeSpeaker(tts_fails)
                    observed = {}

                    def exercise_browser_before_shutdown():
                        server = FakeVisualServer.instances[0]
                        response = server.message_handler("Test", [])
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            completion = server.turn_result_handler(response["turn_id"])
                            if completion["status"] == "complete":
                                observed.update(completion)
                                observed["answer"] = response["answer"]
                                return
                            time.sleep(.01)
                        self.fail("Fehlerisolierter Turn blieb hängen")

                    with tempfile.TemporaryDirectory() as tmp, \
                         mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
                         mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), agent, FakeReminders())), \
                         mock.patch.object(cli, "Recorder"), \
                         mock.patch.object(cli, "Transcriber"), \
                         mock.patch.object(cli, "Speaker", return_value=speaker), \
                         mock.patch.object(cli, "VisualServer", FakeVisualServer), \
                         mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_browser_before_shutdown):
                        self.assertEqual(0, cli.main(["serve"]))

                    self.assertEqual("complete", observed["status"])
                    self.assertEqual(
                        "error" if presentation_fails else "success",
                        observed["presentation"]["status"],
                    )
                    self.assertEqual(
                        "error" if tts_fails else "success",
                        observed["audio"]["status"],
                    )
                    self.assertEqual(
                        "Ich habe das Gerät zu 75 Prozent geöffnet.", observed["answer"],
                    )

    def test_readiness_is_false_when_configured_llm_is_not_loaded(self):
        FakeVisualServer.instances = []
        bus, llm, speaker = FakeBus(), FakeLLM(), FakeSpeaker()
        llm.available_models = ["another-model"]
        config = {
            "audio": {},
            "speech_to_text": {},
            "text_to_speech": {"engine": "qwen3_tts"},
            "visual": {"host": "127.0.0.1", "port": 8790},
        }
        readiness = {}

        def inspect_readiness():
            readiness.update(FakeVisualServer.instances[0].readiness_handler())

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), FakeAgent(), FakeReminders())), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=speaker), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=inspect_readiness):
            result = cli.main(["serve", "--no-tts"])

        self.assertEqual(result, 0)
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["llm"], "not_ready")

    def test_browser_and_reminder_tts_are_serialized(self):
        class DueReminders:
            def __init__(self):
                self.returned = False

            def pop_due(self, limit=None):
                if self.returned:
                    return []
                self.returned = True
                return [{"message": "Test-Erinnerung"}]

        class BlockingSpeaker(FakeSpeaker):
            def __init__(self):
                super().__init__()
                self.entered = threading.Event()
                self.release = threading.Event()
                self.active = 0
                self.overlap = False
                self.guard = threading.Lock()

            def synthesize(self, text):
                with self.guard:
                    self.active += 1
                    self.overlap |= self.active > 1
                self.entered.set()
                self.release.wait(2)
                with self.guard:
                    self.active -= 1
                return super().synthesize(text)

        FakeVisualServer.instances = []
        bus, llm, speaker = FakeBus(), FakeLLM(), BlockingSpeaker()
        config = {
            "audio": {},
            "speech_to_text": {},
            "text_to_speech": {"engine": "qwen3_tts"},
            "visual": {"host": "127.0.0.1", "port": 8790},
        }

        def exercise_concurrent_tts():
            visual = FakeVisualServer.instances[0]
            response_thread = threading.Thread(target=visual.message_handler, args=("Test", []))
            response_thread.start()
            self.assertTrue(speaker.entered.wait(1))
            notification_thread = threading.Thread(target=visual.notification_handler)
            notification_thread.start()
            time.sleep(.05)
            self.assertFalse(speaker.overlap)
            speaker.release.set()
            response_thread.join(2)
            notification_thread.join(2)
            self.assertFalse(response_thread.is_alive())
            self.assertFalse(notification_thread.is_alive())

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli, "load_config", return_value=runtime_config(Path(tmp), config)), \
             mock.patch.object(cli, "build", return_value=(bus, llm, FakeMemory(), FakeAgent(), DueReminders())), \
             mock.patch.object(cli, "Recorder"), \
             mock.patch.object(cli, "Transcriber"), \
             mock.patch.object(cli, "Speaker", return_value=speaker), \
             mock.patch.object(cli, "VisualServer", FakeVisualServer), \
             mock.patch.object(cli, "_wait_for_service_shutdown", side_effect=exercise_concurrent_tts):
            result = cli.main(["serve"])

        self.assertEqual(result, 0)
        self.assertFalse(speaker.overlap)
        self.assertEqual(len(speaker.spoken), 2)


if __name__ == "__main__":
    unittest.main()
