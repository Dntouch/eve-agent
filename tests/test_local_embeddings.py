import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from eve_agent.local_embeddings import LocalONNXEmbeddings, create_embedding_client


class LocalEmbeddingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'model'
        self.directory.mkdir()
        (self.directory/'model.onnx').write_bytes(b'model-v1')
        (self.directory/'tokenizer.json').write_text('{}')
        self.config = {'backend':'local_onnx','model':'test-e5','model_dir':'model',
                       'threads':2,'query_prefix':'query: ','document_prefix':'passage: '}

    def test_factory_selects_offline_client_without_any_llm_config(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            client = create_embedding_client(self.config,self.root)
        self.assertIsInstance(client,LocalONNXEmbeddings)
        self.assertIsNone(create_embedding_client({'model':''},self.root))

    def test_real_asset_content_invalidates_cache_identity(self):
        first=LocalONNXEmbeddings(self.config,self.root).identity
        (self.directory/'model.onnx').write_bytes(b'model-v2')
        self.assertNotEqual(first,LocalONNXEmbeddings(self.config,self.root).identity)

    def test_cpu_only_session_and_explicit_thread_budget(self):
        import onnxruntime
        import tokenizers
        client=LocalONNXEmbeddings(self.config,self.root)
        tokenizer=Mock()
        tokenizer.token_to_id.return_value=1
        with patch.object(onnxruntime,'InferenceSession',return_value=Mock()) as load, \
             patch.object(tokenizers.Tokenizer,'from_file',return_value=tokenizer):
            client._load()
        self.assertEqual(['CPUExecutionProvider'],load.call_args.kwargs['providers'])
        self.assertEqual(2,load.call_args.kwargs['sess_options'].intra_op_num_threads)
        tokenizer.enable_truncation.assert_called_once_with(max_length=512,stride=0)

    def test_mean_pooling_masks_padding_and_includes_overflow(self):
        client=LocalONNXEmbeddings(self.config,self.root)
        def encoding(ids,overflow=()):
            return SimpleNamespace(ids=ids,attention_mask=[1]*len(ids),overflowing=list(overflow))
        client._tokenizer=Mock()
        # First document spans two chunks; second document is shorter.
        client._tokenizer.encode_batch.return_value=[encoding([2,2],[encoding([4])]),encoding([3])]
        client._pad_id=1
        client._session=Mock()
        client._session.get_inputs.return_value=[SimpleNamespace(name='input_ids'),SimpleNamespace(name='attention_mask')]
        def run(_,inputs):
            ids=inputs['input_ids']
            return [np.stack([ids.astype(float),np.ones_like(ids)],axis=-1)]
        client._session.run.side_effect=run
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            vectors=client.embed(['first','second'])
        expected=np.array([8/3,1.]);expected/=np.linalg.norm(expected)
        np.testing.assert_allclose(expected,vectors[0])
        expected=np.array([3.,1.]);expected/=np.linalg.norm(expected)
        np.testing.assert_allclose(expected,vectors[1])
        client._tokenizer.encode_batch.assert_called_with(['passage: first','passage: second'])
        client.embed(['question'],query=True)
        client._tokenizer.encode_batch.assert_called_with(['query: question'])

    def test_http_embeddings_require_own_endpoint(self):
        from eve_agent.memory_search import EmbeddingClient
        with self.assertRaises(KeyError):
            EmbeddingClient({'model':'test'}, {'base_url':'http://dialog.invalid'})
        client=EmbeddingClient({'model':'test','base_url':'http://embedding.invalid/v1'},
                               {'base_url':'http://dialog.invalid','api_key':'dialog-secret'})
        self.assertEqual('http://embedding.invalid/v1',client.base_url)
        self.assertNotEqual('dialog-secret',client.api_key)


if __name__=='__main__': unittest.main()
