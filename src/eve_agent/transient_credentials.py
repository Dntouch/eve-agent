"""Per-turn credential references; raw values exist only in temporary execution state."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import shlex
from urllib.parse import quote, quote_plus
import uuid

_CURRENT = ContextVar('eve_transient_credentials', default=None)
_REFERENCE = re.compile(r'\{\{eve_secret:([a-f0-9]{32})(?:\|(url|shell|json))?\}\}')


def current_credentials():
    return _CURRENT.get()


class CredentialScope:
    def __init__(self, text):
        from .memory import _SECRET_NAMES, redact_sensitive
        self.values = {}
        self.labels = {}
        self.variants = []
        replacements = {}
        pattern = re.compile(rf'(?i)(\b({_SECRET_NAMES})\b\s*[:=]\s*)("[^"\r\n]*"|\'[^\'\r\n]*\'|[^\s\r\n]+)')
        def replace(match):
            value = match[3]
            if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
                value = value[1:-1]
            if not value or value == '[REDACTED]' or _REFERENCE.fullmatch(value):
                return match[0]
            identifier = uuid.uuid4().hex
            self.values[identifier] = value
            self.labels[identifier] = match[2]
            self.variants.extend({value, quote(value, safe=''), quote_plus(value, safe=''),
                                  json.dumps(value, ensure_ascii=False)[1:-1],
                                  json.dumps(value, ensure_ascii=True)[1:-1], shlex.quote(value)})
            marker = 'EVEOPAQUE' + uuid.uuid4().hex
            replacements[marker] = match[1] + '{{eve_secret:' + identifier + '}}'
            return marker
        substituted = pattern.sub(replace, text)
        self.variants = sorted(set(self.variants), key=len, reverse=True)
        if replacements:
            chunks = re.split('(' + '|'.join(map(re.escape, replacements)) + ')', substituted)
            self.model_text = ''.join(replacements[chunk] if chunk in replacements
                                      else redact_sensitive(self.redact(chunk)) for chunk in chunks)
        else:
            self.model_text = redact_sensitive(substituted)

    def contract(self):
        if not self.values:
            return ''
        return ('\nTemporary credentials: use the opaque references from the current message in external tool arguments; '
                'they resolve only during execution and expire at turn end. '
                'For shell use env and quoted variable expansion; |url, |shell and |json encode transport values. '
                'Use credentials solely for authentication or the requested transfer: never print, inspect, split, '
                'transform for diagnostics, or save them to files, logs, Memory or tasks. '
                'Shell output from credential-bearing processes is confidential; verify the task outcome '
                'with a separate credential-free status query. Do not ask again for available credentials.')

    def resolve(self, value):
        if isinstance(value, str):
            def replace(match):
                secret = self.values.get(match[1])
                if secret is None:
                    raise ValueError('Die Zugangsdaten-Referenz ist abgelaufen oder gehört zu einem anderen Auftrag.')
                return {'url': lambda: quote(secret, safe=''), 'shell': lambda: shlex.quote(secret),
                        'json': lambda: json.dumps(secret, ensure_ascii=False)}.get(match[2], lambda: secret)()
            return _REFERENCE.sub(replace, value)
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return value

    def redact(self, value):
        if isinstance(value, str):
            def scrub(text):
                for secret in self.variants:
                    text = text.replace(secret, '[REDACTED]')
                return text
            parts, offset = [], 0
            for reference in _REFERENCE.finditer(value):
                parts.extend([scrub(value[offset:reference.start()]), reference[0]])
                offset = reference.end()
            parts.append(scrub(value[offset:]))
            return ''.join(parts)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    def sanitize_exception(self, error):
        seen = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            error.args = tuple(self.redact(item) for item in error.args)
            error = error.__cause__ or error.__context__

    def clear(self):
        self.values.clear()
        self.labels.clear()
        self.variants.clear()
        self.model_text = ''


@contextmanager
def credential_scope(text):
    scope = CredentialScope(text or '')
    token = _CURRENT.set(scope)
    try:
        yield scope
    except BaseException as exc:
        scope.sanitize_exception(exc)
        raise
    finally:
        _CURRENT.reset(token)
        scope.clear()


def redact_transient(value):
    scope = current_credentials()
    return scope.redact(value) if scope else value


def contains_credentials(value):
    """Whether tool input explicitly carries an opaque credential reference."""
    if isinstance(value, str):
        return bool(_REFERENCE.search(value))
    if isinstance(value, dict):
        return any(contains_credentials(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_credentials(item) for item in value)
    return False


def resolve_credentials(value):
    scope = current_credentials()
    if scope is None:
        if _REFERENCE.search(json.dumps(value, default=str)):
            raise ValueError('Die Zugangsdaten-Referenz ist abgelaufen.')
        return value
    return scope.resolve(value)

