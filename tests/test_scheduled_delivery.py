import tempfile
import json
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
from eve_agent.scheduler import ScheduledTasks
from eve_agent.storage import EveDatabase, ConversationStore
from eve_agent.transport_access import transport_access


class ScheduledDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = EveDatabase(Path(self.tmp.name) / 'eve.db')
        self.source = ConversationStore(self.database).create("Source")["id"]
        self.scheduler = ScheduledTasks(self.database, start_monitor=False)
        self.calls = []
        def execute(action):
            self.calls.append(action)
            return {'notification': {'message': 'Neuigkeiten', 'delivered': False,
                                    'task_id': action['task_id']},
                    'resources': [{'type': 'file', 'content': 'data:text/plain;base64,WA=='}]}
        self.scheduler.register_executor('eve_turn', execute)
        self.target = {'id': 'room:general', 'name': 'Allgemein', 'transport': 'chatto',
                       'server_url': 'https://chat.example', 'room_id': 'general'}
        self.scheduler.output_targets_provider = lambda: [dict(self.target)]

    def create(self, **extra):
        return self.scheduler.execute_operation('create', {
            'request': 'Prüfe Neuigkeiten', 'schedule_type': 'delay', 'schedule': {'seconds': 1},
            **extra}, conversation_id=self.source)['result']

    def due(self):
        with self.database.connect() as connection:
            connection.execute('UPDATE scheduled_tasks SET next_run_at=?',
                               ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))

    def test_current_target_and_authority_are_snapshotted(self):
        context = {'transport': 'chatto', 'room_id': 'general', 'thread_root_id': 'thread',
                   'access_profile': 'public_channel'}
        with transport_access(context, public=True):
            task = self.create()
        context['room_id'] = 'changed'
        self.assertEqual(task['action']['output_target']['room_id'], 'general')
        self.assertEqual(task['action']['execution_context']['thread_root_id'], 'thread')
        self.assertEqual(task['conversation_id'], self.source)

    def test_no_change_succeeds_without_any_delivery_and_advances_recurring_check(self):
        self.scheduler.register_executor('eve_turn', lambda action: {
            'outcome': 'no_change', 'reason': 'Keine meldepflichtige Änderung', 'resources': [],
            'turn': {'turn_id': 'check', 'conversation_id': self.source}})
        for target in ('current', 'room:general'):
            with self.subTest(target=target):
                task = self.scheduler.execute_operation('create', {
                    'request': 'Prüfe Neuigkeiten', 'schedule_type': 'interval', 'schedule': {'seconds': 3600},
                    'output_target_id': target}, conversation_id=self.source)['result']
                self.due()
                self.assertEqual([], self.scheduler.pop_due())
                self.assertEqual([], self.scheduler.claim_deliveries())
                with self.database.connect() as c:
                    run = c.execute('SELECT * FROM task_runs WHERE task_id=?', (task['id'],)).fetchone()
                    self.assertEqual(0, c.execute('SELECT count(*) FROM scheduled_deliveries').fetchone()[0])
                self.assertEqual('succeeded', run['status'])
                self.assertEqual('no_change', json.loads(run['result_json'])['outcome'])
                self.assertNotIn('notification', json.loads(run['result_json']))
                updated = self.scheduler.get_task(task['id'])
                self.assertEqual('active', updated['status'])
                self.assertGreater(updated['next_run_at'], run['scheduled_for'])
                self.scheduler.update_task(task['id'], {'status': 'paused'})
        restored = ScheduledTasks(self.database, start_monitor=False)
        self.assertEqual([], restored.pop_due())
        self.assertEqual([], restored.claim_deliveries())

    def test_explicit_target_is_validated_and_can_be_changed(self):
        task = self.create(output_target_id='room:general')
        self.assertEqual(task['action']['output_target'], self.target)
        self.scheduler.output_targets_provider = lambda: []
        with self.assertRaises(ValueError):
            self.create(output_target_id='room:general')
        self.scheduler.update_task(task['id'], {'output_target_id': 'current'})
        self.assertEqual(self.scheduler.get_task(task['id'])['action']['output_target']['transport'], 'eve')

    def test_channel_to_self_dm_preserves_origin_and_survives_restart_without_browser_output(self):
        from eve_agent.chatto import ChattoAPI
        from eve_agent.config import DEFAULTS
        api = ChattoAPI({**DEFAULTS['chatto'], 'enabled': True, 'server_url': 'https://chat.example',
                         'owner_user_id': 'owner', 'channel_ids': ['general'], 'member_dm_enabled': True},
                        ConversationStore(self.database), Mock())
        self.addCleanup(api.close)
        self.scheduler.output_targets_provider = api.output_targets
        context = dict(transport='chatto', server_url='https://chat.example', owner_id='owner', bot_id='eve',
                       room_id='general', room_kind='channel', sender_id='guest', message_id='m1',
                       thread_root_id='thread', access_profile='public_channel')
        with transport_access(context, public=True):
            task = self.create(output_target_id='chatto:dm:self')
            self.assertEqual(task['action']['execution_context'], context)
            self.assertEqual(task['action']['output_target']['recipient_user_id'], 'guest')
        with transport_access({**context, 'sender_id': 'someone-else'}, public=True):
            self.assertEqual(self.scheduler.list_tasks(), [])
            with self.assertRaises(PermissionError):
                self.scheduler.update_task(task['id'], {'output_target_id': 'current'})
        self.due()
        self.assertEqual(self.scheduler.pop_due(), [])
        restored = ScheduledTasks(self.database, start_monitor=False)
        delivery = restored.claim_deliveries()[0]
        self.assertEqual(delivery['target']['recipient_user_id'], 'guest')
        self.assertNotIn('thread_root_id', delivery['target'])
        self.assertEqual(len(self.calls), 1)

    def test_delivery_is_persistent_and_retry_does_not_execute_task(self):
        task = self.create(output_target_id='room:general')
        self.due()
        self.assertEqual(self.scheduler.pop_due(), [])
        restored = ScheduledTasks(self.database, start_monitor=False)
        deliveries = restored.claim_deliveries()
        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        self.assertEqual(delivery['payload']['resources'][0]['type'], 'file')
        self.assertEqual(restored.claim_deliveries(), [])
        restored.acknowledge_delivery(delivery['id'], 'blocked', 'No access', claim_token=delivery['claim_token'])
        restored.execute_operation('retry_delivery', {'task_id': task['id'], 'delivery_id': delivery['id']})
        retry = restored.claim_deliveries()[0]
        self.assertEqual(retry['id'], delivery['id'])
        self.assertEqual(len(self.calls), 1)
        restored.begin_delivery(retry['id'], retry['claim_token'])
        restored.acknowledge_delivery(retry['id'], 'uncertain', claim_token=retry['claim_token'])
        with self.assertRaises(ValueError):
            restored.execute_operation('retry_delivery', {'task_id': task['id'], 'delivery_id': delivery['id']})
        statuses = restored.execute_operation('list_deliveries', {'task_id': task['id']})['result']
        self.assertEqual(statuses[0]['status'], 'uncertain')

    def enqueue(self):
        task = self.create(output_target_id='room:general')
        self.due()
        self.assertEqual(self.scheduler.pop_due(), [])
        return task

    def test_only_confirmed_delivery_sets_delivered_and_never_leaks_to_browser(self):
        task = self.enqueue()
        delivery = self.scheduler.claim_deliveries()[0]
        def notification():
            with self.database.connect() as connection:
                row = connection.execute('SELECT result_json FROM task_runs WHERE id=?', (delivery['id'],)).fetchone()
            return json.loads(row['result_json'])['notification']
        self.assertFalse(notification()['delivered'])
        self.assertEqual(notification()['delivery_status'], 'claimed')
        self.assertEqual(self.scheduler.pop_due(), [])
        self.scheduler.begin_delivery(delivery['id'], delivery['claim_token'])
        self.assertFalse(notification()['delivered'])
        self.assertEqual(notification()['delivery_status'], 'sending')
        for _ in range(2):
            self.scheduler.acknowledge_delivery(delivery['id'], 'delivered', claim_token=delivery['claim_token'])
        self.assertTrue(notification()['delivered'])
        self.assertEqual(notification()['delivery_status'], 'delivered')
        self.assertEqual(len(self.calls), 1)

    def test_expired_unstarted_claim_recovers_with_new_token_and_fences_old_worker(self):
        self.enqueue()
        first = self.scheduler.claim_deliveries()[0]
        with self.database.connect() as connection:
            connection.execute('UPDATE scheduled_deliveries SET claim_until=0')
        with self.assertRaises(ValueError):
            self.scheduler.begin_delivery(first['id'], first['claim_token'])
        second = self.scheduler.claim_deliveries()[0]
        self.assertNotEqual(first['claim_token'], second['claim_token'])
        with self.assertRaises(ValueError):
            self.scheduler.begin_delivery(first['id'], first['claim_token'])
        for token in (None, first['claim_token']):
            with self.assertRaises(ValueError):
                self.scheduler.acknowledge_delivery(first['id'], 'delivered', claim_token=token)
        self.assertEqual(len(self.calls), 1)

    def test_restart_recovers_unstarted_claim_but_never_replays_started_send(self):
        task = self.enqueue()
        first = self.scheduler.claim_deliveries()[0]
        restored = ScheduledTasks(self.database, start_monitor=False)
        second = restored.claim_deliveries()[0]
        self.assertNotEqual(first['claim_token'], second['claim_token'])
        restored.begin_delivery(second['id'], second['claim_token'])
        restored = ScheduledTasks(self.database, start_monitor=False)
        self.assertEqual(restored.claim_deliveries(), [])
        row = restored.execute_operation('list_deliveries', {'task_id': task['id']})['result'][0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertTrue(row['error'])
        with self.assertRaises(ValueError):
            restored.execute_operation('retry_delivery', {'task_id': task['id'], 'delivery_id': second['id']})
        # A known successful sender may repeat its ACK after an EVE restart.
        restored.acknowledge_delivery(second['id'], 'delivered', claim_token=second['claim_token'])
        self.assertEqual(len(self.calls), 1)

    def test_send_timeout_becomes_uncertain_without_restart_and_accepts_late_ack(self):
        task = self.enqueue()
        delivery = self.scheduler.claim_deliveries()[0]
        self.scheduler.begin_delivery(delivery['id'], delivery['claim_token'])
        with self.database.connect() as connection:
            connection.execute('UPDATE scheduled_deliveries SET claim_until=0')
        # The monitor must recover even when a disconnected bot never polls.
        self.scheduler._run_due(0)
        row = self.scheduler.execute_operation('list_deliveries', {'task_id': task['id']})['result'][0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertEqual(self.scheduler.claim_deliveries(), [])
        self.scheduler.acknowledge_delivery(delivery['id'], 'delivered', claim_token=delivery['claim_token'])

    def test_transient_validation_failure_retries_only_output_after_backoff(self):
        self.enqueue()
        delivery = self.scheduler.claim_deliveries()[0]
        for _ in range(2):
            self.scheduler.acknowledge_delivery(delivery['id'], 'retry', 'Offline', claim_token=delivery['claim_token'])
        self.assertEqual(self.scheduler.claim_deliveries(), [])
        with self.database.connect() as connection:
            connection.execute('UPDATE scheduled_deliveries SET retry_at=0')
        retry = self.scheduler.claim_deliveries()[0]
        self.scheduler.begin_delivery(retry['id'], retry['claim_token'])
        with self.assertRaises(ValueError):
            self.scheduler.acknowledge_delivery(retry['id'], 'retry', claim_token=retry['claim_token'])
        self.assertEqual(len(self.calls), 1)

    def test_legacy_sending_migrates_without_resend_or_false_success(self):
        self.enqueue()
        with self.database.connect() as connection:
            for column in ('claim_token', 'claim_until', 'retry_at'):
                connection.execute(f'ALTER TABLE scheduled_deliveries DROP COLUMN {column}')
            connection.execute("UPDATE scheduled_deliveries SET status='sending'")
            connection.execute("UPDATE task_runs SET result_json=json_set(result_json,'$.notification.delivered',json('true'))")
        for _ in range(2):
            restored = ScheduledTasks(self.database, start_monitor=False)
            self.assertEqual(restored.claim_deliveries(), [])
            self.assertEqual(restored.pop_due(), [])
        with self.database.connect() as connection:
            row = connection.execute('SELECT status,payload_json FROM scheduled_deliveries').fetchone()
            result = json.loads(connection.execute('SELECT result_json FROM task_runs').fetchone()[0])
        self.assertEqual(row['status'], 'uncertain')
        self.assertFalse(result['notification']['delivered'])
        self.assertFalse(json.loads(row['payload_json'])['notification']['delivered'])

    def test_parallel_workers_claim_each_output_once(self):
        self.enqueue()
        other = ScheduledTasks(self.database, start_monitor=False)
        with ThreadPoolExecutor(max_workers=6) as pool:
            batches = list(pool.map(lambda i: (self.scheduler if i % 2 else other).claim_deliveries(), range(12)))
        self.assertEqual(sum(map(len, batches)), 1)

    def test_outbox_and_success_commit_atomically(self):
        self.create(output_target_id='room:general')
        self.due()
        finish = self.scheduler._finish
        def fail_success(*args, **kwargs):
            if kwargs.get('result'):
                raise RuntimeError('Commit interrupted')
            return finish(*args, **kwargs)
        with patch.object(self.scheduler, '_finish', side_effect=fail_success):
            self.scheduler.pop_due()
        self.assertEqual(self.scheduler.claim_deliveries(), [])
        with self.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT status FROM task_runs').fetchone()[0], 'failed')

    def test_bridge_routes_scheduled_dispatch_and_ack_with_claim_token(self):
        from eve_agent.chatto import ChattoAPI
        from eve_agent.config import DEFAULTS
        from eve_agent.storage import ConversationStore
        self.enqueue()
        api = ChattoAPI(DEFAULTS['chatto'], ConversationStore(self.database), Mock())
        self.addCleanup(api.close)
        api.scheduler = self.scheduler
        delivery = api.deliveries({})['deliveries'][0]
        api.delivery_start(delivery)
        for _ in range(2):
            api.delivery_ack({**delivery, 'status': 'delivered'})
        self.assertEqual(api.deliveries({}), {'deliveries': []})

    def test_public_caller_cannot_retarget_private_task(self):
        task = self.create(output_target_id='room:general')
        with transport_access({'transport': 'chatto', 'room_id': 'general', 'access_profile': 'public_channel'}, public=True):
            self.assertEqual(self.scheduler.list_tasks(), [])
            with self.assertRaises(PermissionError):
                self.scheduler.update_task(task['id'], {'output_target_id': 'current'})
            with self.assertRaises(PermissionError):
                self.scheduler.get_task(task['id'])

    def test_local_task_keeps_browser_notification(self):
        self.create()
        self.due()
        self.assertEqual(self.scheduler.pop_due()[0]['message'], 'Neuigkeiten')
        self.assertEqual(self.scheduler.claim_deliveries(), [])

    def test_legacy_run_restores_origin_without_reclassifying_identical_human_input(self):
        store = ConversationStore(self.database)
        task = self.create()
        human, _ = store.append_turn(self.source, 'Prüfe Neuigkeiten', 'Gerne', turn_id='human')
        automatic, answer = store.append_turn(
            self.source, 'Prüfe Neuigkeiten', 'Neuigkeiten', turn_id='scheduled',
            user_metadata={'image_count': 0, 'conversation_source': {'sender_name': 'Stefan'}},
        )
        payload = {'turn': {'turn_id': 'scheduled', 'conversation_id': self.source,
                            'assistant_message_id': answer['id']}}
        with self.database.connect() as connection:
            connection.execute("""INSERT INTO task_runs
                (id,task_id,status,scheduled_for,idempotency_key,created_at,result_json)
                VALUES ('legacy',?,'succeeded','2026-10-28T08:00:00Z','legacy','2026',?)""",
                (task['id'], json.dumps(payload)))
        for _ in range(2):
            ScheduledTasks(self.database, start_monitor=False)
        messages = {m['id']: m for m in store.messages(self.source)['messages']}
        self.assertNotIn('input_kind', messages[human['id']]['metadata'])
        restored = messages[automatic['id']]['metadata']
        self.assertEqual(restored['input_kind'], 'scheduled')
        self.assertEqual(restored['image_count'], 0)
        self.assertNotIn('conversation_source', restored)
        self.assertEqual(restored['scheduled_execution']['run_id'], 'legacy')
        # The answer still carries its disclosure when the input is on another page.
        last = store.messages(self.source, limit=1)['messages'][0]
        self.assertEqual(last['metadata']['scheduled_execution']['request'], 'Prüfe Neuigkeiten')
        self.assertEqual(last['metadata']['scheduled_execution']['task_id'], task['id'])

    def test_legacy_output_copy_is_presented_as_a_scheduled_task(self):
        store = ConversationStore(self.database)
        store.append_turn(self.source, 'Gespeicherter Auftrag', 'Ergebnis',
                          user_metadata={'context_copy': True, 'scheduled_task_id': 'task'})
        ScheduledTasks(self.database, start_monitor=False)
        messages = store.messages(self.source)['messages']
        self.assertEqual(messages[0]['metadata']['input_kind'], 'scheduled')
        self.assertEqual(messages[1]['metadata']['scheduled_execution']['request'], 'Gespeicherter Auftrag')


class ScheduledTurnIntegrationTest(unittest.TestCase):
    def setUp(self):
        import ast
        import threading
        from unittest.mock import Mock
        from eve_agent.chatto import ChattoAPI
        from eve_agent.config import DEFAULTS
        from eve_agent.llm import OpenAICompatibleLLM
        from eve_agent.work_activity import WorkActivity
        self.work_activity = WorkActivity()
        self.llm = OpenAICompatibleLLM({'base_url': 'http://fixture.invalid/v1', 'model': 'fixture'})
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ConversationStore(EveDatabase(Path(self.tmp.name) / 'turn.db'))
        self.source = self.store.create('Source')['id']
        self.target = self.store.create('Target')['id']
        self.context = dict(transport='chatto', server_url='https://chat.example', owner_id='owner',
                            bot_id='eve', room_id='general', room_kind='channel', sender_id='guest', message_id='m1')
        self.bridge = ChattoAPI({**DEFAULTS['chatto'], 'enabled': True, 'server_url': 'https://chat.example',
                                'owner_user_id': 'owner', 'channel_ids': ['general']}, self.store, Mock())
        self.response = Mock(return_value={'answer': 'Ergebnis', 'conversation_id': self.source, 'turn_id': 'turn',
                                          'resources': [{'type': 'file', 'content': 'data:text/plain;base64,WA=='}]})
        # Execute the actual CLI closure with its runtime dependencies injected.
        tree = ast.parse((Path(__file__).parents[1] / 'src/eve_agent/cli.py').read_text())
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'execute_scheduled_eve_turn')
        namespace = dict(agent=Mock(conversation_id=self.source), telemetry=Mock(), bus=Mock(),
                         work_activity=self.work_activity,
                         llm=self.llm,
                         __package__='eve_agent',
                         turn_lock=threading.RLock(), chatto_bridge=self.bridge, conversations=self.store,
                         browser_response=self.response, remember_turn_failure=Mock())
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<scheduled-turn>', 'exec'), namespace)
        self.execute = namespace['execute_scheduled_eve_turn']

    def test_scheduled_execution_reports_work_and_releases_on_failure(self):
        result = self.response.return_value
        for fail in (False, True):
            with self.subTest(fail=fail):
                def response(*args, **kwargs):
                    self.assertTrue(self.work_activity.is_working())
                    if fail:
                        raise RuntimeError('model failed')
                    return result
                self.response.side_effect = response
                if fail:
                    with self.assertRaises(RuntimeError):
                        self.execute({'request': 'Aufgabe', 'conversation_id': self.source})
                else:
                    self.execute({'request': 'Aufgabe', 'conversation_id': self.source})
                self.assertFalse(self.work_activity.is_working())

    def test_no_change_creates_no_notification_or_local_output_copy(self):
        self.response.return_value = {'outcome': 'no_change', 'reason': 'Keine Änderung',
            'answer': '', 'conversation_id': self.source, 'turn_id': 'check', 'resources': []}
        for target in ({'transport': 'eve', 'conversation_id': self.target},
                       {'transport': 'chatto', 'room_id': 'general'}):
            with self.subTest(target=target):
                result = self.execute({'request': 'Prüfe', 'conversation_id': self.source, 'output_target': target})
                self.assertEqual('no_change', result['outcome'])
                self.assertNotIn('notification', result)
                self.assertEqual([], self.store.messages(self.target)['messages'])
                self.assertFalse(self.work_activity.is_working())

    def test_browser_response_skips_audio_presentation_and_learning_for_no_change(self):
        import ast
        import time
        from contextlib import nullcontext
        from types import SimpleNamespace
        from eve_agent.agent import TurnResult
        from eve_agent.answer_stream import unpublished_suffix
        from eve_agent.memory import RedactedTextStream
        tree = ast.parse((Path(__file__).parents[1] / 'src/eve_agent/cli.py').read_text())
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'browser_response')
        result = TurnResult(turn_id='check', answer='', route='chat', sources=(), resources=(),
                            conversation_id=self.source, presentation=None, outcome='no_change', outcome_reason='Unverändert')
        telemetry, bus, learning, postprocessing, artifacts, turn_results, published = (Mock() for _ in range(7))
        telemetry.elapsed_ms.return_value = 0.0
        namespace = dict(agent=SimpleNamespace(respond_turn=Mock(return_value=result)),
                         llm=SimpleNamespace(), conversation_learning=learning, telemetry=telemetry, bus=bus,
                         time=time, nullcontext=nullcontext, RedactedTextStream=RedactedTextStream,
                         unpublished_suffix=unpublished_suffix, StreamingTTSPipeline=object,
                         extract_artifacts=artifacts, post_turn_executor=postprocessing, turn_results=turn_results)
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<browser-response>', 'exec'), namespace)
        response = namespace['browser_response']('Prüfe', conversation_id=self.source, on_chunk=published)
        self.assertEqual('no_change', response['outcome'])
        published.assert_not_called()
        artifacts.assert_not_called()
        postprocessing.submit.assert_not_called()
        learning.accept_turn.assert_not_called()
        turn_results.register.assert_not_called()
        bus.set.assert_called_with('idle')
        telemetry.finish.assert_called_with(status='success', details={'outcome': 'no_change'})

    def test_runtime_reenters_origin_authority_and_preserves_resources(self):
        from eve_agent.transport_access import capability_allowed, transport_metadata
        observed = []
        result = self.response.return_value
        def response(*args, **kwargs):
            observed.append((capability_allowed('shell'), transport_metadata()['room_id']))
            return result
        self.response.side_effect = response
        output = self.execute({'request': 'Prüfe', 'conversation_id': self.source, 'execution_context': self.context})
        self.assertEqual(observed, [(False, 'general')])
        self.assertIsNone(transport_metadata())
        self.assertEqual(output['resources'], result['resources'])

    def test_executor_passes_scheduled_origin_and_destination_without_leaking_scope(self):
        from eve_agent.scheduled_execution import scheduled_metadata
        observed = []
        result = self.response.return_value
        def response(*args, **kwargs):
            observed.append(scheduled_metadata())
            return result
        self.response.side_effect = response
        target = {'transport': 'chatto', 'room_id': 'general'}
        self.execute({'request': 'Erinnere jetzt', 'conversation_id': self.source,
                      'task_id': 'task', 'run_id': 'run', 'scheduled_for': '2026-10-28T08:00:00Z',
                      'execution_context': self.context, 'output_target': target})
        self.assertEqual(observed[0]['task_id'], 'task')
        self.assertEqual(observed[0]['output_target'], target)
        self.assertEqual(observed[0]['origin_source'], self.context)
        self.assertIsNone(scheduled_metadata())

    def test_deadline_expiring_while_waiting_prevents_model_call(self):
        with self.assertRaisesRegex(ValueError, 'Enddatum'):
            self.execute({'request': 'Erinnere', 'ends_at': '2000-01-01T00:00:00Z'})
        self.response.assert_not_called()

    def test_revoked_origin_prevents_execution(self):
        self.bridge.configure({**self.bridge.config, 'channel_ids': []})
        with self.assertRaises(PermissionError):
            self.execute({'request': 'Prüfe', 'conversation_id': self.source, 'execution_context': self.context})
        self.response.assert_not_called()

    def test_local_destination_is_separate_from_execution_conversation(self):
        result = self.execute({'request': 'Prüfe', 'conversation_id': self.source,
                               'output_target': {'transport': 'eve', 'conversation_id': self.target}})
        self.response.assert_called_once_with('Prüfe', conversation_id=self.source)
        self.assertEqual(result['notification']['conversation_id'], self.target)
        self.assertEqual(self.store.messages(self.target)['messages'][-1]['content'], 'Ergebnis')
        copied = self.store.messages(self.target)['messages'][0]['metadata']
        self.assertEqual(copied['input_kind'], 'scheduled')
        self.assertNotIn('conversation_source', copied)
        answer = self.store.messages(self.target, limit=1)['messages'][0]
        self.assertEqual(answer['metadata']['scheduled_execution']['request'], 'Prüfe')
