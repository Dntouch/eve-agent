"""Structural result identities; no interpretation of task success or meaning."""
import hashlib
import json


def value_digest(value):
    raw = (b'bytes:' + value if isinstance(value, bytes) else
           b'json:' + json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode())
    return hashlib.sha256(raw).hexdigest()


def selected_evidence(result):
    """Selection content and actual selection errors, without receipt IDs."""
    return {key: result[key] for key in ('content', 'status', 'projection_complete', 'missing_fields', 'error_class')
            if key in result}


def provider_evidence(capability, operation, result):
    if not isinstance(result, dict):
        return result
    if capability == 'shell':
        return {key: value for key, value in result.items() if key not in {'session_id', 'pid'}}
    if capability == 'working_memory' and operation == 'read' and 'content' in result:
        return selected_evidence(result)
    return result.get('response') if isinstance(result.get('response'), dict) else result
