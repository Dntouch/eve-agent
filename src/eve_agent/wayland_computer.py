"""Native Wayland MCP desktop capability."""
import base64
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import threading

from jsonschema import Draft202012Validator
from .mcp_stdio import McpStdioClient


class WaylandComputerCapability:
    capability_name = 'wayland_computer'

    def __init__(self, config, root):
        self.root = Path(root).resolve()
        python = Path(config.get('python') or self.root / '.venv-wayland-mcp/bin/python')
        work = self.root / 'runtime/wayland-mcp'
        work.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({str(k): str(v) for k,v in config.get('env', {}).items()})
        # Backend selection is explicit configuration, never a semantic fallback.
        env.setdefault('WAYLAND_MCP_CAPTURE_BACKEND', 'portal')
        env.setdefault('WAYLAND_MCP_INPUT_BACKEND', 'portal')
        env.setdefault('WAYLAND_MCP_LOG', str(work / 'server.log'))
        env.setdefault('WAYLAND_MCP_RESTORE_TOKEN_PATH', str(work / 'portal-token'))
        self.client = McpStdioClient([str(python), '-m', 'wayland_mcp.server_mcp'], env=env, cwd=str(work))
        self.lock = threading.RLock()
        self.tools = {}
        self.patch_identity = None
        manifest_path = self.root / 'docs/WAYLAND-MCP-KEYBOARD-PATCH.json'
        if python.absolute() == (self.root / '.venv-wayland-mcp/bin/python') and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            target = Path(manifest['target'])
            helper = target.with_name('portal_keymap.py')
            try:
                verified = (hashlib.sha256(target.read_bytes()).hexdigest() == manifest['patched_sha256']
                    and hashlib.sha256(helper.read_bytes()).hexdigest() == manifest['helper_sha256'])
            except OSError:
                verified = False
            self.patch_identity = {'variant': manifest['variant'], 'source_hashes_verified': verified}

    def native_contract(self):
        with self.lock:
            try:
                self.client.start()
                # Refresh discovery: never cache over an upstream tool change.
                tools, params = {}, {}
                while True:
                    page = self.client.result(self.client.request('tools/list', params, timeout=30))
                    tools.update({tool['name']: tool for tool in page['tools']})
                    if not page.get('nextCursor'):
                        break
                    params = {'cursor': page['nextCursor']}
                self.tools = tools
                return {'description': 'Independent native Wayland MCP desktop capability. '
                    'KDE portal permission is required. '
                    'Keyboard text must be representable in the current compositor keymap; '
                    'otherwise the patched runtime returns an error before sending the text. '
                    'Upstream screenshot images can include measurement rulers around the desktop.',
                    'runtime': {'implementation': 'wayland-mcp-kurojs',
                                'local_patch': deepcopy(self.patch_identity),
                                'server': deepcopy(self.client.server.get('serverInfo', {}))},
                    'operations': {name: {'description': tool.get('description', ''),
                        'effect': 'read' if (tool.get('annotations') or {}).get('readOnlyHint') else 'write',
                        'parameters_schema': deepcopy(tool['inputSchema']),
                        **({'returns_schema': deepcopy(tool['outputSchema'])} if 'outputSchema' in tool else {}),
                        'runtime_tool': deepcopy(tool)} for name,tool in tools.items()}}
            except Exception as exc:
                return {'operations': {}, 'error': str(exc), 'stderr': list(self.client.stderr)}

    def execute_native_operation(self, operation, arguments, *, context=None):
        with self.lock:
            contract = self.native_contract()
            if contract.get('error'):
                return {'status': 'failed', 'error': contract['error'], 'stderr': contract['stderr']}
            if operation not in self.tools:
                raise ValueError('Unknown Wayland MCP operation')
            Draft202012Validator(self.tools[operation]['inputSchema']).validate(arguments)
            try:
                response = self.client.request('tools/call', {'name': operation, 'arguments': arguments})
                evidence = self.client.drain()
                if 'error' in response:
                    return {'status': 'failed', 'error': response['error'], **evidence}
                native = response['result']
                structured = native.get('structuredContent')
                if structured is None:
                    for block in reversed(native.get('content', [])):
                        if block.get('type') == 'text':
                            try:
                                candidate = json.loads(block['text'])
                                if isinstance(candidate, dict):
                                    structured = candidate
                                    break
                            except ValueError:
                                pass
                failed = native.get('isError') or (isinstance(structured, dict) and structured.get('success') is False)
                resources = []
                for block in native.get('content', []):
                    if block.get('type') == 'image':
                        resources.append({'type': 'image', 'source': 'wayland_computer',
                            'media_type': block['mimeType'],
                            'content': f"data:{block['mimeType']};base64,{block['data']}"})
                if not failed and isinstance(structured, dict) and isinstance(structured.get('filename'), str):
                    # Attach the actual image returned by the backend; no made-up
                    # observation or second screenshot driver is involved.
                    path = Path(structured['filename'])
                    try:
                        data = path.read_bytes()
                        if data.startswith(b'\x89PNG\r\n\x1a\n'):
                            resources.append({'type': 'image', 'source': 'wayland_computer',
                                'media_type': 'image/png', 'name': path.name,
                                'content': 'data:image/png;base64,' + base64.b64encode(data).decode()})
                    except OSError as exc:
                        evidence['resource_error'] = str(exc)
                return {'status': 'failed' if failed else 'completed', 'result': native,
                        'resources': resources, **evidence}
            except (OSError, RuntimeError) as exc:
                return {'status': 'unknown', 'error': str(exc), **self.client.drain()}

    def close_all(self):
        with self.lock:
            self.client.close()
