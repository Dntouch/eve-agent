"""Durable Chatto inbox/outbox; executing work never depends on a bot request."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
import uuid


def _now():
    return datetime.now(timezone.utc).isoformat()


class ChattoJobs:
    def __init__(self, database, execute):
        self.database, self.execute = database, execute
        self.lock = threading.RLock()
        self.thread = None
        self.stopped = False
        with database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS chatto_jobs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                request_json TEXT, target_json TEXT NOT NULL,
                state TEXT NOT NULL, progress_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT, delivery_status TEXT NOT NULL DEFAULT 'waiting',
                claim_token TEXT, claim_until REAL, retry_at REAL NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS chatto_jobs_delivery ON chatto_jobs(delivery_status,retry_at)")
            # A claim without dispatch is safe to recover. A started send is not.
            connection.execute("UPDATE chatto_jobs SET delivery_status='pending',claim_token=NULL WHERE delivery_status='claimed'")
            connection.execute("UPDATE chatto_jobs SET delivery_status='uncertain',error='Send interrupted' WHERE delivery_status='sending'")
            for row in connection.execute("SELECT id FROM chatto_jobs WHERE state='running'").fetchall():
                self._finish(connection, row['id'], 'interrupted', self._failure_payload(interrupted=True))

    @staticmethod
    def identity(context):
        identity = json.dumps([context[key] for key in ('server_url', 'bot_id', 'room_id', 'message_id')])
        return 'chatto-job:' + str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    def submit(self, request, context):
        identifier = self.identity(context)
        now = _now()
        with self.lock, self.database.connect() as connection:
            if self.stopped:
                raise RuntimeError('Chatto worker is stopping')
            connection.execute("""INSERT OR IGNORE INTO chatto_jobs
                (id,conversation_id,request_json,target_json,state,created_at,updated_at)
                VALUES (?,?,?,?,'queued',?,?)""", (identifier, request['conversation_id'],
                    json.dumps(request), json.dumps(context), now, now))
            row = connection.execute("SELECT conversation_id,state,target_json FROM chatto_jobs WHERE id=?", (identifier,)).fetchone()
            # The same transport message cannot be rebound to another context.
            if row['conversation_id'] != request['conversation_id']:
                raise PermissionError('Chatto message belongs to another conversation')
            target = json.loads(row['target_json'])
            if any(target.get(key) != context.get(key) for key in ('sender_id', 'access_profile')):
                raise PermissionError('Chatto message belongs to another sender or profile')
            result = {'id': identifier, 'conversation_id': row['conversation_id'], 'state': row['state']}
        self.start()
        return result

    def start(self):
        with self.lock:
            if self.stopped or self.thread is not None:
                return
            self.thread = threading.Thread(target=self._run, name='eve-chatto-jobs', daemon=True)
            self.thread.start()

    def close(self):
        with self.lock:
            self.stopped = True
            thread = self.thread
        if thread:
            thread.join(timeout=5)

    def _run(self):
        try:
            while True:
                with self.lock, self.database.connect() as connection:
                    if self.stopped:
                        return
                    row = connection.execute("SELECT * FROM chatto_jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
                    if row is None:
                        return
                    connection.execute("UPDATE chatto_jobs SET state='running',updated_at=? WHERE id=?", (_now(), row['id']))
                try:
                    result = self.execute(json.loads(row['request_json']), job_id=row['id'])
                    if not isinstance(result.get('answer'), str) or not result['answer'].strip():
                        raise ValueError('Empty Chatto answer')
                    target = json.loads(row['target_json'])
                    target.update(conversation_id=result['conversation_id'], thread_root_id=result.get('thread_root_id', ''))
                    payload = {'notification': {'message': result['answer']}, 'resources': result.get('resources', [])}
                    with self.database.connect() as connection:
                        connection.execute("UPDATE chatto_jobs SET target_json=? WHERE id=?", (json.dumps(target), row['id']))
                        self._finish(connection, row['id'], 'completed', payload)
                except Exception:
                    # Never replay model/tool work after an ambiguous failure.
                    with self.database.connect() as connection:
                        self._finish(connection, row['id'], 'failed', self._failure_payload())
        finally:
            with self.lock:
                self.thread = None
                # Close the race with a submit arriving just as the worker exits.
                with self.database.connect() as connection:
                    queued = connection.execute("SELECT 1 FROM chatto_jobs WHERE state='queued' LIMIT 1").fetchone()
                if queued and not self.stopped:
                    self.start()

    @staticmethod
    def _failure_payload(interrupted=False):
        text = ('Die Bearbeitung wurde durch einen EVE-Neustart unterbrochen.' if interrupted
                else 'EVE konnte den Auftrag nicht abschließen.')
        return {'notification': {'message': text + ' Bereits ausgeführte Aktionen müssen geprüft werden. '
                                'Der Auftrag wird nicht automatisch erneut ausgeführt.'}, 'resources': []}

    @staticmethod
    def _finish(connection, identifier, state, payload):
        connection.execute("""UPDATE chatto_jobs SET state=?,payload_json=?,delivery_status='pending',
            request_json=NULL,updated_at=? WHERE id=?""", (state, json.dumps(payload), _now(), identifier))

    def progress(self, identifier, context, progress):
        with self.database.connect() as connection:
            connection.execute("UPDATE chatto_jobs SET target_json=?,progress_json=?,updated_at=? WHERE id=?",
                               (json.dumps(context), json.dumps(progress), _now(), identifier))

    def working(self):
        with self.database.connect() as connection:
            return connection.execute("SELECT 1 FROM chatto_jobs WHERE state IN ('queued','running') LIMIT 1").fetchone() is not None

    def statuses(self):
        with self.database.connect() as connection:
            # All live work must be visible, even with a large terminal backlog.
            rows = connection.execute("""SELECT id,state,conversation_id,target_json,progress_json,delivery_status,error
                FROM chatto_jobs WHERE state IN ('queued','running') OR id IN
                (SELECT id FROM chatto_jobs WHERE delivery_status!='delivered'
                 AND state NOT IN ('queued','running') ORDER BY created_at DESC LIMIT 100)
                ORDER BY created_at DESC""").fetchall()
        return [self._status(row) for row in rows]

    @staticmethod
    def _status(row):
        return {'id': row['id'], 'state': row['state'], 'conversation_id': row['conversation_id'],
                'target': json.loads(row['target_json']), 'progress': json.loads(row['progress_json']),
                'delivery_status': row['delivery_status'], 'error': row['error']}

    def claim(self):
        now = time.time()
        token = uuid.uuid4().hex
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""UPDATE chatto_jobs SET delivery_status='pending',claim_token=NULL
                WHERE delivery_status='claimed' AND claim_until<?""", (now,))
            row = connection.execute("""UPDATE chatto_jobs SET delivery_status='claimed',claim_token=?,claim_until=?
                WHERE id=(SELECT id FROM chatto_jobs WHERE delivery_status='pending' AND retry_at<=?
                          ORDER BY created_at LIMIT 1) RETURNING *""", (token, now + 60, now)).fetchone()
        if row is None:
            return []
        return [{**self._status(row), 'claim_token': token, 'payload': json.loads(row['payload_json'])}]

    def begin_send(self, identifier, token):
        with self.database.connect() as connection:
            changed = connection.execute("""UPDATE chatto_jobs SET delivery_status='sending',updated_at=?
                WHERE id=? AND claim_token=? AND delivery_status='claimed'""", (_now(), identifier, token)).rowcount
        if not changed:
            raise ValueError('Chatto delivery claim is no longer valid')

    def retry(self, identifier):
        with self.database.connect() as connection:
            changed = connection.execute("""UPDATE chatto_jobs SET delivery_status='pending',error=NULL,
                claim_token=NULL,retry_at=0,updated_at=? WHERE id=? AND delivery_status='blocked'""",
                (_now(), identifier)).rowcount
        if not changed:
            raise ValueError('Only a blocked Chatto delivery can be retried')

    def acknowledge(self, identifier, token, status, error=None):
        if status not in {'delivered', 'retry', 'blocked', 'uncertain'}:
            raise ValueError('Invalid Chatto delivery status')
        required = 'claimed' if status in {'retry', 'blocked'} else 'sending'
        stored = 'pending' if status == 'retry' else status
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            # Acknowledgements are idempotent; an old claim can never alter a new one.
            row = connection.execute("SELECT delivery_status,claim_token FROM chatto_jobs WHERE id=?", (identifier,)).fetchone()
            if row is None or row['claim_token'] != token:
                raise ValueError('Chatto delivery claim is no longer valid')
            if row['delivery_status'] == stored:
                return
            if row['delivery_status'] != required:
                raise ValueError('Invalid Chatto delivery transition')
            connection.execute("""UPDATE chatto_jobs SET delivery_status=?,error=?,retry_at=?,updated_at=?,
                payload_json=CASE WHEN ?='delivered' THEN NULL ELSE payload_json END
                WHERE id=?""", (stored, str(error or '')[:128], time.time() + 15 if status == 'retry' else 0,
                                 _now(), stored, identifier))
