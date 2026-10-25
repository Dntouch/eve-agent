"""Database-backed working material. Selection and interpretation belong to the model.

Original JSON lives in Memory V2 observations; binary originals live in SQLite
BLOBs. Workspace rows only add identity, lifecycle and execution bookkeeping.
Nothing here writes a file, promotes a claim, or infers a task from words.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import threading

from .search import fts_query


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return str(uuid.uuid4())


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS memory_workspaces (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','completed','archived')), checkpoint_id TEXT REFERENCES memory_work_objects(id),
        revision INTEGER NOT NULL DEFAULT 0,
        retention_class TEXT NOT NULL DEFAULT 'standard'
        CHECK(retention_class IN ('standard','temporary_learning')),
        pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_accessed_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memory_work_bindings (
        conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
        workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id))""",
    """CREATE TABLE IF NOT EXISTS memory_work_objects (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        observation_id TEXT NOT NULL UNIQUE REFERENCES memory_observations(id),
        kind TEXT NOT NULL, title TEXT NOT NULL, media_type TEXT NOT NULL,
        content BLOB, sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL,
        created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS memory_work_objects_workspace ON memory_work_objects(workspace_id,created_at,id)",
    """CREATE VIRTUAL TABLE IF NOT EXISTS memory_work_fts USING fts5(
        object_id UNINDEXED, workspace_id UNINDEXED, title, content)""",
    """CREATE TABLE IF NOT EXISTS memory_work_turns (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
        request_id TEXT REFERENCES memory_work_objects(id),
        status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
        answer_id TEXT REFERENCES memory_work_objects(id), error_id TEXT REFERENCES memory_work_objects(id),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memory_work_calls (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        turn_id TEXT NOT NULL REFERENCES memory_work_turns(id),
        call_id TEXT NOT NULL, capability TEXT NOT NULL, operation TEXT NOT NULL,
        effect TEXT NOT NULL, request_id TEXT NOT NULL REFERENCES memory_work_objects(id),
        result_id TEXT REFERENCES memory_work_objects(id),
        status TEXT NOT NULL CHECK(status IN ('prepared','started','returned','cancelled')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(turn_id,call_id))""",
    """CREATE TABLE IF NOT EXISTS memory_work_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        turn_id TEXT REFERENCES memory_work_turns(id), kind TEXT NOT NULL,
        object_id TEXT REFERENCES memory_work_objects(id), created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS memory_work_events_workspace ON memory_work_events(workspace_id,sequence)",
    "CREATE INDEX IF NOT EXISTS memory_work_events_turn ON memory_work_events(turn_id)",
    """CREATE TABLE IF NOT EXISTS memory_work_links (
        from_id TEXT NOT NULL REFERENCES memory_work_objects(id),
        to_id TEXT NOT NULL REFERENCES memory_work_objects(id),
        relation TEXT NOT NULL, PRIMARY KEY(from_id,to_id,relation))""",
    """CREATE TABLE IF NOT EXISTS memory_work_call_reviews (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        call_id TEXT NOT NULL REFERENCES memory_work_calls(id),
        decision_id TEXT NOT NULL REFERENCES memory_work_objects(id), created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memory_work_contexts (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES memory_workspaces(id),
        turn_id TEXT NOT NULL REFERENCES memory_work_turns(id),
        reason TEXT NOT NULL, request_id TEXT NOT NULL REFERENCES memory_work_objects(id),
        input_tokens INTEGER, context_tokens INTEGER, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memory_work_cleanup_runs (
        id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
        dry_run INTEGER NOT NULL CHECK(dry_run IN (0,1)),
        scanned_workspaces INTEGER NOT NULL, eligible_workspaces INTEGER NOT NULL,
        deleted_workspaces INTEGER NOT NULL, deleted_objects INTEGER NOT NULL,
        deleted_bytes INTEGER NOT NULL, retained_observations INTEGER NOT NULL,
        details_json TEXT NOT NULL CHECK(json_valid(details_json)))""",
)


class UncertainCallError(RuntimeError):
    def __init__(self, reference):
        self.call_reference = reference
        super().__init__('Ein identischer früherer Aufruf mit möglicher Außenwirkung hat keinen gesicherten Ausgang. '
                         'Ergebnis prüfen und eine ausdrückliche Wiederholungsentscheidung mit Quellen über '
                         'working_memory.review_call festhalten. Aufrufreferenz: ' + reference)


class WorkingSelectionError(ValueError):
    """Machine-readable structural information; never guess the desired field."""
    def __init__(self, message, structure):
        self.structure = structure
        super().__init__(message)


class WorkingMemoryStore:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _event(c, workspace_id, kind, object_id=None, turn_id=None):
        c.execute('INSERT INTO memory_work_events(workspace_id,turn_id,kind,object_id,created_at) VALUES (?,?,?,?,?)',
                  (workspace_id, turn_id, kind, object_id, _now()))

    @staticmethod
    def _touch(c, workspace_id, now=None):
        now = now or _now()
        c.execute('UPDATE memory_workspaces SET updated_at=?,last_accessed_at=? WHERE id=?',
                  (now, now, workspace_id))

    def create(self, *, title=None, retention_class='standard'):
        if retention_class not in {'standard', 'temporary_learning'}:
            raise ValueError('Ungültige Aufbewahrungsklasse')
        workspace_id, now = _id(), _now()
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('INSERT INTO memory_workspaces '
                      '(id,title,retention_class,created_at,updated_at,last_accessed_at) '
                      'VALUES (?,?,?,?,?,?)',
                      (workspace_id, title or 'Arbeitsstand', retention_class, now, now, now))
        return workspace_id

    def open(self, conversation_id, *, workspace_id=None, title=None):
        """Bind an explicitly selected workspace, or retain this conversation's binding."""
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            if workspace_id is None:
                row = c.execute('SELECT workspace_id FROM memory_work_bindings WHERE conversation_id=?',
                                (conversation_id,)).fetchone()
                workspace_id = row[0] if row else None
            if workspace_id is None:
                workspace_id = _id(); now = _now()
                c.execute('INSERT INTO memory_workspaces '
                          '(id,title,created_at,updated_at,last_accessed_at) VALUES (?,?,?,?,?)',
                          (workspace_id, title or 'Arbeitsstand', now, now, now))
            if not c.execute('SELECT 1 FROM memory_workspaces WHERE id=?', (workspace_id,)).fetchone():
                raise KeyError('Arbeitsstand wurde nicht gefunden')
            self._touch(c, workspace_id)
            c.execute('INSERT INTO memory_work_bindings(conversation_id,workspace_id) VALUES (?,?) '
                      'ON CONFLICT(conversation_id) DO UPDATE SET workspace_id=excluded.workspace_id',
                      (conversation_id, workspace_id))
        return workspace_id

    def put(self, workspace_id, value, *, kind='material', title='', source='assistant',
            turn_id=None, media_type=None, references=(), _connection=None):
        binary = isinstance(value, (bytes, bytearray))
        raw = bytes(value) if binary else _json(value).encode('utf-8')
        identifier, observation, now = _id(), _id(), _now()
        media_type = media_type or ('application/octet-stream' if binary else 'application/json')
        with (nullcontext(_connection) if _connection is not None else self.database.connect(lifecycle_audit=False)) as c:
            canonical_references = []
            for reference in references:
                row = c.execute('SELECT id FROM memory_work_objects WHERE (id=? OR observation_id=?) AND workspace_id=?',
                                (reference, reference, workspace_id)).fetchone()
                if row is None:
                    raise ValueError('Referenz gehört nicht zu diesem Arbeitsstand')
                canonical_references.append(row[0])
            c.execute('INSERT INTO memory_observations '
                      '(id,source_role,source_type,external_ref,structured_value_json,observed_at,scope,metadata_json,created_at) '
                      'VALUES (?,?,?,?,?,?,?,?,?)',
                      (observation, source, 'provider_result' if source == 'tool' else 'turn',
                       'working_memory:' + identifier, _json({'binary_object': identifier}) if binary else raw.decode('utf-8'),
                       now, 'workspace:' + workspace_id,
                       _json({'workspace_id': workspace_id, 'work_turn_id': turn_id, 'kind': kind,
                              'model_authored': source == 'assistant'}), now))
            c.execute('INSERT INTO memory_work_objects VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (identifier, workspace_id, observation, kind, str(title), media_type,
                       raw if binary else None, hashlib.sha256(raw).hexdigest(), len(raw), now))
            c.execute('INSERT INTO memory_work_fts(object_id,workspace_id,title,content) VALUES (?,?,?,?)',
                      (identifier, workspace_id, str(title), '' if binary else raw.decode('utf-8')))
            for reference in dict.fromkeys(canonical_references):
                c.execute('INSERT INTO memory_work_links VALUES (?,?,?)', (identifier, reference, 'model_reference'))
            self._event(c, workspace_id, kind, identifier, turn_id)
            self._touch(c, workspace_id, now)
        return {'reference': identifier, 'reference_kind': 'working_material', 'read_operation': 'working_memory.read', 'workspace_id': workspace_id, 'kind': kind, 'title': str(title), 'media_type': media_type,
                'sha256': hashlib.sha256(raw).hexdigest(), 'byte_count': len(raw), 'created_at': now,
                'observation_id': observation}

    def describe(self, workspace_id, reference):
        with self.database.connect(lifecycle_audit=False) as c:
            row = c.execute('SELECT id,kind,title,media_type,sha256,byte_count,created_at,observation_id '
                            'FROM memory_work_objects WHERE (id=? OR observation_id=?) AND workspace_id=?',
                            (reference, reference, workspace_id)).fetchone()
        if row is None:
            raise KeyError('Arbeitsmaterial gehört nicht zum geöffneten Arbeitsstand')
        return {'reference': row['id'], 'reference_kind': 'working_material', 'read_operation': 'working_memory.read', 'workspace_id': workspace_id, **{k: row[k] for k in row.keys() if k != 'id'}}

    def value(self, workspace_id, reference):
        with self.database.connect(lifecycle_audit=False) as c:
            row = c.execute('SELECT o.content,v.structured_value_json FROM memory_work_objects o '
                            'JOIN memory_observations v ON v.id=o.observation_id '
                            'WHERE (o.id=? OR o.observation_id=?) AND o.workspace_id=?',
                            (reference, reference, workspace_id)).fetchone()
        if row is None:
            raise KeyError('Arbeitsmaterial gehört nicht zum geöffneten Arbeitsstand')
        return bytes(row['content']) if row['content'] is not None else json.loads(row['structured_value_json'])

    @staticmethod
    def pointer(value, pointer):
        if not pointer:
            return value
        if not isinstance(pointer, str) or not pointer.startswith('/'):
            raise ValueError('Pfad muss ein JSON Pointer sein')
        for key in pointer[1:].split('/'):
            key = key.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                if not key.isdecimal() or str(int(key)) != key:
                    raise ValueError('Listenindizes müssen nichtnegative JSON-Pointer-Indizes sein')
                value = value[int(key)]
            else:
                value = value[key]
        return value

    @classmethod
    def field(cls, value, selector):
        # Literal property names and RFC 6901 pointers are both structural
        # selectors. No names, domains or synonyms are supplied by Python.
        if not isinstance(selector, str):
            raise ValueError('Feldselektor muss Text sein')
        return cls.pointer(value, selector) if not selector or selector.startswith('/') else value[selector]

    @staticmethod
    def structure(value, pointer=''):
        """Describe object paths without values. Arrays are explicit traversal boundaries.

        Inspect an array element by its pointer when its shape is needed. This
        avoids assuming all elements have the first element's structure.
        """
        items = []
        pending = [(pointer, value)]
        while pending:
            path, node = pending.pop()
            kind = ('null' if node is None else 'boolean' if isinstance(node, bool) else
                    'object' if isinstance(node, dict) else 'array' if isinstance(node, list) else
                    'string' if isinstance(node, str) else 'binary' if isinstance(node, bytes) else 'number')
            item = {'pointer': path, 'type': kind}
            if isinstance(node, (dict, list, str, bytes)):
                item['length'] = len(node)
            items.append(item)
            if isinstance(node, dict):
                pending.extend((path + '/' + key.replace('~', '~0').replace('/', '~1'), child)
                               for key, child in reversed(list(node.items())))
        return items

    def inspect(self, workspace_id, reference, *, pointer='', offset=0, limit=None):
        if offset < 0 or (limit is not None and limit < 1):
            raise ValueError('Ungültiger Abrufbereich')
        value = self.selected_value(workspace_id, reference, pointer)
        items = self.structure(value, pointer)
        page = items[offset:] if limit is None else items[offset:offset + limit]
        return {'reference': reference, 'pointer': pointer, 'items': page,
                'array_elements_expanded': False, **self._page(len(items), offset, len(page))}

    @classmethod
    def pointer_diagnostic(cls, value, pointer):
        """Report the exact traversal boundary, without selecting a replacement."""
        resolved = ''
        if not isinstance(pointer, str) or not pointer.startswith('/'):
            return {'resolved_pointer': resolved, 'constraint': 'pointer_requires_leading_slash'}
        for token in pointer[1:].split('/'):
            candidate = resolved + '/' + token
            try:
                selected = cls.pointer(value, '/' + token)
            except (KeyError, IndexError, TypeError, ValueError):
                return {'resolved_pointer': resolved, 'failed_token': token,
                        'container': cls.structure(value, resolved)[0],
                        'available_children': cls.structure(value, resolved),
                        **({'element_pointer_format': resolved + '/{index}',
                            'valid_index_range': [0, len(value) - 1] if value else None}
                           if isinstance(value, list) else {})}
            resolved, value = candidate, selected
        return {'resolved_pointer': resolved}

    def selected_value(self, workspace_id, reference, pointer):
        original = self.value(workspace_id, reference)
        try:
            return self.pointer(original, pointer)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WorkingSelectionError('Der gewählte JSON-Pfad ist nicht abrufbar. Die Struktur zeigt die vorhandenen Pfade.',
                {'reference': reference, 'requested_pointer': pointer, 'items': self.structure(original),
                 'array_elements_expanded': False, **self.pointer_diagnostic(original, pointer)}) from exc

    def retrieval_observation(self, workspace_id, operation, parameters):
        """Exact repeats on immutable material, independent of names or task meaning."""
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'))
        with self.database.connect(lifecycle_audit=False) as c:
            rows = c.execute("SELECT v.structured_value_json FROM memory_work_calls t "
                "JOIN memory_work_objects o ON o.id=t.request_id JOIN memory_observations v ON v.id=o.observation_id "
                "WHERE t.workspace_id=? AND t.capability='working_memory' AND t.operation=? AND t.status='returned'",
                (workspace_id, operation)).fetchall()
        # Normalize only documented structural defaults, never field meanings.
        def selection(p):
            return {**{'pointer': '', 'offset': 0, 'limit': None, 'fields': None, 'where': None, 'filters': [], 'as_image': False}, **p}
        repeated = sum(canonical(selection(json.loads(r[0]))) == canonical(selection(parameters)) for r in rows)
        description = self.describe(workspace_id, parameters['reference'])
        return {'previous_identical_selections': repeated, 'original_is_immutable': True,
                'source_kind': description['kind'], 'source_reference': parameters['reference'],
                'source_sha256': description['sha256']}

    def activity(self, workspace_id, *, turn_id=None):
        """Technical counters and last call; not a judgement of task progress."""
        with self.database.connect(lifecycle_audit=False) as c:
            rows = c.execute('SELECT t.*,v.structured_value_json AS parameters FROM memory_work_calls t '
                'JOIN memory_work_objects o ON o.id=t.request_id JOIN memory_observations v ON v.id=o.observation_id '
                'WHERE t.workspace_id=?' + (' AND t.turn_id=?' if turn_id else '') + ' ORDER BY t.created_at,t.id',
                (workspace_id, turn_id) if turn_id else (workspace_id,)).fetchall()
            resets = c.execute("SELECT count(*) FROM memory_work_contexts WHERE workspace_id=? AND reason='fresh_context'"
                + (' AND turn_id=?' if turn_id else ''), (workspace_id, turn_id) if turn_id else (workspace_id,)).fetchone()[0]
            checkpoint = c.execute('SELECT checkpoint_id FROM memory_workspaces WHERE id=?', (workspace_id,)).fetchone()[0]
            if turn_id:
                turn = c.execute('SELECT status,updated_at FROM memory_work_turns WHERE id=? AND workspace_id=?',
                                 (turn_id, workspace_id)).fetchone()
                if turn is None:
                    raise KeyError('Vorgang gehört nicht zu diesem Arbeitsstand')
                if turn['status'] != 'running':
                    historical = c.execute("SELECT object_id FROM memory_work_events WHERE workspace_id=? "
                        "AND kind='checkpoint' AND created_at<=? ORDER BY sequence DESC LIMIT 1",
                        (workspace_id, turn['updated_at'])).fetchone()
                    checkpoint = historical[0] if historical else None
        counts, selections = {}, set()
        repeated = 0
        last = None
        for row in rows:
            key = row['capability'] + '.' + row['operation']
            counts[key] = counts.get(key, 0) + 1
            parameters = json.loads(row['parameters'])
            last = {'capability': row['capability'], 'operation': row['operation'], 'status': row['status'],
                    'request_reference': row['request_id'], 'result_reference': row['result_id']}
            if row['capability'] == 'working_memory' and row['operation'] in {'read', 'inspect'} and row['status'] == 'returned':
                selection = (row['operation'], json.dumps(parameters, sort_keys=True, separators=(',', ':')))
                repeated += selection in selections
                selections.add(selection)
        return {'tool_calls': len(rows), 'operations': counts, 'repeated_material_selections': repeated,
                'distinct_material_selections': len(selections), 'fresh_contexts': resets,
                'checkpoint_reference': checkpoint, 'checkpoint_missing': checkpoint is None,
                'task_progress_assessed': False, 'last_call': last}

    def read(self, workspace_id, reference, *, pointer='', offset=0, limit=None, fields=None, where=None, filters=None):
        value = self.selected_value(workspace_id, reference, pointer)
        description = self.describe(workspace_id, reference)
        origin = {'reference_kind': 'working_material', 'read_operation': 'working_memory.read', 'stored_at': description['created_at'], 'observation_id': description['observation_id'], 'live_verified': False}
        if offset < 0 or (limit is not None and limit < 1):
            raise ValueError('Ungültiger Abrufbereich')
        if isinstance(value, bytes):
            page = value[offset:] if limit is None else value[offset:offset + limit]
            return {**origin, 'reference': reference, 'encoding': 'base64', 'content': base64.b64encode(page).decode(),
                    'media_type': self.describe(workspace_id, reference)['media_type'],
                    **self._page(len(value), offset, len(page))}
        filters = filters or []
        for condition in filters:
            if (not isinstance(condition, dict) or set(condition) != {'field', 'op', 'value'}
                    or not isinstance(condition['field'], str) or condition['op'] not in {'eq', 'starts_with'}
                    or (condition['op'] == 'starts_with' and not isinstance(condition['value'], str))):
                raise ValueError('Filter benötigen field, op (eq oder starts_with) und value; starts_with benötigt Text.')
        if where or filters:
            if not isinstance(value, list):
                raise WorkingSelectionError('Filter benötigen eine Liste; am gewählten Pfad liegt ein '
                    + self.structure(value, pointer)[0]['type'] + '. Die Struktur enthält die verfügbaren Pfade.',
                    {**self.inspect(workspace_id, reference, pointer=pointer),
                     'requested_pointer': pointer, 'actual_type': self.structure(value, pointer)[0]['type'],
                     'required_type': 'array', 'constraint': 'filter_requires_array',
                     'array_pointers': [item['pointer'] for item in self.structure(value, pointer) if item['type'] == 'array']})
            def matches(item):
                try:
                    if not all(self.field(item, key) == expected for key, expected in (where or {}).items()):
                        return False
                    for condition in filters:
                        actual = self.field(item, condition['field'])
                        expected = condition['value']
                        if condition['op'] == 'eq' and actual != expected:
                            return False
                        if condition['op'] == 'starts_with' and (not isinstance(actual, str) or not actual.startswith(expected)):
                            return False
                    return True
                except (KeyError, IndexError, TypeError, ValueError):
                    return False
            value = [item for item in value if matches(item)]
        is_sequence = isinstance(value, (list, str))
        if (offset or limit is not None) and not is_sequence:
            # Dictionary entries can be paged without guessing which keys matter.
            if isinstance(value, dict):
                value = [{'key': key, 'value': item} for key, item in value.items()]
                is_sequence = True
            else:
                raise ValueError('Dieser Wert ist nicht seitenweise abrufbar')
        total = len(value) if is_sequence else 1
        content = value[offset:] if is_sequence and limit is None else value[offset:offset + limit] if is_sequence else value
        missing_fields = []
        available_paths = set()
        if fields:
            def project(item, index):
                projected = {}
                for key in fields:
                    try:
                        projected[key] = self.field(item, key)
                    except (KeyError, IndexError, TypeError, ValueError):
                        missing_fields.append({'item_index': index, 'field': key})
                        available_paths.update(entry['pointer'] for entry in self.structure(item) if entry['pointer'])
                return projected
            content = [project(item, offset + index) for index, item in enumerate(content)] if isinstance(content, list) else project(content, None)
        return {**origin,
                **({'status': 'error', 'error_class': 'WorkingProjectionError',
                    'message': 'Die angeforderten Feldselektoren wurden nicht vollständig aufgelöst. Dies ist ein Auswahlfehler; die vorhandenen Originalpfade stehen in projection_diagnostics. Teilweise projizierte Daten belegen keine fehlenden Originalattribute.'}
                   if missing_fields else {'status': 'completed'}),
                'reference': reference, 'pointer': pointer,
                'selection': {'fields': fields, 'where': where, 'filters': filters},
                'missing_fields': missing_fields, 'projection_complete': not missing_fields,
                **({'projection_diagnostics': {
                    'field_selector_kinds': {key: 'json_pointer' if key.startswith('/') else 'literal_key' for key in fields},
                    'available_field_paths_union': sorted(available_paths),
                    'path_scope': 'relative_to_each_original_item; availability_can_vary',
                    'available_field_selectors': sorted(available_paths),
                    'selector_format': 'RFC6901_pointer_relative_to_item',
                    'missing_projection_is_not_proof_of_missing_source_data': True,
                }} if missing_fields else {}),
                'content': content,
                **self._page(total, offset, len(content) if is_sequence else 1)}

    @staticmethod
    def _page(total, offset, returned):
        end = offset + returned
        return {'total_matches': total, 'offset': offset, 'returned': returned,
                'complete': offset == 0 and end >= total, 'has_more': end < total,
                'next_offset': end if end < total else None}

    def list_objects(self, workspace_id, *, query=None, kind=None, offset=0, limit=None, snapshot=None):
        if offset < 0 or (limit is not None and limit < 1):
            raise ValueError('Ungültiger Abrufbereich')
        with self.database.connect(lifecycle_audit=False) as c:
            if snapshot is None:
                snapshot = c.execute('SELECT coalesce(max(sequence),0) FROM memory_work_events WHERE workspace_id=?',
                                     (workspace_id,)).fetchone()[0]
        conditions, params = ['o.workspace_id=?',
            'EXISTS(SELECT 1 FROM memory_work_events e WHERE e.object_id=o.id AND e.kind=o.kind AND e.sequence<=?)'], [workspace_id, snapshot]
        join, order = '', 'o.created_at,o.id'
        if query:
            match = fts_query(query)
            if not match:
                return {'items': [], **self._page(0, offset, 0)}
            join = ' JOIN memory_work_fts f ON f.object_id=o.id'
            conditions.append('memory_work_fts MATCH ?'); params.append(match)
            order = 'bm25(memory_work_fts),o.created_at,o.id'
        if kind:
            conditions.append('o.kind=?'); params.append(kind)
        sql = 'SELECT o.id,o.kind,o.title,o.media_type,o.sha256,o.byte_count,o.created_at,o.observation_id FROM memory_work_objects o' + join + ' WHERE ' + ' AND '.join(conditions)
        with self.database.connect(lifecycle_audit=False) as c:
            rows = c.execute(sql + ' ORDER BY ' + order, params).fetchall()
        selected = rows[offset:] if limit is None else rows[offset:offset + limit]
        return {'items': [{'reference': r['id'], 'reference_kind': 'working_material', 'read_operation': 'working_memory.read', **{k: r[k] for k in r.keys() if k != 'id'}} for r in selected],
                'snapshot': snapshot, **self._page(len(rows), offset, len(selected))}

    def begin_turn(self, workspace_id, conversation_id, value, trace_id):
        identifier, now = _id(), _now()
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('INSERT INTO memory_work_turns(id,workspace_id,conversation_id,status,created_at,updated_at) '
                      "VALUES (?,?,?,'running',?,?)", (identifier, workspace_id, conversation_id, now, now))
            request = self.put(workspace_id, value, kind='user_request', source='user', turn_id=identifier,
                               title='Benutzerauftrag', media_type='application/json', _connection=c)
            c.execute('UPDATE memory_work_turns SET request_id=? WHERE id=?', (request['reference'], identifier))
        return identifier, request

    def finish_turn(self, workspace_id, turn_id, status, value):
        with self.database.connect(lifecycle_audit=False) as c:
            obj = self.put(workspace_id, value, kind='answer' if status == 'completed' else 'runtime_error',
                           source='assistant' if status == 'completed' else 'system', turn_id=turn_id, _connection=c)
            c.execute('UPDATE memory_work_turns SET status=?,answer_id=?,error_id=?,updated_at=? WHERE id=? AND workspace_id=?',
                      (status, obj['reference'] if status == 'completed' else None,
                       obj['reference'] if status != 'completed' else None, _now(), turn_id, workspace_id))
        return obj

    def start_call(self, workspace_id, turn_id, call_id, capability, operation, effect, parameters):
        identifier, now = _id(), _now()
        with self.database.connect(lifecycle_audit=False) as c:
            request = self.put(workspace_id, parameters, kind='tool_request', title=capability + '.' + operation,
                               source='system', turn_id=turn_id, _connection=c)
            c.execute('INSERT INTO memory_work_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                      (identifier, workspace_id, turn_id, call_id, capability, operation, effect,
                       request['reference'], None, 'prepared', now, now))
        return identifier

    def dispatch_call(self, workspace_id, identifier):
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT t.*,v.structured_value_json AS parameters FROM memory_work_calls t '
                            'JOIN memory_work_objects o ON o.id=t.request_id '
                            'JOIN memory_observations v ON v.id=o.observation_id WHERE t.id=? AND t.workspace_id=?',
                            (identifier, workspace_id)).fetchone()
            if row is None:
                raise KeyError('Werkzeugaufruf wurde nicht gefunden')
            if row['effect'] != 'read':
                previous = c.execute("SELECT t.id,v.structured_value_json FROM memory_work_calls t "
                    "JOIN memory_work_objects o ON o.id=t.request_id JOIN memory_observations v ON v.id=o.observation_id "
                    "WHERE t.workspace_id=? AND t.capability=? AND t.operation=? AND t.status='started' AND t.id!=? "
                    "AND coalesce((SELECT json_extract(vr.structured_value_json,'$.allow_retry') FROM memory_work_call_reviews r "
                    "JOIN memory_work_objects ro ON ro.id=r.decision_id JOIN memory_observations vr ON vr.id=ro.observation_id "
                    "WHERE r.call_id=t.id ORDER BY r.created_at DESC,r.id DESC LIMIT 1),0)!=1",
                    (workspace_id, row['capability'], row['operation'], identifier)).fetchall()
                canonical = lambda value: json.dumps(json.loads(value),sort_keys=True,separators=(',',':'))
                for old in previous:
                    if canonical(old['structured_value_json']) == canonical(row['parameters']):
                        raise UncertainCallError(old['id'])
            c.execute("UPDATE memory_work_calls SET status='started',updated_at=? WHERE id=? AND workspace_id=?",
                      (_now(), identifier, workspace_id))
            self._event(c, workspace_id, 'tool_dispatch', row['request_id'], row['turn_id'])

    def review_call(self, workspace_id, call_reference, decision, evidence_references, *, allow_retry=False, turn_id=None):
        if not str(decision).strip() or not evidence_references:
            raise ValueError('Eine ausdrückliche Entscheidung und Quellenreferenzen sind erforderlich')
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM memory_work_calls WHERE id=? AND workspace_id=?',
                             (call_reference,workspace_id)).fetchone():
                raise KeyError('Werkzeugaufruf gehört nicht zu diesem Arbeitsstand')
            obj = self.put(workspace_id, {'call_reference':call_reference,'decision':decision,
                'evidence_references':evidence_references,'allow_retry':bool(allow_retry),'author':'model','verified_fact':False},
                kind='call_review', source='assistant', turn_id=turn_id,
                references=evidence_references, _connection=c)
            c.execute('INSERT INTO memory_work_call_reviews VALUES (?,?,?,?,?)',
                      (_id(),workspace_id,call_reference,obj['reference'],_now()))
        return {'review':obj,'author':'model','retry_allowed':bool(allow_retry),'original_outcome_remains_unverified':True}

    def finish_call(self, workspace_id, turn_id, identifier, result):
        with self.database.connect(lifecycle_audit=False) as c:
            obj = self.put(workspace_id, result, kind='tool_result', source='tool', turn_id=turn_id, _connection=c)
            updated = c.execute("UPDATE memory_work_calls SET status='returned',result_id=?,updated_at=? WHERE id=? AND workspace_id=? AND turn_id=?",
                      (obj['reference'], _now(), identifier, workspace_id, turn_id))
            if not updated.rowcount:
                raise KeyError('Werkzeugaufruf wurde nicht gefunden')
        return obj

    def checkpoint(self, workspace_id, state, *, expected_revision, references=(), turn_id=None):
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            obj = self.put(workspace_id, state, kind='checkpoint', title='Modellformulierter Arbeitsstand',
                           source='assistant', turn_id=turn_id, references=references, _connection=c)
            updated = c.execute('UPDATE memory_workspaces SET checkpoint_id=?,revision=revision+1,updated_at=? '
                                'WHERE id=? AND revision=?', (obj['reference'], _now(), workspace_id, expected_revision))
            if not updated.rowcount:
                raise ValueError('Arbeitsstand wurde inzwischen geändert; aktuellen Stand lesen')
        return {'checkpoint': obj, 'revision': expected_revision + 1, 'author': 'model', 'verified_fact': False}

    def manifest(self, workspace_id, *, current_turn_id=None):
        with self.database.connect(lifecycle_audit=False) as c:
            row = c.execute('SELECT * FROM memory_workspaces WHERE id=?', (workspace_id,)).fetchone()
            if row is None:
                raise KeyError('Arbeitsstand wurde nicht gefunden')
            counts = c.execute('SELECT kind,count(*) AS n FROM memory_work_objects WHERE workspace_id=? GROUP BY kind',
                               (workspace_id,)).fetchall()
            pending = c.execute("SELECT id,call_id,capability,operation,effect,request_id,result_id,status "
                                "FROM memory_work_calls WHERE workspace_id=? AND status='started' ORDER BY created_at,id",
                                (workspace_id,)).fetchall()
            unfinished = c.execute("SELECT id,request_id,status,error_id FROM memory_work_turns "
                                   "WHERE workspace_id=? AND status!='completed' AND id!=? ORDER BY created_at,id",
                                   (workspace_id, current_turn_id or '')).fetchall()
        return {'workspace_id': workspace_id, 'title': row['title'], 'status': row['status'],
                'retention_class': row['retention_class'], 'pinned': bool(row['pinned']),
                'last_accessed_at': row['last_accessed_at'],
                'revision': row['revision'], 'checkpoint_reference': row['checkpoint_id'],
                'checkpoint_author': 'model', 'checkpoint_is_verified_fact': False,
                'objects_by_kind': {r['kind']: r['n'] for r in counts},
                'uncertain_calls': [dict(r) for r in pending],
                'unfinished_turns': [dict(r) for r in unfinished]}

    def events(self, workspace_id, *, after=0, limit=None, snapshot=None):
        with self.database.connect(lifecycle_audit=False) as c:
            if snapshot is None:
                snapshot = c.execute('SELECT coalesce(max(sequence),0) FROM memory_work_events WHERE workspace_id=?',
                                     (workspace_id,)).fetchone()[0]
            rows = c.execute('SELECT sequence,turn_id,kind,object_id AS reference,created_at '
                             'FROM memory_work_events WHERE workspace_id=? AND sequence>? AND sequence<=? ORDER BY sequence',
                             (workspace_id, after, snapshot)).fetchall()
        selected = rows if limit is None else rows[:limit]
        return {'items': [dict(r) for r in selected], 'snapshot': snapshot, 'after': after, 'has_more': len(selected) < len(rows),
                'next_after': selected[-1]['sequence'] if selected else after}

    def workspaces(self):
        with self.database.connect(lifecycle_audit=False) as c:
            rows = c.execute('SELECT id AS workspace_id,title,status,revision,retention_class,pinned,'
                             'updated_at,last_accessed_at FROM memory_workspaces '
                             'ORDER BY last_accessed_at DESC,id').fetchall()
        return {'items': [{**dict(r), 'pinned': bool(r['pinned'])} for r in rows]}

    def calls(self, workspace_id):
        with self.database.connect(lifecycle_audit=False) as c:
            rows = c.execute('SELECT id AS call_reference,turn_id,capability,operation,effect,status,'
                             'request_id AS request_reference,result_id AS result_reference,created_at '
                             'FROM memory_work_calls WHERE workspace_id=? ORDER BY created_at,id', (workspace_id,)).fetchall()
        return {'items': [dict(row) for row in rows],
                'status_meaning': {'prepared': 'Not dispatched', 'started': 'Outcome unknown',
                                   'returned': 'Tool replied; not independent outcome verification'}}

    def set_status(self, workspace_id, status):
        if status not in {'open', 'completed', 'archived'}:
            raise ValueError('Ungültiger Aufgabenstatus')
        with self.database.connect(lifecycle_audit=False) as c:
            updated = c.execute('UPDATE memory_workspaces SET status=?,updated_at=? WHERE id=?', (status, _now(), workspace_id))
            if not updated.rowcount:
                raise KeyError('Arbeitsstand wurde nicht gefunden')
        return {'workspace_id': workspace_id, 'status': status}

    def set_pinned(self, workspace_id, pinned):
        if type(pinned) is not bool:
            raise ValueError('pinned muss boolesch sein')
        with self.database.connect(lifecycle_audit=False) as c:
            updated = c.execute(
                'UPDATE memory_workspaces SET pinned=?,updated_at=?,last_accessed_at=? WHERE id=?',
                (int(pinned), _now(), _now(), workspace_id),
            )
            if not updated.rowcount:
                raise KeyError('Arbeitsstand wurde nicht gefunden')
        return {'workspace_id': workspace_id, 'pinned': pinned}

    def cleanup(self, config, *, dry_run=False, now=None):
        """Expire technical work material without interpreting its contents."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('now benötigt eine Zeitzone')
        thresholds = {
            'completed': now - timedelta(hours=float(config.get('completed_retention_hours', 1))),
            'failed': now - timedelta(hours=float(config.get('failed_retention_hours', 24))),
            'temporary_learning': now - timedelta(
                hours=float(config.get('temporary_learning_retention_hours', .25))
            ),
        }
        started_at = _now()
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            rows = c.execute(
                """SELECT w.*,
                    EXISTS(SELECT 1 FROM memory_work_turns t
                           WHERE t.workspace_id=w.id AND t.status='running') AS has_running,
                    EXISTS(SELECT 1 FROM memory_work_calls k
                           WHERE k.workspace_id=w.id AND k.status='started') AS has_uncertain,
                    EXISTS(SELECT 1 FROM memory_work_turns t
                           WHERE t.workspace_id=w.id AND t.status IN ('failed','cancelled')) AS has_failure,
                    EXISTS(SELECT 1 FROM memory_work_turns t
                           WHERE t.workspace_id=w.id) AS has_turns,
                    coalesce((SELECT count(*) FROM memory_work_objects o WHERE o.workspace_id=w.id),0) AS object_count,
                    coalesce((SELECT sum(byte_count) FROM memory_work_objects o WHERE o.workspace_id=w.id),0) AS byte_count
                   FROM memory_workspaces w ORDER BY w.last_accessed_at,w.id"""
            ).fetchall()
            candidates = []
            protected = {'pinned': 0, 'running': 0, 'uncertain_call': 0,
                         'not_finished': 0, 'retention': 0}
            for row in rows:
                reason = None
                if row['pinned']:
                    reason = 'pinned'
                elif row['has_running']:
                    reason = 'running'
                elif row['has_uncertain']:
                    reason = 'uncertain_call'
                elif not row['has_turns'] and row['status'] == 'open':
                    reason = 'not_finished'
                else:
                    category = ('failed' if row['has_failure'] else
                                'temporary_learning' if row['retention_class'] == 'temporary_learning'
                                else 'completed')
                    accessed = datetime.fromisoformat(row['last_accessed_at'].replace('Z', '+00:00'))
                    if accessed > thresholds[category]:
                        reason = 'retention'
                if reason:
                    protected[reason] += 1
                    continue
                candidates.append({
                    'workspace_id': row['id'], 'retention_class': row['retention_class'],
                    'outcome': 'failed' if row['has_failure'] else 'completed',
                    'last_accessed_at': row['last_accessed_at'],
                    'object_count': row['object_count'], 'byte_count': row['byte_count'],
                })

            deleted_objects = deleted_bytes = retained_observations = 0
            if not dry_run:
                for item in candidates:
                    workspace_id = item['workspace_id']
                    observations = [r[0] for r in c.execute(
                        'SELECT observation_id FROM memory_work_objects WHERE workspace_id=?',
                        (workspace_id,),
                    ).fetchall()]
                    c.execute('DELETE FROM memory_work_bindings WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_contexts WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_call_reviews WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_links WHERE from_id IN '
                              '(SELECT id FROM memory_work_objects WHERE workspace_id=?) OR to_id IN '
                              '(SELECT id FROM memory_work_objects WHERE workspace_id=?)',
                              (workspace_id, workspace_id))
                    c.execute('DELETE FROM memory_work_events WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_calls WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_turns WHERE workspace_id=?', (workspace_id,))
                    c.execute('UPDATE memory_workspaces SET checkpoint_id=NULL WHERE id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_fts WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_work_objects WHERE workspace_id=?', (workspace_id,))
                    c.execute('DELETE FROM memory_workspaces WHERE id=?', (workspace_id,))
                    deleted_objects += item['object_count']; deleted_bytes += item['byte_count']
                    for observation_id in observations:
                        try:
                            c.execute('DELETE FROM memory_observations WHERE id=?', (observation_id,))
                        except sqlite3.IntegrityError:
                            # A durable claim/evidence reference deliberately outlives work material.
                            retained_observations += 1
            report = {
                'started_at': started_at, 'completed_at': _now(), 'dry_run': bool(dry_run),
                'scanned_workspaces': len(rows), 'eligible_workspaces': len(candidates),
                'deleted_workspaces': 0 if dry_run else len(candidates),
                'deleted_objects': 0 if dry_run else deleted_objects,
                'deleted_bytes': 0 if dry_run else deleted_bytes,
                'retained_observations': 0 if dry_run else retained_observations,
                'eligible_objects': sum(item['object_count'] for item in candidates),
                'eligible_bytes': sum(item['byte_count'] for item in candidates),
                'protected': protected, 'candidates': candidates,
            }
            c.execute('INSERT INTO memory_work_cleanup_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (_id(), report['started_at'], report['completed_at'], int(dry_run),
                       report['scanned_workspaces'], report['eligible_workspaces'],
                       report['deleted_workspaces'], report['deleted_objects'],
                       report['deleted_bytes'], report['retained_observations'], _json({
                           'protected': protected, 'candidates': candidates,
                       })))
        return report


class WorkingMemoryCleanupCoordinator:
    """Run configurable database cleanup at startup and on a quiet timer."""
    def __init__(self, database, config):
        self.store = WorkingMemoryStore(database)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._thread = None
        self.last_report = None
        self.last_error = None
        self.configure(config)

    def configure(self, config):
        with self._lock:
            self.config = dict(config)
        self._wake.set()

    def run_now(self, *, dry_run=False):
        with self._lock:
            config = dict(self.config)
        if not config.get('cleanup_enabled', True):
            return {'status': 'disabled', 'dry_run': bool(dry_run)}
        try:
            self.last_report = self.store.cleanup(config, dry_run=dry_run)
            self.last_error = None
            return self.last_report
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'
            return {'status': 'error', 'error': self.last_error, 'dry_run': bool(dry_run)}

    def start(self):
        self.run_now()
        if self._thread is None:
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, name='eve-working-memory-cleanup', daemon=True)
            self._thread.start()

    def _run(self):
        while True:
            with self._lock:
                seconds = int(self.config.get('cleanup_interval_minutes', 15)) * 60
            self._wake.wait(seconds)
            self._wake.clear()
            if self._closed:
                return
            self.run_now()

    def close(self):
        self._closed = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def contract():
    """Native database operations, loaded on demand like the existing Memory tools."""
    string = {'type': 'string'}
    integer = {'type': 'integer', 'minimum': 0}
    def op(description, properties=None, required=(), effect='read'):
        return {'description': description, 'effect': effect, 'parameters_schema': {
            'type': 'object', 'additionalProperties': False, 'properties': properties or {}, 'required': list(required)}}
    return {'description': 'Task working material and execution journal in SQLite. reference identifies workspace material; memory_id identifies durable knowledge accessed through memory, not this capability.', 'operations': {
        'status': op('Current workspace, checkpoint revision and calls whose outcome is unknown. A started call is not proof of execution; inspect before repeating writes.'),
        'list': op('List or lexical-search material metadata. Reuse snapshot with next_offset for stable paging while new events arrive. No default result cap.',
                   {'query': string, 'kind': string, 'offset': integer, 'snapshot': integer, 'limit': {'type': 'integer', 'minimum': 1}}),
        'inspect': op('Describe actual JSON paths, types and lengths without values. Arrays are not expanded; inspect an element pointer to explore it. Results can be paged.',
                   {'reference': string, 'pointer': {'type': 'string', 'description': 'RFC6901 path from material root. Array element: /rows/0; key a/b: /a~1b; key x~y: /x~0y. Empty selects root.'}, 'offset': integer, 'limit': {'type': 'integer', 'minimum': 1}}, ['reference']),
        'read': op('Read reference at pointer (RFC 6901; empty selects root). Filters require an array at pointer. fields use literal keys or /nested/key, never dot traversal. where uses exact equality. filters combines explicit eq/starts_with conditions with AND. Unresolved projected fields return WorkingProjectionError with partial data and actual paths; null is a value. Follow has_more.',
                   {'reference': string, 'pointer': {'type': 'string', 'description': 'RFC6901 path from material root. Array element: /rows/0; key a/b: /a~1b; key x~y: /x~0y. Empty selects root.'}, 'as_image': {'type': 'boolean'}, 'offset': integer, 'limit': {'type': 'integer', 'minimum': 1},
                    'fields': {'type': 'array', 'description': 'Per item: literal key or RFC6901 pointer. info.display is a literal key; /info/display selects nested display.', 'items': string}, 'where': {'type': 'object', 'additionalProperties': True},
                    'filters': {'type': 'array', 'items': {'type': 'object', 'properties': {
                        'field': string, 'op': {'type': 'string', 'enum': ['eq', 'starts_with']}, 'value': {}},
                        'required': ['field', 'op', 'value'], 'additionalProperties': False}}}, ['reference']),
        'save': op('Save task material or a hypothesis, not verified long-term knowledge. References must belong to this workspace.',
                   {'value': {}, 'title': string, 'references': {'type': 'array', 'items': string}}, ['value'], 'write'),
        'checkpoint': op('Save the current goal, user constraints, decisions versus hypotheses, open questions and next step in your own structured state. Cite originals. Does not verify model statements.',
                   {'state': {'type': 'object', 'additionalProperties': True}, 'expected_revision': integer,
                    'references': {'type': 'array', 'items': string}}, ['state', 'expected_revision'], 'write'),
        'review_call': op('After inspecting an uncertain call, record your explicit retry decision and evidence references. This permits a new attempt; it does not verify the old outcome.',
                          {'call_reference':string,'decision':string,'allow_retry':{'type':'boolean'},'evidence_references':{'type':'array','items':string,'minItems':1}},
                          ['call_reference','decision','allow_retry','evidence_references'], 'write'),
        'reset_context': op('Continue in a fresh model context using the saved checkpoint and database references. Save a checkpoint first when useful. Originals and tool outcomes remain available.'),
        'events': op('Read the durable chronological event directory. Reuse snapshot with next_after for stable paging.', {'after': integer, 'snapshot': integer, 'limit': {'type': 'integer', 'minimum': 1}}),
        'workspaces': op('List existing workspaces for explicit resumption.'),
        'open': op('Select an existing workspace by ID, or create one using create=true. This changes the active task; checkpoint the previous task first.',
                   {'workspace_id': string, 'create': {'type': 'boolean'}, 'title': string}, effect='write'),
        'set_status': op('Mark the selected task open, completed or archived.',
                         {'status': {'enum': ['open', 'completed', 'archived']}}, ['status'], 'write'),
        'set_pinned': op('Protect or release the selected workspace from automatic short-term cleanup.',
                         {'pinned': {'type': 'boolean'}}, ['pinned'], 'write'),
    }}
