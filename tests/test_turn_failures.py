import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.turn_failures import failure_report
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.llm import LocalLLMError, LocalLLMStreamError


class TurnFailureTest(unittest.TestCase):
    def test_typed_empty_response_and_server_grounded_continuation(self):
        from eve_agent.llm import EmptyModelResponseError
        from eve_agent.turn_failures import resume_failure_request
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(EveDatabase(Path(tmp) / 'eve.db'))
            cid = store.create()['id']
            report = failure_report(EmptyModelResponseError(finish_reason='stop', stream_done=True, reasoning_chars=123),
                                    turn_id='empty', input_text='Originalauftrag', conversation_id=cid)
            store.record_failure(cid, report)
            text, loaded = resume_failure_request(store, cid, {'source_turn_id': 'empty', 'correction': ''})
            self.assertTrue(text.startswith('Originalauftrag'))
            self.assertIn('"reasoning_chars": 123', text)
            self.assertTrue(loaded['resumable'])
            self.assertIn('genaue Servergrund', loaded['reason'])
            store.record_retry(cid, 'continuation', 'empty', '')
            with self.assertRaises(ValueError):
                resume_failure_request(store, store.create()['id'], {'source_turn_id': 'empty', 'correction': ''})
            self.assertEqual('empty_model_response', store.failures(cid)[0]['category'])

    def test_stream_mismatch_has_understandable_reason(self):
        from eve_agent.answer_stream import AnswerStreamMismatchError
        for error in (AnswerStreamMismatchError("A", "B"), RuntimeError(
            "Der finale Antworttext stimmt nicht mit dem veröffentlichten Stream überein")):
            report = failure_report(error)
            self.assertEqual("answer_stream_mismatch", report["category"])
            self.assertIn("ausgegebene Antwort", report["reason"])
            self.assertNotIn("unbekannt", report["reason"])

    def test_existing_unknown_stream_error_card_is_classified_when_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ConversationStore(EveDatabase(Path(tmp)/"eve.db"))
            cid=store.create()["id"]
            report=failure_report(RuntimeError("unclassified"),turn_id="old",conversation_id=cid)
            report["technical"]="RuntimeError: Der finale Antworttext stimmt nicht mit dem veröffentlichten Stream überein"
            store.record_failure(cid,report)
            loaded=store.failures(cid)[0]
            self.assertEqual("answer_stream_mismatch",loaded["category"])
            self.assertNotIn("unbekannt",loaded["reason"])

    def test_empty_model_response_keeps_unknown_cause_and_real_last_result(self):
        report = failure_report(
            LocalLLMError('Das lokale LLM lieferte weder Antwort noch Tool-Aufruf.'),
            turn_id='failed-turn', input_text='Welche Lichter?',
            tool_events=[{'tool':'home_assistant','operation':'http_request','status':'completed',
                          'result':{'request':{'path':'/api/states'},
                                    'response':{'status':200,'body':[{}]*1164}}}],
        )
        self.assertEqual('empty_model_response',report['category'])
        self.assertIn('genaue Servergrund',report['reason'])
        self.assertEqual(1164,report['last_step']['result_count'])
        self.assertNotIn('Kontextfenster',report['reason'])
        self.assertNotIn('nur Daten gelesen',json.dumps(report))

    def test_old_card_gets_scoped_activity_on_read_without_rewriting_its_cause(self):
        from eve_agent.working_memory import WorkingMemoryStore
        with tempfile.TemporaryDirectory() as tmp:
            db=EveDatabase(Path(tmp)/'eve.db');conversations=ConversationStore(db)
            cid=conversations.create()['id'];work=WorkingMemoryStore(db);workspace=work.open(cid)
            turn,_=work.begin_turn(workspace,cid,{'text':'Auftrag'},'trace')
            report=failure_report(LocalLLMError('Das lokale LLM lieferte weder Antwort noch Tool-Aufruf.'),conversation_id=cid)
            report['working_memory']={'workspace_id':workspace,'work_turn_id':turn}
            conversations.record_failure(cid,report)
            work.finish_turn(workspace,turn,'failed',{'message':'unknown'})
            work.checkpoint(workspace,{'later':'unrelated to the failure'},expected_revision=0)
            loaded=conversations.failures(cid)[0]
            self.assertTrue(loaded['execution_observation']['checkpoint_missing'])
            self.assertEqual(report['reason'],loaded['reason'])
            with db.connect() as c:
                raw=json.loads(c.execute("SELECT details_json FROM audit_events WHERE event_type='turn_failure'").fetchone()[0])
            self.assertNotIn('execution_observation',raw)
            other=conversations.create()['id'];report['turn_id']='other';report['conversation_id']=other
            conversations.record_failure(other,report)
            self.assertNotIn('execution_observation',conversations.failures(other)[0])

    def test_repeat_observation_does_not_become_an_explanation_for_model_failure(self):
        activity={'repeated_material_selections':42,'fresh_contexts':29,'checkpoint_missing':True,'task_progress_assessed':False}
        report=failure_report(LocalLLMError('Das lokale LLM lieferte weder Antwort noch Tool-Aufruf.'),working_activity=activity)
        self.assertEqual(activity,report['execution_observation'])
        self.assertEqual('empty_model_response',report['category'])
        self.assertIn('genaue Servergrund',report['reason'])
        self.assertNotIn('Berechtigung',report['reason'])

    def test_confirmed_server_context_error_is_classified(self):
        report=failure_report(LocalLLMStreamError({
            'type':'exceed_context_size_error','message':'Too many tokens'}))
        self.assertEqual('context_limit',report['category'])
        self.assertIn('Kontextfenster',report['reason'])

    def test_failure_is_persistent_idempotent_and_not_an_assistant_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=EveDatabase(Path(tmp)/'eve.db')
            store=ConversationStore(database)
            cid=store.create()['id']
            report=failure_report(RuntimeError('failed'),turn_id='one',input_text='Aufgabe',conversation_id=cid)
            store.record_failure(cid,report)
            store.record_failure(cid,report)
            reopened=ConversationStore(EveDatabase(database.path))
            self.assertEqual([report],reopened.failures(cid))
            self.assertEqual([],reopened.messages(cid)['messages'])


if __name__=='__main__': unittest.main()
