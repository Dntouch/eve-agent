import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eve_agent.conversation_assets import ConversationAssets
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.transport_access import transport_access


class ConversationAssetsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ConversationStore(EveDatabase(self.root / 'data/eve.db'))
        self.cid = self.store.create()['id']
        self.body = b'original attachment bytes'
        self.image = 'data:image/png;base64,' + base64.b64encode(self.body).decode()
        self.store.append_turn(self.cid, 'Foto', 'Gesehen', user_attachments=[{'content': self.image}])
        self.asset = self.store.messages(self.cid)['messages'][0]['attachments'][0]['id']

    def test_exact_original_is_listed_viewed_and_materialized_without_search(self):
        access = ConversationAssets(self.store, self.cid)
        with patch('os.walk', side_effect=AssertionError('No filesystem search')):
            listing = access.execute('list', {})
            self.assertEqual([self.asset], [i['asset_id'] for i in listing['items']])
            viewed = access.execute('read', {'asset_id': 'asset:' + self.asset})
            self.assertEqual(self.image, viewed['resources'][0]['content'])
            output = access.execute('materialize', {'asset_id': self.asset})
        self.assertEqual(self.body, Path(output['path']).read_bytes())
        self.assertEqual(hashlib.sha256(self.body).hexdigest(), output['sha256'])
        self.assertEqual(0o600, Path(output['path']).stat().st_mode & 0o777)
        self.assertEqual(output['path'], access.execute('materialize', {'asset_id': self.asset})['path'])
        Path(output['path']).write_bytes(b'changed by a shell consumer')
        self.assertEqual(('image/png', self.body), self.store.read_asset(self.asset))
        self.assertEqual(self.body, Path(access.execute('materialize', {'asset_id': self.asset})['path']).read_bytes())

    def test_current_input_works_before_chat_persistence_and_after_restart(self):
        access = ConversationAssets(self.store, self.cid, [self.image])
        self.assertEqual('input:0', access.list()['items'][0]['asset_id'])
        self.assertEqual(self.image, access.execute('read', {'asset_id': 'input:0'})['resources'][0]['content'])
        self.assertEqual(self.body, Path(access.execute('materialize', {'asset_id': 'input:0'})['path']).read_bytes())
        restarted = ConversationAssets(ConversationStore(EveDatabase(self.root / 'data/eve.db')), self.cid)
        self.assertEqual(self.image, restarted.execute('read', {'asset_id': self.asset})['resources'][0]['content'])

    def test_foreign_deleted_or_guessed_paths_are_rejected(self):
        foreign = self.store.create()['id']
        access = ConversationAssets(self.store, foreign)
        self.assertEqual([], access.list()['items'])
        for operation in ('read', 'materialize'):
            for identifier in (self.asset, '/tmp/other.png', '../eve.db', 'asset:' + self.asset):
                with self.subTest(operation=operation, identifier=identifier), self.assertRaises(KeyError):
                    access.execute(operation, {'asset_id': identifier})
        self.store.delete(self.cid)
        with self.assertRaises(KeyError):
            ConversationAssets(self.store, self.cid).execute('read', {'asset_id': self.asset})

    def test_file_handoff_requires_shell_authority(self):
        access = ConversationAssets(self.store, self.cid, [self.image])
        with transport_access({}, public=True):
            with self.assertRaises(PermissionError):
                access.execute('materialize', {'asset_id': 'input:0'})
        self.assertNotIn('materialize', ConversationAssets.contract(materialize=False)['operations'])


if __name__ == '__main__':
    unittest.main()
