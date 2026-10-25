"""Small persistent stdio MCP transport; no execution policy or tool routing."""
import json
import subprocess
import threading


class McpStdioClient:
    def __init__(self, command, *, env, cwd, protocol_version="2024-11-05"):
        self.protocol_version = protocol_version
        self.command, self.env, self.cwd = command, env, cwd
        self.process = None
        self._condition = threading.Condition()
        self._send_lock = threading.Lock()
        self._responses, self.events, self.stderr = {}, [], []
        self._counter = 0
        self.disconnected = False
        self.initialized = False
        self.server = {}

    def send(self, message):
        with self._send_lock:
            self.process.stdin.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')
            self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                with self._condition:
                    if 'id' in message and 'method' not in message:
                        self._responses[message['id']] = message
                    else:
                        self.events.append(message)
                        if 'id' in message:
                            self.send({'id': message['id'], 'error': {
                                'code': -32601, 'message': 'MCP client capability unavailable'}})
                    self._condition.notify_all()
        except Exception as exc:
            self.stderr.append(f'MCP reader error: {exc}')
        finally:
            with self._condition:
                self.disconnected = True
                self._condition.notify_all()

    def _read_stderr(self):
        for line in self.process.stderr:
            with self._condition:
                self.stderr.append(line.rstrip())

    def request(self, method, params, *, timeout=None):
        # Providers serialize requests, including the identifier allocation.
        self._counter += 1
        identifier = self._counter
        self.send({'id': identifier, 'method': method, 'params': params})
        with self._condition:
            ready = self._condition.wait_for(
                lambda: identifier in self._responses or self.disconnected, timeout=timeout)
            if not ready or identifier not in self._responses:
                raise RuntimeError('MCP transport unavailable; execution outcome unknown; no automatic retry')
            return self._responses.pop(identifier)

    @staticmethod
    def result(response):
        if 'error' in response:
            raise RuntimeError('MCP RPC error: ' + json.dumps(response['error']))
        return response['result']

    def start(self):
        if self.process is not None:
            if self.disconnected or not self.initialized:
                raise RuntimeError('MCP connection is unavailable; close before restarting')
            return
        self.process = subprocess.Popen(self.command, cwd=self.cwd, env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', bufsize=1)
        self.threads = [threading.Thread(target=reader, daemon=True)
                        for reader in (self._read, self._read_stderr)]
        for thread in self.threads:
            thread.start()
        self.server = self.result(self.request('initialize', {
            'protocolVersion': self.protocol_version, 'capabilities': {},
            'clientInfo': {'name': 'eve-native-mcp', 'version': '1'}}, timeout=30))
        self.send({'method': 'notifications/initialized'})
        self.initialized = True

    def drain(self):
        with self._condition:
            events, stderr = self.events, self.stderr
            self.events, self.stderr = [], []
            return {'notifications': events, 'stderr': stderr}

    def close(self):
        if self.process is None:
            return
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for thread in self.threads:
            thread.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()
        self.process = None
        self.initialized = self.disconnected = False
        self._responses.clear()
