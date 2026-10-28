"""Evidence-checked semantic learning from completed turns; never runs a device."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from .home_assistant import HomeAssistant
from .native_semantics import NativeSemanticSession
from .semantic_links import CONTEXT_KEYS, SemanticLinks, action_identity, assessment_conditions


def formulation_schema():
    session = SimpleNamespace(providers={"home_assistant": None})
    schema = deepcopy(NativeSemanticSession.contract(session)["operations"]["record_action"]["parameters_schema"])
    schema["properties"].pop("based_on", None)
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
            "goal_observation_refs": [ref for ref, call in session.calls.items()
                if session.tool_ordinals[ref] > max(session.tool_ordinals[r] for r in session.executions)
                and call['result'].get('status') == 'completed'
                and call['parameters'].get('method') == 'GET'
                and call['parameters'].get('path') in {'/api/states/' + a['entity_id']
                    for execution in session.executions.values() for a in execution['actions']}],
            "action_candidates": session.published["home_assistant"], "existing_formulations": existing,
            "contract": "Return semantic_formulation or null with semantic_learning_reason. Meaning is model-assessed. success requires goal_observation_refs; outcome_uncertain may retain a candidate with empty evidence. Existing meanings require published action and anchor IDs."}

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
        # Online and deferred learning share the same receipt/goal checks.
        # Earlier failed transports do not invalidate a later successful receipt.
        session.validate_record(raw)
        return deepcopy(raw)

    def persist(self, snapshot, raw, connection, *, session):
        existing = self.existing(snapshot, connection, session=session)
        if existing:
            assessment = raw['assessment']
            if (existing.get('link_status') == 'insufficient_evidence' and raw['outcome'] == 'success'
                    and assessment['status'] == 'resolved' and not assessment['uncertainties']
                    and assessment['user_grounding'] != 'unknown'
                    and assessment['action_link']['kind'] in {'new', 'existing'}):
                # Reassess the same proven occurrence, preserving its independent root.
                claim = self.links.experience(existing['claim_id'], _connection=connection)
                if claim.get('strong_semantic_evidence') and claim.get('validity') == 'valid':
                    payload = {key: value for key, value in claim.items() if key not in {'id', 'lifecycle', 'created_at'}}
                    old_assessment = deepcopy(payload['semantic_assessment'])
                    payload['semantic_assessment'] = deepcopy(raw['assessment'])
                    payload['plan']['semantic_learning'] = deepcopy(raw['assessment'])
                    payload['context'] = assessment_conditions(raw['assessment'], session.context,
                                                               snapshot['user_content'], payload['plan'])
                    self.links._link_action(connection, claim['id'], payload, session.published['home_assistant'])
                    if payload['action_link_status'] not in {'created', 'linked'}:
                        raise ValueError('semantic_relink_not_established:' + payload.get('action_link_reason', 'unknown'))
                    self.links._evidence(connection, claim['id'], 'semantic_link_reassessment',
                        {'previous_assessment': old_assessment, 'assessment': raw['assessment'],
                         'same_execution': True}, snapshot['turn_id'])
                    self.links._update(connection, claim['id'], payload, claim['lifecycle'])
                    self.links.differential.refresh_claim(claim['id'], _connection=connection)
                    return self.summary(self.links.experience(claim['id'], _connection=connection),
                                        'relinked' if payload['action_link_status'] in {'created', 'linked'} else 'semantic_candidate')
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
                "direct_execution": claim["lifecycle"] == "active" and replay_recipe(self.links, claim) is not None,
                "link_status": claim.get("action_link_status"), "reason": claim.get("action_link_reason") or (
                    "goal_unverified" if claim.get("technical_status") != "success" else None)}
