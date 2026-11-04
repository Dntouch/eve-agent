import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from eve_agent.chatto import ChattoAPI
from eve_agent.config import DEFAULTS
from eve_agent.storage import EveDatabase, ConversationStore
from eve_agent.transport_access import report_transport_activity, capability_allowed


class ChattoJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ConversationStore(EveDatabase(self.root / 'eve.db'))
        self.config = {**DEFAULTS['chatto'], 'enabled': True, 'server_url': 'https://chat.example',
                       'owner_user_id': 'owner', 'channel_ids': ['general']}
        self.context = dict(server_url='https://chat.example', owner_id='owner', bot_id='eve',
                            room_id='general', room_kind='channel', sender_id='guest', message_id='m1')
        self.handler = Mock(side_effect=lambda text, images, identifier: {
            'answer': 'Fertig', 'conversation_id': identifier, 'turn_id': 'turn'})
        self.api = self.new_api()
        self.request = {**self.api.create_conversation({'context': self.context}),
                        'context': self.context, 'text': 'Auftrag', 'images': []}

    def new_api(self):
        api = ChattoAPI(self.config, self.store, self.handler)
        self.addCleanup(api.close)
        return api

    def finish(self, api=None):
        api = api or self.api
        with api.jobs.lock:
            thread = api.jobs.thread
        if thread:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_accepts_immediately_executes_once_and_persists_output_across_restart(self):
        started, release = threading.Event(), threading.Event()
        def work(text, images, identifier):
            started.set()
            self.assertTrue(release.wait(3))
            self.assertFalse(capability_allowed('shell'))
            return {'answer': 'Fertig', 'conversation_id': identifier, 'turn_id': 'turn',
                    'resources': [{'type': 'file', 'filename': 'part.step',
                                   'content': 'data:application/octet-stream;base64,Y2Fk'}]}
        self.handler.side_effect = work
        try:
            accepted = self.api.submit(self.request)
            self.assertTrue(started.wait(1))
            self.assertEqual(self.api.presence_activity({}), {'working': True})
            self.assertEqual(self.api.deliveries({}), {'deliveries': []})
            # The first response may have been lost; submitting the same ID is safe.
            with ThreadPoolExecutor(max_workers=4) as executor:
                duplicates = list(executor.map(lambda _: self.api.submit(self.request), range(8)))
            self.assertTrue(all(item['id'] == accepted['id'] for item in duplicates))
        finally:
            release.set()
            self.finish()
        self.assertEqual(self.handler.call_count, 1)
        self.assertEqual(self.api.presence_activity({}), {'working': False})
        self.api.close()
        restarted = self.new_api()
        delivery = restarted.deliveries({})['deliveries'][0]
        self.assertEqual(delivery['target']['room_id'], 'general')
        self.assertEqual(delivery['target']['bot_id'], 'eve')
        self.assertEqual(delivery['payload']['notification']['message'], 'Fertig')
        self.assertEqual(delivery['payload']['resources'][0]['filename'], 'part.step')
        restarted.delivery_start(delivery)
        ack = {**delivery, 'status': 'delivered'}
        restarted.delivery_ack(ack)
        restarted.delivery_ack(ack)
        self.assertEqual(restarted.deliveries({}), {'deliveries': []})
        self.assertEqual(self.handler.call_count, 1)

    def test_jobs_run_in_acceptance_order_without_overlapping(self):
        started, release = threading.Event(), threading.Event()
        seen = []
        def work(text, images, identifier):
            seen.append(text)
            if text == 'first':
                started.set()
                self.assertTrue(release.wait(3))
            return {'answer': text, 'conversation_id': identifier, 'turn_id': text}
        self.handler.side_effect = work
        try:
            self.api.submit({**self.request, 'text': 'first'})
            self.assertTrue(started.wait(1))
            self.api.submit({**self.request, 'text': 'second', 'context': {**self.context, 'message_id': 'm2'}})
            self.assertEqual(seen, ['first'])
        finally:
            release.set()
            self.finish()
        self.assertEqual(seen, ['first', 'second'])

    def test_runtime_categories_reach_live_job_snapshots_without_tool_details(self):
        phases = []
        def work(text, images, identifier):
            for event in ({'kind': 'model_start'}, {'kind': 'tool_start', 'tool_id': 'a'},
                          {'kind': 'tool_start', 'tool_id': 'b', 'web': True},
                          {'kind': 'tool_end', 'tool_id': 'b'}, {'kind': 'tool_end', 'tool_id': 'a'},
                          {'kind': 'model_writing'}):
                report_transport_activity(event)
                phases.append(self.api.job_status({})['jobs'][0]['progress']['bot_activity'])
            return {'answer': 'Fertig', 'conversation_id': identifier, 'turn_id': 'turn'}
        self.handler.side_effect = work
        self.api.submit(self.request)
        self.finish()
        self.assertEqual(phases, ['THINKING', 'TOOL_USE', 'WEB_RESEARCH', 'TOOL_USE', 'THINKING', 'WRITING'])
        self.assertEqual(self.api.job_status({})['jobs'][0]['state'], 'completed')

    def test_scheduled_work_reports_the_actual_output_target_and_cleans_up_on_cancel(self):
        from eve_agent.scheduled_execution import scheduled_execution
        from eve_agent.backend_turns import TurnCancelled
        from eve_agent.bot_activity import tool_activity
        target = {'transport': 'chatto', 'server_url': self.config['server_url'],
                  'room_id': 'general', 'thread_root_id': 'actual-thread'}
        with self.assertRaises(TurnCancelled):
            with scheduled_execution({'output_target': target}), self.api.scheduled_access(None):
                self.assertEqual(self.api.job_status({})['jobs'][0]['target'], target)
                with tool_activity('web'):
                    self.assertEqual(self.api.job_status({})['jobs'][0]['progress']['bot_activity'], 'WEB_RESEARCH')
                    raise TurnCancelled()
        self.assertEqual(self.api.job_status({})['jobs'], [])

    def test_live_work_is_not_hidden_by_a_large_terminal_backlog(self):
        with unittest.mock.patch.object(self.api.jobs, 'start'):
            self.api.submit(self.request)
            for index in range(101):
                self.api.submit({**self.request, 'context': {**self.context, 'message_id': f'done-{index}'}})
        with self.store.database.connect() as connection:
            connection.execute("UPDATE chatto_jobs SET state='completed' WHERE id!=?", (self.api.jobs.identity(self.context),))
        states = [job['state'] for job in self.api.job_status({})['jobs']]
        self.assertEqual(states.count('queued'), 1)
        self.assertEqual(states.count('completed'), 100)

    def test_dynamic_thread_and_files_retain_their_origin(self):
        def work(text, images, identifier):
            report_transport_activity({'integration': 'CAD', 'reply_mode': 'thread'})
            return {'answer': 'Modell erstellt', 'conversation_id': identifier, 'turn_id': 'turn',
                    'resources': [{'type': 'file', 'filename': 'part.step',
                                   'content': 'data:application/octet-stream;base64,Y2Fk'}]}
        self.handler.side_effect = work
        self.api.submit(self.request)
        self.finish()
        delivery = self.api.deliveries({})['deliveries'][0]
        self.assertEqual(delivery['target']['thread_root_id'], 'm1')
        self.assertEqual(delivery['target']['message_id'], 'm1')
        self.assertNotEqual(delivery['target']['conversation_id'], self.request['conversation_id'])
        self.assertTrue(delivery['payload']['notification']['message'].startswith('Auftrag: EVE-'))
        self.assertEqual(delivery['progress']['integration'], 'CAD')
        following = {**self.context, 'thread_root_id': 'm1', 'message_id': 'm2'}
        self.assertEqual(self.api.create_conversation({'context': following})['conversation_id'],
                         delivery['target']['conversation_id'])

    def test_original_thread_owner_and_member_dm_are_kept_separate(self):
        self.api.configure({**self.config, 'member_dm_enabled': True})
        for sender in ('owner', 'member'):
            context = {**self.context, 'room_kind': 'dm', 'room_id': sender + '-dm',
                       'sender_id': sender, 'thread_root_id': 'root-' + sender, 'message_id': 'm-' + sender}
            request = {**self.api.create_conversation({'context': context}), 'context': context, 'text': 'Hallo'}
            self.api.submit(request)
        self.finish()
        for sender in ('owner', 'member'):
            delivery = self.api.deliveries({})['deliveries'][0]
            target = delivery['target']
            self.assertEqual(target['room_id'], sender + '-dm')
            self.assertEqual(target['thread_root_id'], 'root-' + sender)
            self.assertEqual(target['access_profile'], 'owner_dm' if sender == 'owner' else 'member_dm')
            self.api.delivery_start(delivery)
            self.api.delivery_ack({**delivery, 'status': 'delivered'})

    def test_invalid_scope_and_payload_never_enqueue(self):
        for patch, exception in (({'context': {**self.context, 'room_id': 'other'}}, PermissionError),
                                 ({'conversation_id': self.store.create()['id']}, PermissionError),
                                 ({'text': ''}, ValueError), ({'images': [123]}, ValueError)):
            with self.assertRaises(exception):
                self.api.submit({**self.request, **patch})
        self.assertEqual(self.api.job_status({}), {'jobs': []})
        self.handler.assert_not_called()

    def test_expired_claim_recovers_but_a_started_send_never_replays(self):
        self.api.submit(self.request)
        self.finish()
        first = self.api.deliveries({})['deliveries'][0]
        self.assertEqual(self.api.deliveries({})['deliveries'], [])
        with self.store.database.connect() as connection:
            connection.execute('UPDATE chatto_jobs SET claim_until=0')
        second = self.api.deliveries({})['deliveries'][0]
        self.assertNotEqual(first['claim_token'], second['claim_token'])
        with self.assertRaises(ValueError):
            self.api.delivery_start(first)
        with self.assertRaises(ValueError):
            self.api.delivery_ack({**first, 'status': 'retry'})
        self.api.delivery_start(second)
        with self.assertRaises(ValueError):
            self.api.delivery_ack({**second, 'status': 'retry'})
        self.api.close()
        restarted = self.new_api()
        self.assertEqual(restarted.deliveries({})['deliveries'], [])
        self.assertEqual(restarted.job_status({})['jobs'][0]['delivery_status'], 'uncertain')
        self.assertEqual(self.handler.call_count, 1)

    def test_predispatch_failure_retries_delivery_without_reexecuting(self):
        self.api.submit(self.request)
        self.finish()
        delivery = self.api.deliveries({})['deliveries'][0]
        self.api.delivery_ack({**delivery, 'status': 'retry', 'error': 'Destination temporarily unavailable'})
        self.assertEqual(self.api.deliveries({})['deliveries'], [])
        with self.store.database.connect() as connection:
            connection.execute('UPDATE chatto_jobs SET retry_at=0')
        retried = self.api.deliveries({})['deliveries'][0]
        self.api.delivery_ack({**retried, 'status': 'blocked'})
        self.assertEqual(self.api.deliveries({})['deliveries'], [])
        self.assertEqual(self.handler.call_count, 1)
        self.api.retry_job_delivery({'id': delivery['id']})
        pending = self.api.deliveries({})['deliveries'][0]
        self.api.delivery_start(pending)
        self.api.delivery_ack({**pending, 'status': 'uncertain'})
        with self.assertRaises(ValueError):
            self.api.retry_job_delivery({'id': pending['id']})
        self.assertEqual(self.handler.call_count, 1)

    def test_restart_recovers_queued_and_claimed_jobs_but_never_reexecutes_running_work(self):
        # Persist an accepted inbox without starting the worker, then simulate exit.
        with unittest.mock.patch.object(self.api.jobs, 'start'):
            self.api.submit(self.request)
            self.api.submit({**self.request, 'context': {**self.context, 'message_id': 'm2'}})
        with self.store.database.connect() as connection:
            connection.execute("UPDATE chatto_jobs SET state='running' WHERE id=?", (self.api.jobs.identity(self.context),))
        self.api.close()
        restarted = self.new_api()
        restarted.jobs.start()
        self.finish(restarted)
        self.assertEqual(self.handler.call_count, 1)
        states = {item['state'] for item in restarted.job_status({})['jobs']}
        self.assertEqual(states, {'interrupted', 'completed'})
        delivery = restarted.deliveries({})['deliveries'][0]
        self.assertIn('Neustart', delivery['payload']['notification']['message'])
        restarted.close()
        again = self.new_api()
        recovered = again.deliveries({})['deliveries'][0]
        self.assertEqual(recovered['id'], delivery['id'])
        self.assertNotEqual(recovered['claim_token'], delivery['claim_token'])

    def test_failed_work_produces_a_scoped_failure_notification_without_private_errors(self):
        self.handler.side_effect = RuntimeError('private credential or model details')
        self.api.submit(self.request)
        self.finish()
        delivery = self.api.deliveries({})['deliveries'][0]
        self.assertEqual(delivery['state'], 'failed')
        self.assertNotIn('private credential', json.dumps(delivery))
        self.assertIn('nicht automatisch erneut', delivery['payload']['notification']['message'])
        self.api.submit(self.request)
        self.finish()
        self.assertEqual(self.handler.call_count, 1)

    def test_http_acceptance_and_token_checks_are_independent_of_model_completion(self):
        import urllib.request
        import urllib.error
        from eve_agent.visual import VisualServer
        started, release = threading.Event(), threading.Event()
        def work(text, images, identifier):
            started.set()
            self.assertTrue(release.wait(3))
            return {'answer': 'Fertig', 'conversation_id': identifier, 'turn_id': 'turn'}
        self.handler.side_effect = work
        server = VisualServer(self.root, Mock(), '127.0.0.1', 0,
                              chatto_handler=self.api, chatto_token='bridge-only')
        self.addCleanup(server.stop)
        server.start()
        def request(path, payload, token='bridge-only'):
            return urllib.request.urlopen(urllib.request.Request(
                f'http://127.0.0.1:{server.port}/api/chatto/' + path,
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token}), timeout=1)
        try:
            for path in ('submit', 'jobs', 'deliveries', 'delivery-start', 'delivery-ack', 'job-retry'):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request(path, self.request, token='wrong')
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
            with request('submit', self.request) as response:
                self.assertEqual(response.status, 202)
                self.assertTrue(json.load(response)['id'].startswith('chatto-job:'))
            self.assertTrue(started.wait(1))
            with request('presence-activity', {}) as response:
                self.assertEqual(json.load(response), {'working': True})
            with request('deliveries', {}) as response:
                self.assertEqual(json.load(response), {'deliveries': []})
        finally:
            release.set()
            self.finish()
        with request('deliveries', {}) as response:
            delivery = json.load(response)['deliveries'][0]
        with request('delivery-start', delivery) as response:
            self.assertEqual(response.status, 200)
        with request('delivery-ack', {**delivery, 'status': 'delivered'}) as response:
            self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
