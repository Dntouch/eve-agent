import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from eve_agent import cli
from eve_agent.config import load_config

from eve_agent.cli import _merge_hotwords


class HotwordMergeTest(unittest.TestCase):
    def test_aliases_do_not_accumulate_across_turns(self):
        first = _merge_hotwords("EVE Rolllade", "Elena, Rolllade")
        second = _merge_hotwords("EVE Rolllade", "Elena, Rolllade")

        self.assertEqual(first, second)
        self.assertEqual(first, "EVE Rolllade Elena")


class DoctorConfigurationTest(unittest.TestCase):
    def test_doctor_uses_explicit_configuration_for_nova(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "eve.local.json"
            path.write_text('{"nova_maintenance":{"enabled":true}}')
            _, cfg = load_config(path, environ={})
            provider = Mock()
            provider.minimal_contract.return_value = {"execution": {"available": False, "message": "not configured"}}
            with patch.object(cli, "ProviderMcpCapability", return_value=provider) as factory, patch.object(cli.OpenAICompatibleLLM, "models", return_value=[]), patch.object(cli.Recorder, "devices", return_value=[]), redirect_stdout(io.StringIO()) as output:
                cli.doctor(root, cfg, config_path=path)
            self.assertEqual(path, factory.call_args.kwargs["config_path"])
            provider.close_all.assert_called_once()
            self.assertIn("Piper-Stimme:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
