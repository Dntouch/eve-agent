import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from eve_agent.shadow_learning import ProductiveLearningPipeline
from eve_agent.conversation_learning import ConversationLearningCoordinator
from eve_agent.storage import EveDatabase, ConversationStore


class LearningReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'eve.db'
        self.database = EveDatabase(self.path)
        self.store = ConversationStore(self.database)
        self.cid = self.store.create('Review')['id']
        self.llm = SimpleNamespace(model='review-test', analyze_conversation_learning=Mock())
        self.pipeline = ProductiveLearningPipeline(self.database, self.llm)

    def failed(self, turn):
        self.store.append_turn(self.cid, 'A source message', 'An answer', turn_id=turn)
        self.pipeline.accept_turn(turn)
        with self.database.connect() as c:
            c.execute("UPDATE memory_learning_jobs SET status='failed',error_class='result_evidence_value_mismatch' WHERE turn_id=?", (turn,))

    def test_review_preserves_failure_and_excludes_all_execution_and_retry_paths(self):
        self.failed('reviewed'); self.failed('unreviewed')
        result = self.pipeline.review_turn('reviewed', 'Belegwert wurde vom Modell verändert.')
        self.assertEqual('reviewed', result['status'])
        self.assertEqual({'reviewed': 1, 'failed': 1}, self.pipeline.job_counts())
        page = self.pipeline.learning_jobs('reviewed')
        self.assertEqual(1, page['total'])
        self.assertEqual('reviewed', page['items'][0]['status'])
        self.assertEqual('result_evidence_value_mismatch', page['items'][0]['error_class'])
        self.assertEqual('Belegwert wurde vom Modell verändert.', page['items'][0]['review_note'])
        self.assertEqual(1, self.pipeline.learning_jobs('failed')['total'])
        self.assertEqual(1, self.pipeline.retry_failed())
        with self.assertRaises(ValueError): self.pipeline.retry_turn('reviewed')
        self.assertTrue(self.pipeline.process_batch(['reviewed'])[0]['idempotent'])
        self.assertEqual('reviewed', self.pipeline.process_turn('reviewed')['status'])
        self.assertEqual('reviewed', self.pipeline.evaluate_turn('reviewed')['status'])
        self.assertEqual(['unreviewed'], self.pipeline.queued_turns(40))
        self.llm.analyze_conversation_learning.assert_not_called()
        with self.database.connect() as c:
            row = c.execute("SELECT status,error_class,attempt_count FROM memory_learning_jobs WHERE turn_id='reviewed'").fetchone()
            self.assertEqual(('failed', 'result_evidence_value_mismatch', 0), tuple(row))
            self.assertEqual(0, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
        restarted = ProductiveLearningPipeline(EveDatabase(self.path), self.llm)
        self.assertEqual(1, restarted.job_counts()['reviewed'])
        self.assertNotIn('reviewed', restarted.pending_turns())

    def test_review_can_be_reopened_and_keeps_user_audit_history(self):
        self.failed('turn')
        self.pipeline.review_turn('turn', 'Geprüft')
        self.assertTrue(self.pipeline.review_turn('turn')['idempotent'])
        self.pipeline.review_turn('turn', reopen=True)
        self.assertEqual({'failed': 1}, self.pipeline.job_counts())
        with self.database.connect() as c:
            events = c.execute("SELECT event_type,actor,details_json FROM audit_events WHERE event_type LIKE 'learning_review%' ORDER BY id").fetchall()
        self.assertEqual(['learning_reviewed', 'learning_review_reopened'], [row[0] for row in events])
        self.assertTrue(all(row[1] == 'user' for row in events))
        self.assertEqual('Geprüft', json.loads(events[1][2])['previous_review_note'])
        self.assertEqual('pending', self.pipeline.retry_turn('turn')['status'])

    def test_review_does_not_wait_for_an_unrelated_model_evaluation(self):
        self.failed('turn')
        errors = []
        def review():
            try: self.pipeline.review_turn('turn')
            except Exception as exc: errors.append(exc)
        self.pipeline._evaluation_lock.acquire()
        worker = threading.Thread(target=review)
        try:
            worker.start(); worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual([], errors)
        finally:
            self.pipeline._evaluation_lock.release()
            worker.join(2)

    def test_targeted_retry_reopens_review_atomically_and_preserves_its_history(self):
        self.failed('selected'); self.failed('untouched')
        self.pipeline.review_turn('selected', 'Originale Prüfnotiz')
        coordinator = ConversationLearningCoordinator(self.database, self.pipeline,
            {'enabled': True}, autostart=False)
        self.addCleanup(coordinator.close)
        result = coordinator.retry_turn('selected')
        self.assertEqual({'turn_id': 'selected', 'status': 'pending'}, result['retry'])
        self.assertEqual(1, result['pending'])
        self.assertEqual(1, result['failed'])
        self.assertFalse(result['pause_requested'])
        self.assertEqual(['selected'], self.pipeline.queued_turns(40))
        with self.database.connect() as c:
            job = c.execute("SELECT status,reviewed_at,review_note,error_class FROM memory_learning_jobs WHERE turn_id='selected'").fetchone()
            self.assertEqual(('pending', None, '', None), tuple(job))
            event = c.execute("SELECT actor,details_json FROM audit_events WHERE event_type='learning_review_reopened'").fetchone()
            self.assertEqual('user', event['actor'])
            self.assertEqual('Originale Prüfnotiz', json.loads(event['details_json'])['previous_review_note'])
            self.assertEqual(0, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
        self.llm.analyze_conversation_learning.assert_not_called()

    def test_targeted_retry_rejects_changed_or_missing_jobs_without_touching_others(self):
        self.failed('failed'); self.failed('changed')
        with self.database.connect() as c:
            c.execute("UPDATE memory_learning_jobs SET status='pending' WHERE turn_id='changed'")
        for turn in ['changed', 'missing', '', None, 5]:
            with self.subTest(turn=turn), self.assertRaises(ValueError):
                self.pipeline.retry_turn(turn, reopen_review=True)
        self.assertEqual(1, self.pipeline.learning_jobs('failed')['total'])

    def test_only_existing_failed_jobs_can_be_reviewed(self):
        self.failed('turn')
        with self.database.connect() as c: c.execute("UPDATE memory_learning_jobs SET status='pending' WHERE turn_id='turn'")
        for turn in ['turn', 'missing']:
            with self.subTest(turn=turn), self.assertRaises(ValueError): self.pipeline.review_turn(turn)
        for value in [None, 5, '']:
            with self.subTest(value=value), self.assertRaises(ValueError): self.pipeline.review_turn(value)

    def test_v22_migration_keeps_jobs_and_creates_a_consistent_backup(self):
        self.failed('turn')
        with sqlite3.connect(self.path) as c:
            c.execute('ALTER TABLE memory_learning_jobs DROP COLUMN reviewed_at')
            c.execute('ALTER TABLE memory_learning_jobs DROP COLUMN review_note')
            c.execute('PRAGMA user_version=22')
        upgraded = EveDatabase(self.path)
        with upgraded.connect() as c:
            row = c.execute('SELECT status,error_class,reviewed_at,review_note FROM memory_learning_jobs').fetchone()
            self.assertEqual(('failed', 'result_evidence_value_mismatch', None, ''), tuple(row))
            self.assertEqual(23, c.execute('PRAGMA user_version').fetchone()[0])
            self.assertEqual([], c.execute('PRAGMA foreign_key_check').fetchall())
        backups = list((self.path.parent / 'backups').glob('*v22-to-v23-*.db'))
        self.assertEqual(1, len(backups))
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(22, c.execute('PRAGMA user_version').fetchone()[0])
            self.assertEqual(1, c.execute('SELECT count(*) FROM memory_learning_jobs').fetchone()[0])
