import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from eve_agent.agent import EveAgent
from eve_agent.home_assistant import HomeAssistant
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime, _response_shape
from eve_agent.minimal import CORE_PROMPT, NativeToolRuntime
from eve_agent.state import StateBus
from eve_agent.storage import EveDatabase


class NativeHome(HomeAssistant):
    def __init__(self):
        super().__init__({"url": "http://fixture.invalid", "token": "fixture"}, Path("."))
        self.calls = []
        self.failure = None

    def execute_native_operation(self, operation, parameters):
        self.calls.append((operation, parameters))
        if self.failure:
            raise self.failure
        return {
            "status": "completed",
            "request": {
                "method": parameters.get("method"),
                "path": parameters.get("path"),
                "query": parameters.get("query", {}),
            },
            "response": {"status": 200, "body": {"entity_id": "light.flur", "state": "on"}},
        }


class NativeRuntimeTest(unittest.TestCase):
    def test_repeated_memory_submission_is_complete_and_retained_for_later_learning(self):
        from eve_agent.storage import ConversationStore
        self.agent.conversations = ConversationStore(self.database)
        self.agent.conversation_id = self.agent.conversations.create('Memory submission')['id']
        fact = 'Private Informationen nur an berechtigte Personen weitergeben.'
        receipts = []

        def model(messages, tools, *args, **kwargs):
            if messages[-1]['role'] == 'tool':
                receipt = json.loads(messages[-1]['content'])
                receipts.append(receipt)
                self.assertTrue(receipt['submission_complete'])
                self.assertFalse(receipt['persisted'])
                self.assertFalse(receipt['retry_needed'])
                self.assertEqual(receipt['processing'], 'after_turn_completion')
            if len(receipts) < 2:
                return {'content': '', 'tool_calls': [{
                    'id': 'remember-' + str(len(receipts)), 'name': 'memory__remember',
                    'arguments': {'fact': fact}}]}
            return {'content': 'Zum Lernen angenommen.', 'tool_calls': []}

        self.llm.request_tool_turn.side_effect = model
        self.assertEqual(self.runtime.respond('Merke dir: ' + fact), 'Zum Lernen angenommen.')
        self.assertFalse(receipts[0]['already_accepted'])
        self.assertTrue(receipts[1]['already_accepted'])
        self.assertEqual(receipts[0]['submission_id'], receipts[1]['submission_id'])
        with self.database.connect() as c:
            message = c.execute("SELECT metadata_json FROM messages WHERE role='assistant'").fetchone()
            details = json.loads(message[0])['turn_state_details']
            self.assertEqual(details['explicit_memory_fact'], fact)
            events = c.execute('SELECT result_json FROM conversation_tool_events ORDER BY ordinal').fetchall()
            self.assertEqual(len(events), 2)
            self.assertEqual([json.loads(row[0])['fact'] for row in events], [fact, fact])
            self.assertEqual(c.execute('SELECT count(*) FROM memory_claims').fetchone()[0], 0)

        receipts.clear()
        self.runtime.respond('Merke dir erneut: ' + fact)
        self.assertFalse(receipts[0]['already_accepted'])

    def test_memory_duplicates_do_not_overwrite_a_later_distinct_submission(self):
        state = {}
        first, _ = self.runtime._execute_direct('memory', 'remember', {'fact': 'Regel A'}, state, [])
        second, _ = self.runtime._execute_direct('memory', 'remember', {'fact': 'Regel B'}, state, [])
        repeated, _ = self.runtime._execute_direct('memory', 'remember', {'fact': 'Regel A'}, state, [])
        self.assertNotEqual(first['submission_id'], second['submission_id'])
        self.assertEqual(first['submission_id'], repeated['submission_id'])
        self.assertTrue(repeated['already_accepted'])
        self.assertEqual(self.agent._turn_state_details['explicit_memory_fact'], 'Regel B')

    def test_direct_revision_is_loaded_after_inspection_and_uses_actual_current_input(self):
        from eve_agent.storage import ConversationStore
        self.agent.conversations = ConversationStore(self.database)
        self.agent.conversation_id = self.agent.conversations.create('Revision')['id']
        with self.database.connect() as c:
            c.execute("INSERT INTO memory_claims(id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,verification_policy,created_at,updated_at) "
                      "VALUES ('old','opaque_fact','user:default','v2:old','v2:emoji','Homocysten','{}','active','stable','2026-01-01','2026-01-01')")
        text = 'Home Assistant war gemeint.'
        calls = []
        def model(messages, tools, *args, **kwargs):
            names = {tool['function']['name'] for tool in tools}
            self.assertEqual(messages[0], {'role': 'system', 'content': CORE_PROMPT})
            calls.append(names)
            if len(calls) == 1:
                self.assertNotIn('memory__revise', names)
                return {'content':'','tool_calls':[{'id':'inspect','name':'memory__inspect','arguments':{'memory_id':'old'}}]}
            if len(calls) == 2:
                self.assertIn('memory__revise', names)
                return {'content':'','tool_calls':[{'id':'revise','name':'memory__revise','arguments':{
                    'mutation_id':'one','target_id':'old','expected_version':self.agent.memory.revisions.inspect('old')['version'],
                    'source_reference':self.runtime.working_session.request['reference'], 'evidence_quote':text,
                    'action':'correct','replacement':{'display_text':text,'payload':{'epistemic_kind':'user_instruction'}}}}]}
            return {'content':'Korrigiert.','tool_calls':[]}
        self.llm.request_tool_turn.side_effect = model
        self.assertEqual(self.runtime.respond(text), 'Korrigiert.')
        self.assertEqual(self.agent.memory.revisions.inspect('old')['claim']['lifecycle'], 'retired')
        result = self.agent._tool_events[-1]['result']
        self.assertEqual(result['status'], 'applied')
        detail = self.agent.memory.revisions.inspect(result['claim_id'])
        self.assertIsNotNone(detail['evidence'][0]['source_message_id'])
        self.assertEqual(self.home.calls, [])
        self.llm.request_tool_turn.side_effect = None
        self.llm.request_tool_turn.return_value = {'content':'Hallo','tool_calls':[]}
        self.runtime.respond('Hallo')
        names = {t['function']['name'] for t in self.llm.request_tool_turn.call_args.args[1]}
        self.assertNotIn('memory__revise', names)

    def test_memory_can_be_called_in_first_round_in_public_channel(self):
        from eve_agent.transport_access import transport_access
        self.llm.request_tool_turn.side_effect = [
            {"content": "", "tool_calls": [{"id": "remember", "name": "memory__remember",
                "arguments": {"fact": "Private Informationen nur mit dem passenden Teilnehmerkreis teilen."}}]},
            {"content": "Verstanden.", "tool_calls": [], "finish_reason": "stop"},
        ]
        with transport_access({'room_kind': 'channel'}, public=True):
            self.assertEqual(self.runtime.respond("Merke dir diese Regel."), "Verstanden.")
        first_tools = self.llm.request_tool_turn.call_args_list[0].args[1]
        self.assertIn('memory__remember', {t['function']['name'] for t in first_tools})
        self.assertEqual(self.agent._tool_events[0]['tool'], 'memory')
        self.assertEqual(self.agent._tool_events[0]['result']['status'], 'accepted')
        self.assertEqual(self.home.calls, [])

    def test_public_channel_hides_and_blocks_privileged_tools_without_changing_prompt(self):
        from eve_agent.transport_access import transport_access
        self.assertIn('home_assistant', self.runtime._capabilities())
        blocked = ('home_assistant', 'home_assistant_inventory', 'shell', 'local_files', 'local_search',
                   'nova', 'network', 'wayland_computer', 'scheduled_tasks', 'work_tasks', 'assist_events', 'presentation')
        with transport_access({'room_kind': 'channel'}, public=True):
            published = self.runtime._capabilities()
            self.assertIn('memory', published)
            for capability in blocked:
                self.assertNotIn(capability, published)
                with self.assertRaises(PermissionError):
                    self.runtime._execute_direct(capability, 'arbitrary', {}, {}, [])
            with self.assertRaises(ValueError):
                self.runtime._execute_direct('eve_runtime', 'load_capabilities', {'capabilities': ['home_assistant']}, {}, [])
            self.llm.request_tool_turn.return_value = {"content": "Hallo.", "tool_calls": [], "finish_reason": "stop"}
            self.runtime.respond("Hallo")
            messages = self.llm.request_tool_turn.call_args.args[0]
            self.assertEqual(messages[0], {"role": "system", "content": CORE_PROMPT})
            self.assertEqual(sum(item["role"] == "system" for item in messages), 1)
        self.assertEqual(self.home.calls, [])
        self.assertIn('home_assistant', self.runtime._capabilities())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        database = EveDatabase(root / "eve.db")
        self.database = database
        self.home = NativeHome()
        self.llm = SimpleNamespace(
            request_tool_turn=Mock(), max_tokens=1500,
            runtime_model_info=lambda: {},
        )
        self.agent = EveAgent(
            "EVE", MemoryV2Runtime(database, MemoryCompiler(database)),
            self.llm, StateBus(root / "runtime"), home_assistant=self.home,
        )
        self.runtime = NativeToolRuntime(self.agent)

    def test_event_inbox_is_available_as_native_tools_without_automatic_consumption(self):
        from eve_agent.assist_events import AssistEventInbox
        inbox = AssistEventInbox(Path(self.tmp.name) / "events.sqlite3")
        inbox.receive({"event_id": "one", "event_type": "arbitrary", "data": {"value": "raw"}})
        self.agent.assist_events = inbox
        self.assertIn("assist_events", self.runtime._capabilities())
        self.llm.request_tool_turn.assert_not_called()
        data, route = self.runtime._execute_direct("assist_events", "list", {}, {}, [])
        self.assertEqual(data["groups"][0]["count"], 1)
        self.assertEqual(inbox.groups()["pending_count"], 1)
        group = data["groups"][0]
        self.runtime._execute_direct("assist_events", "acknowledge", {
            "group_id": group["group_id"], "through_sequence": group["through_sequence"]}, {}, [])
        self.assertEqual(inbox.groups()["pending_count"], 0)
        self.assertEqual(inbox.groups()["total_count"], 1)
        self.llm.request_tool_turn.assert_not_called()

    def test_structured_memory_tool_is_published_and_returns_completeness(self):
        self.llm.request_tool_turn.side_effect = [
            {"content": "", "tool_calls": [{"id": "load", "name": "eve__load_capabilities",
                "arguments": {"capabilities": ["memory"]}}]},
            {"content": "", "tool_calls": [{"id": "inventory", "name": "memory__inventory",
                "arguments": {"provider": "home_assistant", "domain": "light"}}]},
            {"content": "Keine gespeicherten Lichter.", "tool_calls": []},
        ]
        self.runtime.respond("Welche Lichter sind gespeichert?")
        self.assertEqual([], self.home.calls)
        calls = self.llm.request_tool_turn.call_args_list
        tools = {t["function"]["name"] for t in calls[1].args[1]}
        self.assertIn("memory__inventory", tools)
        self.assertIn("memory__find", tools)
        messages = calls[2].args[0]
        result = json.loads(next(m["content"] for m in reversed(messages)
                                 if m.get("role") == "tool"))
        self.assertTrue(result["complete"])
        self.assertEqual(0, result["total_matches"])
        self.assertFalse(result["live_verified"])

    def test_shell_is_discovered_and_real_output_reaches_the_model(self):
        from eve_agent.shell import ShellCapability
        self.agent.shell = ShellCapability({"enabled": True, "forbidden_commands": ["rm -rf"]}, Path(self.tmp.name))
        self.addCleanup(self.agent.shell.close_all)
        self.llm.request_tool_turn.side_effect = [
            {"content": "", "tool_calls": [{"id": "load-shell", "name": "eve__load_capabilities",
                "arguments": {"capabilities": ["shell"]}}]},
            {"content": "", "tool_calls": [{"id": "run-shell", "name": "shell__execute",
                "arguments": {"command": "printf shell-output", "wait_seconds": 5}}]},
            {"content": "shell-output", "tool_calls": []},
        ]
        self.assertEqual("shell-output", self.runtime.respond("Führe einen Shellbefehl aus."))
        messages = self.llm.request_tool_turn.call_args_list[2].args[0]
        result = json.loads(next(message["content"] for message in reversed(messages) if message.get("role") == "tool"))
        self.assertEqual("shell-output", result["stdout"])
        self.assertEqual(0, result["exit_code"])
        self.agent.shell.configure({"enabled": False})
        self.assertNotIn("shell", self.runtime._capabilities())

    def test_transient_password_reaches_shell_with_confidential_output(self):
        import hashlib
        import re
        from eve_agent.shell import ShellCapability
        from eve_agent.storage import ConversationStore
        from eve_agent.transient_credentials import current_credentials, resolve_credentials
        secret = 'Transient-Only&Secret-8216'
        self.agent.conversations = ConversationStore(self.database)
        self.agent.conversation_id = self.agent.conversations.create('Transient credentials')['id']
        self.agent.shell = ShellCapability({'enabled': True, 'forbidden_commands': []}, Path(self.tmp.name))
        self.addCleanup(self.agent.shell.close_all)
        requests = []
        references = []
        def request(messages, tools, *args, **kwargs):
            encoded = json.dumps(messages, ensure_ascii=False)
            self.assertNotIn(secret, encoded)
            requests.append(encoded)
            if len(requests) == 1:
                reference = re.search(r'\{\{eve_secret:[a-f0-9]{32}\}\}', encoded).group(0)
                references.append(reference)
                return {'content': '', 'tool_calls': [{'id': 'load', 'name': 'eve__load_capabilities', 'arguments': {'capabilities': ['shell']}}]}
            if len(requests) == 2:
                return {'content': '', 'tool_calls': [{'id': 'execute', 'name': 'shell__execute', 'arguments': {
                    'command': 'test "$(printf %s "$EVE_PASSWORD" | sha256sum | cut -c1-64)" = ' + hashlib.sha256(secret.encode()).hexdigest() + '; code=$?; printf %s "${EVE_PASSWORD:0:3}"; printf %s "$EVE_PASSWORD" >&2; exit $code',
                    'env': {'EVE_PASSWORD': references[0]}, 'wait_seconds': 5}}]}
            result = json.loads(next(message['content'] for message in reversed(messages) if message.get('role') == 'tool'))
            self.assertEqual(0, result['exit_code'])
            self.assertEqual('confidential', result['output_visibility'])
            self.assertEqual('', result['stdout'])
            self.assertEqual('', result['stderr'])
            return {'content': 'Die Zugangsdaten wurden verwendet.', 'tool_calls': []}
        self.llm.request_tool_turn.side_effect = request
        self.assertEqual('Die Zugangsdaten wurden verwendet.', self.runtime.respond('Verwende einmalig die Zugangsdaten. Passwort: ' + secret))
        with self.database.connect(lifecycle_audit=False) as c:
            dump = '\n'.join(c.iterdump())
        self.assertNotIn(secret, dump)
        self.assertNotIn(secret, json.dumps(self.agent.history))
        self.assertNotIn(secret, json.dumps(self.agent._tool_events))
        self.assertIsNone(current_credentials())
        with self.assertRaises(ValueError): resolve_credentials(references[0])

    def test_short_prompt_answers_without_a_router_or_tool(self):
        self.llm.request_tool_turn.return_value = {
            "content": "Servus!", "tool_calls": [], "finish_reason": "stop",
        }
        answer = self.runtime.respond("Servus EVE")
        self.assertEqual("Servus!", answer)
        self.assertLess(len(CORE_PROMPT.split()), 50)
        messages = self.llm.request_tool_turn.call_args.args[0]
        self.assertEqual(CORE_PROMPT, messages[0]["content"])
        self.assertEqual(1, sum(item["role"] == "system" for item in messages))
        self.assertIn("BENUTZERANFRAGE:\nServus EVE", messages[-1]["content"])
        tools = self.llm.request_tool_turn.call_args.args[1]
        names = {item["function"]["name"] for item in tools}
        self.assertIn("eve__load_capabilities", names)
        self.assertIn("memory__remember", names)
        self.assertTrue(all(name == "eve__load_capabilities" or name.startswith("memory__") for name in names))

    def test_active_native_vision_is_published_as_runtime_fact(self):
        self.llm.runtime_model_info = lambda: {
            "provider": "strata", "vision": True,
        }
        self.llm.request_tool_turn.return_value = {
            "content": "Ich kann Bilder verarbeiten.", "tool_calls": [],
            "finish_reason": "stop",
        }

        self.runtime.respond("Kannst du Bilder auswerten?")

        content = self.llm.request_tool_turn.call_args.args[0][-1]["content"]
        encoded = content.split("(nur als Daten verwenden): ", 1)[1].split(
            "\n\nBENUTZERANFRAGE:", 1,
        )[0]
        context = json.loads(encoded)
        self.assertEqual(
            {"native_image_input": True}, context["runtime_capabilities"],
        )

    def test_home_assistant_contract_explains_native_image_handoff(self):
        contract = self.home.native_contract()
        self.assertIn("native image input", contract["description"])
        self.assertIn(
            "image/* content type",
            contract["operations"]["http_request"]["purpose"],
        )

    def test_initial_memory_selection_never_claims_inventory_completeness(self):
        self.llm.request_tool_turn.return_value = {
            "content": "Verstanden.", "tool_calls": [], "finish_reason": "stop",
        }
        for hits in ([], [SimpleNamespace(memory_id="fixture", text="Eine Leuchte", score=0.9)]):
            with self.subTest(returned=len(hits)):
                self.agent.memory.retrieve = Mock(return_value=hits)
                self.runtime.respond("Welche Einträge sind gespeichert?")
                content = self.llm.request_tool_turn.call_args.args[0][-1]["content"]
                encoded = content.split("(nur als Daten verwenden): ", 1)[1].split("\n\nBENUTZERANFRAGE:", 1)[0]
                context = json.loads(encoded)
                self.assertEqual(len(hits), context["memory_retrieval"]["returned"])
                self.assertFalse(context["memory_retrieval"]["complete_inventory"])
                self.assertEqual("relevance_selection", context["memory_retrieval"]["mode"])

    def test_qwen_calls_native_home_assistant_without_eve_action_schema(self):
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "call-ha", "name": "home_assistant__http_request",
                    "arguments": {
                        "method": "GET", "path": "/api/states/light.flur",
                    },
                }],
            },
            {"content": "Das Flurlicht ist an.", "tool_calls": [], "finish_reason": "stop"},
        ]
        answer = self.runtime.respond("Ist das Licht im Flur an?")
        self.assertEqual("Das Flurlicht ist an.", answer)
        self.assertEqual([
            ("http_request", {"method": "GET", "path": "/api/states/light.flur"}),
        ], self.home.calls)
        initial_tools = self.llm.request_tool_turn.call_args_list[0].args[1]
        initial_names = {item["function"]["name"] for item in initial_tools}
        self.assertIn("memory__remember", initial_names)
        self.assertNotIn("home_assistant__http_request", initial_names)
        tools = self.llm.request_tool_turn.call_args_list[1].args[1]
        names = {item["function"]["name"] for item in tools}
        self.assertIn("eve__load_capabilities", names)
        self.assertIn("home_assistant__http_request", names)
        self.assertIn("home_assistant__websocket_command", names)
        self.assertFalse({
            "home_assistant__discover", "home_assistant__list_entities",
            "home_assistant__execute_actions", "home_assistant__upsert_automation",
        } & names)
        self.assertTrue(all(
            item["function"]["parameters"].get("type") == "object"
            and isinstance(item["function"]["parameters"].get("properties"), dict)
            for item in tools
        ))
        self.assertEqual({
            "state": "tool:home_assistant",
            "detail": "home_assistant · http_request",
        }, {
            key: self.agent.bus.read()[key] for key in ("state", "detail")
        })

    def test_tool_animation_state_uses_the_dispatched_capability_without_routing(self):
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-clock", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["clock"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "clock-now", "name": "clock__now", "arguments": {},
                }],
            },
            {"content": "Es ist Testzeit.", "tool_calls": [], "finish_reason": "stop"},
        ]

        self.runtime.respond("Wie spät ist es?")

        state = self.agent.bus.read()
        self.assertEqual("tool:clock", state["state"])
        self.assertEqual("clock · now", state["detail"])

    def test_confirmed_exact_action_memory_is_published_before_qwen_decides(self):
        text = "Schalte die Stehlampen im Wohnzimmer ein."
        plan = {
            "effect": "write",
            "actions": [{
                "type": "call_service",
                "entity_id": "light.wohnzimmer_stehlampen",
                "service": "light.turn_on",
            }],
            "live_verification_required": True,
            "semantic_learning": {
                "status": "resolved", "context_keys": [],
                "user_grounding": "explicit", "uncertainties": [],
                "utterance_quote": text, "basis": "fixture",
            },
        }
        claim_id = self.agent.semantic_links.learn(
            text, {
                "conversation_id": self.agent.conversation_id,
                "history": [], "pending": None, "focus": [], "task_active": False,
            },
            self.home.semantic_provider_identity(), plan, {"status": "success"},
            source_ref="fixture:turn", provider_validated=True,
        )
        self.agent.semantic_links.decide(
            claim_id, confirmed=True, source_ref="fixture:confirmation",
        )
        self.llm.request_tool_turn.return_value = {
            "content": "Verstanden.", "tool_calls": [], "finish_reason": "stop",
        }

        self.runtime.respond(text)

        messages = self.llm.request_tool_turn.call_args.args[0]
        user_message = messages[-1]["content"]
        self.assertIn('"kind":"learned_action_experience"', user_message)
        self.assertIn('"entity_id":"light.wohnzimmer_stehlampen"', user_message)
        self.assertIn('"service":"light.turn_on"', user_message)
        self.assertIn(claim_id, self.agent._turn_memory_ids)
        self.assertNotIn("semantic_learning", user_message)

    def test_real_provider_error_returns_to_qwen_as_tool_result(self):
        self.home.failure = RuntimeError("HTTP 400: native validation detail")
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "call-ha", "name": "home_assistant__http_request",
                    "arguments": {
                        "method": "POST", "path": "/api/config/automation/config/test",
                        "body": {"alias": "test"},
                    },
                }],
            },
            {
                "content": "Home Assistant hat die Konfiguration mit HTTP 400 abgelehnt.",
                "tool_calls": [], "finish_reason": "stop",
            },
        ]
        answer = self.runtime.respond("Erstelle die Automation")
        self.assertIn("HTTP 400", answer)
        final_messages = self.llm.request_tool_turn.call_args_list[2].args[0]
        tool_result = next(
            item for item in reversed(final_messages)
            if item["role"] == "tool"
        )
        self.assertIn("native validation detail", tool_result["content"])

    def test_binary_tool_resource_is_visible_to_the_next_model_turn(self):
        result = {
            "status": "completed",
            "resources": [{
                "type": "image", "media_type": "image/png",
                "content": "data:image/png;base64,iVBORw0KGgo=",
            }],
        }
        prompt_result = self.runtime._prompt_result(result)
        resource_messages = self.runtime._resource_messages(result)
        self.assertNotIn("iVBORw0KGgo", str(prompt_result))
        self.assertEqual("user", resource_messages[0]["role"])
        self.assertEqual(
            "data:image/png;base64,iVBORw0KGgo=",
            resource_messages[0]["content"][1]["image_url"]["url"],
        )

    def test_provider_result_is_not_hidden_by_a_local_context_guess(self):
        self.llm.runtime_model_info = lambda: {"context_length": 8192}
        result = {
            "status": "completed",
            "request": {"method": "GET", "path": "/api/states"},
            "response": {
                "status": 200,
                "content_type": "application/json",
                "body": [{"entity_id": f"sensor.item_{index}", "state": "x" * 100}
                         for index in range(200)],
            },
        }
        prompt_result = self.runtime._prompt_result(result)
        self.assertEqual("completed", prompt_result["status"])
        self.assertEqual("/api/states", prompt_result["request"]["path"])
        self.assertEqual(200, len(prompt_result["response"]["body"]))
        self.assertIn("sensor.item_199", json.dumps(prompt_result))

    def test_resources_follow_all_results_from_parallel_tool_calls(self):
        self.home.execute_native_operation = Mock(side_effect=[
            {
                "status": "completed",
                "resources": [{
                    "type": "image", "media_type": "image/png",
                    "content": "data:image/png;base64,aW1hZ2Ux",
                }],
            },
            {"status": "completed", "response": {"status": 200, "body": {"state": "on"}}},
        ])
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [
                    {"id": "image", "name": "home_assistant__http_request",
                     "arguments": {"method": "GET", "path": "/api/camera_proxy/camera.front"}},
                    {"id": "state", "name": "home_assistant__http_request",
                     "arguments": {"method": "GET", "path": "/api/states/light.flur"}},
                ],
            },
            {"content": "Fertig.", "tool_calls": [], "finish_reason": "stop"},
        ]
        self.runtime.respond("Zeige Kamera und Lichtstatus")
        messages = self.llm.request_tool_turn.call_args_list[2].args[0]
        assistant_index = max(
            index for index, item in enumerate(messages)
            if item["role"] == "assistant" and item.get("tool_calls")
        )
        roles_after_assistant = [item["role"] for item in messages[assistant_index:]]
        self.assertEqual(["assistant", "tool", "tool", "user"], roles_after_assistant)

    def test_qwen_can_load_multiple_capabilities_without_python_routing(self):
        capabilities = self.runtime._capabilities({"work_task_discoveries": []})
        tools, bindings = self.runtime._published_tools(capabilities, [])
        self.assertIn("memory__remember", bindings)
        self.assertNotIn("home_assistant__http_request", bindings)
        state = {"work_task_discoveries": [], "loaded_capabilities": []}
        result, _route = self.runtime._execute_direct(
            "eve_runtime", "load_capabilities",
            {"capabilities": ["home_assistant", "clock"]}, state, [],
        )
        self.assertEqual(["home_assistant", "clock"], result["loaded"])
        tools, bindings = self.runtime._published_tools(
            self.runtime._capabilities(state), state["loaded_capabilities"],
        )
        names = {item["function"]["name"] for item in tools}
        self.assertIn("home_assistant__http_request", names)
        self.assertIn("clock__now", names)
        self.assertEqual("eve_runtime", bindings["eve__load_capabilities"]["capability"])

    def test_provider_protocol_slots_follow_request_identity(self):
        for path in ["/api/config", "/api/services"]:
            self.agent.memory.record_provider_protocol_experience(
                "home_assistant", "http_request", "Read", {
                    "status": "completed", "request": {"method": "GET", "path": path},
                    "response": {"status": 200, "body": {}},
                },
            )
        with self.database.connect() as connection:
            rows = connection.execute("SELECT id,slot_key FROM memory_claims WHERE "
                                      "scope='provider:home_assistant:protocol'").fetchall()
            self.assertEqual(2, len({r["slot_key"] for r in rows}))
            connection.execute("UPDATE memory_claims SET slot_key='old-shared-slot' WHERE id=?",
                               (rows[0]["id"],))
        # A repeated receipt repairs the old shared slot without adding a fact.
        for path in ["/api/config", "/api/services"]:
            self.agent.memory.record_provider_protocol_experience(
                "home_assistant", "http_request", "Read", {
                    "status": "completed", "request": {"method": "GET", "path": path},
                    "response": {"status": 200, "body": {}},
                },
            )
        with self.database.connect() as connection:
            self.assertEqual(2, connection.execute("SELECT count(DISTINCT slot_key) FROM memory_claims "
                                                   "WHERE scope='provider:home_assistant:protocol'").fetchone()[0])

    def test_provider_memory_is_published_when_capability_is_loaded(self):
        learned = self.agent.memory.record_provider_protocol_experience(
            "home_assistant", "http_request", "Lies die vorhandene Konfiguration", {
                "status": "completed",
                "request": {
                    "method": "GET", "path": "/api/config/item/config/fixture", "query": {},
                },
                "response": {
                    "status": 200, "content_type": "application/json", "body": {"id": "fixture"},
                },
            }, trace_id="fixture-learning",
        )
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {"content": "Gefunden.", "tool_calls": [], "finish_reason": "stop"},
        ]

        self.runtime.respond("Prüfe /api/config/item")

        messages = self.llm.request_tool_turn.call_args_list[1].args[0]
        loaded = json.loads(next(item for item in messages if item["role"] == "tool")["content"])
        claims = loaded["provider_memory"]["home_assistant"]
        self.assertEqual(learned["memory_id"], claims[0]["memory_id"])
        self.assertIn("/api/config/item/config/fixture", claims[0]["content"])
        self.assertEqual(
            "/api/config/item/config/fixture",
            claims[0]["provider_evidence"]["request_signature"]["path"],
        )
        self.assertIn("id", claims[0]["provider_evidence"]["response"]["shape"])
        self.assertIn(learned["memory_id"], self.agent._turn_memory_ids)

    def test_successful_native_call_records_redacted_provider_evidence(self):
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "call-ha", "name": "home_assistant__http_request",
                    "arguments": {
                        "method": "GET", "path": "/api/config/item/config/fixture",
                        "query": {"access_token": "must-not-be-persisted"},
                    },
                }],
            },
            {"content": "Erledigt.", "tool_calls": [], "finish_reason": "stop"},
        ]

        self.runtime.respond("Lies die vorhandene Konfiguration")

        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT c.id,c.payload_json,o.structured_value_json,d.decision_type
                   FROM memory_claims c
                   JOIN memory_evidence e ON e.claim_id=c.id
                   JOIN memory_observations o ON o.id=e.observation_id
                   JOIN memory_learning_decision_claims dc ON dc.claim_id=c.id
                   JOIN memory_learning_decisions d ON d.id=dc.decision_id
                   WHERE json_extract(c.payload_json,'$.kind')='provider_protocol_experience'""",
            ).fetchone()
        self.assertIsNotNone(row)
        payload = json.loads(row["payload_json"])
        self.assertEqual("/api/config/item/config/fixture", payload["request_signature"]["path"])
        self.assertEqual(["access_token"], payload["request_signature"]["query_keys"])
        self.assertNotIn("must-not-be-persisted", row["payload_json"])
        self.assertNotIn("must-not-be-persisted", row["structured_value_json"])
        self.assertNotIn("Lies die vorhandene Konfiguration", row["payload_json"])
        self.assertIn("Lies die vorhandene Konfiguration", row["structured_value_json"])
        self.assertEqual("create_active", row["decision_type"])

    def test_repeated_native_failure_is_exposed_without_blocking_calls(self):
        def fail(_operation, parameters):
            self.home.calls.append((_operation, parameters))
            return {
                "status": "failed",
                "request": {
                    "method": parameters["method"], "path": parameters["path"], "query": {},
                },
                "response": {"status": 404, "body": {"message": "Not found"}},
            }

        self.home.execute_native_operation = fail
        self.llm.request_tool_turn.side_effect = [
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "load-ha", "name": "eve__load_capabilities",
                    "arguments": {"capabilities": ["home_assistant"]},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "first", "name": "home_assistant__http_request",
                    "arguments": {"method": "GET", "path": "/api/unknown/one"},
                }],
            },
            {
                "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "second", "name": "home_assistant__http_request",
                    "arguments": {"method": "GET", "path": "/api/unknown/two"},
                }],
            },
            {"content": "Ich prüfe die offizielle Schnittstelle.", "tool_calls": [], "finish_reason": "stop"},
        ]

        self.runtime.respond("Lies die unbekannte Konfiguration")

        self.assertEqual(2, len(self.home.calls))
        messages = self.llm.request_tool_turn.call_args_list[3].args[0]
        second_result = json.loads([
            item["content"] for item in messages if item["role"] == "tool"
        ][-1])
        observation = second_result["runtime_observation"]
        self.assertEqual("repeated_provider_failure", observation["kind"])
        self.assertEqual(2, observation["equivalent_failures"])
        self.assertFalse(observation["new_provider_evidence"])

    def test_memory_data_without_status_is_not_reported_as_provider_failure(self):
        state = {}
        observe = self.runtime._provider_result_observation
        self.assertIsNone(observe(state,'working_memory','read',{'content':[1]}))
        self.assertIsNone(observe(state,'working_memory','read',{'content':[2]}))
        repeated = observe(state,'working_memory','read',{'content':[2]})
        self.assertEqual('repeated_provider_result',repeated['kind'])
        self.assertNotIn('provider_failure_counts',state)

    def test_repeated_successful_result_is_exposed_as_no_new_evidence(self):
        state = {}
        result = {
            "status": "completed",
            "request": {"method": "GET", "path": "/api/one", "query": {}},
            "response": {"status": 200, "body": {"state": "on"}},
        }
        self.assertIsNone(self.runtime._provider_result_observation(
            state, "provider", "read", result,
        ))
        repeated = dict(result)
        repeated["request"] = {"method": "GET", "path": "/api/two", "query": {}}
        observation = self.runtime._provider_result_observation(
            state, "provider", "read", repeated,
        )
        self.assertEqual("repeated_provider_result", observation["kind"])
        self.assertEqual(2, observation["equivalent_results"])
        self.assertFalse(observation["new_provider_evidence"])

    def test_provider_response_shape_keeps_deep_and_wide_structure(self):
        nested = {"leaf": 1}
        for index in range(8):
            nested = {f"level_{index}": nested}
        payload = {f"field_{index}": index for index in range(80)}
        payload["nested"] = nested

        shape = _response_shape(payload)

        self.assertEqual(81, len(shape))
        cursor = shape["nested"]
        for index in reversed(range(8)):
            cursor = cursor[f"level_{index}"]
        self.assertEqual("number", cursor["leaf"])


if __name__ == "__main__":
    unittest.main()
