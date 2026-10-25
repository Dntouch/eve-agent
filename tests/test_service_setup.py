import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


search = script('setup_search')
embeddings = script('setup_embeddings')


class SearchSetupTest(unittest.TestCase):
    def test_instances_have_separate_names_and_bind_only_to_localhost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertNotEqual(search.instance_name(root), search.instance_name(root / 'second'))
            with patch.object(search, 'ROOT', root), patch.object(search.shutil, 'which', return_value='/bin/podman'), patch.object(search.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run, patch.object(search.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"results":[]}')), patch('sys.argv', ['setup_search.py', '--port', '8889']):
                search.main()
            command = run.call_args_list[1].args[0]
            self.assertIn('127.0.0.1:8889:8080', command)
            self.assertIn('@sha256:', command[-1])
            settings = (root / 'runtime/web-search/settings/settings.yml').read_text()
            self.assertIn('formats: [html, json]', settings)
            self.assertIn('secret_key:', settings)
            self.assertNotIn('replace-me', settings)

    def test_foreign_container_is_never_started_or_stopped(self):
        with patch.object(search.shutil, 'which', return_value='/bin/podman'), patch.object(search.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='somebody-else')) as run, patch('sys.argv', ['setup_search.py', '--stop']):
            with self.assertRaises(SystemExit):
                search.main()
            self.assertEqual(1, run.call_count)


class EmbeddingSetupTest(unittest.TestCase):
    def test_verified_assets_are_reused_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'model.onnx').write_bytes(b'known-model')
            expected = hashlib.sha256(b'known-model').hexdigest()
            with patch.object(embeddings, 'FILES', {'model.onnx': 'onnx/model.onnx'}), patch.object(embeddings, 'SHA256', {'model.onnx': expected}), patch.object(embeddings.urllib.request, 'urlopen') as request, patch('sys.argv', ['setup_embeddings.py', '--output', tmp]):
                embeddings.main()
                request.assert_not_called()

    def test_failed_verification_keeps_previous_asset_and_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / 'model.onnx'
            model.write_bytes(b'previous')
            with patch.object(embeddings, 'FILES', {'model.onnx': 'onnx/model.onnx'}), patch.object(embeddings, 'SHA256', {'model.onnx': '0' * 64}), patch.object(embeddings.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt-download')), patch('sys.argv', ['setup_embeddings.py', '--output', tmp]):
                with self.assertRaisesRegex(ValueError, 'Prüfsumme'):
                    embeddings.main()
            self.assertEqual(b'previous', model.read_bytes())
            self.assertFalse((root / 'model.onnx.part').exists())
