import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
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

    def test_explicit_target_is_validated_and_can_be_changed(self):
        task = self.create(output_target_id='room:general')
        self.assertEqual(task['action']['output_target'], self.target)
        self.scheduler.output_targets_provider = lambda: []
        with self.assertRaises(ValueError):
            self.create(output_target_id='room:general')
        self.scheduler.update_task(task['id'], {'output_target_id': 'current'})
        self.assertEqual(self.scheduler.get_task(task['id'])['action']['output_target']['transport'], 'eve')

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
        restored.acknowledge_delivery(delivery['id'], 'blocked', 'No access')
        restored.execute_operation('retry_delivery', {'task_id': task['id'], 'delivery_id': delivery['id']})
        self.assertEqual(restored.claim_deliveries()[0]['id'], delivery['id'])
        self.assertEqual(len(self.calls), 1)
        restored.acknowledge_delivery(delivery['id'], 'uncertain')
        with self.assertRaises(ValueError):
            restored.execute_operation('retry_delivery', {'task_id': task['id'], 'delivery_id': delivery['id']})
        statuses = restored.execute_operation('list_deliveries', {'task_id': task['id']})['result']
        self.assertEqual(statuses[0]['status'], 'uncertain')

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


class ScheduledTurnIntegrationTest(unittest.TestCase):
    def setUp(self):
        import ast
        import threading
        from unittest.mock import Mock
        from eve_agent.chatto import ChattoAPI
        from eve_agent.config import DEFAULTS
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
                         turn_lock=threading.RLock(), chatto_bridge=self.bridge, conversations=self.store,
                         browser_response=self.response, remember_turn_failure=Mock())
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<scheduled-turn>', 'exec'), namespace)
        self.execute = namespace['execute_scheduled_eve_turn']

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
