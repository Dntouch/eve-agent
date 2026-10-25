import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.storage import ConversationStore, EveDatabase


class AnswerFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.db = EveDatabase(Path(self.temp.name) / 'eve.db')
        self.store = ConversationStore(self.db)
        self.cid = self.store.create()['id']
        self.store.append_turn(self.cid, 'Frage', 'Antwort', turn_id='rated-turn',
                               assistant_metadata={'route': 'web', 'sources': ['kept']})
        rows=self.store.messages(self.cid)['messages']
        self.message=next(r for r in rows if r['role']=='assistant')
        self.user=next(r for r in rows if r['role']=='user')

    def test_plain_answer_rating_persists_and_undo_preserves_other_metadata(self):
        result=self.store.answer_feedback(self.cid,self.message['id'],'correct')
        self.assertTrue(result['can_undo'])
        reloaded=ConversationStore(EveDatabase(self.db.path))
        meta=reloaded.messages(self.cid)['messages'][-1]['metadata']
        self.assertEqual('correct',meta['answer_feedback']['decision'])
        self.assertEqual(['kept'],meta['sources'])
        reloaded.answer_feedback(self.cid,self.message['id'],'undo')
        meta=reloaded.messages(self.cid)['messages'][-1]['metadata']
        self.assertNotIn('answer_feedback',meta)
        self.assertEqual('web',meta['route'])
        with self.db.connect() as c:
            self.assertEqual(2,c.execute("SELECT count(*) FROM audit_events WHERE event_type='answer_feedback'").fetchone()[0])
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_negative_vote_is_one_click_and_explanation_can_be_added_or_changed(self):
        self.store.answer_feedback(self.cid,self.message['id'],'incorrect')
        explanation='Korrektur '*300
        self.store.answer_feedback(self.cid,self.message['id'],'incorrect',explanation)
        meta=self.store.messages(self.cid)['messages'][-1]['metadata']
        self.assertEqual(explanation.strip(),meta['answer_feedback']['explanation'])
        self.store.answer_feedback(self.cid,self.message['id'],'incorrect','Andere Erklärung')
        self.assertEqual('Andere Erklärung',self.store.messages(self.cid)['messages'][-1]['metadata']['answer_feedback']['explanation'])

    def test_duplicate_vote_and_undo_are_idempotent(self):
        for _ in range(2):self.store.answer_feedback(self.cid,self.message['id'],'correct')
        for _ in range(2):self.store.answer_feedback(self.cid,self.message['id'],'undo')
        with self.db.connect() as c:self.assertEqual(2,c.execute("SELECT count(*) FROM audit_events WHERE event_type='answer_feedback'").fetchone()[0])

    def test_rating_cannot_target_user_message_or_another_chat(self):
        other=self.store.create()['id']
        for cid,mid in ((self.cid,self.user['id']),(other,self.message['id'])):
            with self.assertRaises(KeyError):self.store.answer_feedback(cid,mid,'correct')
        with self.assertRaises(ValueError):self.store.answer_feedback(self.cid,self.message['id'],'other')
        with self.assertRaises(ValueError):self.store.answer_feedback(self.cid,self.message['id'],'correct','explanation')

    def test_existing_semantic_feedback_must_use_its_own_reversible_transaction(self):
        with self.db.connect() as c:
            c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                      (json.dumps({'semantic_feedback':{'status':'active','decision':'correct'}}),self.message['id']))
        with self.assertRaises(ValueError):self.store.answer_feedback(self.cid,self.message['id'],'undo')
