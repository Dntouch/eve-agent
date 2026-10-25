"""Configurable external MCP servers; native contracts, no domain interpretation."""
import atexit
import base64
from copy import deepcopy
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import threading

from jsonschema import Draft202012Validator

from .mcp_stdio import McpStdioClient
from .transport_access import capability_allowed, require_capability, transport_metadata, report_transport_activity


PREFIX = 'mcp_'
RESERVED = {'eve_attach_file', 'eve_read_resource', 'eve_list_resources'}


def validate_servers(servers):
    if not isinstance(servers, dict):
        raise ValueError('mcp.servers muss ein JSON-Objekt sein')
    for name, cfg in servers.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', name) or not isinstance(cfg, dict):
            raise ValueError('MCP-Servernamen: Kleinbuchstaben, Ziffern und Unterstriche, maximal 40 Zeichen')
        allowed = {'chatto_reply_mode', 'title', 'enabled', 'command', 'args', 'cwd', 'env', 'scope', 'timeout_seconds', 'protocol_version', 'description', 'attachment_roots', 'startup', 'after_write'}
        if set(cfg) - allowed:
            raise ValueError(f'Unbekannte MCP-Option für {name}: {sorted(set(cfg) - allowed)[0]}')
        if type(cfg.get('enabled', True)) is not bool:
            raise ValueError(f'{name}.enabled muss boolesch sein')
        for key in ('command',):
            if not isinstance(cfg.get(key), str) or not cfg[key].strip() or '\x00' in cfg[key]:
                raise ValueError(f'{name}.{key} muss ein Programmname oder Pfad sein')
        for key in ('args', 'attachment_roots'):
            if not isinstance(cfg.get(key, []), list) or any(not isinstance(v, str) or '\x00' in v for v in cfg.get(key, [])):
                raise ValueError(f'{name}.{key} muss eine Zeichenkettenliste sein')
        for key in ('title', 'cwd', 'description', 'protocol_version'):
            if key in cfg and (not isinstance(cfg[key], str) or '\x00' in cfg[key]):
                raise ValueError(f'{name}.{key} muss eine Zeichenkette sein')
        if not isinstance(cfg.get('chatto_reply_mode', 'inherit'), str) or cfg.get('chatto_reply_mode', 'inherit') not in {'inherit', 'thread'}:
            raise ValueError(f'{name}.chatto_reply_mode muss inherit oder thread sein')
        if not isinstance(cfg.get('scope', 'conversation'), str) or cfg.get('scope', 'conversation') not in {'conversation', 'shared'}:
            raise ValueError(f'{name}.scope muss conversation oder shared sein')
        timeout = cfg.get('timeout_seconds', 330)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 3600:
            raise ValueError(f'{name}.timeout_seconds muss zwischen 1 und 3600 liegen')
        for phase in ('startup', 'after_write'):
            calls = cfg.get(phase, [])
            if not isinstance(calls, list):
                raise ValueError(f'{name}.{phase} muss eine Liste sein')
            for call in calls:
                if (not isinstance(call, dict) or set(call) - {'tool', 'arguments', 'if_exists'}
                    or not isinstance(call.get('tool'), str) or not call['tool']
                    or not isinstance(call.get('arguments', {}), dict)
                    or ('if_exists' in call and not isinstance(call['if_exists'], str))):
                    raise ValueError(f'{name}.{phase}: tool, arguments und optional if_exists erforderlich')
        env = cfg.get('env', {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) or '\x00' in k + v or '=' in k for k, v in env.items()):
            raise ValueError(f'{name}.env muss Umgebungsvariablen auf Zeichenketten abbilden')


class ExternalMcpServers:
    def __init__(self, config, root):
        self.root = Path(root).resolve()
        self.config = deepcopy(config.get('servers', {}))
        validate_servers(self.config)
        self.max_sessions = config.get('max_sessions', 8)
        self.sessions = {}
        self.lock = threading.RLock()
        atexit.register(self.close_all)

    def _session(self, name, conversation_id):
        cfg = self.config[name]
        context = transport_metadata() or {}
        identifier = 'shared' if cfg.get('scope', 'conversation') == 'shared' else context.get('mcp_session_id', conversation_id)
        if not identifier:
            raise ValueError('MCP conversation scope requires a conversation ID')
        key = (name, identifier)
        if key not in self.sessions:
            if len(self.sessions) >= self.max_sessions:
                raise RuntimeError('MCP session limit reached; save work and restart EVE or raise mcp.max_sessions')
            digest = hashlib.sha256(identifier.encode()).hexdigest()[:32]
            workspace = self.root / 'data' / 'mcp' / name / digest
            workspace.mkdir(parents=True, exist_ok=True)
            def expand(value):
                return value.replace('{root}', str(self.root)).replace('{workspace}', str(workspace))
            env = dict(os.environ)
            env.update({k: expand(v) for k, v in cfg.get('env', {}).items()})
            cwd = Path(expand(cfg.get('cwd') or '{workspace}'))
            if not cwd.is_absolute():
                cwd = self.root / cwd
            client = McpStdioClient([expand(cfg['command']), *map(expand, cfg.get('args', []))],
                env=env, cwd=str(cwd), protocol_version=cfg.get('protocol_version', '2025-06-18'))
            roots = [workspace, *(Path(expand(v)).expanduser() for v in cfg.get('attachment_roots', []))]
            roots = [(p if p.is_absolute() else self.root / p).resolve() for p in roots]
            self.sessions[key] = {'client': client, 'workspace': workspace, 'roots': roots, 'tools': {},
                                  'uncertain': False, 'startup_attempted': False, 'startup_error': None}
        return self.sessions[key]

    def _request(self, name, session, method, params):
        client = session['client']
        client.start()
        return client.result(client.request(method, params, timeout=self.config[name].get('timeout_seconds', 330)))

    def _discover(self, name, session):
        tools, params = {}, {}
        while True:
            page = self._request(name, session, 'tools/list', params)
            for tool in page['tools']:
                if tool['name'] in RESERVED:
                    raise ValueError('MCP server uses a reserved EVE operation name')
                Draft202012Validator.check_schema(tool['inputSchema'])
                tools[tool['name']] = tool
            if not page.get('nextCursor'):
                break
            params = {'cursor': page['nextCursor']}
        session['tools'] = tools
        operations = {key: {'description': tool.get('description', ''),
            'effect': 'read' if tool.get('annotations', {}).get('readOnlyHint') else 'write',
            'parameters_schema': deepcopy(tool['inputSchema']), 'runtime_tool': deepcopy(tool)}
            for key, tool in tools.items()}
        operations['eve_attach_file'] = {'description': 'Attach an existing file to this answer. Only the session workspace and configured attachment_roots are readable. Maximum 20 MiB.',
            'effect': 'read', 'parameters_schema': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path'], 'additionalProperties': False}}
        if 'resources' in session['client'].server.get('capabilities', {}):
            operations['eve_list_resources'] = {'description': 'List native MCP resources.', 'effect': 'read',
                'parameters_schema': {'type': 'object', 'properties': {'cursor': {'type': 'string'}}, 'additionalProperties': False}}
            operations['eve_read_resource'] = {'description': 'Read a native MCP resource URI.', 'effect': 'read',
                'parameters_schema': {'type': 'object', 'properties': {'uri': {'type': 'string'}}, 'required': ['uri'], 'additionalProperties': False}}
        if session['startup_error']:
            raise RuntimeError(session['startup_error'])
        if not session['startup_attempted']:
            session['startup_attempted'] = True
            try:
                self._lifecycle(name, session, 'startup')
            except Exception as exc:
                session['uncertain'] = True
                session['startup_error'] = 'MCP startup failed; no automatic retry: ' + str(exc)
                raise RuntimeError(session['startup_error']) from exc
        return operations

    def _lifecycle(self, name, session, phase):
        def expand(value):
            if isinstance(value, str):
                return value.replace('{root}', str(self.root)).replace('{workspace}', str(session['workspace']))
            if isinstance(value, dict):
                return {k: expand(v) for k, v in value.items()}
            if isinstance(value, list):
                return list(map(expand, value))
            return value
        for call in self.config[name].get(phase, []):
            condition = call.get('if_exists')
            if condition:
                path = Path(expand(condition)).expanduser()
                if not (path if path.is_absolute() else session['workspace'] / path).exists():
                    continue
            tool, arguments = call['tool'], expand(call.get('arguments', {}))
            if tool not in session['tools']:
                raise ValueError('Unknown configured lifecycle tool: ' + tool)
            Draft202012Validator(session['tools'][tool]['inputSchema']).validate(arguments)
            result = self._request(name, session, 'tools/call', {'name': tool, 'arguments': arguments})
            if result.get('isError'):
                raise RuntimeError('Lifecycle tool failed: ' + tool)

    def contracts(self, conversation_id):
        contracts = {}
        with self.lock:
            for name, cfg in self.config.items():
                capability = PREFIX + name
                if not cfg.get('enabled', True) or not capability_allowed(capability):
                    continue
                try:
                    session = self._session(name, conversation_id)
                    operations = self._discover(name, session)
                    contracts[capability] = {'description': cfg.get('description') or name,
                        'operations': operations,
                        'runtime': {'transport': 'mcp-stdio', 'server': deepcopy(session['client'].server),
                            'scope': cfg.get('scope', 'conversation'), 'workspace': str(session['workspace']),
                            'attachment_roots': list(map(str, session['roots'])),
                            'execution_outcome_unknown': session['uncertain']}}
                except Exception as exc:
                    contracts[capability] = {'description': cfg.get('description') or name, 'operations': {},
                                             'error': str(exc), 'runtime': {'transport': 'mcp-stdio', 'error': str(exc)}}
        return contracts

    def select(self, capability):
        require_capability(capability)
        name = capability.removeprefix(PREFIX)
        cfg = self.config.get(name)
        if cfg and cfg.get('enabled', True):
            report_transport_activity({'integration': cfg.get('title') or name,
                                       'reply_mode': cfg.get('chatto_reply_mode', 'inherit')})

    def execute(self, capability, operation, arguments, conversation_id):
        require_capability(capability)
        self.select(capability)
        name = capability.removeprefix(PREFIX)
        with self.lock:
            if name not in self.config or not self.config[name].get('enabled', True):
                raise ValueError('Unknown or disabled MCP server')
            session = self._session(name, conversation_id)
            operations = self._discover(name, session)
            if operation not in operations:
                raise ValueError('Unknown MCP operation')
            Draft202012Validator(operations[operation]['parameters_schema']).validate(arguments)
            if operation == 'eve_attach_file':
                path = Path(arguments['path']).expanduser()
                path = (path if path.is_absolute() else session['workspace'] / path).resolve()
                if not any(path.is_relative_to(root) for root in session['roots']):
                    raise PermissionError('File outside configured MCP attachment roots')
                with path.open('rb') as stream:
                    data = stream.read(20 * 1024 * 1024 + 1)
                if not data or len(data) > 20 * 1024 * 1024:
                    raise ValueError('Attachment must contain 1 byte to 20 MiB')
                mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                content = f'data:{mime};base64,' + base64.b64encode(data).decode()
                return {'status': 'completed', 'resources': [{'type': 'file', 'source': capability,
                    'filename': path.name, 'media_type': mime, 'content': content}]}
            method = {'eve_read_resource': 'resources/read', 'eve_list_resources': 'resources/list'}.get(operation, 'tools/call')
            if session['uncertain'] and method == 'tools/call' and operations[operation]['effect'] != 'read':
                raise RuntimeError('Previous MCP execution outcome unknown; inspect server state and restart EVE before further changes. No automatic retry.')
            params = arguments if method != 'tools/call' else {'name': operation, 'arguments': arguments}
            try:
                result = self._request(name, session, method, params)
            except (RuntimeError, OSError):
                if method == 'tools/call':
                    session['uncertain'] = True
                raise
            checkpoint_error = None
            if method == 'tools/call' and operations[operation]['effect'] != 'read':
                try:
                    self._lifecycle(name, session, 'after_write')
                except Exception as exc:
                    session['uncertain'] = True
                    checkpoint_error = str(exc)
            resources = []
            if not result.get('isError'):
                for block in result.get('content', []):
                    if block.get('type') == 'image':
                        resources.append({'type': 'image', 'source': capability, 'media_type': block['mimeType'],
                            'content': f"data:{block['mimeType']};base64,{block['data']}"})
            return {'status': 'failed' if result.get('isError') else 'completed', 'result': result, 'resources': resources,
                    **({'checkpoint_error': checkpoint_error, 'do_not_retry_operation': True} if checkpoint_error else {})}

    def close_all(self):
        with self.lock:
            for session in self.sessions.values():
                session['client'].close()
            self.sessions.clear()
