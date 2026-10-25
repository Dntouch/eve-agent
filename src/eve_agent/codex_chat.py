"""Local Codex WebSocket transport and visible EVE job coordination."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import select
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from .nova_chat_mcp import write_json

class ProtocolError(RuntimeError):
    pass


class SharedServer:
    """Small RFC 6455 client for the local Unix control socket."""
    def __init__(self, command="codex", socket=None, timeout=10):
        import socket as sockets
        import base64
        import hashlib
        import os
        self.errors = []
        self.events = deque()
        self.timeout = timeout
        self.sequence = 0
        path = socket or str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
                             / "app-server-control/app-server-control.sock")
        self.connection = sockets.socket(sockets.AF_UNIX, sockets.SOCK_STREAM)
        self.connection.settimeout(timeout)
        try:
            self.connection.connect(path)
            key = base64.b64encode(os.urandom(16)).decode()
            self.connection.sendall(("GET /rpc HTTP/1.1\r\nHost: localhost\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                header.extend(self._exact(1))
                if len(header) > 16384:
                    raise ProtocolError("Oversized WebSocket handshake")
            lines = header.decode("ascii").split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if (lines[0].split()[1] != "101" or headers.get("sec-websocket-accept") != expected
                    or headers.get("upgrade", "").lower() != "websocket"):
                raise ProtocolError("Invalid WebSocket upgrade response")
        except BaseException:
            self.connection.close()
            raise

    def _exact(self, length):
        data = bytearray()
        while len(data) < length:
            chunk = self.connection.recv(length - len(data))
            if not chunk:
                raise ProtocolError("Shared-server connection closed")
            data.extend(chunk)
        return bytes(data)

    def _frame(self, opcode, payload):
        import os
        import struct
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", size)
        self.connection.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, message):
        self._frame(1, json.dumps(message).encode())

    def _message(self):
        import struct
        data = bytearray()
        while True:
            first, second = self._exact(2)
            opcode = first & 15
            size = second & 127
            if first & 0x70 or second & 0x80:
                raise ProtocolError("Unsupported WebSocket frame flags")
            if size == 126:
                size = struct.unpack("!H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._exact(8))[0]
            if size + len(data) > 16777216:
                raise ProtocolError("Oversized WebSocket message")
            payload = self._exact(size)
            if opcode == 8:
                raise ProtocolError("Shared-server WebSocket closed")
            if opcode == 9:
                self._frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise ProtocolError("Expected text WebSocket message")
            data.extend(payload)
            if first & 0x80:
                return json.loads(data)

    def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError(f"Timeout waiting for {method}")
            self.connection.settimeout(remaining)
            message = self._message()
            if message.get("id") != request_id or "method" in message:
                self.events.append(message)
                continue
            if "error" in message:
                raise ProtocolError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result", {})

    def next_event(self, timeout=10):
        if self.events:
            return self.events.popleft()
        if not select.select([self.connection], [], [], timeout)[0]:
            raise TimeoutError("No Codex event before deadline")
        self.connection.settimeout(max(10, timeout))
        return self._message()

    def close(self):
        self.connection.close()


def project_for_workspace(client, workspace):
    workspace = Path(workspace).resolve()
    matches, cursor = [], None
    while True:
        page = client.request("project/list", {"limit": 100, "cursor": cursor})
        for project in page.get("data", []):
            for root in project.get("roots", []):
                path = Path(root["path"]).resolve()
                if path == workspace or path in workspace.parents:
                    matches.append((len(path.parts), project["id"], path))
        cursor = page.get("nextCursor")
        if not cursor:
            break
    if not matches:
        raise ProtocolError("Kein Codex-Projekt für das EVE-Arbeitsverzeichnis gefunden")
    longest = max(length for length, _, _ in matches)
    identifiers = {identifier for length, identifier, _ in matches if length == longest}
    if len(identifiers) != 1:
        raise ProtocolError("Das Codex-Projekt ist nicht eindeutig")
    identifier = identifiers.pop()
    return identifier, next(path for length, project_id, path in matches
                            if length == longest and project_id == identifier)


COORDINATOR_INSTRUCTIONS = """Du koordinierst einen sichtbaren EVE-Auftrag mit Stefan.
Der Auftrag stammt von EVE und wird als solcher gekennzeichnet. Stefans spätere
Eingaben im Chat korrigieren den Auftrag. Halte Fortschritt und Ergebnisse knapp
und verständlich auf Deutsch fest. Führe keinerlei Datei-, Prozess-, Netzwerk-
oder App-Aktionen selbst aus. Verwende ausschließlich eve_execute_snapshot für
die Ausführung. Dieses Werkzeug arbeitet im separaten isolierten Snapshot und
liefert einen technisch geprüften Bericht. Übergib darin den vollständigen,
aktuell korrigierten Auftrag; es ersetzt keine Sicherheitsgrenzen. Falls während
der Ausführung eine Korrektur eintrifft, warte auf das Werkzeugergebnis und führe
bei Bedarf den korrigierten Auftrag erneut aus. Berichte niemals eine Änderung
oder einen Test ohne entsprechendes Werkzeugergebnis. Beende den Turn erst,
wenn das letzte Werkzeugergebnis die aktuellen Eingaben erfüllt. Sage bei
Rückfragen ausdrücklich, welche Eingabe fehlt; erfinde keine Zustimmung.
Es erfolgt kein Deployment. Nach Abschluss des EVE-Aufrufs ist das Ausführungs-
werkzeug nicht mehr verbunden; für neue Arbeit muss EVE erneut beauftragt werden.
"""



class SharedChatJob:
    """One visible EVE request; execution remains in the caller's isolated worker."""
    def __init__(self, workspace, job_id, state_path, *, socket=None, timeout=900,
                 client_factory=SharedServer):
        self.workspace = Path(workspace).resolve()
        self.job_id, self.state_path = job_id, Path(state_path)
        self.timeout, self.client_factory, self.socket = timeout, client_factory, socket
        self.thread_id = None
        self.turn_id = None
        self.state = {"job_id": job_id, "status": "connecting"}

    def save(self, **updates):
        self.state.update(updates)
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.state_path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(self.state, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, self.state_path)

    def run(self, instruction, execute):
        client = self.client_factory(socket=self.socket)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eve-isolated-nova")
        pending, last_result, revision = None, None, 0
        accepted_calls = set()
        user_messages = set()
        correction_revision = 0
        execution_correction_revision = -1
        channel = self.state_path.parent / "mcp-mailbox"
        channel.mkdir(parents=True, exist_ok=True, mode=0o700)
        active = channel / "active"
        write_json(active, {"job_id": self.job_id})
        try:
            client.request("initialize", {"clientInfo": {"name": "eve_nova_bridge", "version": "0.1.0"},
                                          "capabilities": {"experimentalApi": True}})
            client.send({"method": "initialized"})
            project, project_root = project_for_workspace(client, self.workspace)
            thread = client.request("thread/start", {
                "projectId": project, "cwd": str(project_root), "ephemeral": False,
                "approvalPolicy": "never", "sandbox": "read-only",
                "developerInstructions": COORDINATOR_INSTRUCTIONS,
                "config": {"web_search": "disabled", "features.shell_tool": False,
                           "features.apply_patch_freeform": False,
                           "mcp_servers.eve_snapshot": {
                               "command": sys.executable,
                               "args": [str(Path(__file__).with_name("nova_chat_mcp.py")),
                                        "--directory", str(channel.resolve())],
                               "enabled": True, "required": True,
                               "startup_timeout_sec": 15, "tool_timeout_sec": self.timeout,
                           }},
            })["thread"]
            self.thread_id = thread["id"]
            title = f"EVE → Nova · {self.job_id}"
            self.save(thread_id=self.thread_id, project_id=project, title=title, status="submitted")
            client.request("thread/name/set", {"threadId": self.thread_id, "name": title})
            turn = client.request("turn/start", {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": f"Auftrag von EVE ({self.job_id}):\n\n{instruction}"}],
            })["turn"]
            self.turn_id = turn["id"]
            self.save(turn_id=self.turn_id, status="running")
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if pending and pending[1].done():
                    response_path, future, call_revision = pending
                    pending = None
                    try:
                        report = future.result()
                        last_result = report if execution_correction_revision == correction_revision else None
                        result = {"success": True, "report": report}
                        self.save(status="running", execution_revision=call_revision,
                                  checked_result=report)
                    except Exception as exc:
                        last_result = None
                        result = {"success": False, "error": str(exc)}
                        self.save(status="running", execution_error=str(exc))
                    write_json(response_path, result)
                if pending is None:
                    requests = sorted(channel.glob("*.request.json"))
                    for request_path in requests:
                        identifier = request_path.name.removesuffix(".request.json")
                        if identifier in accepted_calls:
                            continue
                        if len(identifier) != 32 or any(ch not in "0123456789abcdef" for ch in identifier):
                            raise ProtocolError("Ungültige MCP-Auftragskennung")
                        arguments = json.loads(request_path.read_text())
                        if (not isinstance(arguments, dict) or set(arguments) != {"instruction"}
                                or not isinstance(arguments["instruction"], str)
                                or not arguments["instruction"].strip() or len(arguments["instruction"]) > 64000):
                            raise ProtocolError("Ungültiger isolierter Auftrag")
                        accepted_calls.add(identifier)
                        revision += 1
                        execution_correction_revision = correction_revision
                        last_result = None
                        self.save(status="executing", execution_revision=revision,
                                  effective_instruction=arguments["instruction"])
                        pending = (channel / f"{identifier}.response.json",
                                   pool.submit(execute, arguments["instruction"]), revision)
                        break
                try:
                    message = client.next_event(timeout=min(0.1, max(0, deadline - time.monotonic())))
                except TimeoutError:
                    continue
                method, params = message.get("method"), message.get("params", {})
                if method in {"item/started", "item/completed"} and params.get("threadId") == self.thread_id:
                    item = params.get("item", {})
                    if item.get("type") == "userMessage" and item.get("id") not in user_messages:
                        user_messages.add(item.get("id"))
                        text = "\n".join(part.get("text", "") for part in item.get("content", [])
                                         if part.get("type") == "text")
                        if text != f"Auftrag von EVE ({self.job_id}):\n\n{instruction}":
                            correction_revision += 1
                            last_result = None
                            self.save(correction_revision=correction_revision)
                if "id" in message and method:
                    client.send({"id": message["id"], "error": {
                        "code": -32601, "message": "The EVE dispatcher handles no interactive server requests"}})
                elif method == "turn/completed" and params.get("threadId") == self.thread_id:
                    completed = params.get("turn", {})
                    if completed.get("id") != self.turn_id:
                        continue
                    status = completed.get("status")
                    if status != "completed":
                        raise ProtocolError(f"Arbeitschat endete mit Status {status}; keine Aktivierung")
                    if pending or last_result is None:
                        raise ProtocolError("Arbeitschat lieferte kein abgeschlossenes isoliertes Ergebnis")
                    self.save(status="completed")
                    return last_result
            raise ProtocolError("Zeitlimit des sichtbaren EVE-Auftrags erreicht")
        except BaseException as exc:
            self.save(status="failed", error=str(exc))
            if self.turn_id:
                try:
                    client.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})
                except Exception:
                    pass
            raise
        finally:
            # A running isolated subprocess may finish its bounded snapshot work;
            # interruption never promotes its result or prepares a deployment.
            active.unlink(missing_ok=True)
            pool.shutdown(wait=False, cancel_futures=True)
            client.close()
