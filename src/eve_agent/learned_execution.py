"""Replay confirmed, context-free experiences with live provider verification.

No words are interpreted here. Memory supplies the unique released experience;
protocol fields and previously observed goal values supply the execution.
"""
from copy import deepcopy
import json
import re
import sqlite3
import time

from .backend_turns import TurnCancelled
from .dialog import Route
from .memory import redact_sensitive
from .provenance import PlanningProvenance
from .semantic_links import action_identity
from .transport_access import capability_allowed
from .working_memory import WorkingMemoryStore


def replay_recipe(links, hit, *, released_composition=False):
    """Validate a bounded HA recipe, including evidence-backed goal values."""
    plan = hit.get("plan", {})
    if (hit.get("confirmation") not in {"confirmed", "corroborated", "operationally_grounded"} or hit.get("validity") != "valid"
            or hit.get("provider_validated") is not True or hit.get("context")
            or hit.get("technical_status") != "success"
            or plan.get("effect") != "write" or plan.get("context_required")
            or plan.get("contextual_authorization") or plan.get("target_from_context")
            or plan.get("clarification")):
        return None
    assessment = hit.get("semantic_assessment") or {}
    if not released_composition and (not hit.get("assessment_valid") or assessment.get("status") != "resolved"
            or assessment.get("user_grounding") != "explicit" or assessment.get("uncertainties")
            or assessment.get("context_keys")):
        return None
    actions = plan.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 8:
        return None
    recipe = []
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "call_service":
            return None
        entity, service = action.get("entity_id"), action.get("service")
        if (not isinstance(entity, str) or not re.fullmatch(r"[a-z0-9_]+\.[A-Za-z0-9_]+", entity)
                or not isinstance(service, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", service)):
            return None
        data = action.get("parameters", action.get("data", {}))
        if (not isinstance(data, dict) or set(data) & {"entity_id", "area_id", "device_id"}
                or ("parameters" in action and "data" in action and action["parameters"] != action["data"])):
            return None
        recipe.append({"entity_id": entity, "service": service, "data": deepcopy(data)})
    # Repeating an entity within one plan can require intermediate state goals.
    if len({item["entity_id"] for item in recipe}) != len(recipe):
        return None
    observations = deepcopy(plan.get("replay_observations", []))
    if not observations:
        # Compatibility with older experiences whose provider result already
        # contains an independently read, confirmed state. Do not guess states
        # from service names, nor apply state-only checks to parameter changes.
        if any(item["data"] for item in recipe):
            return None
        with links.database.connect(lifecycle_audit=False) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM memory_evidence WHERE claim_id=? "
                "AND evidence_type='provider_result' ORDER BY created_at DESC,id DESC", (hit["id"],),
            ).fetchall()
        for row in rows:
            result = json.loads(row[0])
            if result.get("status") != "success" or len(result.get("action_results", [])) != len(recipe):
                continue
            found = []
            for action, item in zip(result.get("action_results", []), recipe):
                verification = action.get("verification") or {}
                values = verification.get("observations") or []
                if (action.get("entity_id") != item["entity_id"] or action.get("service") != item["service"]
                        or action.get("status") != "success" or verification.get("final_decision") != "target_confirmed"
                        or not values or values[-1].get("target_match") is not True
                        or values[-1].get("stale") is True or values[-1].get("contradictory") is True
                        or not isinstance(values[-1].get("state"), str)):
                    break
                found.append({"entity_id": item["entity_id"], "pointer": "/response/body/state",
                              "value": values[-1]["state"]})
            if len(found) == len(recipe):
                observations = found
                break
    if not isinstance(observations, list) or not observations:
        return None
    for observation in observations:
        if (not isinstance(observation, dict) or observation.get("entity_id") not in {item["entity_id"] for item in recipe}
                or not isinstance(observation.get("pointer"), str)
                or not (observation["pointer"] == "/response/body/state"
                        or observation["pointer"].startswith("/response/body/attributes/"))
                or "value" not in observation):
            return None
        if observation["pointer"] == "/response/body/state" and (
                not isinstance(observation["value"], str) or observation["value"] in {"unknown", "unavailable"}):
            return None
    if {o["entity_id"] for o in observations} != {item["entity_id"] for item in recipe}:
        return None
    return recipe, observations


def select_replay(links, text, context, provider):
    """Use Memory's existing release policies, never a separate language router."""
    hit = links.lookup(text, context, provider)
    if hit:
        prepared = replay_recipe(links, hit)
        return (hit, prepared, "exact", None) if prepared else None
    similar = links.similarity_lookup(text, context, provider)
    if similar.get("status") == "ambiguous" or similar.get("negative_relation_present"):
        return None
    candidate = similar.get("hit")
    if candidate and not similar.get("truncated"):
        hit = links.experience(candidate["id"])
        if hit.get("lifecycle") == "active" and action_identity(hit["plan"]) == action_identity(candidate["plan"]):
            prepared = replay_recipe(links, hit)
            if prepared:
                return hit, prepared, "similarity", similar
        return None
    composed = links.composition_lookup(text, context, provider)
    candidate = composed.get("hit")
    if not candidate or not composed.get("execution_authorized") or composed.get("truncated") or candidate.get("context"):
        return None
    # A composed plan may carry the representative's old goal metadata. Never
    # reuse it: derive a goal only if independent released experiences agree on
    # the same service/parameters across at least two distinct target devices.
    actions = candidate["plan"].get("actions", [])
    if len(actions) != 1:
        return None
    action = actions[0]
    experience_ids = {source for proof in candidate.get("evidence", [])
                      for source in proof.get("support_experiences", [])}
    if any(proof.get("dependency_examples_truncated") for proof in candidate.get("evidence", [])):
        return None
    goals, roots, targets, dependencies = {}, set(), set(), []
    with links.database.connect(lifecycle_audit=False) as connection:
        source_ids = [row[0] for experience_id in sorted(experience_ids)
                      for row in connection.execute(
                          "SELECT claim_id FROM semantic_differential_experiences WHERE id=? AND state='eligible'",
                          (experience_id,))]
    for source_id in sorted(source_ids):
        source = links.experience(source_id)
        source_actions = source.get("plan", {}).get("actions", [])
        if source.get("lifecycle") != "active" or source.get("provider") != provider or len(source_actions) != 1:
            continue
        original = source_actions[0]
        if (original.get("service") != action.get("service")
                or original.get("parameters", original.get("data", {})) != action.get("parameters", action.get("data", {}))
                or original.get("entity_id", "").split(".")[0] != action.get("entity_id", "").split(".")[0]):
            continue
        prepared = replay_recipe(links, source)
        if not prepared:
            continue
        goal = [{**o, "entity_id": action["entity_id"]} for o in prepared[1]]
        goals[json.dumps(goal, sort_keys=True)] = goal
        if source.get("differential_provenance_root"):
            roots.add(source["differential_provenance_root"])
        targets.add(original["entity_id"])
        dependencies.append(source_id)
    if len(goals) != 1 or len(roots) < 2 or len(targets) < 2:
        return None
    # Meaning and technical fields were released by differential evidence. The
    # verification goal above is transferred only across evidenced target variation.
    plan = deepcopy(candidate["plan"])
    plan["replay_observations"] = next(iter(goals.values()))
    # Do not attribute the representative's model interpretation to this new
    # request, or manufacture a fresh model assessment of the composition.
    plan.pop("semantic_learning", None)
    hit = {"id": None, "plan": plan, "provider": provider, "confirmation": "corroborated",
           "validity": "valid", "provider_validated": True, "technical_status": "success",
           "context": {}}
    prepared = replay_recipe(links, hit, released_composition=True)
    proof = {"evaluation_id": composed.get("evaluation_id"), "hypothesis_ids": candidate.get("hypothesis_ids", []),
             "source_claim_ids": dependencies, "goal_policy": "independent_target_invariant_goal_v1"}
    return (hit, prepared, "composition", proof) if prepared else None


def try_replay(runtime, text, images, state):
    """Return None only before dispatching a write, allowing the model fallback."""
    agent = runtime.agent
    session = runtime.semantic_session
    home = getattr(agent, "home_assistant", None)
    if (images or not session or not home or not home.configured
            or not capability_allowed("home_assistant") or session.context.get("pending")
            or session.context.get("task_active")
            or (agent._last_operational_turn or {}).get("details", {}).get("write_retry_forbidden")):
        return None
    links = session.links
    try:
        selected = select_replay(links, text, session.context, home.semantic_provider_identity())
        if not selected:
            return None
    except (KeyError, ValueError, TypeError, OSError, sqlite3.Error):
        return None
    hit, prepared, match_kind, match_proof = selected
    recipe, observations = prepared
    round_provenance = PlanningProvenance.create(agent._trace_id)

    def call(parameters, *, write=False, preflight=False):
        agent._cancel_checkpoint()
        provenance = round_provenance.create_plan(1).reserve_tool_event()
        agent.bus.set("tool:home_assistant", "home_assistant · gespeicherte Aktion")
        try:
            result, _ = runtime._execute_direct("home_assistant", "http_request", parameters, state, [])
        except TurnCancelled:
            raise
        except Exception as exc:
            result = {"status": "outcome_uncertain" if write else "error",
                      "error_class": type(exc).__name__, "message": redact_sensitive(str(exc))}
        agent._tool_events.append({"id": provenance.tool_event_id, "tool": "home_assistant",
                                  "operation": "http_request", "status": result.get("status", "error"),
                                  "replay_preflight": preflight,
                                  "input": deepcopy(parameters), "result": deepcopy(result),
                                  "provenance": provenance.as_dict()})
        return result

    # Validate all service and target identities before the first write.
    services = call({"method": "GET", "path": "/api/services"}, preflight=True)
    body = services.get("response", {}).get("body")
    if services.get("status") != "completed" or not isinstance(body, list):
        return None
    available = {f'{domain.get("domain")}.{service}' for domain in body if isinstance(domain, dict)
                 and isinstance(domain.get("services"), dict) for service in domain["services"]}
    if any(item["service"] not in available for item in recipe):
        return None
    for item in recipe:
        result = call({"method": "GET", "path": "/api/states/" + item["entity_id"]}, preflight=True)
        body = result.get("response", {}).get("body")
        if (result.get("status") != "completed" or not isinstance(body, dict)
                or body.get("entity_id") != item["entity_id"] or not isinstance(body.get("state"), str)
                or body["state"] in {"unavailable", "unknown"}):
            return None
    # A UI correction or inventory refresh during preflight must invalidate reuse.
    current = select_replay(links, text, session.context, home.semantic_provider_identity())
    if (not current or current[0]["id"] != hit["id"] or current[2] != match_kind
            or current[1] != prepared or action_identity(current[0]["plan"]) != action_identity(hit["plan"])):
        return None
    agent._turn_state_details.update(decision_origin="semantic_replay", llm_used=False,
                                    semantic_link_id=hit["id"], semantic_reuse=match_kind,
                                    semantic_replay_evidence=deepcopy(match_proof))
    if match_kind == "similarity":
        agent._turn_state_details["semantic_similarity"] = {
            "semantic_reuse": "similarity", "learned_claim_id": hit["id"],
            "action_representation_id": hit.get("action_representation_id"),
        }
    if hit["id"]:
        agent._turn_memory_ids.append(hit["id"])
    outcomes = []
    for item in recipe:
        domain, service = item["service"].split(".")
        # Preserve the no-retry boundary even if cancellation or persistence
        # fails after the provider has received a write.
        agent._turn_state_details["write_retry_forbidden"] = True
        agent._last_operational_turn = {"state": "operational_unresolved", "utterance": text,
                                        "route": Route.HOME, "details": deepcopy(agent._turn_state_details)}
        result = call({"method": "POST", "path": f"/api/services/{domain}/{service}",
                       "body": {**item["data"], "entity_id": item["entity_id"]}}, write=True)
        confirmed = False
        reads = []
        if result.get("status") == "completed":
            for attempt in range(3):
                if attempt:
                    time.sleep(.15)
                observed = call({"method": "GET", "path": "/api/states/" + item["entity_id"]})
                reads.append(observed)
                try:
                    goals = [o for o in observations if o["entity_id"] == item["entity_id"]]
                    body = observed.get("response", {}).get("body")
                    confirmed = (observed.get("status") == "completed"
                                 and isinstance(body, dict) and body.get("entity_id") == item["entity_id"]
                                 and all(json.dumps(WorkingMemoryStore.pointer(observed, o["pointer"]), sort_keys=True)
                                         == json.dumps(o["value"], sort_keys=True) for o in goals))
                except (KeyError, ValueError, TypeError, IndexError):
                    confirmed = False
                if confirmed:
                    break
        outcomes.append({"entity_id": item["entity_id"], "service": item["service"],
                         "status": "success" if confirmed else "outcome_uncertain",
                         "verification": {"final_decision": "target_confirmed" if confirmed else "target_unconfirmed",
                                          "observations": reads}})
        if not confirmed:
            # Never pass an uncertain write to the model for another attempt.
            break
    success = len(outcomes) == len(recipe) and all(o["status"] == "success" for o in outcomes)
    status = "success" if success else "outcome_uncertain"
    answer = ("Erledigt." if success else
              "Ich konnte nicht bestätigen, ob das geklappt hat. Ich wiederhole den Befehl nicht automatisch.")
    if not success:
        agent._tool_events.append({"id": round_provenance.create_plan(0).reserve_tool_event().tool_event_id,
                                  "tool": "home_assistant", "operation": "verify_learned_action",
                                  "status": "outcome_uncertain", "input": {},
                                  "result": {"status": status, "action_results": outcomes}})
    feedback = {"status": status, "action_results": outcomes, "summary": answer}
    if match_kind == "composition":
        claim_id = links.learn(text, session.context, hit["provider"], hit["plan"], feedback,
                              source_ref=agent._trace_id, provider_validated=True,
                              differential_evidence=match_proof, provenance_root="",
                              interpretation_source="differential_composition")
        agent._turn_state_details["semantic_link_id"] = claim_id
    else:
        links.feedback(hit["id"], feedback, source_ref=agent._trace_id)
    home.last_entities = [item["entity_id"] for item in recipe]
    agent._turn_state = "operational_resolved" if success else "operational_unresolved"
    return runtime._finish(text, answer, Route.HOME, result=feedback)
