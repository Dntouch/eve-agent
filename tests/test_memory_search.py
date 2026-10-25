import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from eve_agent.memory_search import MemorySearch, normalized
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.storage import EveDatabase


class FakeEmbeddings:
    identity = "test-model-v1"
    def __init__(self):
        self.documents = []
    def embed(self, texts, *, query=False):
        if not query:
            self.documents.extend(texts)
        # Semantic match has no lexical overlap with the question.
        return [[1., 0.] if query or 'H6008' in text else [0., 1.] for text in texts]


class MemorySearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = EveDatabase(Path(self.tmp.name) / "eve.db")
        self.client = FakeEmbeddings()
        self.runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database), embedding_client=self.client)
        self.index = self.runtime.search_index
        with self.database.connect() as db:
            for key, name, domain, area, lifecycle in (
                ('a', 'H6008', 'light', 'Wohnzimmer', 'active'),
                ('b', 'Tischlampe', 'light', 'Wohnzimmer', 'active'),
                ('c', 'Rollo', 'cover', 'Wohnzimmer', 'active'),
                ('d', 'Altlampe', 'light', 'Wohnzimmer', 'retired'),
            ):
                db.execute("""INSERT INTO memory_claims
                    (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                     valid_from,verification_policy,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, 'provider_binding', 'provider:test', key, key, name,
                     json.dumps({'provider':'home_assistant','external_reference':domain+'.'+key,
                                 'subject':name,'provider_metadata':{'domain':domain,'area':area,'availability':'available'}}),
                     lifecycle, '2026-01-01', 'dynamic', '2026-01-01', '2026-01-01'))

    def test_inventory_is_complete_by_metadata_not_name(self):
        result = self.index.inventory(domain='light')
        self.assertEqual(2, result['total_matches'])
        self.assertEqual({'light.a','light.b'}, {i['entity_id'] for i in result['items']})
        self.assertTrue(result['complete'])
        self.assertFalse(result['live_verified'])
        self.assertEqual(0, self.index.inventory(domain='light',area='Keller')['total_matches'])

    def test_search_preserves_original_speakers_without_merging_display_names(self):
        with self.database.connect() as db:
            for index, role, sender in [(1, 'user', 'jan-one'), (2, 'user', 'jan-two'),
                                         (3, 'assistant', None)]:
                cid, mid = 'c' + str(index), 'm' + str(index)
                db.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES (?,?,'2026','2026')",
                           (cid, cid))
                metadata = {'conversation_source': {'sender_name': 'Jan', 'sender_id': sender,
                                                     'room_kind': 'dm'}} if sender else {}
                db.execute("INSERT INTO messages(id,conversation_id,role,content,ordinal,metadata_json,created_at) "
                           "VALUES (?,?,?,'H6008',0,?,'2026')", (mid, cid, role, json.dumps(metadata)))
                db.execute("INSERT INTO memory_evidence(id,claim_id,stance,evidence_type,source_message_id,"
                           "payload_json,observed_at,created_at) VALUES (?,'a','supports',?,?, '{}','2026','2026')",
                           ('e' + str(index), 'user_message' if role == 'user' else 'conversation_record', mid))
        self.runtime.retrieve = lambda *a, **kw: [SimpleNamespace(memory_id='a')]
        item = self.index.search('H6008', mode='lexical')['items'][0]
        sources = item['source_context']
        self.assertEqual(['user', 'user', 'assistant'], [s['role'] for s in sources])
        self.assertEqual(['jan-one', 'jan-two'],
                         [s['conversation_source']['sender_id'] for s in sources[:2]])
        self.assertEqual('conversation_record', sources[2]['evidence_type'])

    def test_pagination_reports_missing_results(self):
        page = self.index.inventory(domain='light',limit=1)
        self.assertFalse(page['complete'])
        self.assertTrue(page['has_more'])
        second = self.index.inventory(domain='light',offset=page['next_offset'],limit=1)
        self.assertFalse(second['has_more'])
        self.assertNotEqual(page['items'][0]['memory_id'],second['items'][0]['memory_id'])

    def test_semantic_search_cache_updates_and_forgetting(self):
        result = self.index.search('Anwesenheit simulieren',mode='semantic',domain='light')
        self.assertEqual('a',result['items'][0]['memory_id'])
        self.assertEqual('available',result['semantic_status'])
        self.assertEqual(2,len(self.client.documents))
        self.index.search('another question',mode='semantic',domain='light')
        self.assertEqual(2,len(self.client.documents))
        with self.database.connect() as db:
            db.execute("UPDATE memory_claims SET display_text='H6008 neu' WHERE id='a'")
            db.execute("UPDATE memory_claims SET lifecycle='retired' WHERE id='b'")
        result = self.index.search('again',mode='semantic',domain='light')
        self.assertEqual(3,len(self.client.documents))
        self.assertEqual(['a'],[i['memory_id'] for i in result['items']])

    def test_model_change_invalidates_cache(self):
        self.index.search('query',mode='semantic',domain='light')
        self.client.identity='different-model'
        self.index.search('query',mode='semantic',domain='light')
        self.assertEqual(4,len(self.client.documents))

    def test_hybrid_fallback_is_explicit(self):
        self.index.client=None
        self.runtime.retrieve=lambda *a,**kw: [SimpleNamespace(memory_id='a')]
        result=self.index.search('query',domain='light')
        self.assertEqual('unavailable',result['semantic_status'])
        self.assertTrue(result['warnings'])
        self.assertEqual(['lexical'],result['items'][0]['methods'])
        with self.assertRaises(RuntimeError):
            self.index.search('query',mode='semantic')

    def test_cancelled_semantic_index_is_not_hidden_as_fallback(self):
        from eve_agent.backend_turns import TurnCancelled
        def cancel():
            raise TurnCancelled("cancelled")
        with self.assertRaises(TurnCancelled):
            self.index.search('query', checkpoint=cancel)
        self.assertEqual([], self.client.documents)

    def test_invalid_vectors_are_rejected(self):
        for v in ([],[0,0],[float('nan'),1]):
            with self.assertRaises(ValueError): normalized(v)


if __name__ == '__main__':
    unittest.main()
