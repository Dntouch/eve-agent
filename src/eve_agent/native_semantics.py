"""Model-owned semantic writing in the existing native tool turn.

No utterance classifier, second planner, or replay executor. Provider adapters
prove protocol identities; the current model declares meaning and goal evidence.
"""
from copy import deepcopy
import json
from uuid import uuid4

from .provider_schemas import obj, text
from .semantic_links import CONTEXT_KEYS, assessment_conditions, action_identity
from .working_memory import WorkingMemoryStore



class NativeSemanticSession:
    def __init__(self, agent, utterance, trace_id):
        self.agent, self.links, self.utterance, self.trace_id = agent, agent.semantic_links, utterance, trace_id
        self.context = {"conversation_id": agent.conversation_id, "history": deepcopy(agent.history),
                        "focus": list(getattr(agent.home_assistant, "last_entities", []) or []),
                        "pending": deepcopy(agent._pending_context()),
                        "task_active": bool(agent.work_tasks and getattr(agent.work_tasks, "has_active_context", lambda _: False)(agent.conversation_id))}
        self.providers = {}
        for name, provider in vars(agent).items():
            identity = getattr(provider, "semantic_provider_identity", None)
            if callable(identity) and getattr(provider, "configured", True):
                self.providers[name] = provider
        self.calls, self.executions, self.recorded, self.published = {}, {}, {}, {}
        self.retrieved = {}
        self.record_arguments = {}
        self.published_languages = {}
        self.references = self.links.dialog_references(agent.conversation_id)
        agent._semantic_turn_ref = trace_id

    def observe(self, event_id, capability, operation, parameters, result):
        provider = self.providers.get(capability)
        projection = getattr(provider, "native_semantic_execution", None)
        if not callable(projection):
            return None
        reference = "native-call:" + uuid4().hex
        event = {"tool_event_id": event_id, "capability": capability, "operation": operation,
                 "parameters": deepcopy(parameters), "result": deepcopy(result)}
        self.calls[reference] = event
        from .transient_credentials import contains_credentials
        execution = projection(operation, parameters, result) if not contains_credentials(parameters) else None
        if execution:
            self.executions[reference] = {**execution, "capability": capability}
        return ({"call_reference": reference, "record_operation": "semantic_learning.record_action",
                 "executed": deepcopy(execution), "meaning_assessed": False} if execution else {"call_reference": reference})

    def contract(self):
        keys = {"type": "array", "items": {"enum": list(CONTEXT_KEYS)}, "uniqueItems": True,
                "description": "Only context necessary to resolve this request, not all context present. Existing history or focus alone is not a dependency. Matching a complete request to durable Memory does not require conversational history."}
        assessment = obj({"status": {"enum": ["resolved", "uncertain"]}, "context_keys": keys,
            "user_grounding": {"enum": ["explicit", "contextual", "unknown"]},
            "utterance_quote": text(), "basis": text(minLength=1),
            "uncertainties": {"type": "array", "items": text()},
            "action_link": obj({"kind": {"enum": ["new", "existing", "none"]},
                "meaning": text(), "representation_id": text(), "anchor_claim_id": text(), "basis": text()},
                ["kind", "basis"])},
            ["status", "context_keys", "user_grounding", "utterance_quote", "basis", "uncertainties", "action_link"])
        evidence = obj({"call_reference": text(), "pointer": text("RFC6901 path into the original result, e.g. /response/body/state; no dot/bracket syntax. Empty selects root"), "value": {"description": "Exact original JSON value, including its type"}}, ["call_reference", "pointer", "value"])
        def operation(description, schema, effect="write"):
            return {"description": description, "effect": effect, "parameters_schema": schema}
        return {"description": "Learn semantic action experiences from completed native calls and goal evidence; record explicit language relations and confirm/correct earlier meanings. The current model decides meaning; nothing is executed or replayed by these memory tools.",
            "operations": {
                "inspect": operation("Read current execution receipts, earlier meanings and causal feedback references before selecting exact IDs.", obj(), "read"),
                "action_candidates": operation("Read published meanings and anchors for an existing-equivalence declaration; equal API calls alone do not prove equal meaning.",
                    obj({"capability": ({"enum": list(self.providers)} if self.providers else text())}, ["capability"]), "read"),
                "record_action": operation("Record your interpretation of a completed action. Cite actual goal-result values, not merely transport acceptance. Infer no user confirmation. Use uncertain if meaning or outcome is unresolved. This never executes an action.",
                    obj({"call_references": {"type": "array", "minItems": 1, "items": text("Use only references carrying semantic_execution; observation/read references belong in evidence"), "uniqueItems": True},
                         "assessment": assessment, "outcome": {"enum": ["success", "partial", "failed", "outcome_uncertain"]},
                         "outcome_basis": text(minLength=1), "based_on": text("Optional published learned_action_experience memory_id used for this interpretation"), "evidence": {"type": "array", "minItems": 1, "items": evidence}},
                        ["call_references", "assessment", "outcome", "outcome_basis", "evidence"])),
                "feedback": operation("Record explicit evaluation of an earlier published occurrence. Quote the current user and its antecedent exactly. This changes memory, never repeats the action.",
                    obj({"link_id": text(), "occurrence_ref": text(), "decision": {"enum": ["confirm", "contradict"]},
                         "user_quote": text(), "antecedent_quote": text(), "basis": text(minLength=1)},
                        ["link_id", "occurrence_ref", "decision", "user_quote", "antecedent_quote", "basis"])),
                "language_relation": operation("Store an explicit user-declared surface equivalence/difference or resource alias. Both surfaces must occur in the current user text. Do not infer synonyms.",
                    obj({"relation_kind": {"enum": ["surface_equivalence", "resource_alias"]},
                         "surfaces": {"type": "array", "items": text()}, "source_surface": text(), "new_surface": text(),
                         "polarity": {"enum": ["positive", "negative"]}, "context_keys": keys,
                         "capability": ({"enum": list(self.providers)} if self.providers else text()), "basis": text(minLength=1)},
                        ["relation_kind", "polarity", "context_keys", "basis"])),
                "correct_language": operation("Correct or undo an explicitly evaluated published language relation. Quote the current user exactly; no action is executed.",
                    obj({"relation_id": text(), "user_quote": text(), "basis": text(minLength=1), "undo": {"type": "boolean"}},
                        ["relation_id", "user_quote", "basis", "undo"])),
                "action_resource": operation("Bind a published action representation and anchor to an explicitly named, inventoried provider executor; no device action is performed.",
                    obj({"capability": ({"enum": list(self.providers)} if self.providers else text()), "resource_surface": text(),
                         "representation_id": text(), "anchor_claim_id": text(), "basis": text(minLength=1)},
                        ["capability", "resource_surface", "representation_id", "anchor_claim_id", "basis"])),
            }}

    def execute(self, operation, args):
        if operation == "inspect":
            languages = self.links.language_relations(self.context)
            self.published_languages.update({item["id"]: deepcopy(item) for item in languages})
            return {"context": deepcopy(self.context),
                    "executions": deepcopy(self.executions), "feedback_references": deepcopy(self.references),
                    "language_relations": languages}
        if operation == "action_candidates":
            provider = self.providers[args["capability"]].semantic_provider_identity()
            candidates = self.links.action_candidates(provider, context=self.context)
            self.published[args["capability"]] = deepcopy(candidates)
            return {"items": candidates}
        if operation == "record_action":
            return self.record(args)
        if operation == "feedback":
            decision = {"type": args["decision"], "reason": "explicit_feedback", "replan": False,
                "clarification": None, "current_turn_ref": self.trace_id, "link_id": args["link_id"],
                "occurrence_ref": args["occurrence_ref"], "user_quote": args["user_quote"], "basis": args["basis"],
                "causal_evidence": {"feedback_only": True, "explicit_evaluation": True,
                                    "uncertainties": [], "antecedent_quote": args["antecedent_quote"]}}
            claim = self.links.apply_dialog_decision(decision, utterance=self.utterance,
                conversation_id=self.agent.conversation_id, source_ref=self.trace_id, published=self.references)
            self.agent._turn_state_details["semantic_decision"] = decision
            return {"status": "completed", "claim_id": claim, "action_executed": False}
        if operation == "language_relation":
            options = {key: deepcopy(value) for key, value in args.items() if key != "capability"}
            if args.get("capability"):
                options["provider"] = self.providers[args["capability"]].semantic_provider_identity()
            return self.links.record_language_relation(**options, context=self.context,
                source_ref=self.trace_id, user_utterance=self.utterance)
        if operation == "correct_language":
            if args["user_quote"] != self.utterance or args["relation_id"] not in self.published_languages:
                raise ValueError("Language correction lacks a published reference or exact user evidence")
            return self.links.correct_language_relation(args["relation_id"], source_ref=self.trace_id,
                basis=args["basis"], undo=args["undo"])
        if operation == "action_resource":
            candidates = self.published.get(args["capability"], [])
            if not any(c["representation_id"] == args["representation_id"] and any(
                    e["claim_id"] == args["anchor_claim_id"] for e in c["examples"]) for c in candidates):
                raise ValueError("Action and anchor were not published in this turn")
            return self.links.record_action_resource_relation(args["resource_surface"],
                {"representation_id": args["representation_id"], "anchor_claim_id": args["anchor_claim_id"]},
                provider=self.providers[args["capability"]].semantic_provider_identity(),
                source_ref=self.trace_id, basis=args["basis"], user_utterance=self.utterance)
        raise ValueError("Unknown semantic learning operation")

    def record(self, args, *, _connection=None):
        refs = tuple(args["call_references"])
        if refs in self.recorded:
            if self.record_arguments[refs] != args:
                raise ValueError("The same execution already has a different semantic assessment")
            return deepcopy(self.recorded[refs])
        if any(set(refs) & set(previous) for previous in self.recorded):
            raise ValueError("Overlapping executions cannot manufacture independent experience")
        if any(ref not in self.executions for ref in refs):
            raise ValueError("Action references must name executed service receipts only; put read references in evidence. Available execution references: " + ", ".join(self.executions))
        if list(refs) != [ref for ref in self.executions if ref in refs]:
            raise ValueError("Experience references must preserve actual execution order")
        executions = [self.executions[ref] for ref in refs]
        provider = executions[0]["provider"]
        if any(item["provider"] != provider for item in executions):
            raise ValueError("One experience must reference one provider identity")
        evidence = deepcopy(args["evidence"])
        for item in evidence:
            source = self.calls[item["call_reference"]]
            if source["capability"] != executions[0]["capability"] or not isinstance(source["result"], dict) or source["result"].get("status") != "completed":
                raise ValueError("Goal evidence needs a successful observation from the same provider")
            actual = WorkingMemoryStore.pointer(source["result"], item["pointer"])
            if json.dumps(actual, sort_keys=True, ensure_ascii=False) != json.dumps(item["value"], sort_keys=True, ensure_ascii=False):
                raise ValueError("Goal evidence does not match the original result value and type")
        plan = {"effect": executions[0]["effect"],
            "actions": [deepcopy(action) for item in executions for action in item["actions"]],
            "semantic_learning": deepcopy(args["assessment"])}
        # Preserve actual goal observations for later verified replay. No service
        # name or user wording is translated into an assumed target state.
        observations = []
        for item in evidence:
            source = self.calls[item["call_reference"]]
            parameters = source["parameters"]
            path = parameters.get("path", "")
            if (source["operation"] == "http_request" and parameters.get("method") == "GET"
                    and path.startswith("/api/states/")
                    and (item["pointer"] == "/response/body/state"
                         or item["pointer"].startswith("/response/body/attributes/"))):
                observations.append({"entity_id": path[len("/api/states/"):],
                                     "pointer": item["pointer"], "value": deepcopy(item["value"])})
        if observations:
            plan["replay_observations"] = observations
        if assessment_conditions(plan["semantic_learning"], self.context, self.utterance, plan) is None:
            raise ValueError("Invalid model-authored semantic assessment or user grounding")
        outcome = {"status": args["outcome"], "basis": args["outcome_basis"], "evidence": evidence,
                   "native_call_references": list(refs)}
        root = self.trace_id
        differential_evidence = None
        if args.get("based_on"):
            source = self.retrieved.get(args["based_on"])
            if not source or source["provider"] != provider or action_identity(source["plan"]) != action_identity(plan):
                raise ValueError("Reused experience is unpublished or differs from the executed action")
            if source.get("match") == "composition":
                root = ""
                differential_evidence = {"memory_id": args["based_on"], "source": "native_published_composition"}
            else:
                root = self.links.experience(args["based_on"]).get("differential_provenance_root") or ""
        claim_id = self.links.learn(self.utterance, self.context, provider, plan, outcome,
            source_ref=self.trace_id, provider_validated=True,
            exact_replay_authorized=args["outcome"] == "success" and bool(observations),
            published_actions=self.published.get(executions[0]["capability"], []),
            differential_evidence=differential_evidence, provenance_root=root, _connection=_connection)
        if not claim_id:
            raise ValueError("The experience cannot be stored without changing its source identity")
        audit = self.agent._turn_state_details.setdefault("native_semantic_references", {})
        for ref in [*refs, *(item["call_reference"] for item in evidence)]:
            audit[ref] = self.calls[ref]["tool_event_id"]
        ids = self.agent._turn_state_details.setdefault("semantic_link_candidate_ids", [])
        ids.append(claim_id)
        if len(ids) == 1:
            self.agent._turn_state_details["semantic_link_candidate_id"] = claim_id
        else:
            self.agent._turn_state_details.pop("semantic_link_candidate_id", None)
        if args["outcome"] == "success":
            self.agent._turn_state = "operational_resolved"
            self.agent._turn_state_details.update(operational_execution=True)
        result = {"status": "completed", "claim_id": claim_id, "action_executed": False,
                  "experience": self.links.experience(claim_id, _connection=_connection)}
        self.recorded[refs] = deepcopy(result)
        self.record_arguments[refs] = deepcopy(args)
        return result
