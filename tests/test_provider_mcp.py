import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator

from eve_agent.agent import EveAgent
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.minimal import NativeToolRuntime
from eve_agent.nova_maintenance import NovaMaintenance
from eve_agent.provider_mcp import ProviderMcpCapability
from eve_agent.state import StateBus
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.work_tasks import WorkTaskStore


class ProviderMcpTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = EveDatabase(self.root / "eve.db")
        self.store = WorkTaskStore(self.db)
        self.tasks = self.store.create_list("Projekt Heimnetz")
        self.other = self.store.create_list("Andere Liste")
        self.conversations = ConversationStore(self.db)
        self.conversation = self.conversations.create("MCP fixture")
        self.provider = self.client("work_tasks")

    def client(self, name):
        client = ProviderMcpCapability(name, self.root, database=self.db.path)
        self.addCleanup(client.close_all)
        return client

    def test_discovery_create_read_search_update_and_provenance_cross_real_stdio(self):
        contract = self.provider.minimal_contract(self.conversation["id"])
        self.assertEqual("mcp-stdio", contract["runtime"]["transport"])
        self.assertNotIn("attach_mutation_provenance", contract["operations"])
        schema = contract["operations"]["create_item"]["parameters_schema"]
        self.assertIn("list_id", schema["properties"])
        self.assertNotIn("arguments", schema["properties"])
        args = {"list_id": self.tasks["id"], "title": "Dual-Stack beantragen", "description": "Testbeschreibung"}
        Draft202012Validator(schema).validate(args)
        created = self.provider.execute_operation("create_item", args, conversation_id=self.conversation["id"])["result"]
        self.assertEqual(self.tasks["id"], created["list_id"])
        user, _ = self.conversations.append_turn(self.conversation["id"], "Lege die Aufgabe an", "Erledigt")
        links = self.provider.attach_mutation_provenance(self.conversation["id"], user["id"])
        self.assertEqual(user["id"], links[0]["start_message_id"])
        loaded = self.provider.execute_operation("list_items", {"list_name": "Projekt Heimnetz"})["result"]
        self.assertEqual([created["id"]], [item["id"] for item in loaded])
        self.assertEqual([], self.provider.execute_operation("list_items", {"list_id": self.other["id"]})["result"])
        discoveries = []
        search = self.provider.execute_operation("search_items", {"query": "Dual-Stack"}, discoveries=discoveries)
        self.assertEqual(created["id"], search["result"][0]["id"])
        self.assertTrue(discoveries)
        self.provider.execute_operation("complete_item", {"item_id": created["id"]}, discoveries=discoveries)
        self.assertEqual("completed", self.store.get_item(created["id"])["status"])
        refreshed = self.provider.minimal_contract(self.conversation["id"], discoveries)
        self.assertEqual(created["id"], refreshed["active_items"][0]["id"])

    def test_nested_arguments_rejected_by_server_without_writing_and_errors_are_preserved(self):
        self.provider.minimal_contract()
        result = self.provider._request("tools/call", {"name": "create_item", "arguments": {
            "arguments": {"list_id": self.tasks["id"], "title": "Wrong envelope"}}})
        self.assertTrue(result["isError"])
        self.assertEqual("ValidationError", result["structuredContent"]["error_class"])
        self.assertEqual([], self.store.list_items())
        with self.assertRaisesRegex(ValueError, "nicht veröffentlicht"):
            self.provider.execute_operation("create_item", {"list_id": "missing", "title": "Missing list"})
        self.assertEqual([], self.store.list_items())

    def test_cli_build_keeps_browser_store_and_mcp_on_the_same_database(self):
        from eve_agent.cli import build
        from eve_agent.config import load_config
        shared = self.root / "shared"
        shared.mkdir()
        config_path = self.root / "test-instance.json"
        config_path.write_text(json.dumps({"paths": {"database": str(self.db.path)},
            "local_files": {"roots": [str(shared)]},
            "memory_search": {"model": ""}, "wayland_computer": {"enabled": False},
            "web": {"enabled": False}}))
        (self.root / "eve.json").write_text('{"local_files":{"roots":[]}}')
        _, config = load_config(config_path, environ={})
        _, _, _, agent, reminders = build(self.root, config, config_path=config_path)
        self.addCleanup(agent.work_tasks.close_all)
        self.addCleanup(agent.shell.close_all)
        self.addCleanup(agent.working_memory_cleanup.close)
        self.addCleanup(reminders.stop)
        self.assertEqual((shared,), agent.local_files.reader.roots())
        config_path.write_text('{"local_files":{"roots":[]}}')
        self.assertEqual((), agent.local_files.reader.roots())
        self.assertIsInstance(agent.work_tasks, ProviderMcpCapability)
        self.assertIsInstance(agent.work_task_store, WorkTaskStore)
        gui_item = agent.work_task_store.create_item(self.tasks["id"], "Browser task")
        result = agent.work_tasks.execute_operation("list_items", {"list_id": self.tasks["id"]})["result"]
        self.assertEqual([gui_item["id"]], [item["id"] for item in result])

    def test_model_tool_path_uses_the_discovered_schema_and_persists_the_right_task(self):
        llm = SimpleNamespace(request_tool_turn=Mock(), max_tokens=1500, runtime_model_info=lambda: {})
        agent = EveAgent("EVE", MemoryV2Runtime(self.db, MemoryCompiler(self.db)), llm,
                         StateBus(self.root / "runtime"), work_tasks=self.provider)
        agent.conversation_id = self.conversation["id"]
        llm.request_tool_turn.side_effect = [
            {"content": "", "tool_calls": [{"id": "load", "name": "eve__load_capabilities", "arguments": {"capabilities": ["work_tasks"]}}]},
            {"content": "", "tool_calls": [{"id": "create", "name": "work_tasks__create_item", "arguments": {
                "list_name": "Projekt Heimnetz", "title": "Dual-Stack bei DGN beantragen", "description": "Öffentliche IPv4 anfragen"}}]},
            {"content": "Die Aufgabe wurde erstellt.", "tool_calls": []},
        ]
        self.assertEqual("Die Aufgabe wurde erstellt.", NativeToolRuntime(agent).respond("Erstelle die Heimnetzaufgabe"))
        tool = next(t["function"] for t in llm.request_tool_turn.call_args_list[1].args[1]
                    if t["function"]["name"] == "work_tasks__create_item")
        self.assertIn("title", tool["parameters"]["required"])
        result = json.loads(next(m["content"] for m in reversed(llm.request_tool_turn.call_args_list[2].args[0]) if m["role"] == "tool"))
        self.assertEqual(self.tasks["id"], result["list_id"])
        self.assertEqual("Dual-Stack bei DGN beantragen", self.store.list_items(list_id=self.tasks["id"])[0]["title"])

    def test_nova_discovery_and_run_execute_a_real_configured_program_through_mcp(self):
        binary = self.root / "fixture-codex"
        binary.write_text('''#!/usr/bin/python3
import json,sys
from pathlib import Path
schema=json.loads(Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
result={"status":"completed","root_cause_found":True,"error_description":"Fixture consultation reached Codex", "changes":[],"changed_files":[],"tests":{"status":"not_run","summary":"diagnosis"},"remaining_risks":[],"next_action":"Inspect the contract", "restart_or_deployment_required":False}
Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(result))
''')
        binary.chmod(0o700)
        (self.root / "src").mkdir()
        (self.root / "src/sample.py").write_text("VALUE = 1\n")
        (self.root / "eve.json").write_text('{"nova_maintenance":{"enabled":false}}')
        config_path = self.root / "eve.local.json"
        config_path.write_text(json.dumps({"nova_maintenance": {
            "enabled": True, "command": str(binary), "require_process_isolation": False}}))
        nova = ProviderMcpCapability("nova", self.root, config_path=config_path)
        self.addCleanup(nova.close_all)
        contract = nova.minimal_contract()
        self.assertEqual(["instruction", "level"], contract["operations"]["run"]["parameters_schema"]["required"])
        llm = SimpleNamespace(request_tool_turn=Mock(), max_tokens=1500, runtime_model_info=lambda: {})
        agent = EveAgent("EVE", MemoryV2Runtime(self.db, MemoryCompiler(self.db)), llm,
                         StateBus(self.root / "runtime"), nova_maintenance=nova)
        llm.request_tool_turn.side_effect = [
            {"content": "", "tool_calls": [{"id": "load", "name": "eve__load_capabilities", "arguments": {"capabilities": ["nova"]}}]},
            {"content": "", "tool_calls": [{"id": "consult", "name": "nova__run", "arguments": {"instruction": "Inspect the schema", "level": "diagnosis"}}]},
            {"content": "Nova wurde konsultiert.", "tool_calls": []},
        ]
        NativeToolRuntime(agent).respond("Lass Nova die Schnittstelle prüfen")
        answer = json.loads(next(m["content"] for m in reversed(llm.request_tool_turn.call_args_list[2].args[0]) if m["role"] == "tool"))
        self.assertIn("Fixture consultation reached Codex", answer["result"])
        self.assertEqual("completed", answer["report"]["status"])
        self.assertEqual("VALUE = 1\n", (self.root / "src/sample.py").read_text())
        self.assertIn("keinen offenen", nova.execute_operation("pending_info", {})["result"])

    def test_standard_mcp_client_can_search_then_read_without_eve_metadata(self):
        item = self.store.create_item(self.tasks["id"], "Standalone MCP task")
        self.provider.minimal_contract()
        found = self.provider._request("tools/call", {"name": "search_items", "arguments": {"query": "Standalone"}})
        self.assertFalse(found["isError"])
        read = self.provider._request("tools/call", {"name": "get_item", "arguments": {"item_id": item["id"]}})
        self.assertFalse(read["isError"])
        self.assertEqual(item["id"], read["structuredContent"]["result"]["id"])

    def test_array_and_object_fields_are_typed_and_execute_without_a_second_envelope(self):
        self.provider.minimal_contract()
        batch = self.provider.execute_operation("create_items", {"list_id": self.tasks["id"],
            "items": [{"title": "Erster Schritt"}, {"title": "Zweiter Schritt", "description": "Details"}]})["result"]
        self.assertEqual(2, sum(item["status"] == "created" for item in batch["items"]))
        discoveries = []
        found = self.provider.execute_operation("search_items", {"query": "Erster"}, discoveries=discoveries)["result"]
        item_id = found[0]["id"]
        self.provider.execute_operation("update_item", {"item_id": item_id,
            "changes": {"title": "Neuer Titel", "metadata": {"integration_test": True}}}, discoveries=discoveries)
        self.assertEqual("Neuer Titel", self.store.get_item(item_id)["title"])
        self.assertEqual(True, self.store.get_item(item_id)["metadata"]["integration_test"])

    def test_nova_launch_failure_is_a_tool_error_and_contains_the_cause(self):
        (self.root / "eve.json").write_text(json.dumps({"nova_maintenance": {
            "enabled": True, "command": str(self.root / "missing-codex")}}))
        nova = self.client("nova")
        self.assertFalse(nova.minimal_contract()["execution"]["available"])
        with self.assertRaisesRegex(ValueError, "Codex-Programm wurde nicht gefunden"):
            nova.execute_operation("run", {"instruction": "Synthetic diagnostic", "level": "diagnosis"})

    def test_disconnected_write_is_not_retried_or_replaced_by_direct_execution(self):
        self.provider.minimal_contract()
        process = self.provider.client.process
        process.terminate()
        process.wait(timeout=5)
        for thread in self.provider.client.threads:
            thread.join(timeout=1)
        with self.assertRaises(RuntimeError):
            self.provider.execute_operation("create_item", {"list_id": self.tasks["id"], "title": "No retry"})
        self.assertEqual([], self.store.list_items())

    def test_nova_resolves_desktop_binary_even_with_service_path(self):
        nova = NovaMaintenance(self.root, {"enabled": True})
        desktop = self.root / "desktop-bin"
        desktop.mkdir()
        binary = desktop / "codex"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}), patch.object(
                nova, "_runner_environment", return_value={"PATH": str(desktop)}):
            self.assertEqual(str(binary), nova._resolve_command())
        nova.command = str(self.root / "missing-explicit-codex")
        with self.assertRaisesRegex(RuntimeError, "nicht gefunden"):
            nova._resolve_command()


if __name__ == "__main__":
    unittest.main()
