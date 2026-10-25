"""Bounded, evidence-only differential composition for Semantic Links.

This module assigns no linguistic meaning.  It compares normalized surface
features with leaf differences in confirmed technical plans and releases only
relations supported by independent provenance and an exact one-field contrast.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
import unicodedata
import uuid
from collections import defaultdict
from contextlib import nullcontext

from .storage import _now, _safe_json


POLICY = "differential_one_field_contrast_v1"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    import re
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFKC", str(text)).casefold())


def _features(tokens: list[str]) -> dict[str, list[list[int]]]:
    found: dict[str, list[list[int]]] = defaultdict(list)
    for start in range(len(tokens)):
        for width in range(1, min(3, len(tokens) - start) + 1):
            kind = "tok" if width == 1 else "cmp"
            value = tokens[start] if width == 1 else "\u241f".join(tokens[start:start + width])
            found[f"{kind}:{value}"].append(list(range(start, start + width)))
    return dict(found)


def _escape(part: str) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _unescape(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def flatten_plan(plan: dict) -> tuple[dict[str, object], str]:
    """Return JSON-pointer leaves and a versioned structural identity."""
    leaves: dict[str, object] = {}
    structure: list[tuple[str, str]] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            structure.append((path, "object"))
            for key in sorted(value):
                walk(value[key], path + "/" + _escape(key))
        elif isinstance(value, list):
            structure.append((path, f"array:{len(value)}"))
            for index, item in enumerate(value):
                walk(item, path + "/" + str(index))
        else:
            structure.append((path, "leaf"))
            leaves[path] = value

    technical = {"effect": plan.get("effect"), "actions": plan.get("actions")}
    walk(technical, "")
    return leaves, _hash({"version": 1, "structure": structure})


def _set_pointer(document, path: str, value) -> None:
    parts = [_unescape(part) for part in path.split("/")[1:]]
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    final = parts[-1]
    if isinstance(target, list):
        target[int(final)] = copy.deepcopy(value)
    else:
        target[final] = copy.deepcopy(value)


class DifferentialSemantics:
    def __init__(self, database, config=None):
        self.database = database
        self.configure(config or {})

    def configure(self, config):
        if not isinstance(config, dict):
            raise ValueError("Composition configuration must be an object")
        values = {
            "enabled": config.get("enabled", True),
            "mode": config.get("mode", "active"),
            "min_support_roots": config.get("min_support_roots", 2),
            "max_tokens": config.get("max_tokens", 64),
            "max_fields": config.get("max_fields", 32),
            "max_lookup_candidates": config.get("max_lookup_candidates", 512),
            "max_shapes": config.get("max_shapes", 8),
            "max_support_scan": config.get("max_support_scan", 20000),
            "max_update_pairs": config.get("max_update_pairs", 200000),
            "policy": POLICY,
        }
        if type(values["enabled"]) is not bool or values["mode"] not in {"active", "shadow"}:
            raise ValueError("Invalid composition mode")
        bounds = {
            "min_support_roots": (2, 20), "max_tokens": (1, 256), "max_fields": (1, 256),
            "max_lookup_candidates": (1, 5000), "max_shapes": (1, 64),
            "max_support_scan": (10, 100000), "max_update_pairs": (100, 2000000),
        }
        for key, (low, high) in bounds.items():
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"Invalid composition bound: {key}")
        values["version"] = _hash(values)[:12]
        self.config = values
        return dict(values)

    def settings(self):
        return dict(self.config)

    @staticmethod
    def _explicit_language_features(db, tokens, features, context, provider):
        """Add only direct, active user-declared surface edges to this lookup."""
        rows = db.execute("""SELECT id,payload_json FROM memory_claims
            WHERE scope='semantic_language_relations' AND lifecycle='active'
            ORDER BY updated_at DESC,id DESC LIMIT 501""").fetchall()
        truncated = len(rows) > 500
        relations = []
        for row in rows[:500]:
            payload = json.loads(row["payload_json"])
            conditions = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            if any(key not in context or context[key] != value for key, value in conditions.items()):
                continue
            binding = payload.get("provider")
            if binding is not None and binding != provider:
                continue
            if payload.get("relation_kind") == "resource_alias":
                source_claim_ids = payload.get("source_claim_ids", [])
                if not isinstance(source_claim_ids, list) or not source_claim_ids:
                    continue
                marks = ",".join("?" for _ in source_claim_ids)
                dependencies = db.execute(
                    f"""SELECT lifecycle,payload_json FROM memory_claims
                    WHERE scope='semantic_links' AND id IN ({marks})""",
                    source_claim_ids,
                ).fetchall()
                dependency_valid = False
                for dependency in dependencies:
                    source_payload = json.loads(dependency["payload_json"])
                    source_resources = {
                        action.get("entity_id")
                        for action in source_payload.get("plan", {}).get("actions", [])
                        if isinstance(action, dict) and action.get("entity_id")
                    }
                    if (dependency["lifecycle"] == "active"
                            and source_payload.get("validity") == "valid"
                            and source_payload.get("provider_validated") is True
                            and source_payload.get("technical_status") == "success"
                            and source_payload.get("provider") == provider
                            and payload.get("resource_identity") in source_resources):
                        dependency_valid = True
                        break
                if not dependency_valid:
                    continue
            relations.append((row["id"], payload))
        negatives = {
            _json(edge)
            for _relation_id, payload in relations if payload.get("polarity") == "negative"
            for edge in payload.get("edges", []) if isinstance(edge, list) and len(edge) == 2
        }
        expanded = {key: [list(span) for span in spans] for key, spans in features.items()}
        relation_features: dict[str, set[str]] = defaultdict(set)
        relation_resources: dict[str, set[str]] = defaultdict(set)
        mappings = []
        for relation_id, payload in relations:
            if payload.get("polarity") != "positive":
                continue
            for edge in payload.get("edges", []):
                if not isinstance(edge, list) or len(edge) != 2:
                    continue
                directions = [edge]
                if payload.get("relation_kind") == "surface_equivalence":
                    directions.append([edge[1], edge[0]])
                for source, target in directions:
                    if not isinstance(source, list) or not source or not isinstance(target, list) or not target:
                        continue
                    if _json([source, target]) in negatives or _json([target, source]) in negatives:
                        continue
                    for start in range(len(tokens) - len(source) + 1):
                        if tokens[start:start + len(source)] != source:
                            continue
                        source_span = list(range(start, start + len(source)))
                        additions = _features(target)
                        for feature in additions:
                            if feature not in expanded:
                                expanded[feature] = []
                            if source_span not in expanded[feature]:
                                expanded[feature].append(source_span)
                            relation_features[feature].add(relation_id)
                            if payload.get("resource_identity"):
                                relation_resources[feature].add(payload["resource_identity"])
                        mappings.append({
                            "relation_id": relation_id, "relation_kind": payload.get("relation_kind"),
                            "source_tokens": source, "target_tokens": target, "input_span": source_span,
                            "resource_identity": payload.get("resource_identity"),
                        })
        return {
            "features": expanded, "relation_features": relation_features,
            "relation_resources": relation_resources, "mappings": mappings,
            "relation_ids": sorted({item["relation_id"] for item in mappings}),
            "negative_relation_present": bool(negatives), "truncated": truncated,
        }

    @staticmethod
    def _eligible(lifecycle: str, payload: dict) -> tuple[bool, str]:
        if payload.get("validity") != "valid" or lifecycle in {"invalid", "retired"}:
            return False, "inactive_or_invalid"
        if ((payload.get("technical_status") != "success" and not payload.get("last_success"))
                or payload.get("provider_validated") is not True):
            return False, "technical_result_not_confirmed"
        confirmed = payload.get("confirmation") == "confirmed"
        corroborated = (payload.get("confirmation") == "corroborated"
                        and payload.get("strong_semantic_evidence") is True)
        if not (confirmed or corroborated):
            return False, "semantic_experience_unconfirmed"
        if lifecycle != "active":
            return False, "inactive_or_invalid"
        if not payload.get("plan", {}).get("actions"):
            return False, "empty_action"
        return True, "eligible"

    def refresh_claim(self, claim_id: str, *, _connection=None, _rebuild=True) -> dict:
        """Update one experience and only its affected technical partition."""
        with nullcontext(_connection) if _connection is not None else self.database.connect() as db:
            row = db.execute(
                "SELECT lifecycle,payload_json FROM memory_claims WHERE id=? AND scope='semantic_links'",
                (claim_id,),
            ).fetchone()
            old = db.execute(
                "SELECT provider_key,context_key,shape_key FROM semantic_differential_experiences WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            affected = {tuple(old) if old else None}
            if row is None:
                if old:
                    db.execute("DELETE FROM semantic_differential_experiences WHERE claim_id=?", (claim_id,))
            else:
                payload = json.loads(row["payload_json"])
                eligible, reason = self._eligible(row["lifecycle"], payload)
                plan = payload.get("plan") or {}
                leaves, shape = flatten_plan(plan)
                tokens = _tokens(payload.get("utterance", ""))
                provider_key = _hash(payload.get("provider"))
                context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
                context_key = _hash(context)
                affected.add((provider_key, context_key, shape))
                state = "eligible" if eligible else "invalid" if payload.get("validity") == "invalid" else "ineligible"
                now = _now()
                existing = db.execute(
                    "SELECT id,version,created_at FROM semantic_differential_experiences WHERE claim_id=?",
                    (claim_id,),
                ).fetchone()
                experience_id = existing["id"] if existing else str(uuid.uuid4())
                version = int(existing["version"]) + 1 if existing else 1
                db.execute(
                    """INSERT OR REPLACE INTO semantic_differential_experiences
                    (id,claim_id,provider_key,context_key,context_json,shape_key,utterance,tokens_json,
                     plan_json,action_key,provenance_root,state,reason,version,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (experience_id, claim_id, provider_key, context_key, _json(context), shape,
                     payload.get("utterance", ""), _json(tokens), _json({"effect": plan.get("effect"),
                     "actions": plan.get("actions")}), _hash({"provider": payload.get("provider"),
                     "context": context, "plan": {"effect": plan.get("effect"), "actions": plan.get("actions")},
                     "status": payload.get("technical_status")}), payload.get("differential_provenance_root"),
                     state, reason, version, existing["created_at"] if existing else now, now),
                )
                db.execute("DELETE FROM semantic_differential_features WHERE experience_id=?", (experience_id,))
                db.execute("DELETE FROM semantic_differential_fields WHERE experience_id=?", (experience_id,))
                if eligible and len(tokens) <= self.config["max_tokens"] and len(leaves) <= self.config["max_fields"]:
                    for feature, spans in _features(tokens).items():
                        db.execute("INSERT INTO semantic_differential_features VALUES (?,?,?)",
                                   (experience_id, feature, _json(spans)))
                    encoded = {path: _json(value) for path, value in leaves.items()}
                    for path, value_json in encoded.items():
                        other = _hash([(key, encoded[key]) for key in sorted(encoded) if key != path])
                        db.execute("INSERT INTO semantic_differential_fields VALUES (?,?,?,?)",
                                   (experience_id, path, value_json, other))
                elif eligible:
                    db.execute("UPDATE semantic_differential_experiences SET state='ineligible',reason=? WHERE id=?",
                               ("experience_bound", experience_id))
            partitions = sorted(item for item in affected if item)
            reports = [self._rebuild_partition(db, *partition) for partition in partitions] if _rebuild else []
            return {"claim_id": claim_id, "partition_keys": partitions, "partitions": reports}

    def rebuild_all(self) -> list[dict]:
        """Bounded administrative/bootstrap rebuild; live updates stay partition-local."""
        with self.database.connect() as db:
            partitions = db.execute("""SELECT DISTINCT provider_key,context_key,shape_key
                FROM semantic_differential_experiences""").fetchall()
            return [self._rebuild_partition(db, *tuple(row)) for row in partitions]

    def _rebuild_partition(self, db, provider_key: str, context_key: str, shape_key: str) -> dict:
        limit = self.config["max_support_scan"]
        rows = db.execute(
            """SELECT * FROM semantic_differential_experiences
               WHERE provider_key=? AND context_key=? AND shape_key=? AND state='eligible'
               ORDER BY updated_at,id LIMIT ?""", (provider_key, context_key, shape_key, limit + 1),
        ).fetchall()
        truncated = len(rows) > limit
        rows = rows[:limit]
        experience_ids = [row["id"] for row in rows]
        if not experience_ids:
            db.execute("UPDATE semantic_differential_hypotheses SET status='retired',updated_at=? "
                       "WHERE provider_key=? AND context_key=? AND shape_key=?",
                       (_now(), provider_key, context_key, shape_key))
            return {"experiences": 0, "hypotheses": 0, "truncated": False}
        marks = ",".join("?" for _ in experience_ids)
        feature_rows = db.execute(
            f"SELECT experience_id,feature FROM semantic_differential_features WHERE experience_id IN ({marks})",
            experience_ids,
        ).fetchall()
        field_rows = db.execute(
            f"SELECT experience_id,field_path,value_json,other_signature FROM semantic_differential_fields WHERE experience_id IN ({marks})",
            experience_ids,
        ).fetchall()
        roots = {row["id"]: row["provenance_root"] for row in rows}
        feature_experiences: dict[str, set[str]] = defaultdict(set)
        experience_features: dict[str, set[str]] = defaultdict(set)
        for item in feature_rows:
            feature_experiences[item["feature"]].add(item["experience_id"])
            experience_features[item["experience_id"]].add(item["feature"])
        field_data: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        for item in field_rows:
            field_data[item["field_path"]][item["experience_id"]] = (item["value_json"], item["other_signature"])
        pair_count = len(feature_experiences) * len(field_data)
        partition_truncated = truncated or pair_count > self.config["max_update_pairs"]
        touched: set[str] = set()
        if not partition_truncated:
            for feature, with_feature in feature_experiences.items():
                for path, values in field_data.items():
                    by_other: dict[str, set[str]] = defaultdict(set)
                    for experience_id, (_field_value, other_signature) in values.items():
                        by_other[other_signature].add(experience_id)
                    grouped: dict[str, set[str]] = defaultdict(set)
                    for experience_id in with_feature & values.keys():
                        grouped[values[experience_id][0]].add(experience_id)
                    for value_json, support in grouped.items():
                        counters = {eid for eid in with_feature & values.keys()
                                    if values[eid][0] != value_json}
                        support_roots = {roots[eid] for eid in support if roots[eid]}
                        nuisance = {values[eid][1] for eid in support}
                        contrasts: set[str] = set()
                        for eid in support:
                            other = values[eid][1]
                            for peer in by_other[other]:
                                if peer not in with_feature and values[peer][0] != value_json:
                                    contrasts.add(peer)
                        status = "released" if (
                            len(support_roots) >= self.config["min_support_roots"]
                            and not counters and len(nuisance) >= 2 and contrasts
                        ) else "blocked" if counters else "candidate"
                        key_data = [provider_key, context_key, shape_key, feature, path, value_json]
                        hypothesis_key = _hash(key_data)
                        hypothesis_id = str(uuid.uuid5(uuid.UUID("5632a109-b171-4a36-bbfa-82ac2558f71f"), hypothesis_key))
                        previous = db.execute(
                            "SELECT version,status,payload_json,created_at FROM semantic_differential_hypotheses WHERE id=?",
                            (hypothesis_id,),
                        ).fetchone()
                        # A single root is an observation, not yet a durable
                        # relation hypothesis.  It remains indexed as experience
                        # evidence and is materialized when a second independent
                        # root arrives.
                        if len(support_roots) < self.config["min_support_roots"] and previous is None:
                            continue
                        payload = _safe_json({
                            "policy": POLICY, "feature": feature, "field_path": path,
                            "value": json.loads(value_json), "support_experiences": sorted(support)[:64],
                            "independent_roots": sorted(support_roots)[:64], "counterexamples": sorted(counters)[:64],
                            "contrast_experiences": sorted(contrasts)[:64], "nuisance_signatures": sorted(nuisance)[:64],
                            "evidence_counts": {"support": len(support), "independent_roots": len(support_roots),
                                "counterexamples": len(counters), "contrasts": len(contrasts),
                                "nuisance_values": len(nuisance)},
                            "dependency_examples_truncated": any(len(items) > 64 for items in
                                (support, support_roots, counters, contrasts, nuisance)),
                            "complete_candidate_space": True,
                        })
                        changed = previous is None or previous["status"] != status or previous["payload_json"] != _json(payload)
                        version = (int(previous["version"]) + 1) if previous and changed else int(previous["version"]) if previous else 1
                        now = _now()
                        touched.add(hypothesis_id)
                        if not changed:
                            continue
                        values_to_write = (hypothesis_id, hypothesis_key, provider_key, context_key,
                            shape_key, feature, path, value_json, status, len(support_roots), len(counters),
                            len(nuisance), len(contrasts), version, _json(payload),
                            previous["created_at"] if previous else now, now)
                        if previous:
                            db.execute("""UPDATE semantic_differential_hypotheses SET
                                hypothesis_key=?,provider_key=?,context_key=?,shape_key=?,feature=?,field_path=?,
                                value_json=?,status=?,support_roots=?,counterexamples=?,nuisance_values=?,
                                contrast_count=?,version=?,payload_json=?,created_at=?,updated_at=? WHERE id=?""",
                                (*values_to_write[1:], hypothesis_id))
                        else:
                            db.execute("""INSERT INTO semantic_differential_hypotheses
                                (id,hypothesis_key,provider_key,context_key,shape_key,feature,field_path,value_json,
                                 status,support_roots,counterexamples,nuisance_values,contrast_count,version,payload_json,
                                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                values_to_write)
                        if changed:
                            db.execute("INSERT INTO semantic_differential_hypothesis_versions VALUES (?,?,?,?,?)",
                                       (hypothesis_id, version, status, _json(payload), now))
                        db.execute("DELETE FROM semantic_differential_dependencies WHERE hypothesis_id=?",
                                   (hypothesis_id,))
                        for stance, ids in (("support", support), ("counter", counters), ("contrast", contrasts)):
                            for eid in sorted(ids)[:64]:
                                db.execute("INSERT INTO semantic_differential_dependencies VALUES (?,?,?,?)",
                                           (hypothesis_id, eid, roots[eid], stance))
        if partition_truncated:
            db.execute("UPDATE semantic_differential_hypotheses SET status='truncated',updated_at=? "
                       "WHERE provider_key=? AND context_key=? AND shape_key=?",
                       (_now(), provider_key, context_key, shape_key))
        elif touched:
            marks = ",".join("?" for _ in touched)
            db.execute(f"UPDATE semantic_differential_hypotheses SET status='retired',updated_at=? "
                       f"WHERE provider_key=? AND context_key=? AND shape_key=? AND id NOT IN ({marks})",
                       (_now(), provider_key, context_key, shape_key, *sorted(touched)))
        return {"experiences": len(rows), "hypotheses": len(touched), "truncated": partition_truncated,
                "examined_pairs": min(pair_count, self.config["max_update_pairs"])}

    def lookup(self, utterance: str, context: dict, provider: dict) -> dict:
        started = time.perf_counter()
        cfg = self.settings()
        tokens = _tokens(utterance)
        input_features = _features(tokens) if tokens and len(tokens) <= cfg["max_tokens"] else {}
        base = {"policy": POLICY, "config": cfg, "input_tokens": tokens, "model_requests": 0,
                "prompt_tokens": 0, "completion_tokens": 0,
                "explicit_language_relation_ids": [], "explicit_language_mappings": []}
        if not cfg["enabled"]:
            return self._record({**base, "status": "disabled", "reason": "disabled", "hit": None,
                                 "candidate_count": 0}, utterance, context, provider, started)
        if not input_features:
            return self._record({**base, "status": "fallback", "reason": "input_bound", "hit": None,
                                 "candidate_count": 0}, utterance, context, provider, started)
        provider_key = _hash(provider)
        with self.database.connect() as db:
            language = self._explicit_language_features(
                db, tokens, input_features, context, provider)
            input_features = language["features"]
            base.update(
                explicit_language_relation_ids=language["relation_ids"],
                explicit_language_mappings=language["mappings"],
                explicit_language_negative_relation_present=language["negative_relation_present"],
                explicit_language_scan_truncated=language["truncated"],
            )
            raw_partitions = db.execute(
                """SELECT context_key,context_json,shape_key,COUNT(*) experience_count
                   FROM semantic_differential_experiences
                   WHERE provider_key=? AND state='eligible'
                   GROUP BY context_key,context_json,shape_key ORDER BY context_key,shape_key
                   LIMIT ?""", (provider_key, cfg["max_lookup_candidates"] + 1),
            ).fetchall()
            partition_index_truncated = len(raw_partitions) > cfg["max_lookup_candidates"]
            compatible = [row for row in raw_partitions[:cfg["max_lookup_candidates"]] if all(
                key in context and context[key] == value
                for key, value in json.loads(row["context_json"]).items())]
            shape_truncated = len(compatible) > cfg["max_shapes"]
            compatible = compatible[:cfg["max_shapes"]]
            scan_truncated = partition_index_truncated or language["truncated"]
            candidates = []
            hypothesis_candidates = 0
            conflicts = []
            missing = []
            if not scan_truncated and not shape_truncated:
                for partition in compatible:
                    context_key, shape_key = partition["context_key"], partition["shape_key"]
                    marks = ",".join("?" for _ in input_features)
                    hypotheses = db.execute(
                        f"""SELECT * FROM semantic_differential_hypotheses
                        WHERE provider_key=? AND context_key=? AND shape_key=? AND status='released'
                        AND feature IN ({marks}) LIMIT ?""",
                        (provider_key, context_key, shape_key, *input_features.keys(),
                         cfg["max_lookup_candidates"] + 1),
                    ).fetchall()
                    if len(hypotheses) > cfg["max_lookup_candidates"]:
                        scan_truncated = True
                        break
                    hypothesis_candidates += len(hypotheses)
                    by_path: dict[str, list] = defaultdict(list)
                    for hypothesis in hypotheses:
                        by_path[hypothesis["field_path"]].append(hypothesis)
                    representative_row = db.execute("""SELECT plan_json,context_json
                        FROM semantic_differential_experiences WHERE provider_key=? AND context_key=?
                        AND shape_key=? AND state='eligible' ORDER BY updated_at DESC,id LIMIT 1""",
                        (provider_key, context_key, shape_key)).fetchone()
                    representative = json.loads(representative_row["plan_json"])
                    all_fields = db.execute(
                        """SELECT DISTINCT f.field_path,f.value_json
                        FROM semantic_differential_fields f
                        JOIN semantic_differential_experiences e ON e.id=f.experience_id
                        WHERE e.provider_key=? AND e.context_key=? AND e.shape_key=? AND e.state='eligible'
                        LIMIT ?""", (provider_key, context_key, shape_key,
                                     cfg["max_lookup_candidates"] + 1),
                    ).fetchall()
                    if len(all_fields) > cfg["max_lookup_candidates"]:
                        scan_truncated = True
                        break
                    values: dict[str, set[str]] = defaultdict(set)
                    for field in all_fields:
                        values[field["field_path"]].add(field["value_json"])
                    chosen = {}
                    used = []
                    ambiguous = False
                    for path, options in values.items():
                        if len(options) == 1:
                            chosen[path] = json.loads(next(iter(options)))
                            continue
                        relations = by_path.get(path, [])
                        relation_values = {item["value_json"] for item in relations}
                        if len(relation_values) != 1:
                            ambiguous = True
                            conflicts.append({"shape_key": shape_key, "field_path": path,
                                              "values": sorted(relation_values)})
                            break
                        relation = max(relations, key=lambda item: (item["support_roots"], item["id"]))
                        chosen[path] = json.loads(relation["value_json"])
                        used.append(relation)
                    if ambiguous or not used:
                        missing.append({"shape_key": shape_key, "reason": "unresolved_or_constant_only"})
                        continue
                    covered = set()
                    for relation in used:
                        for span in input_features.get(relation["feature"], []):
                            covered.update(span)
                    # A surface unit is neutral only when observed across at least two
                    # different technical actions in this exact partition.
                    for index, token in enumerate(tokens):
                        feature = f"tok:{token}"
                        action_count = db.execute("""SELECT COUNT(DISTINCT e.action_key)
                            FROM semantic_differential_features f
                            JOIN semantic_differential_experiences e ON e.id=f.experience_id
                            WHERE f.feature=? AND e.provider_key=? AND e.context_key=?
                            AND e.shape_key=? AND e.state='eligible'""",
                            (feature, provider_key, context_key, shape_key)).fetchone()[0]
                        if action_count >= 2:
                            covered.add(index)
                    if covered != set(range(len(tokens))):
                        missing.append({"shape_key": shape_key, "reason": "surface_not_fully_covered",
                                        "uncovered_indices": sorted(set(range(len(tokens))) - covered)})
                        continue
                    plan = copy.deepcopy(representative)
                    for path, value in chosen.items():
                        _set_pointer(plan, path, value)
                    used_features = {item["feature"] for item in used}
                    relation_ids = sorted({
                        relation_id for feature in used_features
                        for relation_id in language["relation_features"].get(feature, set())
                    })
                    required_resources = {
                        resource for feature in used_features
                        for resource in language["relation_resources"].get(feature, set())
                    }
                    plan_resources = {
                        action.get("entity_id") for action in plan.get("actions", [])
                        if isinstance(action, dict) and action.get("entity_id")
                    }
                    if required_resources and not required_resources <= plan_resources:
                        missing.append({"shape_key": shape_key,
                                        "reason": "resource_alias_identity_mismatch",
                                        "required_resources": sorted(required_resources)})
                        continue
                    candidates.append({"plan": plan, "shape_key": shape_key,
                        "context": json.loads(representative_row["context_json"]),
                        "hypothesis_ids": sorted({item["id"] for item in used}),
                        "evidence": [json.loads(item["payload_json"]) for item in used],
                        "language_relation_ids": relation_ids})
        plan_keys = {_json(item["plan"]): item for item in candidates}
        if scan_truncated or shape_truncated:
            status, reason, selected = "fallback", "candidate_space_truncated", None
        elif len(plan_keys) == 1:
            status, reason, selected = "candidate", "unique_released_composition", next(iter(plan_keys.values()))
        elif len(plan_keys) > 1:
            status, reason, selected = "ambiguous", "multiple_complete_actions", None
        else:
            status, reason, selected = "fallback", "insufficient_released_evidence", None
        active = selected is not None and cfg["mode"] == "active"
        outcome = {**base, "status": "hit" if active else "shadow_hit" if selected else status,
                   "reason": reason, "hit": selected if active else None,
                   "shadow_candidate": selected if selected and not active else None,
                   "candidate_count": len(candidates),
                   "checked_count": sum(int(row["experience_count"]) for row in compatible),
                   "hypothesis_candidate_count": hypothesis_candidates,
                   "truncated": scan_truncated or shape_truncated,
                   "conflicts": conflicts, "missing_evidence": missing,
                   "execution_authorized": active}
        return self._record(outcome, utterance, context, provider, started)

    def _record(self, result: dict, utterance: str, context: dict, provider: dict, started: float) -> dict:
        result["duration_ms"] = (time.perf_counter() - started) * 1000
        candidate = result.get("hit") or result.get("shadow_candidate")
        result["evaluation_id"] = str(uuid.uuid4())
        details = {key: result.get(key) for key in (
            "reason", "checked_count", "hypothesis_candidate_count", "truncated", "conflicts",
            "missing_evidence", "model_requests", "prompt_tokens", "completion_tokens",
            "execution_authorized", "explicit_language_relation_ids",
            "explicit_language_mappings", "explicit_language_negative_relation_present",
            "explicit_language_scan_truncated")}
        try:
            with self.database.connect() as db:
                db.execute(
                    """INSERT INTO semantic_differential_evaluations
                    (id,input_text,provider_key,context_json,mode,status,candidate_plan_json,
                     hypothesis_ids_json,details_json,duration_ms,candidate_count,config_version,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (result["evaluation_id"], utterance, _hash(provider), _json(_safe_json(context)),
                     self.config["mode"] if self.config["enabled"] else "disabled", result["status"],
                     _json(candidate["plan"]) if candidate else None,
                     _json(candidate.get("hypothesis_ids", []) if candidate else []), _json(details),
                     result["duration_ms"], result.get("candidate_count", 0), self.config["version"], _now()),
                )
        except Exception:
            # Diagnostics persistence must never convert a safe fallback into action.
            result["diagnostic_persistence"] = "failed"
        return result
