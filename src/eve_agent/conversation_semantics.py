"""Evidence-checked semantic learning from completed turns; never runs a device."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from .home_assistant import HomeAssistant
from .native_semantics import NativeSemanticSession
from .semantic_links import CONTEXT_KEYS, SemanticLinks, action_identity, assessment_conditions
from .working_memory import WorkingMemoryStore


def formulation_schema():
    session = SimpleNamespace(providers={"home_assistant": None})
    schema = deepcopy(NativeSemanticSession.contract(session)["operations"]["record_action"]["parameters_schema"])
    schema["properties"].pop("based_on", None)
    declaration = schema['properties']['assessment']['properties']['action_link']
    declaration['anyOf'] = [
        {'properties': {'kind': {'const': 'existing'}, 'representation_id': {'minLength': 1},
                        'anchor_claim_id': {'minLength': 1}}, 'required': ['representation_id', 'anchor_claim_id']},
        {'properties': {'kind': {'const': 'new'}, 'meaning': {'minLength': 1}}, 'required': ['meaning']},
        {'properties': {'kind': {'const': 'none'}}},
    ]
    schema["description"] = "Optional semantic learning alongside the general Memory decision. References name original tool event IDs from this turn, never execute actions."
    return schema


class ConversationSemantics:
    def __init__(self, database, links=None):
        self.links = links or SemanticLinks(database)

    def session(self, snapshot):
        details = snapshot.get("turn_state_details") or {}
        context = details.get("semantic_context")
        if (not isinstance(context, dict) or not set(CONTEXT_KEYS) <= context.keys()
                or context['conversation_id'] != snapshot['conversation_id']
                or details.get("decision_origin") == "semantic_replay"):
            return None
        tools = []
        identities = {}
        for row in snapshot["tools"]:
            if row["tool"] != "home_assistant":
                continue
            result = json.loads(row["result_json"])
            if not isinstance(result, dict):
                return None
            if result.get('semantic_execution_recordable') is False:
                return None
            provider = result.get("provider_identity")
            if (not isinstance(provider, dict) or provider.get("provider") != "home_assistant"
                    or not isinstance(provider.get("endpoint"), str) or not provider["endpoint"]):
                return None
            identities[json.dumps(provider, sort_keys=True)] = provider
            parameters = json.loads(row["input_json"])
            if not isinstance(parameters, dict):
                return None
            operation = "http_request" if "method" in parameters and "path" in parameters else "websocket_command"
            tools.append((row, operation, parameters, result))
        if len(identities) != 1:
            return None
        provider = next(iter(identities.values()))
        home = HomeAssistant({"url": provider["endpoint"], "token": "offline-projection-only"}, Path("."))
        agent = SimpleNamespace(semantic_links=self.links, conversation_id=snapshot["conversation_id"],
            history=deepcopy(context.get("history", [])), home_assistant=home, work_tasks=None,
            _pending_context=lambda: deepcopy(context.get("pending")), _turn_state_details={})
        session = NativeSemanticSession(agent, snapshot["user_content"], snapshot["turn_id"])
        session.context = deepcopy(context)
        session.tool_ordinals = {}
        for row, operation, parameters, result in tools:
            reference = row["id"]
            session.calls[reference] = {"tool_event_id": reference, "capability": "home_assistant",
                "operation": operation, "parameters": parameters, "result": result}
            session.tool_ordinals[reference] = row["ordinal"]
            execution = home.native_semantic_execution(operation, parameters, result)
            if execution:
                session.executions[reference] = {**execution, "capability": "home_assistant"}
        if not session.executions:
            return None
        targets = {a["entity_id"] for e in session.executions.values() for a in e["actions"]}
        session.published["home_assistant"] = self.links.action_candidates(
            provider, context=session.context, effect="write", resources=sorted(targets))
        return session

    def context(self, snapshot):
        session = self.session(snapshot)
        if session is None:
            return {"available": False, "reason": "no_complete_original_semantic_execution_context"}
        with self.links.database.connect(lifecycle_audit=False) as c:
            existing = [dict(row) for row in c.execute(
                "SELECT DISTINCT m.id,m.display_text,m.lifecycle FROM memory_claims m JOIN memory_evidence e "
                "ON e.claim_id=m.id WHERE m.scope='semantic_links' AND e.source_turn_id=?", (snapshot["turn_id"],))]
        return {"available": True, "current_formulation": snapshot["user_content"],
            "context_at_execution": session.context, "executions": session.executions,
            "observations": {ref: call for ref, call in session.calls.items() if ref not in session.executions},
            "action_candidates": session.published["home_assistant"], "existing_formulations": existing,
            "contract": "Use semantic_formulation to learn the complete original formulation. Prefer an existing meaning when equivalent; equal API calls alone do not prove equivalence. Cite successful state observations AFTER the actions. Keep context-dependent or uncertain interpretations as candidates. Never infer user confirmation. A null semantic_formulation requires semantic_learning_reason."}

    def validate(self, snapshot, raw, *, session=None):
        if raw is None:
            return None
        Draft202012Validator(formulation_schema()).validate(raw)
        session = session or self.session(snapshot)
        if session is None:
            raise ValueError("semantic_original_context_unavailable")
        refs = raw["call_references"]
        if refs != list(session.executions):
            raise ValueError("semantic_execution_scope_or_order_mismatch")
        if any(row["status"] not in {"completed", "returned"} for row in snapshot["tools"]
               if row["tool"] == "home_assistant") and raw["outcome"] == "success":
            raise ValueError("semantic_unresolved_execution")
        provider = next(iter(session.executions.values()))["provider"]
        plan = {"effect": "write", "actions": [a for ref in refs for a in session.executions[ref]["actions"]]}
        if assessment_conditions(raw["assessment"], session.context, snapshot["user_content"], plan) is None:
            raise ValueError("semantic_invalid_context_assessment")
        declaration = raw["assessment"]["action_link"]
        if declaration["kind"] == "existing":
            published = next((p for p in session.published["home_assistant"]
                if p["representation_id"] == declaration.get("representation_id")
                and any(e["claim_id"] == declaration.get("anchor_claim_id") for e in p["examples"])), None)
            if not published:
                raise ValueError("semantic_unpublished_action_reference")
            anchor = self.links.experience(declaration["anchor_claim_id"])
            if anchor["provider"] != provider or action_identity(anchor["plan"]) != action_identity(plan):
                raise ValueError("semantic_action_execution_mismatch")
        targets = {a["entity_id"] for a in plan["actions"]}
        observed = set()
        for evidence in raw["evidence"]:
            ref = evidence["call_reference"]
            call = session.calls.get(ref)
            if not call or session.tool_ordinals[ref] <= max(session.tool_ordinals[r] for r in refs):
                raise ValueError("semantic_goal_must_follow_execution")
            result, parameters = call["result"], call["parameters"]
            entity = parameters.get("path", "").removeprefix("/api/states/")
            body = result.get("response", {}).get("body")
            if (call["operation"] != "http_request" or parameters.get("method") != "GET"
                    or not parameters.get("path", "").startswith("/api/states/") or entity not in targets
                    or result.get("status") != "completed" or not isinstance(body, dict)
                    or body.get("entity_id") != entity
                    or not (evidence["pointer"] == "/response/body/state"
                            or evidence["pointer"].startswith("/response/body/attributes/"))):
                raise ValueError("semantic_goal_requires_target_observation")
            actual = WorkingMemoryStore.pointer(result, evidence["pointer"])
            if json.dumps(actual, sort_keys=True) != json.dumps(evidence["value"], sort_keys=True):
                raise ValueError("semantic_goal_value_mismatch")
            if evidence["pointer"] == "/response/body/state" and (not isinstance(actual, str)
                    or actual in ("unknown", "unavailable")):
                raise ValueError("semantic_goal_state_unavailable")
            observed.add(entity)
        if raw["outcome"] == "success" and observed != targets:
            raise ValueError("semantic_goal_targets_incomplete")
        return deepcopy(raw)

    def persist(self, snapshot, raw, connection, *, session):
        existing = self.existing(snapshot, connection, session=session)
        if existing:
            return existing
        result = session.record(raw, _connection=connection)
        claim = result["experience"]
        self.links.attach_turn_provenance(snapshot["turn_id"], snapshot["turn_id"],
                                         snapshot["user_message_id"], _connection=connection)
        # Keep the existing correct/incorrect feedback usable on the original
        # answer, even when its semantic interpretation was learned afterwards.
        message = connection.execute('SELECT metadata_json FROM messages WHERE id=?',
                                     (snapshot['assistant_message_id'],)).fetchone()
        if message:
            metadata = json.loads(message[0] or '{}')
            details = metadata.setdefault('turn_state_details', {})
            if not details.get('semantic_link_candidate_id') and not details.get('semantic_link_id'):
                details['semantic_link_candidate_id'] = claim['id']
                details['native_semantic_references'] = session.agent._turn_state_details.get('native_semantic_references', {})
                connection.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                                   (json.dumps(metadata, ensure_ascii=False), snapshot['assistant_message_id']))
        kind = {"linked": "new_formulation", "created": "new_action"}.get(claim.get("action_link_status"), "semantic_candidate")
        return self.summary(claim, kind)

    def existing(self, snapshot, connection, *, session):
        if session is None:
            return None
        plan = {"effect": "write", "actions": [a for e in session.executions.values() for a in e["actions"]]}
        # Online and deferred learning refer to the SAME real execution. Never
        # count it twice or let a retry mint another independent experience.
        rows = connection.execute(
            "SELECT DISTINCT m.id FROM memory_claims m JOIN memory_evidence e ON e.claim_id=m.id "
            "WHERE m.scope='semantic_links' AND e.source_turn_id=? AND m.display_text=?",
            (snapshot["turn_id"], snapshot["user_content"]),
        ).fetchall()
        for row in rows:
            existing = self.links.experience(row["id"], _connection=connection)
            if existing["provider"] == next(iter(session.executions.values()))["provider"] and action_identity(existing["plan"]) == action_identity(plan):
                return self.summary(existing, "supporting_evidence")
        return None

    def summary(self, claim, kind):
        from .learned_execution import replay_recipe
        return {"kind": kind, "claim_id": claim["id"], "release": claim["lifecycle"],
                "action_id": claim.get("action_representation_id"),
                "context_dependent": bool(claim.get("context")),
                "direct_execution": claim["lifecycle"] == "active" and replay_recipe(self.links, claim) is not None}
