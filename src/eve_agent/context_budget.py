"""Transport-only context accounting; no relevance rules or content summaries."""
from __future__ import annotations

import json


def anthropic_count_request(messages, tools, model, reasoning_effort=None, enable_thinking=None):
    """Represent the same chat frames for the standard Messages token-count API."""
    result = {'model': model, 'messages': [], 'tools': []}
    for message in messages:
        role = message['role']
        content = message.get('content')
        if role in {'system', 'developer'}:
            if 'system' in result:
                # Keep separate/late system frames intact on servers supporting them.
                result['messages'].append({'role': 'system', 'content': content or ''})
            else:
                result['system'] = content or ''
            continue
        if role == 'tool':
            result['messages'].append({'role': 'user', 'content': [{'type': 'tool_result',
                'tool_use_id': message.get('tool_call_id', ''), 'content': content or ''}]})
            continue
        parts = []
        if isinstance(content, str):
            if content:
                parts.append({'type': 'text', 'text': content})
        elif isinstance(content, list):
            for part in content:
                if part.get('type') == 'text':
                    parts.append(part)
                elif part.get('type') == 'image_url':
                    url = part['image_url']['url']
                    if url.startswith('data:'):
                        header, data = url.split(',', 1)
                        parts.append({'type': 'image', 'source': {'type': 'base64',
                            'media_type': header[5:].split(';')[0], 'data': data}})
                    else:
                        parts.append({'type': 'image', 'source': {'type': 'url', 'url': url}})
                else:
                    raise ValueError('Unsupported content block for token accounting')
        if message.get('reasoning_content'):
            parts.append({'type': 'thinking', 'thinking': message['reasoning_content']})
        for call in message.get('tool_calls') or []:
            function = call['function']
            arguments = function.get('arguments') or '{}'
            parts.append({'type': 'tool_use', 'id': call['id'], 'name': function['name'],
                          'input': json.loads(arguments) if isinstance(arguments, str) else arguments})
        result['messages'].append({'role': role, 'content': parts if parts else content or ''})
    for tool in tools or []:
        function = tool.get('function', tool)
        result['tools'].append({'name': function['name'], 'description': function.get('description', ''),
                                'input_schema': function.get('parameters', {})})
    if enable_thinking is False or reasoning_effort == 'none':
        result['thinking'] = {'type': 'disabled'}
    elif reasoning_effort:
        result['output_config'] = {'effort': reasoning_effort}
    return result


class WorkingContextBudgetError(RuntimeError):
    provider_code = 'working_context_limit'

    def __init__(self, workspace_id, detail):
        self.workspace_id = workspace_id
        super().__init__('Der aktive Modellkontext kann nicht weiter verkleinert werden. '
                         'Der Arbeitsstand und die Originaldaten bleiben in der Datenbank erhalten. ' + detail)
