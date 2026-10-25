"""Native host shell processes with an explicitly configured source denylist."""
from __future__ import annotations

import codecs
import os
from pathlib import Path
import re
import pwd
import shlex
import signal
import subprocess
import threading
import uuid
from copy import deepcopy


def command_tokens(source: str) -> list[str]:
    """Canonicalize submitted shell words, not their eventual execution effects.

    Whitespace/quoting and adjacent short option groups are normalized. This is
    deliberately a source filter, not an interpreter or an OS security boundary.
    """
    lexer = shlex.shlex(source, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        words = list(lexer)
    except ValueError:
        # Incomplete stdin fragments are still valid input to a running process.
        words = source.split()
    result = []
    flags = ""
    for word in words:
        if re.fullmatch(r"-[A-Za-z]+", word):
            flags += word[1:]
            continue
        if flags:
            result.append("-" + "".join(sorted(set(flags))))
            flags = ""
        result.append(word)
    if flags:
        result.append("-" + "".join(sorted(set(flags))))
    return result


class ShellCapability:
    capability_name = "shell"

    def __init__(self, config: dict, root: Path):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.sessions = {}
        self.configure(config)

    def configure(self, config):
        with self.lock:
            self.config = deepcopy(config)

    def self_descriptions(self):
        from .runtime_self_knowledge import RuntimeSelfDescription
        if not self.enabled:
            return []
        return [RuntimeSelfDescription(
            "shell.execute", "shell.execute",
            "Ich kann Shellbefehle mit den Linux-Rechten meines Benutzerkontos ausführen, Ausgaben lesen und laufende Prozesse bedienen. Die konfigurierte Befehlssperrliste gilt für übergebenen Text.",
            "ShellCapability", "execute,poll,write,terminate",
        )]

    @property
    def enabled(self):
        with self.lock:
            return bool(self.config.get("enabled", False))

    def _blocked(self, source):
        tokens = command_tokens(source)
        for entry in self.config.get("forbidden_commands", []):
            pattern = command_tokens(entry)
            def matches(index):
                for offset, expected in enumerate(pattern):
                    actual = tokens[index + offset]
                    if offset == 0 and "/" not in expected and "/" in actual:
                        actual = Path(actual).name
                    if re.fullmatch(r"-[A-Za-z]+", expected) and re.fullmatch(r"-[A-Za-z]+", actual):
                        if not set(expected[1:]).issubset(actual[1:]):
                            return False
                    elif actual != expected:
                        return False
                return True
            if pattern and any(matches(index) for index in range(len(tokens) - len(pattern) + 1)):
                return entry
        return None

    def native_contract(self):
        if not self.enabled:
            return None
        def operation(description, properties, required=(), effect="write"):
            return {"description": description, "effect": effect, "parameters_schema": {
                "type": "object", "additionalProperties": False,
                "properties": properties, "required": list(required),
            }}
        session = {"session_id": {"type": "string"}}
        wait = {"wait_seconds": {"type": "number", "minimum": 0,
                                  "description": "Wait for exit at most this long; does not limit process lifetime. Default 1 second."}}
        return {
            "description": "Execute real shell commands as the EVE Linux user, with inherited host permissions and environment. "
                "No directory allowlist, approval step, output truncation or execution timeout. "
                "Each execute starts an independent shell. Poll sessions for incremental output, write stdin or send signals. "
                "Only configured forbidden command word sequences in submitted source are rejected; "
                "this does not constrain indirect script effects or expanded commands.",
            "runtime": {"user": pwd.getpwuid(os.geteuid()).pw_name, "uid": os.geteuid(),
                        "executable": self.config.get("executable", "/bin/bash"), "default_cwd": str(self.root)},
            "forbidden_commands": deepcopy(self.config.get("forbidden_commands", [])),
            "operations": {
                "execute": operation("Start a shell command. Returns stdout, stderr, exit_code and session_id. "
                    "If still running, use poll/write/terminate. Credential-bearing processes return only status and exit code; "
                    "stdout/stderr are confidential, including transformed values. Verify the task separately without credentials.", {
                        "command": {"type": "string", "minLength": 1},
                        "cwd": {"type": "string", "description": "Any working directory accessible to the EVE user. Relative to project root; default project root."},
                        "env": {"type": "object", "additionalProperties": {"type": "string"}},
                        **wait,
                    }, ["command"]),
                "poll": operation("Read new stdout/stderr and current exit status of a process.", {**session, **wait}, ["session_id"], "read"),
                "write": operation("Send text to process stdin; include a newline when needed. "
                    "close_stdin sends EOF after text. The command denylist also checks each submitted input fragment.", {
                        **session, **wait, "text": {"type": "string"}, "close_stdin": {"type": "boolean"},
                    }, ["session_id", "text"]),
                "terminate": operation("Send a named Linux signal to the shell process group. Default SIGTERM; SIGKILL forces termination.", {
                    **session, **wait, "signal": {"type": "string"},
                }, ["session_id"]),
            },
        }

    @staticmethod
    def _reader(session, stream, key):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while chunk := os.read(stream.fileno(), 65536):
                with session["lock"]:
                    if not session["confidential_output"]:
                        session[key].append(decoder.decode(chunk))
            with session["lock"]:
                if not session["confidential_output"]:
                    session[key].append(decoder.decode(b"", final=True))
        finally:
            stream.close()

    @staticmethod
    def _reap(session):
        session["process"].wait()
        with session["input_lock"]:
            session["process"].stdin.close()
        for reader in session["readers"]:
            reader.join()
        with session["lock"]:
            session["done"].set()

    def _result(self, identifier, wait_seconds):
        session = self.sessions[identifier]
        session["done"].wait(wait_seconds)
        with session["lock"]:
            stdout, stderr = "".join(session["stdout"]), "".join(session["stderr"])
            session["stdout"].clear()
            session["stderr"].clear()
            code = session["process"].poll()
            complete = session["done"].is_set()
        return {"status": ("completed" if code == 0 else "failed") if complete else "running",
                "session_id": identifier, "pid": session["process"].pid,
                "stdout": stdout, "stderr": stderr, "exit_code": code if complete else None,
                "output_visibility": "confidential" if session["confidential_output"] else "public"}

    def execute_native_operation(self, operation, parameters):
        from jsonschema import Draft202012Validator
        contract = self.native_contract()
        if contract is None:
            return {"status": "failed", "error": "Shellzugriff ist deaktiviert."}
        if operation not in contract["operations"]:
            raise ValueError("Unknown shell operation")
        Draft202012Validator(contract["operations"][operation]["parameters_schema"]).validate(parameters)
        from .transient_credentials import contains_credentials, resolve_credentials, redact_transient
        confidential = contains_credentials(parameters)
        parameters = resolve_credentials(parameters)
        wait_seconds = parameters.get("wait_seconds", 1)
        with self.lock:
            if not self.config.get("enabled", False):
                return {"status": "failed", "error": "Shellzugriff ist deaktiviert."}
            source = parameters.get("command", parameters.get("text", ""))
            blocked = self._blocked(source)
            if blocked:
                return {"status": "blocked", "error": "Konfigurierter verbotener Befehl erkannt.", "matched_rule": blocked}
            if operation == "execute":
                cwd = Path(parameters.get("cwd") or self.root).expanduser()
                if not cwd.is_absolute():
                    cwd = self.root / cwd
                environment = dict(os.environ)
                environment.update(parameters.get("env", {}))
                try:
                    process = subprocess.Popen([self.config.get("executable", "/bin/bash"), "-c", parameters["command"]],
                        cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, start_new_session=True)
                except (OSError, ValueError) as exc:
                    return {"status": "failed", "error": redact_transient(str(exc))}
                identifier = uuid.uuid4().hex
                session = {"process": process, "stdout": [], "stderr": [], "lock": threading.RLock(),
                           "done": threading.Event(), "input_lock": threading.Lock(),
                           "confidential_output": confidential}
                process.args = redact_transient(process.args)
                session["readers"] = [threading.Thread(target=self._reader, args=(session, stream, key), daemon=True)
                                      for stream, key in [(process.stdout, "stdout"), (process.stderr, "stderr")]]
                self.sessions[identifier] = session
                for reader in session["readers"]:
                    reader.start()
                threading.Thread(target=self._reap, args=(session,), daemon=True).start()
            else:
                identifier = parameters["session_id"]
                session = self.sessions.get(identifier)
                if session is None:
                    return {"status": "failed", "error": "Unbekannte Shell-Sitzung."}
        # Never hold the configuration lock while waiting for a child or stdin.
        if operation == "write":
            with session["lock"]:
                if confidential:
                    session["confidential_output"] = True
                    session["stdout"].clear()
                    session["stderr"].clear()
            try:
                with session["input_lock"]:
                    session["process"].stdin.write(parameters["text"].encode("utf-8"))
                    session["process"].stdin.flush()
                    if parameters.get("close_stdin"):
                        session["process"].stdin.close()
            except (OSError, ValueError) as exc:
                return {"status": "failed", "session_id": identifier, "error": redact_transient(str(exc))}
        elif operation == "terminate":
            name = parameters.get("signal", "SIGTERM")
            signum = getattr(signal, name, None)
            if not isinstance(signum, signal.Signals):
                raise ValueError("Unknown Linux signal")
            if not session["done"].is_set():
                try:
                    os.killpg(session["process"].pid, signum)
                except ProcessLookupError:
                    pass
        return self._result(identifier, wait_seconds)

    def close_all(self):
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            if session["done"].is_set():
                continue
            try:
                os.killpg(session["process"].pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for session in sessions:
            if not session["done"].wait(1):
                try:
                    os.killpg(session["process"].pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            session["process"].wait()
            if not session["process"].stdin.closed:
                session["process"].stdin.close()
