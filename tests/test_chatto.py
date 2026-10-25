import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor

from eve_agent.chatto import ChattoAPI, ChattoProcess
from eve_agent.config import ConfigError, DEFAULTS, editable_config, load_config, update_editable_config
from eve_agent.storage import EveDatabase, ConversationStore
from eve_agent.transport_access import capability_allowed, require_capability, transport_access, transport_metadata


class ChattoTest(unittest.TestCase):
    def test_web_list_filters_only_member_dms_before_pagination(self):
        self.api.configure({**self.config, "member_dm_enabled": True})
        channel = self.api.create_conversation({"context": self.context})["conversation_id"]
        owner = self.api.create_conversation({"context": {
            **self.context, "room_kind": "dm", "room_id": "owner-dm", "sender_id": "owner",
        }})["conversation_id"]
        member = self.api.create_conversation({"context": {
            **self.context, "room_kind": "dm", "room_id": "member-dm",
        }})["conversation_id"]
        web = self.store.create()["id"]
        # Put the hidden conversation first to catch filtering after LIMIT/OFFSET.
        with self.store.database.connect() as connection:
            connection.execute("UPDATE conversations SET updated_at='9999' WHERE id=?", (member,))
        visible = self.store.list(include_member_dms=False)
        self.assertEqual({item["id"] for item in visible}, {channel, owner, web})
        self.assertEqual(self.store.list(limit=1, include_member_dms=False), visible[:1])
        self.assertEqual(self.store.list(limit=1, offset=1, include_member_dms=False), visible[1:2])
        self.assertIn(member, {item["id"] for item in self.store.list(include_member_dms=True)})
        self.assertEqual(self.store.get(member)["source"], "chatto")
        for members in (False, True):
            for owners in (False, True):
                for channels in (False, True):
                    expected = {web}
                    if members:
                        expected.add(member)
                    if owners:
                        expected.add(owner)
                    if channels:
                        expected.add(channel)
                    self.assertEqual({item["id"] for item in self.store.list(
                        include_member_dms=members, include_owner_dms=owners,
                        include_chatto_channels=channels,
                    )}, expected)


    def test_member_dm_is_separate_restricted_and_revocable_while_owner_keeps_rights(self):
        self.api.configure({**self.config, 'member_dm_enabled': True,
                            'channel_capabilities': ['shell', 'home_assistant']})
        guest = {**self.context, 'room_kind': 'dm', 'room_id': 'guest-dm',
                 'sender_name': 'Sebastian', 'access_profile': 'owner_dm'}
        created = self.api.create_conversation({'context': guest})
        self.assertEqual(self.store.get(created['conversation_id'])['title'], 'Chatto · Sebastian')
        def answer(*args):
            self.assertEqual(transport_metadata()['access_profile'], 'member_dm')
            for tool in ('home_assistant', 'home_assistant_inventory', 'shell', 'local_files', 'nova'):
                self.assertFalse(capability_allowed(tool))
            self.assertTrue(capability_allowed('memory'))
            return {'answer': 'Hallo Sebastian', 'conversation_id': args[2], 'turn_id': 'turn'}
        self.handler.side_effect = answer
        self.api.conversation({**created, 'context': guest, 'text': 'Hallo'})
        for other in ({**guest, 'sender_id': 'other'}, {**guest, 'room_id': 'other-room'},
                      {**guest, 'sender_id': 'owner'}):
            with self.assertRaises(PermissionError):
                self.api.conversation({**created, 'context': other, 'text': 'Hallo'})
        owner = {**guest, 'sender_id': 'owner', 'room_id': 'owner-dm'}
        owner_created = self.api.create_conversation({'context': owner})
        def owner_answer(*args):
            self.assertEqual(transport_metadata()['access_profile'], 'owner_dm')
            self.assertTrue(capability_allowed('home_assistant'))
            self.assertTrue(capability_allowed('shell'))
            return {'answer': 'Hallo', 'conversation_id': args[2], 'turn_id': 'owner-turn'}
        self.handler.side_effect = owner_answer
        self.api.conversation({**owner_created, 'context': owner, 'text': 'Hallo'})
        self.api.configure(self.config)
        with self.assertRaises(PermissionError):
            self.api.conversation({**created, 'context': guest, 'text': 'Hallo'})

    def test_silent_observation_is_durable_idempotent_and_has_no_assistant_or_actions(self):
        from eve_agent.shadow_learning import ProductiveLearningPipeline
        from test_conversation_learning import BatchLLM
        self.api.configure({**self.config, 'channel_learning_ids': ['general']})
        created = self.api.create_conversation({'context': self.context})
        payload = {**created, 'context': {**self.context, 'sender_name': 'Sebastian'}, 'text': 'Dauerhafte Information'}
        first = self.api.observe(payload)
        self.assertEqual(first, self.api.observe(payload))
        self.handler.assert_not_called()
        with self.store.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT status FROM memory_learning_jobs').fetchone()[0], 'pending')
            self.assertIsNone(connection.execute('SELECT assistant_message_id FROM turns').fetchone()[0])
        pipeline = ProductiveLearningPipeline(self.store.database, BatchLLM())
        context = pipeline._model_context(pipeline._snapshot(first['turn_id']), [])
        self.assertEqual(context['user_message']['conversation_source']['sender_name'], 'Sebastian')
        pipeline.process_batch([first['turn_id']])
        with self.store.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT status FROM memory_learning_jobs').fetchone()[0], 'applied')
        self.api.configure(self.config)
        with self.assertRaises(PermissionError):
            self.api.observe(payload)
        self.api.configure({**self.config, 'channel_learning_ids': ['other']})
        with self.assertRaises(PermissionError):
            self.api.observe({**payload, 'context': {**self.context, 'room_id': 'other'}})

    def test_outgoing_image_resource_is_returned_without_local_paths_or_provider_metadata(self):
        created = self.api.create_conversation({'context': self.context})
        image = 'data:image/jpeg;base64,/9j/AA=='
        self.handler.return_value['resources'] = [
            {'type': 'image', 'content': image, 'provider_path': '/private-camera'},
            {'type': 'image', 'content': '/private/local-file.jpg'},
            {'type': 'file', 'content': '/private/config'},
        ]
        response = self.api.conversation({**created, 'context': self.context, 'text': 'Bild bitte'})
        self.assertEqual(response['resources'], [{'type': 'image', 'content': image}])

    def test_images_reach_existing_vision_path_without_granting_privileged_tools(self):
        created = self.api.create_conversation({'context': self.context})
        image = 'data:image/png;base64,iVBORw0KGgo='
        def answer(text, images, identifier):
            self.assertEqual(text, '')
            self.assertEqual(images, [image])
            self.assertFalse(capability_allowed('local_files'))
            return {'answer': 'Bild erhalten', 'conversation_id': identifier, 'turn_id': 'turn'}
        self.handler.side_effect = answer
        self.api.conversation({**created, 'context': self.context, 'text': '', 'images': [image]})
        for invalid in ('not-a-list', [image] * 5, [123]):
            with self.assertRaises(ValueError):
                self.api.conversation({**created, 'context': self.context, 'text': '', 'images': invalid})

    def test_http_requires_dedicated_bridge_token_and_preserves_scope_denial(self):
        import urllib.request
        import urllib.error
        from eve_agent.visual import VisualServer
        server = VisualServer(self.root, Mock(), '127.0.0.1', 0,
                              chatto_handler=self.api, chatto_token='bridge-only')
        self.addCleanup(server.stop)
        server.start()
        base = f'http://127.0.0.1:{server.port}/api/chatto/'
        def request(payload, token, path='conversations'):
            return urllib.request.urlopen(urllib.request.Request(
                base + path, data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}), timeout=3)
        with self.assertRaises(urllib.error.HTTPError) as error:
            request({'context': self.context}, 'assist-token')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with request({'context': self.context}, 'bridge-only') as response:
            self.assertEqual(response.status, 201)
            identifier = json.load(response)['conversation_id']
            self.assertTrue(identifier)
        with self.assertRaises(urllib.error.HTTPError) as error:
            request({'context': {**self.context, 'room_id': 'not-allowed'}}, 'bridge-only')
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.handler.assert_not_called()
        import base64
        image = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\0' * 200000).decode()
        with request({'context': self.context, 'conversation_id': identifier, 'text': '', 'images': [image]}, 'bridge-only', 'conversation') as response:
            self.assertEqual(response.status, 200)
        self.handler.assert_called_once_with('', [image], identifier)
        with self.assertRaises(urllib.error.HTTPError) as error:
            request({'context': self.context, 'conversation_id': identifier, 'text': '', 'images': ['data:image/png;base64,bm90LWFuLWltYWdl']}, 'bridge-only', 'conversation')
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ConversationStore(EveDatabase(self.root / 'eve.db'))
        self.config = {**DEFAULTS['chatto'], 'enabled': True, 'server_url': 'https://chat.example', 'owner_user_id': 'owner', 'channel_ids': ['general']}
        self.context = dict(server_url='https://chat.example', owner_id='owner', bot_id='eve', room_id='general', room_kind='channel', sender_id='guest', message_id='m1')
        self.handler = Mock(return_value={'answer': 'Antwort', 'conversation_id': 'unused', 'turn_id': 'turn'})
        self.api = ChattoAPI(self.config, self.store, self.handler)

    def test_channel_scope_is_bound_and_cannot_reuse_private_conversation(self):
        created = self.api.create_conversation({'context': self.context})
        seen = []
        def answer(*args):
            seen.append((capability_allowed('home_assistant'), capability_allowed('memory'), transport_metadata()))
            return {'answer': 'Antwort', 'conversation_id': args[2], 'turn_id': 'turn'}
        self.handler.side_effect = answer
        self.api.conversation({**created, 'context': self.context, 'text': 'Licht an'})
        self.assertEqual(seen[0][:2], (False, True))
        self.assertEqual(seen[0][2]['sender_id'], 'guest')
        other = {**self.context, 'sender_id': 'another-member'}
        self.api.conversation({**created, 'context': other, 'text': 'Hallo'})
        dm = {**self.context, 'room_kind': 'dm', 'room_id': 'dm', 'sender_id': 'owner'}
        with self.assertRaises(PermissionError):
            self.api.conversation({**created, 'context': dm, 'text': 'Hallo'})
        self.assertTrue(capability_allowed('home_assistant'))
        self.assertIsNone(transport_metadata())

    def test_unlisted_rooms_and_nonowner_dms_are_rejected_before_handler(self):
        for change in ({'room_id': 'unknown'}, {'room_kind': 'dm'}, {'server_url': 'https://other.example'}):
            with self.assertRaises(PermissionError):
                self.api.create_conversation({'context': {**self.context, **change}})
        self.handler.assert_not_called()

    def test_permissions_cannot_be_overridden_in_payload_and_restore_after_failure(self):
        created = self.api.create_conversation({'context': self.context})
        def attempt(*args):
            require_capability('shell')
        self.handler.side_effect = attempt
        with self.assertRaises(PermissionError):
            self.api.conversation({**created, 'context': {**self.context, 'access_profile': 'owner_dm', 'allowed_capabilities': ['shell']}, 'text': 'Bitte'})
        self.assertTrue(capability_allowed('shell'))
        with transport_access({'transport': 'chatto'}, public=True):
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertTrue(executor.submit(capability_allowed, 'shell').result())
            self.assertFalse(capability_allowed('shell'))

    def test_config_secret_input_is_private_and_default_channel_permissions_are_restrictive(self):
        path = self.root / 'eve.json'
        path.write_text('{}')
        result = update_editable_config(path, {'values': {'chatto.enabled': True, 'chatto.owner_user_id': 'owner', 'chatto.channel_ids': ['general']}, 'secrets': {'chatto.api_key': 'fixture-secret'}}, environ={})
        self.assertNotIn('fixture-secret', json.dumps(result))
        self.assertNotIn('fixture-secret', path.read_text())
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        _, effective = load_config(path, environ={})
        self.assertEqual(effective['chatto']['api_key'], 'fixture-secret')
        self.assertNotIn('shell', effective['chatto']['channel_capabilities'])
        secret = next(s for s in editable_config(path, environ={})['sections'] if s['id'] == 'chatto')['secrets'][0]
        self.assertTrue(secret['configured'])
        with self.assertRaises(ConfigError):
            update_editable_config(path, {'values': {'chatto.channel_capabilities': ['unknown']}}, environ={})
        with self.assertRaises(ConfigError):
            update_editable_config(path, {'values': {'chatto.server_url': 'http://example.org'}}, environ={})

    def test_managed_process_exports_no_bot_key_and_closes_child(self):
        from copy import deepcopy
        from unittest.mock import patch
        config = deepcopy(DEFAULTS)
        config['paths']['runtime'] = str(self.root / 'runtime')
        config['chatto'].update(enabled=True, api_key='private-key')
        process = ChattoProcess(self.root, config)
        with patch('eve_agent.chatto.subprocess.Popen') as spawn:
            process.start()
            exported = (process.directory / 'effective-config.json').read_text()
            self.assertNotIn('private-key', exported)
            self.assertEqual(spawn.call_args.kwargs['env']['EVE_CHATTO_BOT_KEY'], 'private-key')
            spawn.return_value.poll.return_value = None
            process.close()
            spawn.return_value.terminate.assert_called_once()

    def test_channel_changes_are_applied_without_restarting_child_and_revocations_reach_api(self):
        from copy import deepcopy
        from unittest.mock import patch
        config = deepcopy(DEFAULTS)
        config['paths']['runtime'] = str(self.root / 'runtime')
        config['chatto'].update(self.config, api_key='private-key')
        process = ChattoProcess(self.root, config)
        with patch('eve_agent.chatto.subprocess.Popen') as spawn:
            process.start()
            updated = deepcopy(config)
            updated['chatto']['channel_ids'] = ['new-room']
            process.configure(updated)
            self.assertEqual(spawn.call_count, 1)
            spawn.return_value.terminate.assert_not_called()
            exported = json.loads((process.directory / 'effective-config.json').read_text())
            self.assertEqual(exported['chatto']['channel_ids'], ['new-room'])
            self.assertNotIn('private-key', json.dumps(exported))
            self.api.configure(updated['chatto'])
            with self.assertRaises(PermissionError):
                self.api.create_conversation({'context': self.context})
            self.api.create_conversation({'context': {**self.context, 'room_id': 'new-room'}})
            spawn.return_value.poll.return_value = None
            updated['chatto']['api_key'] = 'replacement-key'
            process.configure(updated)
            self.assertEqual(spawn.call_count, 2)
            spawn.return_value.terminate.assert_called_once()
            self.assertEqual(spawn.call_args.kwargs['env']['EVE_CHATTO_BOT_KEY'], 'replacement-key')
            process.close()


if __name__ == '__main__':
    unittest.main()
