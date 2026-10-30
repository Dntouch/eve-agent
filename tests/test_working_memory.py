import base64
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from eve_agent.agent import EveAgent
from eve_agent.context_budget import WorkingContextBudgetError, anthropic_count_request
from eve_agent.llm import LocalLLMContextLimitError
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.minimal import NativeToolRuntime, CORE_PROMPT
from eve_agent.state import StateBus
from eve_agent.storage import ConversationStore, EveDatabase, SCHEMA_VERSION
from eve_agent.working_memory import WorkingMemoryStore


def call(name, arguments=None, identifier=None):
    return {'content': '', 'tool_calls': [{'id': identifier or name, 'name': name, 'arguments': arguments or {}}]}


class WorkingMemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = EveDatabase(self.root/'eve.db')
        self.conversations = ConversationStore(self.db)
        self.conversation = self.conversations.create()['id']
        self.store = WorkingMemoryStore(self.db)
        self.workspace = self.store.open(self.conversation)

    def test_pointer_failure_reports_array_boundary_and_roundtrippable_selectors(self):
        from eve_agent.working_memory import WorkingSelectionError
        obj = self.store.put(self.workspace, {'a/b': {'x~y': [
            {'info': {'display': None}, 'info.display': 'literal', 'a/b': 3}]}})
        self.assertEqual('working_material', obj['reference_kind'])
        with self.assertRaises(WorkingSelectionError) as caught:
            self.store.read(self.workspace, obj['reference'], pointer='/a~1b/x~0y~0')
        self.assertEqual('/a~1b', caught.exception.structure['resolved_pointer'])
        with self.assertRaises(WorkingSelectionError) as caught:
            self.store.read(self.workspace, obj['reference'], pointer='/a~1b/x~0y/nope')
        diagnostic = caught.exception.structure
        self.assertEqual('/a~1b/x~0y', diagnostic['resolved_pointer'])
        self.assertEqual('array', diagnostic['container']['type'])
        self.assertEqual([0, 0], diagnostic['valid_index_range'])
        item = self.store.read(self.workspace, obj['reference'], pointer='/a~1b/x~0y/0')['content']
        result = self.store.read(self.workspace, obj['reference'], pointer='/a~1b/x~0y', fields=['wrong'])
        selectors = result['projection_diagnostics']['available_field_selectors']
        self.assertIn('/info/display', selectors)
        self.assertIn('/info.display', selectors)
        self.assertIn('/a~1b', selectors)
        for selector in selectors:
            self.store.field(item, selector)
        corrected = self.store.read(self.workspace, obj['reference'], pointer='/a~1b/x~0y',
                                    fields=['/info/display', '/info.display'])
        self.assertTrue(corrected['projection_complete'])
        self.assertEqual([{'/info/display': None, '/info.display': 'literal'}], corrected['content'])

    def test_explicit_filters_and_projection_diagnostics(self):
        obj = self.store.put(self.workspace, {'payload': [
            {'key': 'alpha.one', 'details': {'label': None}, 'details.label': 'literal'},
            {'key': 'alpha.two', 'details': {'label': 'Two'}},
            {'key': 'beta.three'},
        ]})
        result = self.store.read(self.workspace, obj['reference'], pointer='/payload',
            filters=[{'field': 'key', 'op': 'starts_with', 'value': 'alpha.'}],
            fields=['key', '/details/label', 'details.label'])
        self.assertEqual(2, result['total_matches'])
        self.assertIsNone(result['content'][0]['/details/label'])
        self.assertEqual('literal', result['content'][0]['details.label'])
        self.assertEqual([{'item_index': 1, 'field': 'details.label'}], result['missing_fields'])
        self.assertEqual('error', result['status'])
        self.assertEqual('WorkingProjectionError', result['error_class'])
        self.assertFalse(result['projection_complete'])
        self.assertEqual('literal_key', result['projection_diagnostics']['field_selector_kinds']['details.label'])
        self.assertIn('/details/label', result['projection_diagnostics']['available_field_paths_union'])
        corrected = self.store.read(self.workspace, obj['reference'], pointer='/payload',
            filters=[{'field': 'key', 'op': 'starts_with', 'value': 'alpha.'}], fields=['key', '/details/label'])
        self.assertTrue(corrected['projection_complete'])
        self.assertEqual([], corrected['missing_fields'])
        self.assertEqual('Two', corrected['content'][1]['/details/label'])
        exact = self.store.read(self.workspace, obj['reference'], pointer='/payload', where={'key': 'alpha.'})
        self.assertEqual(0, exact['total_matches'])
        combined = self.store.read(self.workspace, obj['reference'], pointer='/payload',
            where={'key': 'alpha.two'}, filters=[{'field': '/details/label', 'op': 'eq', 'value': 'Two'}])
        self.assertEqual(1, combined['total_matches'])
        with self.assertRaises(ValueError):
            self.store.read(self.workspace, obj['reference'], pointer='/payload',
                filters=[{'field': 'key', 'op': 'guess', 'value': 'alpha'}])

    def test_filter_type_error_identifies_constraint_without_selecting_a_list(self):
        from eve_agent.working_memory import WorkingSelectionError
        obj = self.store.put(self.workspace, {'a': [1], 'nested': {'b': [2]}})
        with self.assertRaises(WorkingSelectionError) as caught:
            self.store.read(self.workspace, obj['reference'], where={'id': 1})
        info = caught.exception.structure
        self.assertEqual('filter_requires_array', info['constraint'])
        self.assertEqual('', info['requested_pointer'])
        self.assertEqual('object', info['actual_type'])
        self.assertEqual('array', info['required_type'])
        self.assertEqual(['/a', '/nested/b'], info['array_pointers'])
        self.assertNotIn('suggested_pointer', info)

    def test_observation_identity_resolves_only_the_same_working_original(self):
        obj=self.store.put(self.workspace,{'rows':[{'id':1}]})
        self.assertEqual(self.store.value(self.workspace,obj['reference']),
                         self.store.value(self.workspace,obj['observation_id']))
        self.assertEqual(obj['reference'],self.store.describe(self.workspace,obj['observation_id'])['reference'])
        checkpoint=self.store.checkpoint(self.workspace,{'evidence':obj['observation_id']},expected_revision=0,
                                         references=[obj['reference'],obj['observation_id']])
        with self.db.connect() as c:
            links=c.execute('SELECT to_id FROM memory_work_links WHERE from_id=?',
                            (checkpoint['checkpoint']['reference'],)).fetchall()
        self.assertEqual([obj['reference']],[r[0] for r in links])
        other=self.store.open(self.conversations.create()['id'])
        with self.assertRaises(KeyError):self.store.value(other,obj['observation_id'])
        with self.assertRaises(ValueError):self.store.checkpoint(other,{},expected_revision=0,references=[obj['observation_id']])

    def test_structure_exposes_wrapped_list_and_never_samples_array_elements(self):
        original = {'response': {'result': [{'a/b': 1}, {'different': 2}]}, 'secret': 'not in outline'}
        obj = self.store.put(self.workspace, original)
        result = self.store.inspect(self.workspace, obj['reference'])
        paths = {i['pointer']: i for i in result['items']}
        self.assertEqual({'pointer':'/response/result','type':'array','length':2},paths['/response/result'])
        self.assertNotIn('not in outline',json.dumps(result))
        self.assertNotIn('/response/result/0',paths)
        element = self.store.inspect(self.workspace,obj['reference'],pointer='/response/result/0')
        self.assertIn('/response/result/0/a~1b',[i['pointer'] for i in element['items']])
        self.assertEqual(original,self.store.value(self.workspace,obj['reference']))

    def test_invalid_pointer_exposes_actual_structure_without_guessing_a_replacement(self):
        from eve_agent.working_memory import WorkingSelectionError
        obj=self.store.put(self.workspace,{'a/b':{'rows':[{'id':1}]}})
        with self.assertRaises(WorkingSelectionError) as caught:
            self.store.read(self.workspace,obj['reference'],pointer='/wrong')
        self.assertEqual('/wrong',caught.exception.structure['requested_pointer'])
        self.assertIn('/a~1b/rows',[i['pointer'] for i in caught.exception.structure['items']])
        self.assertNotIn('suggested_pointer',caught.exception.structure)

    def test_structure_is_uncapped_and_can_be_paged(self):
        obj=self.store.put(self.workspace,{str(i): [] for i in range(1700)})
        full=self.store.inspect(self.workspace,obj['reference'])
        self.assertEqual(1701,len(full['items']))
        page=self.store.inspect(self.workspace,obj['reference'],offset=100,limit=10)
        self.assertEqual(full['items'][100:110],page['items'])
        self.assertEqual(110,page['next_offset'])
        other=self.store.open(self.conversations.create()['id'])
        with self.assertRaises(KeyError):self.store.inspect(other,obj['reference'])

    def test_wrong_filter_returns_actual_list_path_and_targeted_read_works(self):
        from eve_agent.working_memory import WorkingSelectionError
        original={'status':'completed','response':{'result':[{'id':i,'proof':str(i)} for i in range(1164)]}}
        obj=self.store.put(self.workspace,original)
        with self.assertRaises(WorkingSelectionError) as caught:
            self.store.read(self.workspace,obj['reference'],where={'id':1163})
        self.assertIn('/response/result',[v['pointer'] for v in caught.exception.structure['items']])
        result=self.store.read(self.workspace,obj['reference'],pointer='/response/result',where={'id':1163},fields=['proof'])
        self.assertEqual([{'proof':'1163'}],result['content'])
        self.assertEqual(original,self.store.value(self.workspace,obj['reference']))

    def test_exact_repeat_is_observable_without_forbidding_retry_or_assessing_task(self):
        obj=self.store.put(self.workspace,{'rows':[1,2]})
        turn,_=self.store.begin_turn(self.workspace,self.conversation,{},'trace')
        params={'reference':obj['reference'],'pointer':'/rows'}
        for i in range(4):
            observation=self.store.retrieval_observation(self.workspace,'read',params)
            self.assertEqual(i,observation['previous_identical_selections'])
            call_id=self.store.start_call(self.workspace,turn,str(i),'working_memory','read','read',params)
            self.store.dispatch_call(self.workspace,call_id)
            self.store.finish_call(self.workspace,turn,call_id,self.store.read(self.workspace,**params))
        restarted=WorkingMemoryStore(EveDatabase(self.root/'eve.db'))
        self.assertEqual(4,restarted.retrieval_observation(self.workspace,'read',params)['previous_identical_selections'])
        activity=restarted.activity(self.workspace,turn_id=turn)
        self.assertEqual(3,activity['repeated_material_selections'])
        self.assertFalse(activity['task_progress_assessed'])
        self.assertTrue(activity['checkpoint_missing'])
        self.assertEqual(0,restarted.retrieval_observation(self.workspace,'read',{**params,'offset':1})['previous_identical_selections'])

    def test_original_json_and_binary_are_in_database_and_survive_restart(self):
        original = {'data': [{'text': 'ä'*5000, 'number': i} for i in range(1200)]}
        obj = self.store.put(self.workspace, original, source='tool')
        raw = bytes(range(256))*100
        binary = self.store.put(self.workspace, raw, media_type='image/png')
        restarted = WorkingMemoryStore(EveDatabase(self.root/'eve.db'))
        self.assertEqual(original, restarted.value(self.workspace, obj['reference']))
        self.assertEqual(raw, restarted.value(self.workspace, binary['reference']))
        self.assertEqual(base64.b64encode(raw).decode(), restarted.read(self.workspace,binary['reference'])['content'])
        self.assertFalse(any(p.suffix in {'.json','.md','.png','.bin'} for p in self.root.rglob('*')))
        with self.db.connect() as c:
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(2,c.execute('SELECT count(*) FROM memory_observations').fetchone()[0])

    def test_same_content_through_new_read_receipts_has_one_original_identity(self):
        original = self.store.put(self.workspace, {'stdout': 'identical failure output'})
        turn, _ = self.store.begin_turn(self.workspace, self.conversation, {}, 'read-chain')
        reference, pointer = original['reference'], '/stdout'
        identities = []
        for number in range(3):
            parameters = {'reference': reference, 'pointer': pointer}
            observed = self.store.retrieval_observation(self.workspace, 'read', parameters)
            self.assertEqual(number, observed['previous_identical_content_reads'])
            self.assertEqual(0, observed['previous_identical_selections'])
            self.assertEqual(original['reference'], observed['origin_reference'])
            result = self.store.read(self.workspace, **parameters)
            identities.append(self.store.read_identity(self.workspace, parameters, result))
            call_id = self.store.start_call(self.workspace, turn, str(number), 'working_memory', 'read', 'read', parameters)
            self.store.dispatch_call(self.workspace, call_id)
            receipt = self.store.finish_call(self.workspace, turn, call_id, result)
            reference, pointer = receipt['reference'], '/content'
        self.assertEqual(1, len(set(identities)))
        restarted = WorkingMemoryStore(EveDatabase(self.root / 'eve.db'))
        self.assertEqual(2, restarted.activity(self.workspace, turn_id=turn)['repeated_content_reads'])
        different = self.store.put(self.workspace, {'stdout': 'identical failure output'})
        result = self.store.read(self.workspace, different['reference'], pointer='/stdout')
        self.assertNotEqual(identities[0], self.store.read_identity(self.workspace,
            {'reference': different['reference'], 'pointer': '/stdout'}, result))

    def test_no_default_material_limit_and_exact_filter_projection_paging(self):
        obj = self.store.put(self.workspace, {'rows': [{'type':'x' if i%2 else 'y','nested':{'id':i}} for i in range(1164)]})
        all_rows = self.store.read(self.workspace,obj['reference'],pointer='/rows')
        self.assertEqual(1164,all_rows['returned']); self.assertTrue(all_rows['complete'])
        selected = self.store.read(self.workspace,obj['reference'],pointer='/rows',where={'/type':'x'},fields=['/nested/id'],offset=2,limit=3)
        self.assertEqual([{'/nested/id':5},{'/nested/id':7},{'/nested/id':9}],selected['content'])
        self.assertEqual(582,selected['total_matches']); self.assertEqual(5,selected['next_offset'])
        self.assertFalse(selected['complete'])

    def test_literal_property_selectors_do_not_silently_return_empty_results(self):
        obj = self.store.put(self.workspace, {'rows': [{'id': 1163, 'proof': 'abc'}]})
        result = self.store.read(self.workspace, obj['reference'], pointer='/rows',
                                 where={'id': 1163}, fields=['proof'])
        self.assertEqual([{'proof': 'abc'}], result['content'])

    def test_pagination_snapshot_does_not_expand_with_its_own_journal(self):
        for i in range(5): self.store.put(self.workspace, {'original': i})
        first = self.store.list_objects(self.workspace, limit=2)
        self.store.put(self.workspace, {'new': 6}, kind='tool_result')
        second = self.store.list_objects(self.workspace, offset=2, limit=3, snapshot=first['snapshot'])
        self.assertEqual(5, second['total_matches']); self.assertFalse(second['has_more'])
        self.assertEqual(6, self.store.list_objects(self.workspace)['total_matches'])

    def test_json_pointer_escaping_and_invalid_selection(self):
        obj=self.store.put(self.workspace,{'a/b':{'~key':[7]}})
        self.assertEqual([7],self.store.read(self.workspace,obj['reference'],pointer='/a~1b/~0key')['content'])
        with self.assertRaises(ValueError):self.store.read(self.workspace,obj['reference'],pointer='a/b')
        with self.assertRaises(ValueError):self.store.read(self.workspace,obj['reference'],offset=-1)

    def test_lexical_search_and_workspace_isolation(self):
        one=self.store.put(self.workspace,{'text':'Originaldokument Zebra'},title='Quelle')
        other=self.store.open(self.conversations.create()['id'])
        two=self.store.put(other,{'text':'Zebra aus anderem Auftrag'})
        self.assertEqual([one['reference']],[x['reference'] for x in self.store.list_objects(self.workspace,query='Zebra')['items']])
        with self.assertRaises(KeyError):self.store.value(self.workspace,two['reference'])
        with self.assertRaises(ValueError):self.store.checkpoint(self.workspace,{},expected_revision=0,references=[two['reference']])

    def test_checkpoint_versions_are_atomic_and_not_verified_claims(self):
        source=self.store.put(self.workspace,{'source':'abc'},source='user')
        first=self.store.checkpoint(self.workspace,{'hypothesis':'unbestätigt','user_constraint':'Nur beschreiben'},expected_revision=0,references=[source['reference']])
        before=self.store.list_objects(self.workspace)['total_matches']
        with self.assertRaises(ValueError):self.store.checkpoint(self.workspace,{'bad':'stale'},expected_revision=0)
        self.assertEqual(before,self.store.list_objects(self.workspace)['total_matches'])
        entry=self.store.manifest(self.workspace)
        self.assertEqual(first['checkpoint']['reference'],entry['checkpoint_reference'])
        self.assertFalse(entry['checkpoint_is_verified_fact'])
        with self.db.connect() as c:self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_running_call_is_uncertain_not_success_after_process_restart(self):
        turn,_=self.store.begin_turn(self.workspace,self.conversation,{'text':'Auftrag'},'trace')
        identifier=self.store.start_call(self.workspace,turn,'c1','provider','write','write',{'value':7})
        self.assertEqual([],self.store.manifest(self.workspace)['uncertain_calls'])
        self.store.dispatch_call(self.workspace,identifier)
        restarted=WorkingMemoryStore(EveDatabase(self.root/'eve.db'))
        unknown=restarted.manifest(self.workspace)['uncertain_calls']
        self.assertEqual('started',unknown[0]['status']);self.assertIsNone(unknown[0]['result_id'])
        result=restarted.finish_call(self.workspace,turn,identifier,{'status':'error','message':'not verified'})
        self.assertEqual([],restarted.manifest(self.workspace)['uncertain_calls'])
        self.assertEqual('error',restarted.value(self.workspace,result['reference'])['status'])

    def test_uncertain_write_requires_explicit_model_review_before_identical_dispatch(self):
        from eve_agent.working_memory import UncertainCallError
        turn, request = self.store.begin_turn(self.workspace,self.conversation,{'text':'Auftrag'},'trace')
        first = self.store.start_call(self.workspace,turn,'first','provider','write','write',{'value':7})
        self.store.dispatch_call(self.workspace,first)
        second = self.store.start_call(self.workspace,turn,'second','provider','write','write',{'value':7})
        with self.assertRaises(UncertainCallError):self.store.dispatch_call(self.workspace,second)
        review = self.store.review_call(self.workspace,first,'Nach Prüfung neu versuchen',[request['reference']],allow_retry=True,turn_id=turn)
        self.store.dispatch_call(self.workspace,second)
        self.assertTrue(review['original_outcome_remains_unverified'])
        self.assertEqual(2,len(self.store.manifest(self.workspace)['uncertain_calls']))
        self.store.review_call(self.workspace,first,'Nicht erneut versuchen',[request['reference']],allow_retry=False,turn_id=turn)
        third = self.store.start_call(self.workspace,turn,'third','provider','write','write',{'value':7})
        with self.assertRaises(UncertainCallError): self.store.dispatch_call(self.workspace,third)
        with self.db.connect() as c:self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_failed_finish_call_rolls_back_original_and_index(self):
        turn,_=self.store.begin_turn(self.workspace,self.conversation,{},'trace')
        before=self.store.list_objects(self.workspace)['total_matches']
        with self.assertRaises(KeyError):self.store.finish_call(self.workspace,turn,'missing',{'value':'rollback'})
        self.assertEqual(before,self.store.list_objects(self.workspace)['total_matches'])
        self.assertEqual([],self.store.list_objects(self.workspace,query='rollback')['items'])

    def test_completed_and_archived_material_is_retained(self):
        obj=self.store.put(self.workspace,{'original':'stays'})
        self.store.set_status(self.workspace,'completed');self.store.set_status(self.workspace,'archived')
        self.assertEqual({'original':'stays'},self.store.value(self.workspace,obj['reference']))
        self.assertEqual(self.workspace,self.store.open(self.conversation))

    def test_cleanup_uses_configured_retention_classes_and_protections(self):
        now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        config = {
            'completed_retention_hours': 1,
            'failed_retention_hours': 24,
            'temporary_learning_retention_hours': .25,
        }

        def finished(age_hours, *, status='completed', retention_class='standard', pinned=False):
            workspace = self.store.create(retention_class=retention_class)
            turn, _ = self.store.begin_turn(workspace, self.conversation, {'request': workspace}, workspace)
            self.store.finish_turn(workspace, turn, status, {'result': status})
            if pinned:
                self.store.set_pinned(workspace, True)
            stamp = (now - timedelta(hours=age_hours)).isoformat()
            with self.db.connect(lifecycle_audit=False) as c:
                c.execute('UPDATE memory_workspaces SET updated_at=?,last_accessed_at=? WHERE id=?',
                          (stamp, stamp, workspace))
            return workspace

        expired = finished(2)
        recent = finished(.5)
        failed_recent = finished(2, status='failed')
        failed_expired = finished(25, status='failed')
        temporary = finished(.3, retention_class='temporary_learning')
        pinned = finished(48, pinned=True)
        running = self.store.create()
        self.store.begin_turn(running, self.conversation, {}, 'running')
        with self.db.connect(lifecycle_audit=False) as c:
            stamp = (now - timedelta(hours=48)).isoformat()
            c.execute('UPDATE memory_workspaces SET updated_at=?,last_accessed_at=? WHERE id=?',
                      (stamp, stamp, running))

        preview = self.store.cleanup(config, dry_run=True, now=now)
        self.assertEqual(3, preview['eligible_workspaces'])
        self.assertEqual({expired, failed_expired, temporary},
                         {item['workspace_id'] for item in preview['candidates']})
        self.assertEqual(0, preview['deleted_workspaces'])

        result = self.store.cleanup(config, now=now)
        self.assertEqual(3, result['deleted_workspaces'])
        remaining = {item['workspace_id'] for item in self.store.workspaces()['items']}
        self.assertTrue({recent, failed_recent, pinned, running}.issubset(remaining))
        self.assertFalse({expired, failed_expired, temporary} & remaining)
        with self.db.connect(lifecycle_audit=False) as c:
            self.assertEqual(0, c.execute('PRAGMA foreign_key_check').fetchall().__len__())
            self.assertEqual(2, c.execute('SELECT count(*) FROM memory_work_cleanup_runs').fetchone()[0])

    def test_started_external_call_is_never_cleaned_automatically(self):
        now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        workspace = self.store.create()
        turn, _ = self.store.begin_turn(workspace, self.conversation, {}, 'trace')
        call_id = self.store.start_call(workspace, turn, 'call', 'provider', 'write', 'write', {})
        self.store.dispatch_call(workspace, call_id)
        self.store.finish_turn(workspace, turn, 'failed', {'message': 'unknown'})
        old = (now - timedelta(days=7)).isoformat()
        with self.db.connect(lifecycle_audit=False) as c:
            c.execute('UPDATE memory_workspaces SET updated_at=?,last_accessed_at=? WHERE id=?',
                      (old, old, workspace))
        result = self.store.cleanup({
            'completed_retention_hours': 1, 'failed_retention_hours': 24,
            'temporary_learning_retention_hours': .25,
        }, now=now)
        self.assertEqual(0, result['deleted_workspaces'])
        self.assertEqual(1, result['protected']['uncertain_call'])

    def test_v20_upgrade_preserves_existing_working_material(self):
        obj = self.store.put(self.workspace, {'original': 'preserve'})
        with self.db.connect(lifecycle_audit=False) as c:
            c.execute('DROP INDEX memory_work_events_turn')
            c.execute('PRAGMA user_version=20')
        upgraded = EveDatabase(self.root/'eve.db')
        self.assertEqual({'original':'preserve'},WorkingMemoryStore(upgraded).value(self.workspace,obj['reference']))
        with upgraded.connect() as c:
            self.assertEqual(SCHEMA_VERSION,c.execute('PRAGMA user_version').fetchone()[0])
            self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE name='memory_work_events_turn'").fetchone())

    def test_real_v19_migration_creates_backup_and_preserves_conversations(self):
        with self.db.connect(lifecycle_audit=False) as c:
            # Reconstruct the previous schema; no working material exists there.
            for table in ('memory_work_contexts','memory_work_call_reviews','memory_work_links','memory_work_events','memory_work_calls','memory_work_turns','memory_work_bindings','memory_work_objects','memory_work_fts','memory_workspaces'):
                c.execute('DROP TABLE '+table)
            c.execute('PRAGMA user_version=19')
        migrated=EveDatabase(self.root/'eve.db')
        self.assertEqual(self.conversation,ConversationStore(migrated).get(self.conversation)['id'])
        backups=list((self.root/'backups').glob('*.db'));self.assertEqual(1,len(backups))
        with closing(sqlite3.connect(backups[0])) as c:self.assertEqual(19,c.execute('PRAGMA user_version').fetchone()[0])
        with migrated.connect() as c:self.assertEqual(SCHEMA_VERSION,c.execute('PRAGMA user_version').fetchone()[0])


class WorkingRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=EveDatabase(self.root/'eve.db');self.conversations=ConversationStore(self.db)
        self.llm=SimpleNamespace(request_tool_turn=Mock(),generation_max_tokens=None,use_server_limits=True)
        memory=MemoryV2Runtime(self.db,MemoryCompiler(self.db))
        self.agent=EveAgent('EVE',memory,self.llm,StateBus(self.root/'runtime'),conversations=self.conversations)
        self.runtime=NativeToolRuntime(self.agent)

    def test_cancelled_request_images_and_tool_results_survive_reload(self):
        from eve_agent.backend_turns import TurnCancelled
        image = 'data:image/png;base64,' + base64.b64encode(b'original-image').decode()
        self.llm.request_tool_turn.side_effect = [
            call('eve__load_capabilities', {'capabilities': ['local_files']}),
            call('local_files__fetch'), TurnCancelled('Abbruch')]
        self.agent.local_files = SimpleNamespace(minimal_contract=lambda: {'description': 'fixture',
            'operations': {'fetch': {'effect': 'read', 'parameters_schema': {'type': 'object', 'properties': {}}}}},
            execute_operation=Mock(return_value={'original': 'kept'}))
        with self.assertRaises(TurnCancelled):
            self.runtime.respond('Kannst Du Dir mittels Shell helfen?', images=[image])
        session = self.runtime.working_session
        restarted = ConversationStore(EveDatabase(self.root / 'eve.db'))
        page = restarted.messages(self.agent.conversation_id)['messages']
        self.assertEqual(['user', 'assistant'], [m['role'] for m in page])
        self.assertEqual('Kannst Du Dir mittels Shell helfen?', page[0]['content'])
        self.assertEqual('Vorgang abgebrochen.', page[1]['content'])
        self.assertEqual('cancelled', page[1]['metadata']['runtime_status'])
        self.assertEqual(session.turn_id, page[1]['metadata']['working_memory']['work_turn_id'])
        self.assertEqual(('image/png', b'original-image'), restarted.read_asset(page[0]['attachments'][0]['id']))
        self.assertTrue(any(e['result'] == {'original': 'kept'} for e in page[1]['tool_events']))
        self.assertFalse(restarted.preserve_interrupted_turn(session.turn_id))
        self.assertEqual(2, len(restarted.messages(self.agent.conversation_id)['messages']))
        self.assertEqual(1, self.agent.local_files.execute_operation.call_count)

    def test_failed_request_remains_in_conversation_context(self):
        self.llm.request_tool_turn.side_effect = RuntimeError('Modell nicht erreichbar')
        with self.assertRaisesRegex(RuntimeError, 'Modell nicht erreichbar'):
            self.runtime.respond('Bitte prüfe mein Bild.')
        history = self.conversations.recent_history(self.agent.conversation_id)
        self.assertEqual(['Bitte prüfe mein Bild.', 'Vorgang fehlgeschlagen.'],
                         [m['content'].split('\n[')[0] for m in history])

    def test_isolated_learning_failure_does_not_create_chat_messages(self):
        from eve_agent.working_context import WorkingMemorySession
        self.agent.conversation_id = self.conversations.create()['id']
        session = WorkingMemorySession(self.agent, 'Internes Lernmaterial', [], 'isolated', isolated=True)
        session.finish('cancelled', {'message': 'Abbruch'})
        self.assertEqual([], self.conversations.messages(self.agent.conversation_id)['messages'])

    def test_live_followup_keeps_exact_attachment_reference_and_can_materialize_it(self):
        body = b'exact image bytes'
        image = 'data:image/png;base64,' + base64.b64encode(body).decode()
        self.llm.request_tool_turn.return_value = {'content': 'Bild erhalten.', 'tool_calls': []}
        self.runtime.respond('Hier das Bild.', images=[image])
        cid = self.agent.conversation_id
        asset = self.conversations.messages(cid)['messages'][0]['attachments'][0]['id']
        self.assertIn('asset:' + asset, self.agent.history[0]['content'])
        self.llm.request_tool_turn.side_effect = [
            call('eve__load_capabilities', {'capabilities': ['conversation_assets']}),
            call('conversation_assets__materialize', {'asset_id': asset}),
            {'content': 'Original als Datei verfügbar.', 'tool_calls': []}]
        self.runtime.respond('Nutze für dieses Bild die Shell.')
        messages = self.llm.request_tool_turn.call_args_list[-1].args[0]
        result = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
        self.assertEqual(body, Path(result['path']).read_bytes())
        self.assertEqual(asset, result['asset_id'])

    def budget(self,capacity):
        # Deterministic byte tokenizer for boundary tests, not production counting.
        def measure(messages,tools):
            size=len(json.dumps(messages,ensure_ascii=False).encode())+len(json.dumps(tools).encode())
            return {'fits':size<capacity,'input_tokens':size,'context_tokens':capacity,'remaining_tokens':capacity-size}
        self.llm.context_budget=measure

    def test_large_result_does_not_externalize_small_receipt_that_still_fits(self):
        from eve_agent.working_context import WorkingMemorySession
        self.agent.conversation_id = self.conversations.create('Evidence retention')['id']
        session = WorkingMemorySession(self.agent, 'Question', [], 'trace-receipts')
        self.budget(12000)
        small_value = {'items': [{'content': 'The explicitly corrected value is retained.'}]}
        large_value = {'items': ['x' * 50000]}
        frames = []
        descriptors = []
        for value in (small_value, large_value):
            descriptor = session.store.put(session.workspace_id, value, kind='tool_result')
            message = {'role': 'tool', 'tool_call_id': str(len(frames)), 'content': json.dumps(value)}
            session.tool_frame(message, descriptor)
            frames.append(message)
            descriptors.append(descriptor)
        session._externalize_tools(frames, tools=[])
        self.assertEqual(small_value, json.loads(frames[0]['content']))
        self.assertFalse(json.loads(frames[1]['content'])['content_in_context'])
        self.assertTrue(self.llm.context_budget(frames, [])['fits'])
        self.assertEqual(large_value, session.store.value(session.workspace_id, descriptors[1]['reference']))
        session.finish('completed', 'checked')

    def test_empty_model_response_is_archived_and_unchanged_recovery_stops(self):
        from eve_agent.llm import EmptyModelResponseError
        error = EmptyModelResponseError(finish_reason='stop', stream_done=True, reasoning_chars=42)
        self.llm.request_tool_turn.side_effect = error
        with self.assertRaises(EmptyModelResponseError):
            self.runtime.respond('Auftrag')
        self.assertEqual(2, self.llm.request_tool_turn.call_count)
        session = self.runtime.working_session
        with self.db.connect() as c:
            row = c.execute("SELECT o.structured_value_json,o.source_role FROM memory_work_objects w "
                            "JOIN memory_observations o ON o.id=w.observation_id "
                            "WHERE w.workspace_id=? AND w.kind='model_response_error'", (session.workspace_id,)).fetchone()
            status = c.execute('SELECT status FROM memory_work_turns WHERE id=?',(session.turn_id,)).fetchone()[0]
        self.assertEqual(error.response_evidence, json.loads(row[0]))
        self.assertEqual('system', row[1])
        self.assertEqual('failed', status)
        self.assertEqual(session.workspace_id, session.store.open(self.agent.conversation_id))

    def test_wrapped_original_is_discoverable_and_structural_error_is_in_tool_frame(self):
        self.budget(18000)
        original={'status':'completed','response':{'result':[{'id':i,'proof':str(i),'raw':'x'*1024} for i in range(1164)]}}
        self.agent.local_files=SimpleNamespace(minimal_contract=lambda:{'description':'fixture','operations':{
            'fetch':{'effect':'read','parameters_schema':{'type':'object','properties':{}}}}},
            execute_operation=Mock(return_value=original))
        selected={}
        def model(messages,tools,*a,**kw):
            n=self.llm.request_tool_turn.call_count
            if n==1:return call('eve__load_capabilities',{'capabilities':['local_files','working_memory']})
            if n==2:return call('local_files__fetch')
            if n==3:
                value=json.loads(messages[-1]['content'])
                selected['ref']=value['stored_result']['reference']
                self.assertIn('/response/result',[v['pointer'] for v in value['structure']['items']])
                return call('working_memory__read',{'reference':selected['ref'],'where':{'id':1163}},identifier='wrong-root')
            if n==4:
                value=json.loads(messages[-1]['content'])
                self.assertEqual('error',value['status'])
                selected['pointer']=next(v['pointer'] for v in value['structure']['items'] if v['type']=='array')
                return call('working_memory__read',{'reference':selected['ref'],'pointer':selected['pointer'],
                                                  'where':{'id':1163},'fields':['proof']},identifier='selected-list')
            self.assertEqual([{'proof':'1163'}],json.loads(messages[-1]['content'])['content'])
            return {'content':'1163','tool_calls':[]}
        self.llm.request_tool_turn.side_effect=model
        self.assertEqual('1163',self.runtime.respond('Prüfwert ermitteln'))
        self.assertEqual(1,self.agent.local_files.execute_operation.call_count)
        self.assertEqual(original,self.runtime.working_session.store.value(self.runtime.working_session.workspace_id,selected['ref']))

    def test_opening_current_workspace_does_not_restart_the_original_task(self):
        self.llm.request_tool_turn.return_value={'content':'Start','tool_calls':[]}
        self.runtime.respond('Auftrag')
        session=self.runtime.working_session
        turn=session.turn_id
        result=session.execute('open',{'workspace_id':session.workspace_id})
        self.assertTrue(result['already_current'])
        self.assertEqual(turn,session.turn_id)
        self.assertIsNone(session.pending_workspace)
        self.assertFalse(session.reset_requested)

    def test_fresh_context_publishes_missing_checkpoint_and_technical_activity(self):
        self.llm.request_tool_turn.side_effect=[call('eve__load_capabilities',{'capabilities':['working_memory']}),
            call('working_memory__reset_context'),{'content':'Fortsetzung','tool_calls':[]}]
        self.runtime.respond('Auftrag')
        messages=self.llm.request_tool_turn.call_args.args[0]
        data=json.loads(messages[2]['content'].split(': ',1)[1])
        self.assertTrue(data['execution_activity']['checkpoint_missing'])
        self.assertFalse(data['execution_activity']['task_progress_assessed'])
        self.assertIn('execution_journal_reference',data)
        self.assertNotIn('execution_journal',data)

    def test_scheduler_stays_callable_after_context_reset_with_many_targets(self):
        from eve_agent.scheduler import ScheduledTasks
        from eve_agent.transport_access import transport_access
        self.agent.reminders = ScheduledTasks(self.db, start_monitor=False)
        self.agent.reminders.output_targets_provider = lambda: [
            {'id': f'eve:conversation:{i:032x}', 'name': f'Chat {i}',
             'transport': 'eve', 'conversation_id': f'{i:032x}'} for i in range(1000)]
        self.budget(32768)
        context = {'transport': 'chatto', 'room_id': 'owner-room',
                   'room_kind': 'dm', 'access_profile': 'owner_dm'}

        def model(messages, tools, *args, **kwargs):
            self.assertTrue(self.llm.context_budget(messages, tools)['fits'])
            names = {tool['function']['name'] for tool in tools}
            round_number = self.llm.request_tool_turn.call_count
            if round_number == 1:
                return call('eve__load_capabilities', {'capabilities': ['scheduled_tasks', 'working_memory']})
            self.assertIn('scheduled_tasks__create', names)
            if round_number == 2:
                return call('working_memory__reset_context')
            if round_number == 3:
                fresh = json.loads(messages[2]['content'].split(': ', 1)[1])
                self.assertEqual('fresh', fresh['context'])
                self.assertTrue(fresh['transition']['requested_reset_completed'])
                return call('scheduled_tasks__create', {'name': 'Test-Erinnerung',
                    'request': 'Arbeiten gehen', 'schedule_type': 'delay', 'schedule': {'seconds': 3600}})
            self.assertEqual('active', json.loads(messages[-1]['content'])['status'])
            return {'content': 'Erinnerung angelegt.', 'tool_calls': []}

        self.llm.request_tool_turn.side_effect = model
        with transport_access(context):
            self.assertEqual('Erinnerung angelegt.', self.runtime.respond('Erinnere mich in einer Stunde.'))
            tasks = self.agent.reminders.list_tasks()
        self.assertEqual(4, self.llm.request_tool_turn.call_count)
        self.assertEqual(1, len(tasks))
        self.assertEqual('Arbeiten gehen', tasks[0]['action']['request'])
        self.assertEqual('owner-room', tasks[0]['action']['output_target']['room_id'])
        self.assertEqual('owner_dm', tasks[0]['action']['execution_context']['access_profile'])

    def test_huge_tool_result_is_durable_before_next_request_and_retrieved_selectively(self):
        # Fit the published tool schemas while keeping the original far above context capacity.
        self.budget(20000)
        original={'rows':[{'id':i,'label':'unmodified original '*30} for i in range(1164)]}
        provider=SimpleNamespace(minimal_contract=lambda:{'description':'fixture','operations':{
            'fetch':{'effect':'read','parameters_schema':{'type':'object','properties':{}}}}},
            execute_operation=lambda *a,**kw:original)
        self.agent.local_files=provider
        answers=[]
        def model(messages,tools,*a,**kw):
            answers.append(json.loads(json.dumps(messages)))
            n=len(answers)
            if n==1:return call('eve__load_capabilities',{'capabilities':['local_files','working_memory']})
            if n==2:return call('local_files__fetch')
            if n==3:
                event=json.loads(messages[-1]['content'])
                ref=event['stored_result']['reference']
                store=self.runtime.working_session.store;workspace=self.runtime.working_session.workspace_id
                self.assertEqual(original,store.value(workspace,ref))
                return call('working_memory__read',{'reference':ref,'pointer':'/rows','where':{'/id':1100},'fields':['/id']})
            self.assertEqual([{'/id':1100}],json.loads(messages[-1]['content'])['content'])
            return {'content':'Gefunden: 1100','tool_calls':[]}
        self.llm.request_tool_turn.side_effect=model
        self.assertEqual('Gefunden: 1100',self.runtime.respond('Lies die Originaldaten gezielt.'))
        self.assertEqual(4,len(answers))
        self.assertTrue(all(self.llm.context_budget(m,[])['fits'] for m in answers))

    def test_model_checkpoint_and_fresh_context_survive_new_agent(self):
        def model(messages,tools,*a,**kw):
            n=self.llm.request_tool_turn.call_count
            if n==1:return call('eve__load_capabilities',{'capabilities':['working_memory']})
            if n==2:return call('working_memory__checkpoint',{'expected_revision':0,'state':{
                'goal':'Auswahl klären','constraint':'Nichts schalten','hypothesis':'noch unbekannt'}})
            if n==3:return call('working_memory__reset_context')
            self.assertIn('Nichts schalten',json.dumps(messages,ensure_ascii=False))
            self.assertEqual(1,sum(m['role']=='system' for m in messages))
            return {'content':'Arbeitsstand gesichert.','tool_calls':[]}
        self.llm.request_tool_turn.side_effect=model
        self.runtime.respond('Nur besprechen.')
        workspace=self.runtime.working_session.workspace_id
        fresh_llm=SimpleNamespace(request_tool_turn=Mock(return_value={'content':'Ich fahre fort.','tool_calls':[]}),generation_max_tokens=None)
        fresh=EveAgent('EVE',MemoryV2Runtime(EveDatabase(self.root/'eve.db'),MemoryCompiler(self.db)),fresh_llm,
                       StateBus(self.root/'runtime2'),conversations=ConversationStore(self.db))
        runtime=NativeToolRuntime(fresh);runtime.respond('Bitte fortsetzen.')
        self.assertEqual(workspace,runtime.working_session.workspace_id)
        self.assertEqual('Nichts schalten',runtime.working_session.store.value(workspace,
            runtime.working_session.entry()['checkpoint_reference'])['constraint'])

    def test_oversized_read_stays_in_database_without_runtime_selected_page(self):
        self.budget(16000)
        pages=[]
        def model(messages,tools,*a,**kw):
            n=self.llm.request_tool_turn.call_count
            if n==1:return call('eve__load_capabilities',{'capabilities':['working_memory']})
            if n==2:
                s=self.runtime.working_session
                ref=s.store.put(s.workspace_id,list(range(10000)))['reference']
                return call('working_memory__read',{'reference':ref})
            page=json.loads(messages[-1]['content']);pages.append(page)
            return {'content':'Seite gelesen.','tool_calls':[]}
        self.llm.request_tool_turn.side_effect=model
        self.runtime.respond('Lies die Zahlen.')
        frame=pages[0]
        self.assertFalse(frame['content_in_context'])
        self.assertEqual('working_memory.inspect',frame['structure_access'])
        self.assertNotIn('next_offset',frame)
        self.assertNotIn('limit',frame['requested_selection'])
        session=self.runtime.working_session
        original=session.store.value(session.workspace_id,frame['requested_selection']['reference'])
        self.assertEqual(list(range(10000)),original)

    def test_failure_keeps_results_before_conversation_append_and_does_not_replay(self):
        self.agent.local_files=SimpleNamespace(minimal_contract=lambda:{'description':'fixture','operations':{
            'fetch':{'effect':'read','parameters_schema':{'type':'object','properties':{}}}}},
            execute_operation=Mock(return_value={'original':'kept'}))
        self.llm.request_tool_turn.side_effect=[call('eve__load_capabilities',{'capabilities':['local_files']}),
            call('local_files__fetch'),RuntimeError('aborted')]
        with self.assertRaisesRegex(RuntimeError,'aborted'):self.runtime.respond('Test')
        session=self.runtime.working_session
        originals=session.store.list_objects(session.workspace_id,kind='tool_result')['items']
        self.assertTrue(any(session.store.value(session.workspace_id,x['reference'])=={'original':'kept'} for x in originals))
        self.assertEqual('failed',session.store.manifest(session.workspace_id)['unfinished_turns'][0]['status'])
        self.assertEqual(1,self.agent.local_files.execute_operation.call_count)

    def test_provider_context_rejection_restarts_without_reexecuting_tools(self):
        self.llm.request_tool_turn.side_effect=[LocalLLMContextLimitError('actual server refusal'),
            {'content':'Fortgesetzt','tool_calls':[]}]
        self.assertEqual('Fortgesetzt',self.runtime.respond('Auftrag bleibt erhalten'))
        self.assertEqual(2,self.llm.request_tool_turn.call_count)

    def test_identical_fresh_context_refusal_stops_with_originals_retained(self):
        self.llm.request_tool_turn.side_effect=LocalLLMContextLimitError('still refused')
        with self.assertRaises(WorkingContextBudgetError):self.runtime.respond('Auftrag')
        self.assertEqual(2,self.llm.request_tool_turn.call_count)
        s=self.runtime.working_session
        self.assertEqual('Auftrag',s.store.value(s.workspace_id,s.request['reference'])['text'])

    def test_context_rejection_keeps_images_in_database_and_defers_them(self):
        from eve_agent.working_context import WorkingMemorySession
        session = WorkingMemorySession(self.agent, 'Bild prüfen', ['data:image/png;base64,AA=='], 'trace')
        session.recover([], LocalLLMContextLimitError('image tokens exceed context'))
        capabilities = {'working_memory': __import__('eve_agent.working_memory',fromlist=['contract']).contract()}
        state = {'loaded_capabilities': []}
        tools,_ = self.runtime._published_tools(capabilities, [])
        messages,_,_ = session.prepare([{'role':'system','content':CORE_PROMPT}],tools,capabilities,state,
                                        CORE_PROMPT,self.runtime._published_tools)
        self.assertFalse(any(isinstance(m.get('content'),list) for m in messages))
        self.assertIn('deferred_images_reference',json.dumps(messages))
        self.assertEqual(['data:image/png;base64,AA=='],session.store.value(session.workspace_id,session.request['reference'])['images'])

    def test_core_prompt_does_not_grow(self):
        self.assertLess(len(CORE_PROMPT.split()),50)


class CountingProtocolTest(unittest.TestCase):
    def test_text_tool_calls_and_schemas_are_preserved_for_server_count(self):
        messages=[{'role':'system','content':'EVE'}, {'role':'user','content':'Auftrag'},
                  {'role':'assistant','content':None,'tool_calls':[{'id':'a','function':{'name':'read','arguments':'{"offset":3}'}}]},
                  {'role':'tool','tool_call_id':'a','content':'Ergebnis'}]
        payload=anthropic_count_request(messages,[{'type':'function','function':{'name':'read','parameters':{'type':'object'}}}],
                                        'model',reasoning_effort='low')
        self.assertEqual('EVE',payload['system'])
        self.assertEqual({'offset':3},payload['messages'][1]['content'][0]['input'])
        self.assertEqual('Ergebnis',payload['messages'][2]['content'][0]['content'])
        self.assertEqual('low',payload['output_config']['effort'])
