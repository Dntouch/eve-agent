import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("eve_installer", Path(__file__).resolve().parents[1] / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTest(unittest.TestCase):
    def test_rejects_invalid_addresses_and_empty_models(self):
        for url, model in [("file:///tmp/model", "model"), ("http://u:p@localhost/v1", "model"), ("http://localhost/v1?key=secret", "model"), ("http://localhost/v1", " ")]:
            with self.assertRaises(ValueError):
                installer.configuration({}, url, model)

    def test_fresh_install_downloads_speech_and_creates_config(self):
        with tempfile.TemporaryDirectory(prefix="eve installer ") as tmp:
            root = Path(tmp)
            (root / "eve.example.json").write_text('{"shell":{"enabled":false}}')
            with patch.object(installer, "ROOT", root), patch.object(installer, "verify_voice"), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run") as run, patch("sys.argv", ["install.py", "--non-interactive", "--llm-url", "http://localhost:1234/v1", "--model", "example", "--with-speech", "--searxng-url", "http://localhost:8888"]):
                self.assertEqual(0, installer.main())
            cfg = json.loads((root / "eve.local.json").read_text())
            self.assertFalse(cfg["shell"]["enabled"])
            self.assertEqual("de_DE-eve-medium", cfg["text_to_speech"]["voice"])
            self.assertTrue(cfg["web"]["enabled"])
            self.assertEqual("intfloat/multilingual-e5-small", cfg["memory_search"]["model"])
            self.assertIn("setup_embeddings.py", run.call_args_list[1].args[0][1])
            self.assertEqual(3, run.call_count)
            self.assertIn("WhisperModel", run.call_args_list[2].args[0][2])
            self.assertFalse(any("piper.download_voices" in call.args[0] for call in run.call_args_list))

    def test_second_instance_uses_own_port_and_relative_data_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = Path(__file__).resolve().parents[1] / "eve.example.json"
            (root / "eve.example.json").write_text(base.read_text())
            with patch.object(installer, "ROOT", root), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run"), patch("sys.argv", ["install.py", "--non-interactive", "--llm-url", "http://localhost:1234/v1", "--model", "another-model", "--port", "8791"]):
                installer.main()
            cfg = json.loads((root / "eve.local.json").read_text())
            self.assertEqual(8791, cfg["visual"]["port"])
            self.assertEqual("another-model", cfg["llm"]["model"])
            self.assertNotIn("paths", cfg)
            starter = root / ("EVE-starten.cmd" if installer.os.name == "nt" else "eve-start")
            self.assertIn("http://127.0.0.1:8791", starter.read_text())

    def test_web_search_setup_is_explicit_and_uses_its_own_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.example.json").write_text('{}')
            with patch.object(installer, "ROOT", root), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run") as run, patch("sys.argv", ["install.py", "--non-interactive", "--llm-url", "http://localhost/v1", "--model", "example", "--port", "8791", "--with-web-search", "--search-port", "8889"]):
                installer.main()
            cfg = json.loads((root / "eve.local.json").read_text())
            self.assertEqual({"enabled": True, "searxng_url": "http://127.0.0.1:8889"}, cfg["web"])
            self.assertEqual(["--port", "8889"], run.call_args_list[-1].args[0][-2:])

    def test_failed_embedding_download_does_not_publish_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.example.json").write_text('{}')
            with patch.object(installer, "ROOT", root), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run", side_effect=[None, installer.subprocess.CalledProcessError(1, "setup_embeddings.py")]), patch("sys.argv", ["install.py", "--non-interactive", "--llm-url", "http://localhost/v1", "--model", "example"]):
                with self.assertRaises(installer.subprocess.CalledProcessError):
                    installer.main()
            self.assertFalse((root / "eve.local.json").exists())

    def test_existing_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "eve.local.json"
            original = '{"llm": {"model": "keep-me"}}\n'
            path.write_text(original)
            with patch.object(installer, "ROOT", root), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run"), patch("sys.argv", ["install.py", "--non-interactive"]):
                installer.main()
            self.assertEqual(original, path.read_text())

    def test_failed_package_install_does_not_write_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.example.json").write_text('{}')
            with patch.object(installer, "ROOT", root), patch.object(installer.venv.EnvBuilder, "create"), patch.object(installer.subprocess, "run", side_effect=installer.subprocess.CalledProcessError(1, "pip")), patch("sys.argv", ["install.py", "--non-interactive", "--llm-url", "http://localhost/v1", "--model", "example"]):
                with self.assertRaises(installer.subprocess.CalledProcessError):
                    installer.main()
            self.assertFalse((root / "eve.local.json").exists())

    def test_windows_starter_quotes_paths_and_calls_console_entrypoint(self):
        with tempfile.TemporaryDirectory(prefix="eve windows ") as tmp:
            root = Path(tmp)
            with patch.object(installer.os, "name", "nt"):
                installer.write_starters(root, speech=True)
            text = (root / "EVE-starten.cmd").read_text()
            self.assertIn('"%~dp0.venv\\Scripts\\eve.exe" serve', text)
            self.assertIn('"%~dp0eve.local.json"', text)
            self.assertNotIn("--no-tts", text)

    def test_voice_integrity_rejects_incomplete_or_corrupt_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = root / "voices"
            voices.mkdir()
            model = voices / "voice.onnx"
            (voices / "eve-voice.json").write_text(json.dumps({"sha256": {"voice.onnx": hashlib.sha256(b"valid voice").hexdigest()}}))
            with self.assertRaises(ValueError):
                installer.verify_voice(root)
            model.write_bytes(b"git-lfs-pointer-or-corrupt-data")
            with self.assertRaises(ValueError):
                installer.verify_voice(root)
            model.write_bytes(b"valid voice")
            installer.verify_voice(root)
