import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock

from eve_agent.agent import EveAgent
from eve_agent.home_assistant import HomeAssistant
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.state import StateBus
from eve_agent.storage import EveDatabase, ConversationStore


class SyntheticHome(HomeAssistant):
    def __init__(self):
        super().__init__({"url": "http://fixture.invalid", "token": "fixture"}, Path("."))
        self.states, self.calls = {}, []
        self.fail = False

    def execute_native_operation(self, operation, parameters):
        self.calls.append((operation, copy.deepcopy(parameters)))
        if parameters["method"] == "POST":
            entity = parameters["body"]["entity_id"]
            self.states[entity] = parameters["path"].rsplit("/", 1)[1]
            body = [{"entity_id": entity, "state": self.states[entity]}]
        else:
            entity = parameters["path"].rsplit("/", 1)[1]
            body = {"entity_id": entity, "state": self.states.get(entity, "unknown")}
        return {"status": "failed" if self.fail else "completed", "request": copy.deepcopy(parameters),
                "response": {"status": 500 if self.fail else 200, "body": body}}


class NativeSemanticLearningTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.db = EveDatabase(self.root / "eve.db")
        self.home = SyntheticHome()
        self.llm = SimpleNamespace(request_tool_turn=Mock(), max_tokens=2000, runtime_model_info=lambda: {})
        self.store = ConversationStore(self.db)
        self.agent = EveAgent("EVE", MemoryV2Runtime(self.db, MemoryCompiler(self.db)), self.llm,
                              StateBus(self.root / "runtime"), home_assistant=self.home, conversations=self.store)
        self.agent.conversation_id = self.store.create("Native semantic fixture")["id"]

    @staticmethod
    def call(name, arguments):
        return {"content": "", "tool_calls": [{"id": uuid.uuid4().hex, "name": name, "arguments": arguments}]}

    @staticmethod
    def results(messages):
        return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]

    def action(self, text, entity="light.A", service="p", *, mutate=None, existing=None):
        step = 0
        def turn(messages, tools, *args, **kwargs):
            nonlocal step
            stage = step; step += 1
            if stage == 0:
                return self.call("eve__load_capabilities", {"capabilities": ["home_assistant", "semantic_learning"]})
            if stage == 1:
                return self.call("home_assistant__http_request", {"method": "POST", "path": f"/api/services/light/{service}", "body": {"entity_id": entity}})
            if stage == 2:
                return self.call("home_assistant__http_request", {"method": "GET", "path": f"/api/states/{entity}"})
            if stage == 3 and existing:
                return self.call("semantic_learning__action_candidates", {"capability": "home_assistant"})
            if stage == (4 if existing else 3):
                data = self.results(messages)
                execution = next(d["semantic_execution"] for d in data if "semantic_execution" in d)
                verification = next(d for d in data if isinstance(d.get("response", {}).get("body"), dict) and d["response"]["body"].get("entity_id") == entity)
                declaration = {"kind": "new", "meaning": f"Fixture {entity} {service}", "basis": "Explicit meaning of this user request."}
                if existing:
                    declaration = {"kind": "existing", "representation_id": existing["action_representation_id"], "anchor_claim_id": existing["id"], "basis": "Same intended meaning as the published example."}
                record = {"call_references": [execution["call_reference"]],
                    "assessment": {"status": "resolved", "context_keys": [], "user_grounding": "explicit",
                        "utterance_quote": text, "basis": "Explicit user target and action.", "uncertainties": [], "action_link": declaration},
                    "outcome": "success", "outcome_basis": "The subsequent state query returned the intended state.",
                    "evidence": [{"call_reference": verification["call_reference"], "pointer": "/response/body/state", "value": service}]}
                if mutate: mutate(record)
                return self.call("semantic_learning__record_action", record)
            return {"content": "Ausgeführt und bewertet.", "tool_calls": []}
        self.llm.request_tool_turn.side_effect = turn
        self.agent.respond(text)
        events = self.agent._tool_events
        record = next(e for e in events if e.get("operation") == "record_action")
        return record["result"]

    def feedback(self, text, decision="confirm"):
        step = 0
        def turn(messages, tools, *args, **kwargs):
            nonlocal step
            stage = step; step += 1
            if stage == 0: return self.call("eve__load_capabilities", {"capabilities": ["semantic_learning"]})
            if stage == 1: return self.call("semantic_learning__inspect", {})
            if stage == 2:
                ref = self.results(messages)[-1]["feedback_references"][0]
                return self.call("semantic_learning__feedback", {"link_id": ref["link_id"], "occurrence_ref": ref["occurrence_ref"],
                    "decision": decision, "user_quote": text, "antecedent_quote": ref["utterance"], "basis": "Explicit evaluation of this published occurrence."})
            return {"content": "Bewertung gespeichert; keine Aktion wiederholt.", "tool_calls": []}
        self.llm.request_tool_turn.side_effect = turn
        self.agent.respond(text)
        return next(e["result"] for e in self.agent._tool_events if e.get("operation") == "feedback")

    def test_native_execution_creates_evidenced_experience_and_supports_ui_feedback(self):
        result = self.action("do xa p")
        self.assertEqual("completed", result["status"], result)
        claim = self.agent.semantic_links.experience(result["claim_id"])
        self.assertEqual("candidate", claim["lifecycle"])
        self.assertEqual("created", claim["action_link_status"])
        self.assertEqual("light.A", claim["plan"]["actions"][0]["entity_id"])
        with self.db.connect() as c:
            evidence = c.execute("SELECT source_turn_id,source_message_id FROM memory_evidence WHERE claim_id=? AND evidence_type='provider_result'", (claim["id"],)).fetchone()
            message = c.execute("SELECT id,conversation_id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertTrue(evidence[0])
        self.assertIsNone(evidence[1])
        self.assertEqual(2, len(self.home.calls))
        feedback = self.agent.semantic_links.execution_feedback(message["conversation_id"], message["id"], "correct")
        self.assertEqual("correct", feedback["decision"])
        self.assertEqual(2, len(self.home.calls))
        self.assertEqual("confirmed", self.agent.semantic_links.experience(claim["id"])["confirmation"])

    def test_dialog_confirmation_correction_and_exact_retrieval_do_not_replay(self):
        result = self.action("do xa p")
        self.assertEqual("completed", self.feedback("Das war richtig.")["status"])
        context = self.agent._native_tool_runtime.semantic_session.context
        self.assertIsNotNone(self.agent.semantic_links.lookup("do xa p", context, self.home.semantic_provider_identity()))
        self.assertEqual(2, len(self.home.calls))
        self.assertEqual("completed", self.feedback("Nein, diese Zuordnung war falsch.", "contradict")["status"])
        self.assertEqual("invalid", self.agent.semantic_links.experience(result["claim_id"])["lifecycle"])
        self.assertIsNone(self.agent.semantic_links.lookup("do xa p", context, self.home.semantic_provider_identity()))
        self.assertEqual(2, len(self.home.calls))

    def test_wrong_json_value_or_type_and_uncertain_outcome_never_create_active_success(self):
        result = self.action("do xa p", mutate=lambda r: r["evidence"][0].update(value=True))
        self.assertEqual("error", result["status"])
        self.assertEqual([], self.agent.semantic_links.export())
        result = self.action("do xa p", mutate=lambda r: r.update(outcome="outcome_uncertain"))
        claim = self.agent.semantic_links.experience(result["claim_id"])
        self.assertFalse(claim["strong_semantic_evidence"])
        self.assertEqual("candidate", claim["lifecycle"])

    def test_differential_composition_is_trained_by_real_native_turns_and_confirmations(self):
        rows = [("do xa p", "light.A", "p"), ("do xa r", "light.A", "r"),
                ("do xb p", "light.B", "p"), ("do xb q", "light.B", "q"), ("do xb r", "light.B", "r"),
                ("do xc p", "light.C", "p"), ("do xc q", "light.C", "q")]
        for text, entity, service in rows:
            result = self.action(text, entity, service)
            self.assertEqual("completed", result["status"], result)
            self.assertEqual("completed", self.feedback("Das war richtig.")["status"])
        runtime = self.agent._native_tool_runtime
        published, _ = runtime._semantic_memory_context("do xa q", "fixture-retrieval")
        composition = next(p for p in published if p["match"] == "composition")
        self.assertEqual("light.A", composition["plan"]["actions"][0]["entity_id"])
        self.assertEqual("light.q", composition["plan"]["actions"][0]["service"])
        self.assertEqual(14, len(self.home.calls), "Retrieval must not execute a device action")
        reused = self.action("do xa q", "light.A", "q", mutate=lambda r: r.update(based_on=next(k for k, v in self.agent._native_tool_runtime.semantic_session.retrieved.items() if v["match"] == "composition")))
        self.assertEqual("completed", reused["status"], reused)
        self.assertEqual("", reused["experience"]["differential_provenance_root"])
        self.assertEqual("composition", reused["experience"]["differential_origin"])

    def test_dynamic_similarity_uses_native_learned_membership(self):
        first = self.action("do xa p")["experience"]
        self.feedback("Das war richtig.")
        second = self.action("do xa p", existing=first)
        self.assertEqual("linked", second["experience"]["action_link_status"])
        self.feedback("Das war richtig.")
        published, _ = self.agent._native_tool_runtime._semantic_memory_context("p xa do", "fixture-variant")
        self.assertTrue(any(p["match"] == "similarity" for p in published), published)
        self.assertEqual(4, len(self.home.calls))

    def test_explicit_language_relation_is_written_by_the_native_model_tool(self):
        text = "Mit xa und alpha meine ich dasselbe."
        self.llm.request_tool_turn.side_effect = [
            self.call("eve__load_capabilities", {"capabilities": ["semantic_learning"]}),
            self.call("semantic_learning__language_relation", {"relation_kind": "surface_equivalence", "polarity": "positive",
                "surfaces": ["xa", "alpha"], "context_keys": [], "basis": "Both forms explicitly equated by user."}),
            {"content": "Sprachbeziehung gespeichert.", "tool_calls": []}]
        self.agent.respond(text)
        relations = self.agent.semantic_links.language_relations()
        self.assertEqual(1, len(relations)); self.assertEqual(["xa", "alpha"], relations[0]["surfaces"])
        self.assertEqual([], self.home.calls)

    def test_receipts_remain_auditable_without_exposing_event_sidecars(self):
        result = self.action("do xa p")
        session = self.agent._native_tool_runtime.semantic_session
        with self.db.connect() as c:
            stored = c.execute("SELECT payload_json FROM memory_evidence WHERE claim_id=? AND evidence_type='provider_result'", (result["claim_id"],)).fetchone()
        refs = json.loads(stored[0])["native_call_references"]
        for ref in refs:
            self.assertTrue(ref.startswith("native-call:"))
            event_id = self.agent._turn_state_details["native_semantic_references"][ref]
            self.assertNotEqual(event_id, ref)
            self.assertTrue(any(e["id"] == event_id for e in self.agent._tool_events))
            self.assertNotIn(event_id, json.dumps(result))
        arguments = next(iter(session.record_arguments.values()))
        self.assertEqual(result, session.record(copy.deepcopy(arguments)))
        changed = copy.deepcopy(arguments); changed["outcome"] = "failed"
        with self.assertRaises(ValueError): session.record(changed)
        self.assertEqual(1, len(self.agent.semantic_links.export()))

    def test_failed_transport_has_no_recordable_execution(self):
        self.home.fail = True
        from eve_agent.native_semantics import NativeSemanticSession
        session = NativeSemanticSession(self.agent, "do xa p", "fixture-failed")
        params = {"method": "POST", "path": "/api/services/light/p", "body": {"entity_id": "light.A"}}
        result = self.home.execute_native_operation("http_request", params)
        receipt = session.observe("internal-event", "home_assistant", "http_request", params, result)
        self.assertNotIn("executed", receipt)
        self.assertEqual({}, session.executions)

    def test_websocket_projection_retains_exact_targets_and_rejects_implicit_expansion(self):
        command = {"type": "call_service", "domain": "light", "service": "turn_on",
                   "target": {"entity_id": ["light.A", "light.B"]}, "service_data": {"brightness": 18}}
        projection = self.home.native_semantic_execution("websocket_command", {"command": command}, {"status": "completed"})
        self.assertEqual(["light.A", "light.B"], [a["entity_id"] for a in projection["actions"]])
        self.assertEqual({"brightness": 18}, projection["actions"][0]["parameters"])
        command["target"] = {"area_id": "living_room"}
        self.assertIsNone(self.home.native_semantic_execution("websocket_command", {"command": command}, {"status": "completed"}))

    def test_reused_experience_keeps_its_original_independent_root(self):
        first = self.action("do xa p")["experience"]
        self.feedback("Das war richtig.")
        result = self.action("do xa p", existing=first, mutate=lambda r: r.update(based_on=first["id"]))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(first["differential_provenance_root"], result["experience"]["differential_provenance_root"])
        self.assertNotEqual(result["experience"]["origin_ref"], result["experience"]["differential_provenance_root"])
