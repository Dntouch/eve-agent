import json
from pathlib import Path
import tempfile
import time
import unittest

from eve_agent.codex_chat import SharedChatJob, ProtocolError


class ScriptedServer:
    def __init__(self, socket=None):
        self.requests, self.sent = [], []
        self.events = []
        self.executions = 0
        self.closed = False

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "project/list":
            return {"data": [{"id": "project", "roots": [{"path": "/tmp"}]}]}
        if method == "thread/start":
            self.channel = Path(params["config"]["mcp_servers.eve_snapshot"]["args"][-1])
            return {"thread": {"id": "chat"}}
        if method == "turn/start":
            self.submit(1, "Originalauftrag")
            return {"turn": {"id": "turn"}}
        return {}

    def submit(self, number, instruction):
        from eve_agent.nova_chat_mcp import write_json
        write_json(self.channel / (str(number) * 32 + ".request.json"), {"instruction": instruction})

    def send(self, message):
        self.sent.append(message)

    def next_event(self, timeout):
        if self.events:
            return self.events.pop(0)
        if self.executions == 0 and (self.channel / ("1" * 32 + ".response.json")).exists():
            self.executions += 1
            self.submit(2, "Stefans korrigierter Auftrag")
            return {"method": "item/completed", "params": {"threadId": "chat", "item": {
                "id": "stefan-correction", "type": "userMessage", "content": [
                    {"type": "text", "text": "Korrektur von Stefan"}]}}}
        elif self.executions == 1 and (self.channel / ("2" * 32 + ".response.json")).exists():
            self.executions += 1
            return {"method": "turn/completed", "params": {
                "threadId": "chat", "turn": {"id": "turn", "status": "completed"}}}
        time.sleep(0.001)
        raise TimeoutError()

    def close(self):
        self.closed = True


class SharedChatTests(unittest.TestCase):
    def test_corrected_execution_is_the_result_returned_to_eve(self):
        server = ScriptedServer()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.json"
            job = SharedChatJob(directory, "job", path, client_factory=lambda **_: server)
            result = job.run("EVE initial", lambda instruction: calls.append(instruction) or {"value": instruction})
            self.assertEqual(calls, ["Originalauftrag", "Stefans korrigierter Auftrag"])
            self.assertEqual(result, {"value": "Stefans korrigierter Auftrag"})
            state = json.loads(path.read_text())
            self.assertEqual(state["thread_id"], "chat")
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["checked_result"], result)
            self.assertEqual(state["correction_revision"], 1)
            start = dict(server.requests)["thread/start"]
            self.assertEqual(start["projectId"], "project")
            self.assertEqual(start["cwd"], "/tmp")
            self.assertNotIn("environments", start)
            self.assertEqual(start["sandbox"], "read-only")
            self.assertTrue(server.closed)

    def test_no_fabricated_result_if_chat_never_runs_worker(self):
        server = ScriptedServer()
        original = server.request
        def request(method, params):
            result = original(method, params)
            if method == "turn/start":
                for path in server.channel.glob("*.request.json"):
                    path.unlink()
                server.events = [{"method": "turn/completed", "params": {
                    "threadId": "chat", "turn": {"id": "turn", "status": "completed"}}}]
            return result
        server.request = request
        with tempfile.TemporaryDirectory() as directory:
            job = SharedChatJob(directory, "job", Path(directory) / "chat.json", client_factory=lambda **_: server)
            with self.assertRaisesRegex(ProtocolError, "kein abgeschlossenes"):
                job.run("EVE", lambda _: self.fail("Unexpected execution"))
            self.assertEqual(dict(server.requests)["turn/interrupt"]["turnId"], "turn")

    def test_interruption_is_not_success(self):
        server = ScriptedServer()
        original = server.request
        def request(method, params):
            result = original(method, params)
            if method == "turn/start":
                for path in server.channel.glob("*.request.json"):
                    path.unlink()
                server.events = [{"method": "turn/completed", "params": {
                    "threadId": "chat", "turn": {"id": "turn", "status": "interrupted"}}}]
            return result
        server.request = request
        with tempfile.TemporaryDirectory() as directory:
            job = SharedChatJob(directory, "job", Path(directory) / "chat.json", client_factory=lambda **_: server)
            with self.assertRaisesRegex(ProtocolError, "interrupted"):
                job.run("EVE", lambda _: self.fail("Unexpected execution"))
            self.assertFalse((server.channel / "active").exists())

    def test_worker_failure_cannot_return_a_previous_success(self):
        server = ScriptedServer()
        def execute(instruction):
            if instruction.startswith("Stefans"):
                raise ValueError("worker failed")
            return {"value": "stale"}
        with tempfile.TemporaryDirectory() as directory:
            job = SharedChatJob(directory, "job", Path(directory) / "chat.json", client_factory=lambda **_: server)
            with self.assertRaisesRegex(ProtocolError, "kein abgeschlossenes"):
                job.run("EVE", execute)

    def test_unexecuted_correction_invalidates_previous_result(self):
        server = ScriptedServer()
        original = server.submit
        def submit(number, instruction):
            if number == 2:
                server.events.append({"method": "turn/completed", "params": {
                    "threadId": "chat", "turn": {"id": "turn", "status": "completed"}}})
            else:
                original(number, instruction)
        server.submit = submit
        with tempfile.TemporaryDirectory() as directory:
            job = SharedChatJob(directory, "job", Path(directory) / "chat.json", client_factory=lambda **_: server)
            with self.assertRaisesRegex(ProtocolError, "kein abgeschlossenes"):
                job.run("EVE", lambda _: {"value": "old"})


class MailboxTests(unittest.TestCase):
    def test_completed_job_refuses_late_execution(self):
        from eve_agent.nova_chat_mcp import dispatch
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "abgeschlossen"):
                dispatch(Path(directory), "tools/call", {
                    "name": "eve_execute_snapshot", "arguments": {"instruction": "late"}})

    def test_mailbox_returns_the_dispatchers_report(self):
        from eve_agent.nova_chat_mcp import dispatch, write_json
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            channel = Path(directory)
            write_json(channel / "active", {})
            with ThreadPoolExecutor() as pool:
                future = pool.submit(dispatch, channel, "tools/call", {
                    "name": "eve_execute_snapshot", "arguments": {"instruction": "corrected"}}, 2)
                deadline = time.monotonic() + 1
                requests = []
                while time.monotonic() < deadline:
                    requests = list(channel.glob("*.request.json"))
                    if requests:
                        break
                    time.sleep(.001)
                self.assertTrue(requests)
                self.assertEqual(json.loads(requests[0].read_text())["instruction"], "corrected")
                response = requests[0].with_name(requests[0].name.replace(".request.json", ".response.json"))
                write_json(response, {"success": True, "report": {"value": "corrected"}})
                self.assertEqual(future.result()["structuredContent"]["report"]["value"], "corrected")
