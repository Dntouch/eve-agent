"""User-visible Home Assistant policies and portable language profiles in Memory V2."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .memory import redact_sensitive
from .memory_lifecycle import lifecycle_operation
from .training_packages import (
    AMBIGUITY_PACKAGE,
    LANGUAGE_PACKAGE,
    PORTABLE_AMBIGUITY_KIND,
    PORTABLE_LANGUAGE_KIND,
)


_NAMESPACE = uuid.UUID("2f445d91-1e76-4802-a9cc-7fce35862d54")
POLICY_KIND = "home_assistant_aggregate_scope_policy"
LANGUAGE_KIND = "home_assistant_language_profile"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _endpoint_hash(provider: dict) -> str:
    endpoint = str((provider or {}).get("endpoint") or "")
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:16]


def _policy_scope(provider: dict) -> str:
    return f"provider:home-assistant:{_endpoint_hash(provider)}:policies"


def _language_scope(provider: dict, locale: str) -> str:
    return f"provider:home-assistant:{_endpoint_hash(provider)}:language:{locale.casefold()}"


def _inventory_scope(provider: dict) -> str:
    return f"provider:home-assistant:{_endpoint_hash(provider)}"


def _safe_text(value) -> str:
    return redact_sensitive(str(value or "").strip())


class HomeAssistantMemory:
    """Store household policy and explicitly imported language knowledge in Memory."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _ground_language_profiles(connection, provider: dict, locale: str, now: str) -> dict:
        """Link concrete provider bindings to the generic profiles they support."""
        inventory_scope = _inventory_scope(provider)
        language_scope = _language_scope(provider, locale)
        profiles = {
            row["domain"]: row["id"] for row in connection.execute(
                """SELECT id,json_extract(payload_json,'$.domain') domain
                   FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.kind')=?""",
                (language_scope, LANGUAGE_KIND),
            ).fetchall()
        }
        created = 0
        for binding in connection.execute(
            """SELECT id,json_extract(payload_json,'$.provider_metadata.domain') domain
               FROM memory_claims WHERE scope=? AND lifecycle='active'
               AND claim_kind='provider_binding'
               AND json_extract(payload_json,'$.inventory_source')='home_assistant'""",
            (inventory_scope,),
        ).fetchall():
            profile_id = profiles.get(binding["domain"])
            if not profile_id:
                continue
            evidence = connection.execute(
                """SELECT id FROM memory_evidence WHERE claim_id=?
                   AND evidence_type='provider_inventory'
                   ORDER BY observed_at DESC,id DESC LIMIT 1""",
                (binding["id"],),
            ).fetchone()
            if evidence is None:
                continue
            relation_id = uuid.uuid5(
                _NAMESPACE, f"ha-language-grounding:{binding['id']}:{profile_id}"
            ).hex
            cursor = connection.execute(
                """INSERT OR IGNORE INTO memory_relations
                   (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
                   VALUES (?,?,?,'refines',?,?)""",
                (relation_id, binding["id"], profile_id, evidence["id"], now),
            )
            created += int(cursor.rowcount > 0)
        active = connection.execute(
            """SELECT count(*) FROM memory_relations r
               JOIN memory_claims binding ON binding.id=r.from_claim_id
               JOIN memory_claims profile ON profile.id=r.to_claim_id
               WHERE r.relation_type='refines' AND binding.scope=?
               AND binding.lifecycle='active' AND binding.claim_kind='provider_binding'
               AND profile.scope=? AND profile.lifecycle='active'
               AND json_extract(profile.payload_json,'$.kind')=?""",
            (inventory_scope, language_scope, LANGUAGE_KIND),
        ).fetchone()[0]
        return {"active": active, "created": created, "unchanged": active - created}

    @staticmethod
    def _merge_surface_map(target: dict, source: dict) -> None:
        for key, values in (source or {}).items():
            current = target.setdefault(str(key), [])
            for value in values or []:
                if isinstance(value, str) and value not in current:
                    current.append(value)

    def portable_language_profiles(self, locale="de") -> list[dict]:
        """Return effective generic profiles without local provider identities."""
        locale = str(locale or "de").strip().casefold()[:16] or "de"
        profiles = []
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM memory_claims
                   WHERE lifecycle='active' AND scope=?
                   AND json_extract(payload_json,'$.kind')=?
                   AND json_extract(payload_json,'$.provider')='home_assistant'
                   ORDER BY canonical_key,id""",
                (f"portable:training:home_assistant:{LANGUAGE_PACKAGE}:{locale}",
                 PORTABLE_LANGUAGE_KIND),
            ).fetchall()
        profiles.extend(
            payload["entry"] for row in rows
            for payload in [json.loads(row["payload_json"])]
            if isinstance(payload.get("entry"), dict)
        )
        merged = {}
        for profile in profiles:
            domain = str(profile.get("domain") or "").casefold()
            if not domain:
                continue
            current = merged.setdefault(domain, {
                "id": f"profile.{domain}", "domain": domain, "surfaces": [],
                "actions": {}, "properties": {}, "parameters": {},
                "source_version": "eve-portable-merged-v1",
            })
            for surface in profile.get("surfaces") or []:
                if isinstance(surface, str) and surface not in current["surfaces"]:
                    current["surfaces"].append(surface)
            for operation, definition in (profile.get("actions") or {}).items():
                action = current["actions"].setdefault(str(operation), {"surfaces": []})
                for surface in (definition or {}).get("surfaces", []):
                    if isinstance(surface, str) and surface not in action["surfaces"]:
                        action["surfaces"].append(surface)
                effect = (definition or {}).get("effect")
                if effect in {"read", "write"}:
                    if "effect" not in action:
                        action["effect"] = effect
                    elif action["effect"] != effect:
                        action.pop("effect", None)
            self._merge_surface_map(current["properties"], profile.get("properties") or {})
            self._merge_surface_map(current["parameters"], profile.get("parameters") or {})
        return [merged[key] for key in sorted(merged)]

    def portable_ambiguities(self, locale="de") -> list[dict]:
        locale = str(locale or "de").strip().casefold()[:16] or "de"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM memory_claims
                   WHERE lifecycle='active' AND scope=?
                   AND json_extract(payload_json,'$.kind')=?
                   AND json_extract(payload_json,'$.provider')='home_assistant'
                   ORDER BY canonical_key,id""",
                (f"portable:training:home_assistant:{AMBIGUITY_PACKAGE}:{locale}",
                 PORTABLE_AMBIGUITY_KIND),
            ).fetchall()
        result = []
        seen = set()
        for row in rows:
            entry = json.loads(row["payload_json"]).get("entry")
            if isinstance(entry, dict) and entry.get("id") not in seen:
                seen.add(entry.get("id"))
                result.append(entry)
        return result

    @lifecycle_operation("memory.home_assistant", "generated_ambiguities_sync")
    def sync_generated_ambiguities(self, *, locale="de") -> dict:
        """Persist lexical collisions from profiles as explicit portable ambiguity claims."""
        locale = str(locale or "de").strip().casefold()[:16] or "de"
        occurrences = {}
        for profile in self.portable_language_profiles(locale):
            domain = profile["domain"]
            for surface in profile["surfaces"]:
                occurrences.setdefault(surface.casefold(), {}).setdefault(domain, set()).add("get_state")
            for operation, definition in profile["actions"].items():
                for surface in definition.get("surfaces", []):
                    occurrences.setdefault(surface.casefold(), {}).setdefault(domain, set()).add(operation)
        entries = []
        for surface, domains in sorted(occurrences.items()):
            distinct = {(domain, operation) for domain, operations in domains.items() for operation in operations}
            if len(domains) < 2 and len(distinct) < 2:
                continue
            digest = hashlib.sha256((locale + ":" + surface).encode("utf-8")).hexdigest()[:16]
            options = [
                {"domain": domain, "operations": [operation]}
                for domain, operations in sorted(domains.items())
                for operation in sorted(operations)
            ]
            entries.append({
                "id": f"generated.{digest}", "surfaces": [surface], "options": options,
            })
        now = _now()
        scope = f"portable:training:home_assistant:{AMBIGUITY_PACKAGE}:{locale}"
        active = set()
        with self.database.connect() as connection:
            for entry in entries:
                canonical = f"training:home_assistant:ambiguities:{locale}:eve:generated:{entry['id']}"
                active.add(canonical)
                previous = connection.execute(
                    """SELECT id FROM memory_claims
                       WHERE scope=? AND claim_kind='opaque_fact' AND canonical_key=?""",
                    (scope, canonical),
                ).fetchone()
                claim_id = previous["id"] if previous is not None else uuid.uuid5(
                    _NAMESPACE, f"{scope}:{canonical}"
                ).hex
                payload = {
                    "kind": PORTABLE_AMBIGUITY_KIND, "provider": "home_assistant",
                    "package_kind": AMBIGUITY_PACKAGE, "locale": locale,
                    "metadata": {"name": "Generated ambiguities", "publisher": "eve"},
                    "entry": entry,
                }
                if previous is None:
                    connection.execute(
                        """INSERT INTO memory_claims
                           (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                            lifecycle,verification_policy,created_at,updated_at)
                           VALUES (?,'opaque_fact',?,?,?,?,?,'active','configuration',?,?)""",
                        (claim_id, scope, canonical, f"ha_ambiguity:{entry['id']}",
                         "collision:" + " · ".join(entry["surfaces"]), _json(payload), now, now),
                    )
                else:
                    connection.execute(
                        """UPDATE memory_claims SET display_text=?,payload_json=?,lifecycle='active',
                           valid_until=NULL,verification_policy='configuration',updated_at=?
                           WHERE id=?""",
                        ("collision:" + " · ".join(entry["surfaces"]),
                         _json(payload), now, claim_id),
                    )
            generated_prefix = "training:home_assistant:ambiguities:%:eve:generated:%"
            for row in connection.execute(
                """SELECT id,canonical_key FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND canonical_key LIKE ?""", (scope, generated_prefix),
            ).fetchall():
                if row["canonical_key"] not in active:
                    connection.execute(
                        "UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=? WHERE id=?",
                        (now, now, row["id"]),
                    )
        return {"active": len(entries), "locale": locale}

    def ambiguity_hints(
        self, query: str, provider: dict, *, locale="de", limit: int | None = None
    ) -> list[dict]:
        """Publish grounded ambiguity records; the model decides applicability."""
        language_scope = _language_scope(provider, str(locale or "de"))
        inventory_scope = _inventory_scope(provider)
        with self.database.connect() as connection:
            available = {
                str(row["domain"]) for row in connection.execute(
                    """SELECT DISTINCT json_extract(profile.payload_json,'$.domain') domain
                       FROM memory_relations relation
                       JOIN memory_claims binding ON binding.id=relation.from_claim_id
                       JOIN memory_claims profile ON profile.id=relation.to_claim_id
                       WHERE relation.relation_type='refines'
                       AND binding.scope=? AND binding.lifecycle='active'
                       AND binding.claim_kind='provider_binding'
                       AND profile.scope=? AND profile.lifecycle='active'
                       AND json_extract(profile.payload_json,'$.kind')=?""",
                    (inventory_scope, language_scope, LANGUAGE_KIND),
                ).fetchall() if row["domain"]
            }
        result = []
        for entry in self.portable_ambiguities(locale):
            options = [item for item in entry.get("options", []) if item.get("domain") in available]
            if len(options) > 1:
                result.append({**entry, "options": options})
            if limit is not None and len(result) >= max(0, int(limit)):
                break
        return result

    @lifecycle_operation("memory.home_assistant", "language_profile_sync")
    def sync_language_profiles(self, provider: dict, records: list[dict], *, locale="de") -> dict:
        """Activate only profiles grounded by domains and services in this inventory."""
        locale = str(locale or "de").strip().casefold()[:16] or "de"
        scope = _language_scope(provider, locale)
        domains = {
            str(item.get("provider_metadata", {}).get("domain") or "")
            for item in records if isinstance(item, dict)
        }
        services = {
            str(service)
            for item in records if isinstance(item, dict)
            for service in item.get("provider_metadata", {}).get("services", [])
            if isinstance(service, str)
        }
        properties_by_domain = {}
        for item in records:
            metadata = item.get("provider_metadata", {}) if isinstance(item, dict) else {}
            domain = str(metadata.get("domain") or "")
            if domain:
                properties_by_domain.setdefault(domain, set()).update(
                    str(name) for name in metadata.get("properties", [])
                    if isinstance(name, str)
                )
        selected = []
        for profile in self.portable_language_profiles(locale):
            domain = str(profile.get("domain") or "").strip().casefold()
            if not domain or domain not in domains:
                continue
            native_operations = {"get_state"}
            if domain == "camera":
                native_operations.add("get_camera_snapshot")
            if domain == "calendar":
                native_operations.add("get_calendar_events")
            native_operations.update(
                f"get_property.{name}" for name in properties_by_domain.get(domain, set())
            )
            actions = {
                name: details for name, details in (profile.get("actions") or {}).items()
                if name in native_operations or name in services
            }
            selected.append({
                "domain": domain,
                "surfaces": list(profile.get("surfaces") or []),
                "actions": actions,
                "properties": dict(profile.get("properties") or {}),
                "parameters": dict(profile.get("parameters") or {}),
                "locale": locale,
                "source_version": str(profile.get("source_version") or "ha-language-v1"),
            })
        now = _now()
        seen = set()
        created = updated = unchanged = retired = 0
        with self.database.connect() as connection:
            existing = {
                row["canonical_key"]: row for row in connection.execute(
                    """SELECT * FROM memory_claims WHERE scope=?
                       AND json_extract(payload_json,'$.kind')=?""",
                    (scope, LANGUAGE_KIND),
                ).fetchall()
            }
            for profile in selected:
                canonical = f"home_assistant_language:{locale}:{profile['domain']}"
                seen.add(canonical)
                claim_id = uuid.uuid5(_NAMESPACE, f"{scope}:{canonical}").hex
                payload = {
                    "kind": LANGUAGE_KIND,
                    "provider": "home_assistant",
                    "endpoint_fingerprint": _endpoint_hash(provider),
                    **profile,
                }
                surfaces = " · ".join(_safe_text(item) for item in profile["surfaces"])
                action_words = " · ".join(
                    _safe_text(surface)
                    for details in profile["actions"].values()
                    for surface in (details.get("surfaces") or [])
                )
                display = (
                    f"Home-Assistant-Sprachprofil {profile['domain']}: {surfaces}"
                    + (f" · Aktionen: {action_words}" if action_words else "")
                )
                encoded = _json(payload)
                previous = existing.get(canonical)
                if previous is None:
                    connection.execute(
                        """INSERT INTO memory_claims
                           (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                            lifecycle,verification_policy,created_at,updated_at)
                           VALUES (?,'opaque_fact',?,?,?,?,?,'active','configuration',?,?)""",
                        (claim_id, scope, canonical, f"ha_language:{locale}:{profile['domain']}",
                         display, encoded, now, now),
                    )
                    created += 1
                elif (previous["display_text"] != display or previous["payload_json"] != encoded
                      or previous["lifecycle"] != "active"):
                    connection.execute(
                        """UPDATE memory_claims SET display_text=?,payload_json=?,lifecycle='active',
                           valid_until=NULL,updated_at=? WHERE id=?""",
                        (display, encoded, now, previous["id"]),
                    )
                    updated += 1
                else:
                    unchanged += 1
            for canonical, previous in existing.items():
                if canonical in seen or previous["lifecycle"] != "active":
                    continue
                connection.execute(
                    """UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=?
                       WHERE id=?""", (now, now, previous["id"]),
                )
                retired += 1
            relations = self._ground_language_profiles(connection, provider, locale, now)
        return {
            "scope": scope, "locale": locale, "active": len(selected),
            "created": created, "updated": updated, "unchanged": unchanged,
            "retired": retired,
            "relations": relations,
        }

    def refresh_language_profiles(self, provider: dict, *, locale="de") -> dict:
        """Re-ground portable profiles using only already persisted inventory facts."""
        inventory_scope = _inventory_scope(provider)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND claim_kind='provider_binding'
                   AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                   ORDER BY canonical_key,id""", (inventory_scope,),
            ).fetchall()
        records = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            metadata = payload.get("provider_metadata")
            if isinstance(metadata, dict):
                records.append({"provider_metadata": metadata})
        return self.sync_language_profiles(provider, records, locale=locale)

    def language_hints(
        self, query: str, provider: dict, *, locale="de", limit: int | None = None
    ) -> list[dict]:
        """Publish a compact grounded domain catalogue without interpreting the utterance."""
        scope = _language_scope(provider, str(locale or "de"))
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.kind')=? ORDER BY canonical_key,id""",
                (scope, LANGUAGE_KIND),
            ).fetchall()
            grounded = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                relations = connection.execute(
                    """SELECT r.id,binding.id claim_id FROM memory_relations r
                       JOIN memory_claims binding ON binding.id=r.from_claim_id
                       WHERE r.to_claim_id=? AND r.relation_type='refines'
                       AND binding.scope=? AND binding.lifecycle='active'
                       AND binding.claim_kind='provider_binding'
                       AND json_extract(binding.payload_json,'$.inventory_source')='home_assistant'
                       ORDER BY r.id""",
                    (row["id"], _inventory_scope(provider)),
                ).fetchall()
                if not relations:
                    continue
                grounded.append({
                    "claim_id": row["id"],
                    "domain": payload.get("domain"),
                    "surfaces": payload.get("surfaces") or [],
                    "property_names": sorted((payload.get("properties") or {}).keys()),
                    "locale": payload.get("locale"),
                    "grounding_relation_ids": [item["id"] for item in relations],
                    "grounded_entity_claim_ids": [item["claim_id"] for item in relations],
                    "grounded_entity_count": len(relations),
                })
        return grounded if limit is None else grounded[:max(0, int(limit))]

    def language_profile(self, domain: str, provider: dict, *, locale="de") -> dict | None:
        """Load one model-selected domain profile by exact technical identity."""
        domain = str(domain or "").strip().casefold()
        if not domain:
            return None
        scope = _language_scope(provider, str(locale or "de"))
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.kind')=?
                   AND json_extract(payload_json,'$.domain')=?
                   ORDER BY canonical_key,id LIMIT 1""",
                (scope, LANGUAGE_KIND, domain),
            ).fetchone()
            if row is None:
                return None
            relations = connection.execute(
                """SELECT r.id,binding.id claim_id FROM memory_relations r
                   JOIN memory_claims binding ON binding.id=r.from_claim_id
                   WHERE r.to_claim_id=? AND r.relation_type='refines'
                   AND binding.scope=? AND binding.lifecycle='active'
                   AND binding.claim_kind='provider_binding'
                   AND json_extract(binding.payload_json,'$.inventory_source')='home_assistant'
                   ORDER BY r.id""",
                (row["id"], _inventory_scope(provider)),
            ).fetchall()
            if not relations:
                return None
            payload = json.loads(row["payload_json"])
        return {
            "claim_id": row["id"],
            **{
                key: value for key, value in payload.items()
                if key in {"domain", "surfaces", "actions", "properties", "parameters", "locale"}
            },
            "grounding_relation_ids": [item["id"] for item in relations],
            "grounded_entity_claim_ids": [item["claim_id"] for item in relations],
            "grounded_entity_count": len(relations),
        }

    def areas(self, provider: dict) -> list[dict]:
        scope = _inventory_scope(provider)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT json_extract(payload_json,'$.provider_metadata.area') area,
                          count(*) entity_count,
                          count(DISTINCT json_extract(payload_json,'$.provider_metadata.domain')) domain_count
                   FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND claim_kind='provider_binding'
                   AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                   AND json_extract(payload_json,'$.provider_metadata.area') IS NOT NULL
                   GROUP BY area ORDER BY area COLLATE NOCASE""",
                (scope,),
            ).fetchall()
        return [dict(row) for row in rows]

    def aggregate_policy(self, provider: dict) -> dict:
        scope = _policy_scope(provider)
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.kind')=?
                   ORDER BY updated_at DESC,id DESC LIMIT 1""",
                (scope, POLICY_KIND),
            ).fetchone()
        if row is None:
            return {
                "claim_id": None, "excluded_areas": [], "effects": ["write"],
                "explicit_targets_override": True, "version": 0,
            }
        payload = json.loads(row["payload_json"])
        return {
            "claim_id": row["id"],
            "excluded_areas": list(payload.get("excluded_areas") or []),
            "effects": list(payload.get("effects") or ["write"]),
            "explicit_targets_override": bool(payload.get("explicit_targets_override", True)),
            "version": int(payload.get("version") or 1),
            "updated_at": row["updated_at"],
        }

    def overview(self, provider: dict) -> dict:
        policy = self.aggregate_policy(provider)
        areas = self.areas(provider)
        known = {item["area"] for item in areas}
        return {
            "policy": policy,
            "areas": [
                {**item, "excluded": item["area"] in set(policy["excluded_areas"])}
                for item in areas
            ],
            "unknown_excluded_areas": sorted(set(policy["excluded_areas"]) - known),
            "semantics": {
                "applies_to": "implicit_aggregate_write",
                "explicit_area_command_overrides": True,
                "storage": "memory_v2",
            },
        }

    @lifecycle_operation("memory.home_assistant", "aggregate_policy_update")
    def set_aggregate_policy(self, provider: dict, excluded_areas: list[str], *,
                             source_ref="ui:home-assistant-policy") -> dict:
        if not isinstance(excluded_areas, list) or any(
            not isinstance(item, str) or not item.strip() or len(item.strip()) > 300
            for item in excluded_areas
        ):
            raise ValueError("Bereichsausschlüsse müssen eine Liste vorhandener Areas sein")
        canonical_areas = {item["area"].casefold(): item["area"] for item in self.areas(provider)}
        requested = []
        for item in excluded_areas:
            key = item.strip().casefold()
            if key not in canonical_areas:
                raise ValueError(f"Unbekannte Home-Assistant-Area: {item.strip()}")
            if canonical_areas[key] not in requested:
                requested.append(canonical_areas[key])
        requested.sort(key=str.casefold)
        current = self.aggregate_policy(provider)
        if requested == current["excluded_areas"]:
            return {**self.overview(provider), "status": "unchanged"}
        now = _now()
        scope = _policy_scope(provider)
        version = int(current.get("version") or 0) + 1
        claim_id = str(uuid.uuid4())
        observation_id = str(uuid.uuid4())
        payload = {
            "kind": POLICY_KIND,
            "provider": "home_assistant",
            "endpoint_fingerprint": _endpoint_hash(provider),
            "excluded_areas": requested,
            "effects": ["write"],
            "explicit_targets_override": True,
            "confirmation": "user_configured",
            "version": version,
            "source_ref": source_ref,
        }
        display = (
            "Home Assistant: Nicht ausdrücklich benannte Sammel-Schreibaufträge schließen "
            + (", ".join(requested) if requested else "keine Areas") + " aus."
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,external_ref,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'user','external',?,?,?,?,?,?,?)""",
                (observation_id, source_ref, display, _json({"excluded_areas": requested}),
                 now, scope, _json({"producer": "home_assistant.policy_ui"}), now),
            )
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                    lifecycle,verification_policy,created_at,updated_at)
                   VALUES (?,'opaque_fact',?,?,?,?,?,'active','configuration',?,?)""",
                (claim_id, scope, f"home_assistant_aggregate_policy:{version}:{claim_id}",
                 "home_assistant:aggregate_scope_policy", display, _json(payload), now, now),
            )
            evidence_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_ref,payload_json,
                    observed_at,created_at)
                   VALUES (?,?,?,'supports','user_configured_policy',?,?,?,?)""",
                (evidence_id, claim_id, observation_id, source_ref,
                 _json({"excluded_areas": requested}), now, now),
            )
            previous = current.get("claim_id")
            if previous:
                connection.execute(
                    """UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=?
                       WHERE id=? AND lifecycle='active'""", (now, now, previous),
                )
                connection.execute(
                    """INSERT INTO memory_relations
                       (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
                       VALUES (?,?,?,'supersedes',?,?)""",
                    (str(uuid.uuid4()), claim_id, previous, evidence_id, now),
                )
        return {**self.overview(provider), "status": "stored"}

    def apply_aggregate_policy(self, provider: dict, bindings: list[dict], *,
                               effect: str, explicit_target: bool) -> dict:
        policy = self.aggregate_policy(provider)
        excluded = set(policy["excluded_areas"])
        applies = effect in policy["effects"] and not explicit_target and bool(excluded)
        kept, removed = [], []
        for item in bindings:
            if applies and item.get("area") in excluded:
                removed.append(item)
            else:
                kept.append(item)
        return {
            "bindings": kept,
            "excluded": removed,
            "policy": policy,
            "applied": applies,
        }
