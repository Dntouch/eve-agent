"""Exact, conversation-scoped access to current and persisted attachments."""
from __future__ import annotations

import base64
import hashlib
import os


class ConversationAssets:
    def __init__(self, conversations, conversation_id, images=()):
        self.conversations = conversations
        self.conversation_id = conversation_id
        self.images = tuple(images)

    @staticmethod
    def contract(*, materialize=True):
        def operation(description, properties=None, required=(), effect='read'):
            return {'description': description, 'effect': effect, 'parameters_schema': {
                'type': 'object', 'additionalProperties': False,
                'properties': properties or {}, 'required': list(required)}}
        identifier = {'asset_id': {'type': 'string', 'minLength': 1}}
        operations = {
            'list': operation('List current input and saved attachments in this conversation. IDs identify exact originals; no filesystem search.',
                              {'offset': {'type': 'integer', 'minimum': 0},
                               'limit': {'type': 'integer', 'minimum': 1}}),
            'read': operation('Return the selected original image as model-visible media.', identifier, ['asset_id']),
        }
        if materialize:
            operations['materialize'] = operation(
                'Write the selected original attachment to a local file for shell processing; returns its exact path, media type and SHA-256.',
                identifier, ['asset_id'], 'write')
        return {'description': 'Exact original images and attachments from this conversation and current input; view them or obtain a local file for shell tools.',
                'operations': operations}

    def _current(self, index):
        try:
            header, data = self.images[index].split(',', 1)
            if not header.startswith('data:') or not header.endswith(';base64'):
                raise ValueError('Unsupported image representation')
            return header[5:-7], base64.b64decode(data, validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError('Current input image was not found') from exc

    def list(self, offset=0, limit=None):
        items = []
        for index in range(len(self.images)):
            media, body = self._current(index)
            items.append({'asset_id': f'input:{index}', 'source': 'current_input',
                          'media_type': media, 'byte_size': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        with self.conversations.database.connect(lifecycle_audit=False) as c:
            rows = c.execute(
                """SELECT a.id AS asset_id,a.message_id,a.media_type,a.byte_size,a.sha256,a.created_at,m.role
                   FROM conversation_assets a JOIN messages m ON m.id=a.message_id
                   JOIN conversations c ON c.id=a.conversation_id
                   WHERE a.conversation_id=? AND c.status!='deleted' ORDER BY m.ordinal,a.ordinal""",
                (self.conversation_id,)).fetchall()
        items.extend({**dict(row), 'source': 'conversation'} for row in rows)
        selected = items[offset:] if limit is None else items[offset:offset + limit]
        from .working_memory import WorkingMemoryStore
        return {'items': selected, **WorkingMemoryStore._page(len(items), offset, len(selected))}

    def _read(self, identifier):
        if identifier.startswith('input:'):
            index = identifier.removeprefix('input:')
            if not index.isdecimal():
                raise ValueError('Invalid current input image ID')
            return self._current(int(index))
        identifier = identifier.removeprefix('asset:')
        with self.conversations.database.connect(lifecycle_audit=False) as c:
            row = c.execute('SELECT 1 FROM conversation_assets WHERE id=? AND conversation_id=?',
                            (identifier, self.conversation_id)).fetchone()
        if row is None:
            raise KeyError('Attachment does not belong to this conversation')
        return self.conversations.read_asset(identifier)

    def execute(self, operation, parameters):
        if operation == 'list':
            return self.list(**parameters)
        media, body = self._read(parameters['asset_id'])
        digest = hashlib.sha256(body).hexdigest()
        result = {'asset_id': parameters['asset_id'], 'media_type': media,
                  'byte_size': len(body), 'sha256': digest, 'status': 'completed'}
        if operation == 'read':
            if not media.startswith('image/'):
                raise ValueError('Selected attachment is not an image')
            return {**result, 'resources': [{'type': 'image',
                    'content': f'data:{media};base64,' + base64.b64encode(body).decode()}]}
        if operation != 'materialize':
            raise ValueError('Unknown attachment operation')
        from .transport_access import require_capability
        require_capability('shell')
        # A separate copy leaves the conversation original intact. No model path
        # is accepted, and file identity follows the selected original bytes.
        import tempfile
        directory = self.conversations.database.path.parent / 'materialized-assets'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(media, '.bin')
        path = directory / (digest + suffix)
        descriptor, temporary = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(descriptor, 'wb') as target:
                target.write(body)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {**result, 'path': str(path.resolve())}
