import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from eve_agent.config import ConfigError, config_status, editable_config, load_config, update_editable_config
from eve_agent.home_assistant import HomeAssistant
from eve_agent.llm import OpenAICompatibleLLM


class ConfigurationTest(unittest.TestCase):
    def test_optional_llm_temperature_is_loaded_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (None, 0, 1.0, 2):
                with self.subTest(value=value):
                    path = self.write_config(Path(directory), {"llm": {"temperature": value}})
                    config = load_config(path, environ={})[1]
                    self.assertEqual(value, OpenAICompatibleLLM(config["llm"]).temperature)
            for value in (True, "1", -0.1, 2.1, float("nan"), float("inf")):
                with self.subTest(value=value):
                    path = self.write_config(Path(directory), {"llm": {"temperature": value}})
                    with self.assertRaises(ConfigError):
                        load_config(path, environ={})

    def test_page_fetch_limit_is_defaulted_editable_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {})
            self.assertEqual(5_000_000, load_config(path, environ={})[1]["web"]["max_page_bytes"])
            update_editable_config(path, {"values": {"web.max_page_bytes": 8_000_000}}, environ={})
            self.assertEqual(8_000_000, load_config(path, environ={})[1]["web"]["max_page_bytes"])
            for value in (0, 20_000_001):
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    update_editable_config(path, {"values": {"web.max_page_bytes": value}}, environ={})

    def test_pdf_fetch_limit_is_separate_defaulted_editable_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {"web": {"max_page_bytes": 5_000_000}})
            self.assertEqual(50 * 1024 * 1024, load_config(path, environ={})[1]["web"]["max_pdf_bytes"])
            for value in (750_000, 100 * 1024 * 1024, 200 * 1024 * 1024):
                update_editable_config(path, {"values": {"web.max_pdf_bytes": value}}, environ={})
                config = load_config(path, environ={})[1]["web"]
                self.assertEqual(value, config["max_pdf_bytes"])
                self.assertEqual(5_000_000, config["max_page_bytes"])
            for value in (True, "50000000", 0, 200 * 1024 * 1024 + 1):
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    update_editable_config(path, {"values": {"web.max_pdf_bytes": value}}, environ={})

    def test_external_mcp_is_portable_editable_and_channel_access_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {})
            servers = {'cad': {'command': 'solidcraft-cli', 'args': ['mcp', '--headless', '--allow-path', '{workspace}']}}
            update_editable_config(path, {'values': {'mcp.servers': servers,
                'chatto.channel_capabilities': ['memory', 'mcp_cad']}}, environ={})
            config = load_config(path, environ={})[1]
            self.assertEqual(config['mcp']['servers'], servers)
            fields = {field['id']: field for section in editable_config(path, environ={})['sections'] for field in section['fields']}
            self.assertNotIn('mcp.servers', fields)
            self.assertEqual(fields['mcp.server.cad.command']['type'], 'text')
            self.assertTrue(fields['mcp.server.cad.command']['restart_required'])
            with self.assertRaises(ConfigError):
                update_editable_config(path, {'values': {'mcp.servers': {}}}, environ={})

    def test_mcp_categories_and_individual_gui_fields_preserve_other_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {'mcp': {'servers': {
                'solidcraft': {'title': 'SolidCraft', 'command': 'before',
                              'startup': [{'tool': 'open', 'arguments': {'path': '{workspace}/model'}}]},
                'other': {'title': 'Andere App', 'command': 'other'}}}})
            data = editable_config(path, environ={})
            titles = [section['title'] for section in data['sections']]
            self.assertEqual(titles, sorted(titles, key=str.casefold))
            self.assertIn('SolidCraft', titles)
            self.assertIn('Andere App', titles)
            update_editable_config(path, {'values': {
                'mcp.server.solidcraft.command': '/my/cli',
                'mcp.server.solidcraft.env': {'LANG': 'de_DE.UTF-8'},
                'mcp.server.new_server.command': 'new-cli',
                'mcp.server.new_server.title': 'Neue App'}}, environ={})
            servers = load_config(path, environ={})[1]['mcp']['servers']
            self.assertEqual(servers['solidcraft']['command'], '/my/cli')
            self.assertEqual(servers['solidcraft']['startup'][0]['arguments']['path'], '{workspace}/model')
            self.assertEqual(servers['other'], {'title': 'Andere App', 'command': 'other'})
            self.assertEqual(servers['new_server']['command'], 'new-cli')
            before = path.read_bytes()
            for field, value in [('mcp.server.new_server.scope', 'invalid'),
                                 ('mcp.server.new_server.enabled', 'yes'),
                                 ('mcp.server.new_server.unknown', True),
                                 ('mcp.server.invalid.name.command', 'wrong')]:
                with self.assertRaises(ConfigError):
                    update_editable_config(path, {'values': {field: value}}, environ={})
                self.assertEqual(path.read_bytes(), before)

    def test_local_configuration_is_preferred_and_explicit_path_is_preserved(self):
        from unittest.mock import patch
        import eve_agent.config as configuration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / "eve.json"
            local = root / "eve.local.json"
            example.write_text('{"llm":{"model":"example"}}')
            local.write_text('{"llm":{"model":"installed"}}')
            with patch.object(configuration, "ROOT", root):
                self.assertEqual("installed", load_config(environ={})[1]["llm"]["model"])
                self.assertEqual("example", load_config(example, environ={})[1]["llm"]["model"])
                local.unlink()
                self.assertEqual("example", load_config(environ={})[1]["llm"]["model"])

    def test_member_dm_web_visibility_defaults_off_and_is_editable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {})
            self.assertFalse(load_config(path, environ={})[1]["chatto"]["show_member_dms_in_web"])
            for field in ("show_owner_dms_in_web", "show_channels_in_web"):
                self.assertTrue(load_config(path, environ={})[1]["chatto"][field])
                update_editable_config(path, {"values": {"chatto." + field: False}}, environ={})
                self.assertFalse(load_config(path, environ={})[1]["chatto"][field])

            update_editable_config(path, {"values": {
                "chatto.show_member_dms_in_web": True,
            }}, environ={})
            self.assertTrue(load_config(path, environ={})[1]["chatto"]["show_member_dms_in_web"])
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {
                    "chatto.show_member_dms_in_web": "false",
                }}, environ={})

    def test_only_wayland_desktop_is_configurable(self):
        from eve_agent.config import DEFAULTS, UI_FIELDS, UI_SECTIONS
        self.assertNotIn("computer", DEFAULTS)
        self.assertNotIn("computer", dict(UI_SECTIONS))
        self.assertFalse(any(key.startswith("computer.") for key in UI_FIELDS))
        self.assertIn("wayland_computer.enabled", UI_FIELDS)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(Path(directory), {})
            update_editable_config(path, {"values": {"wayland_computer.enabled": True}}, environ={})
            self.assertTrue(load_config(path, environ={})[1]["wayland_computer"]["enabled"])
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {"computer.enabled": True}}, environ={})

    def test_local_file_roots_are_editable_persisted_and_reject_filesystem_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); shared = root / "shared"; shared.mkdir()
            path = self.write_config(root, {})
            result = update_editable_config(
                path, {"values": {"local_files.roots": [str(shared)]}, "secrets": {}}, environ={},
            )
            field = next(
                field for section in result["sections"] for field in section["fields"]
                if field["id"] == "local_files.roots"
            )
            self.assertEqual([str(shared.resolve())], field["value"])
            self.assertFalse(field["restart_required"])
            self.assertEqual([str(shared.resolve())], load_config(path, environ={})[1]["local_files"]["roots"])
            with self.assertRaises(ConfigError):
                update_editable_config(
                    path, {"values": {"local_files.roots": [str(Path('/'))]}, "secrets": {}}, environ={},
                )
    @staticmethod
    def write_config(root: Path, payload: dict) -> Path:
        path = root / "eve.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_config_loads_and_components_receive_resolved_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {
                "llm": {"base_url": "http://llm.local:1234/v1", "model": "eve-model"},
                "home_assistant": {"enabled": True, "url": "http://ha.local:8123"},
                "storage": {"data_path": "assets", "cache_path": "cache"},
            })
            loaded_root, config = load_config(path, environ={
                "EVE_HOME_ASSISTANT_TOKEN": "test-ha-secret",
                "EVE_LLM_API_KEY": "test-llm-secret",
            })

        self.assertEqual(root, loaded_root)
        self.assertEqual("eve-model", OpenAICompatibleLLM(config["llm"]).model)
        home = HomeAssistant(config["home_assistant"], root)
        self.assertTrue(home.configured)
        self.assertEqual("test-ha-secret", home.token)
        self.assertEqual(root / "assets", Path(config["storage"]["data_path"]))
        self.assertEqual(root / "cache", Path(config["storage"]["cache_path"]))

    def test_defaults_and_relative_paths_preserve_existing_storage_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = load_config(self.write_config(root, {}), environ={})
        self.assertEqual("http://127.0.0.1:1234/v1", config["llm"]["base_url"])
        self.assertTrue(config["llm"]["use_server_limits"])
        self.assertEqual(root / "data" / "eve.db", Path(config["paths"]["database"]))
        self.assertNotIn("memory", config["paths"])
        self.assertEqual(root / "data" / "assets", Path(config["storage"]["data_path"]))
        self.assertEqual(root / "runtime" / "cache", Path(config["storage"]["cache_path"]))
        self.assertEqual({}, config["conversation"])
        self.assertEqual(config["conversation_learning"], {
            "enabled": True, "idle_delay_seconds": 120, "batch_size": 2,
        })
        self.assertEqual(config["working_memory"], {
            "cleanup_enabled": True,
            "completed_retention_hours": 1.0,
            "failed_retention_hours": 24.0,
            "temporary_learning_retention_hours": 0.25,
            "cleanup_interval_minutes": 15,
        })
        self.assertNotIn("mcp_enabled", config["home_assistant"])
        self.assertNotIn("mcp_catalog_ttl_seconds", config["home_assistant"])
        self.assertEqual(config["semantic_similarity"], {
            "enabled": True, "mode": "active", "threshold": .85,
        })
        self.assertEqual(config["semantic_composition"]["mode"], "active")
        self.assertTrue(config["semantic_composition"]["enabled"])
        self.assertEqual(config["memory_runtime_telemetry"], {
            "enabled": False,
            "lifecycle_audit": "required",
            "contract_version": "memory-runtime-events-v1",
            "retention_days": 30,
            "max_detail_bytes": 4096,
        })

    def test_removed_artificial_limits_are_rejected_instead_of_ignored(self):
        cases = (
            {"memory": {"retrieval_limit": 6}},
            {"memory": {"compiler_planner_budget": 384}},
            {"conversation": {"inactivity_timeout_minutes": 5}},
            {"web": {"results": 5}},
            {"web": {"read_pages": 3}},
            {"web": {"page_chars": 5000}},
        )
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                path = self.write_config(Path(directory), payload)
                with self.assertRaisesRegex(ConfigError, "Entfernte künstliche Begrenzung"):
                    load_config(path, environ={})

    def test_memory_runtime_telemetry_configuration_is_versioned_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = load_config(self.write_config(root, {
                "memory_runtime_telemetry": {
                    "enabled": True, "retention_days": 90, "max_detail_bytes": 2048,
                },
            }), environ={})
            self.assertTrue(config["memory_runtime_telemetry"]["enabled"])
            self.assertEqual(90, config["memory_runtime_telemetry"]["retention_days"])
            for value in (511, 16385):
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    load_config(self.write_config(root, {
                        "memory_runtime_telemetry": {"max_detail_bytes": value},
                    }), environ={})
            with self.assertRaises(ConfigError):
                load_config(self.write_config(root, {
                    "memory_runtime_telemetry": {"contract_version": "future-v2"},
                }), environ={})
            with self.assertRaises(ConfigError):
                load_config(self.write_config(root, {
                    "memory_runtime_telemetry": {"lifecycle_audit": "disabled"},
                }), environ={})

    def test_working_memory_retention_is_editable_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {})
            edited = update_editable_config(path, {"values": {
                "working_memory.completed_retention_hours": 2.5,
                "working_memory.failed_retention_hours": 36,
                "working_memory.temporary_learning_retention_hours": 0.5,
                "working_memory.cleanup_interval_minutes": 30,
            }, "secrets": {}}, environ={})
            values = {field["id"]: field["value"] for section in edited["sections"]
                      for field in section["fields"]}
            self.assertEqual(2.5, values["working_memory.completed_retention_hours"])
            self.assertFalse(next(field for section in edited["sections"] for field in section["fields"]
                                  if field["id"] == "working_memory.completed_retention_hours")["restart_required"])
            self.assertEqual(36.0, load_config(path, environ={})[1]["working_memory"]["failed_retention_hours"])
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {
                    "working_memory.temporary_learning_retention_hours": 0,
                }, "secrets": {}}, environ={})

    def test_dynamic_similarity_configuration_is_persisted_editable_and_live_capable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = self.write_config(root, {})
            for threshold in (.80, .85, .95):
                view = update_editable_config(path, {"values": {
                    "semantic_similarity.enabled": True,
                    "semantic_similarity.mode": "shadow" if threshold == .95 else "active",
                    "semantic_similarity.threshold": threshold,
                }}, environ={})
                fields = {item["id"]: item for section in view["sections"] for item in section["fields"]}
                self.assertEqual(fields["semantic_similarity.threshold"]["value"], threshold)
                self.assertFalse(fields["semantic_similarity.threshold"]["restart_required"])
                self.assertEqual(load_config(path, environ={})[1]["semantic_similarity"]["threshold"], threshold)
            before = path.read_bytes()
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {
                    "semantic_similarity.threshold": 1.01,
                }}, environ={})
            self.assertEqual(path.read_bytes(), before)

    def test_home_assistant_defaults_publish_only_the_native_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = load_config(self.write_config(root, {}), environ={})
            self.assertEqual(
                {"enabled", "url", "token", "language", "timeout_seconds"},
                set(config["home_assistant"]),
            )

    def test_process_environment_overrides_dotenv_and_local_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {"llm": {"model": "json-model"}})
            (root / ".env").write_text("EVE_LLM_MODEL=dotenv-model\n", encoding="utf-8")
            _, config = load_config(path, environ={"EVE_LLM_MODEL": "environment-model"})
        self.assertEqual("environment-model", config["llm"]["model"])

    def test_secret_from_dotenv_is_supported_and_not_logged(self):
        secret = "never-print-this-secret"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {
                "home_assistant": {"enabled": True, "url": "http://ha.local:8123"},
            })
            (root / ".env").write_text(f"EVE_HOME_ASSISTANT_TOKEN={secret}\n", encoding="utf-8")
            _, config = load_config(path, environ={})
            output = io.StringIO()
            with redirect_stdout(output):
                print("\n".join(config_status(config)))
        self.assertEqual(secret, config["home_assistant"]["token"])
        self.assertNotIn(secret, output.getvalue())

    def test_enabled_optional_integration_requires_its_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {
                "home_assistant": {"enabled": True, "url": "http://ha.local:8123"},
            })
            with self.assertRaisesRegex(ConfigError, "EVE_HOME_ASSISTANT_TOKEN"):
                load_config(path, environ={})

    def test_legacy_token_file_is_migrated_only_by_central_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "secrets").mkdir()
            (root / "secrets" / "home-assistant.token").write_text("legacy-secret", encoding="utf-8")
            path = self.write_config(root, {
                "home_assistant": {"enabled": True, "url": "http://ha.local:8123", "token_file": "secrets/home-assistant.token"},
            })
            _, config = load_config(path, environ={})
        self.assertEqual("legacy-secret", config["home_assistant"]["token"])
        self.assertNotIn("token_file", config["home_assistant"])

    def test_invalid_urls_numbers_paths_and_secrets_in_json_are_rejected(self):
        cases = (
            ({"llm": {"base_url": "not-a-url"}}, "llm.base_url"),
            ({"audio": {"sample_rate": 1}}, "audio.sample_rate"),
            ({"storage": {"data_path": ""}}, "storage.data_path"),
            ({"home_assistant": {"token": "must-not-be-in-json"}}, "home_assistant.token"),
            ({"llm": {"api_key": "must-not-be-in-json"}}, "llm.api_key"),
        )
        for payload, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                path = self.write_config(Path(directory), payload)
                with self.assertRaisesRegex(ConfigError, message.replace(".", r"\.")):
                    load_config(path, environ={})

    def test_editable_config_reports_effective_sources_without_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {"llm": {"model": "json-model"}})
            (root / ".env").write_text("EVE_HOME_ASSISTANT_TOKEN=top-secret\nEVE_LLM_MODEL=dotenv-model\n", encoding="utf-8")
            view = editable_config(path, environ={"EVE_LLM_MODEL": "process-model"})
        serialized = json.dumps(view)
        self.assertNotIn("top-secret", serialized)
        fields = {item["id"]: item for section in view["sections"] for item in section["fields"]}
        secrets = {item["id"]: item for section in view["sections"] for item in section["secrets"]}
        self.assertEqual(fields["llm.model"]["value"], "process-model")
        self.assertEqual(fields["llm.model"]["source"], "environment")
        self.assertTrue(fields["llm.model"]["overridden"])
        self.assertTrue(secrets["home_assistant.token"]["configured"])

    def test_non_operational_storage_paths_are_not_exposed_as_editable_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {})
            (root / ".env").write_text("EVE_LLM_API_KEY=keep-me\n", encoding="utf-8")
            view = editable_config(path, environ={})
            with self.assertRaisesRegex(ConfigError, "storage.data_path"):
                update_editable_config(path, {
                    "values": {"storage.data_path": "var/assets"},
                    "secrets": {"llm.api_key": ""},
                }, environ={})
            env_text = (root / ".env").read_text(encoding="utf-8")
        self.assertIn("EVE_LLM_API_KEY=keep-me", env_text)
        self.assertNotIn("storage", {section["id"] for section in view["sections"]})

    def test_editable_fields_are_described_and_environment_overrides_are_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {})
            (root / ".env").write_text("EVE_STT_MODEL=medium\n", encoding="utf-8")
            view = editable_config(path, environ={})
        fields = {item["id"]: item for section in view["sections"] for item in section["fields"]}
        secrets = {item["id"]: item for section in view["sections"] for item in section["secrets"]}
        self.assertTrue(all(item.get("description") for item in (*fields.values(), *secrets.values())))
        self.assertEqual("medium", fields["speech_to_text.model"]["value"])
        self.assertTrue(fields["speech_to_text.model"]["locked"])
        self.assertEqual("small", fields["speech_to_text.model"]["default"])
        self.assertFalse(fields["speech_to_text.language"]["locked"])

    def test_stt_runtime_values_are_bounded_to_values_consumed_by_faster_whisper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {
                "speech_to_text": {"model": "medium", "language": "DE", "device": "cpu", "compute_type": "int8"},
            })
            _, config = load_config(path, environ={})
            self.assertEqual("medium", config["speech_to_text"]["model"])
            self.assertEqual("de", config["speech_to_text"]["language"])
            for key, value in (("device", "metal"), ("compute_type", "fp8")):
                with self.subTest(key=key), self.assertRaises(ConfigError):
                    load_config(self.write_config(root, {"speech_to_text": {key: value}}), environ={})

    def test_editable_update_sets_secret_and_reloads_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {})
            view = update_editable_config(path, {"secrets": {"home_assistant.token": "new-secret"}}, environ={})
            mode = (root / ".env").stat().st_mode & 0o777
            serialized = json.dumps(view)
        self.assertEqual(mode, 0o600)
        self.assertNotIn("new-secret", serialized)
        self.assertIn('"configured": true', serialized)

    def test_invalid_or_unknown_edit_is_rejected_without_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_config(root, {"llm": {"model": "before"}})
            before = path.read_bytes()
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {"llm.timeout_seconds": 0}}, environ={})
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": {"visual.secret_switch": True}}, environ={})
            self.assertEqual(path.read_bytes(), before)
