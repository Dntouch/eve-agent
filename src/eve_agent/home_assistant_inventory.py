"""Provider-grounded, read-only Home Assistant inventory persisted in Memory V2.

This module copies technical facts published by Home Assistant into structured
claims.  It deliberately contains no language-to-device mappings and never
calls a Home Assistant service.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from .memory import redact_sensitive
from .memory_lifecycle import lifecycle_operation
from .home_assistant_memory import HomeAssistantMemory


_NAMESPACE = uuid.UUID("fc3aacdc-55ba-48ea-9902-f4070f6bfd89")
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, limit: int = 300) -> str:
    return redact_sensitive(str(value or "").strip())[:limit]


def _entity_id(value) -> str | None:
    """Validate provider identities without treating long object IDs as credentials."""
    candidate = str(value or "").strip().casefold()
    if len(candidate) > 512 or not _ENTITY_ID.fullmatch(candidate):
        return None
    return candidate


class HomeAssistantInventory:
    """Synchronize provider-published entity structure into productive memory."""

    capability_name = "home_assistant_inventory"

    def __init__(self, home_assistant, database):
        self.home_assistant = home_assistant
        self.database = database
        self._scan_lock = threading.Lock()
        self.home_assistant_memory = HomeAssistantMemory(database)

    @property
    def configured(self) -> bool:
        return bool(self.home_assistant and self.home_assistant.configured)

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "home_assistant.inventory",
            "home_assistant.inventory",
            "Ich kann den verbundenen Home Assistant rein lesend inventarisieren und seine "
            "veröffentlichten Entitäten als belegtes technisches Wissen in Memory aktualisieren.",
            "HomeAssistantInventory",
            "scan",
        )]

    def minimal_contract(self) -> dict:
        return {
            "description": (
                "Home Assistant rein lesend inventarisieren und die vom Provider veröffentlichten "
                "Entitäten, Namen, Areas und technischen Fähigkeiten als belegtes Wissen in "
                "Memory V2 aktualisieren. Für natürliche Aufträge, Home Assistant kennenzulernen, "
                "Entitäten zu entdecken, eine Inventur zu erstellen oder Änderungen neu einzulesen."
            ),
            "operations": {
                "scan": {
                    "effect": "read",
                    "parameters_schema": {"type": "object", "maxProperties": 0},
                },
            },
        }

    def execute_operation(self, operation: str, parameters: dict) -> dict:
        if operation != "scan" or parameters:
            raise ValueError("Nicht veröffentlichte Home-Assistant-Inventur-Operation")
        result = self.run()
        counts = result["counts"]
        answer = (
            "Die Home-Assistant-Inventur ist abgeschlossen. "
            f"{counts['total']} Entitäten sind im Memory erfasst; "
            f"{counts['created']} neu, {counts['updated']} geändert, "
            f"{counts['retired']} nicht mehr vorhanden und {counts['unavailable']} nicht verfügbar."
        )
        return {"answer": answer, "result": result}

    @lifecycle_operation("home_assistant.inventory", "provider_inventory_scan")
    def run(self) -> dict:
        with self._scan_lock:
            return self._run()

    def _run(self) -> dict:
        if not self.configured:
            raise RuntimeError("Home Assistant ist nicht konfiguriert")
        published = self.home_assistant.inventory_catalog()
        entities = published.get("entities") if isinstance(published, dict) else None
        if not isinstance(entities, list):
            raise RuntimeError("Home Assistant lieferte keinen gültigen Entitätskatalog")

        observed_at = _now()
        snapshot_id = uuid.uuid4().hex
        provider = self.home_assistant.semantic_provider_identity()
        endpoint_hash = hashlib.sha256(
            str(provider.get("endpoint") or "").encode("utf-8")
        ).hexdigest()[:16]
        scope = f"provider:home-assistant:{endpoint_hash}"
        observation_id = uuid.uuid4().hex
        decision_id = uuid.uuid4().hex
        records_by_reference = {}
        unavailable = 0
        skipped = 0
        for item in entities:
            record = self._record(item)
            if record is None:
                skipped += 1
                continue
            reference = record["external_reference"]
            if reference in records_by_reference:
                skipped += 1
                continue
            unavailable += int(record["provider_metadata"].get("availability") == "unavailable")
            records_by_reference[reference] = record
        records = list(records_by_reference.values())
        records.sort(key=lambda item: item["external_reference"])

        created = updated = unchanged = restored = retired = 0
        seen_claim_ids = set()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,external_ref,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'provider','provider_result',?,?,?,?,?,?)""",
                (
                    observation_id, f"home-assistant-inventory:{snapshot_id}",
                    _json({"snapshot_id": snapshot_id, "entity_count": len(records)}),
                    observed_at, scope,
                    _json({"producer": "home_assistant.inventory", "effect": "read"}),
                    observed_at,
                ),
            )
            connection.execute(
                """INSERT INTO memory_learning_decisions
                   (id,observation_id,decision_type,method,policy_version,rationale,
                    metadata_json,uncertainty,created_at)
                   VALUES (?,?,'create_active','provider_inventory','ha-inventory-v1',?,?,0,?)""",
                (
                    decision_id, observation_id,
                    "Direkt vom verbundenen Home-Assistant-Provider veröffentlichte Struktur.",
                    _json({"snapshot_id": snapshot_id, "effect": "read"}), observed_at,
                ),
            )
            existing = {
                row["id"]: row for row in connection.execute(
                    """SELECT id,slot_key,display_text,payload_json,lifecycle FROM memory_claims
                       WHERE scope=? AND claim_kind='provider_binding'
                       AND json_extract(payload_json,'$.inventory_source')='home_assistant'""",
                    (scope,),
                ).fetchall()
            }
            replaced = connection.execute(
                """SELECT id FROM memory_claims
                   WHERE scope<>? AND claim_kind='provider_binding' AND lifecycle='active'
                   AND json_extract(payload_json,'$.inventory_source')='home_assistant'""",
                (scope,),
            ).fetchall()
            for previous in replaced:
                claim_id = previous["id"]
                connection.execute(
                    """UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=?
                       WHERE id=?""",
                    (observed_at, observed_at, claim_id),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO memory_learning_decision_claims
                       (decision_id,claim_id) VALUES (?,?)""",
                    (decision_id, claim_id),
                )
                retired += 1
            for record in records:
                canonical = (
                    f"home_assistant_inventory:{endpoint_hash}:"
                    f"{record['external_reference']}"
                )
                claim_id = uuid.uuid5(_NAMESPACE, canonical).hex
                seen_claim_ids.add(claim_id)
                payload = {
                    "provider": "home_assistant",
                    "subject": record["subject"],
                    "property": "resource",
                    "external_reference": record["external_reference"],
                    "inventory_source": "home_assistant",
                    "provider_metadata": record["provider_metadata"],
                }
                display = self._display(record)
                encoded = _json(payload)
                previous = existing.get(claim_id)
                slot = (
                    "provider_binding:home_assistant:"
                    + hashlib.sha256(record["external_reference"].encode("utf-8")).hexdigest()[:20]
                    + ":resource"
                )
                if previous is None:
                    connection.execute(
                        """INSERT INTO memory_claims
                           (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                            lifecycle,verification_policy,created_at,updated_at)
                           VALUES (?,'provider_binding',?,?,?,?,?,'active','configuration',?,?)""",
                        (claim_id, scope, canonical, slot, display, encoded, observed_at, observed_at),
                    )
                    created += 1
                elif (previous["slot_key"] != slot
                      or previous["display_text"] != display or previous["payload_json"] != encoded
                      or previous["lifecycle"] != "active"):
                    connection.execute(
                        """UPDATE memory_claims SET slot_key=?,display_text=?,payload_json=?,
                           lifecycle='active',valid_until=NULL,updated_at=? WHERE id=?""",
                        (slot, display, encoded, observed_at, claim_id),
                    )
                    if previous["lifecycle"] == "active":
                        updated += 1
                    else:
                        restored += 1
                else:
                    unchanged += 1
                evidence_id = uuid.uuid5(
                    _NAMESPACE, f"{snapshot_id}:{claim_id}:provider_inventory"
                ).hex
                connection.execute(
                    """INSERT INTO memory_evidence
                       (id,claim_id,observation_id,stance,evidence_type,source_ref,
                        payload_json,observed_at,created_at)
                       VALUES (?,?,?,'supports','provider_inventory',?,?,?,?)""",
                    (
                        evidence_id, claim_id, observation_id,
                        f"home-assistant-inventory:{snapshot_id}",
                        _json({"external_reference": record["external_reference"]}),
                        observed_at, observed_at,
                    ),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO memory_learning_decision_claims
                       (decision_id,claim_id) VALUES (?,?)""",
                    (decision_id, claim_id),
                )
            for claim_id, previous in existing.items():
                if claim_id in seen_claim_ids or previous["lifecycle"] != "active":
                    continue
                connection.execute(
                    """UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=?
                       WHERE id=?""",
                    (observed_at, observed_at, claim_id),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO memory_learning_decision_claims
                       (decision_id,claim_id) VALUES (?,?)""",
                    (decision_id, claim_id),
                )
                retired += 1

        domains = {}
        areas = {}
        for record in records:
            metadata = record["provider_metadata"]
            domain = metadata["domain"]
            domains[domain] = domains.get(domain, 0) + 1
            area = metadata.get("area")
            if area:
                areas[area] = areas.get(area, 0) + 1
        language = self.home_assistant_memory.sync_language_profiles(
            provider, records,
            locale=str(getattr(self.home_assistant, "config", {}).get("language", "de")),
        )
        return {
            "status": "completed",
            "effect": "read",
            "snapshot_id": snapshot_id,
            "observed_at": observed_at,
            "counts": {
                "total": len(records), "created": created, "updated": updated,
                "unchanged": unchanged, "restored": restored, "retired": retired,
                "unavailable": unavailable, "skipped": skipped,
            },
            "domains": dict(sorted(domains.items())),
            "areas": dict(sorted(areas.items())),
            "language_profiles": language,
        }

    @staticmethod
    def _record(item) -> dict | None:
        if not isinstance(item, dict):
            return None
        entity_id = _entity_id(item.get("entity_id"))
        if entity_id is None:
            return None
        domain = entity_id.split(".", 1)[0]
        name = _text(item.get("name"), 300) or entity_id
        metadata = {
            "domain": domain,
            "name": name,
            "area": _text(item.get("area"), 300) or None,
            "device_class": _text(item.get("device_class"), 120) or None,
            "unit": _text(item.get("unit"), 80) or None,
            "state_class": _text(item.get("state_class"), 120) or None,
            "availability": (
                "unavailable" if str(item.get("state") or "").casefold() == "unavailable"
                else "unknown" if str(item.get("state") or "").casefold() == "unknown"
                else "available"
            ),
            "supported_features": (
                int(item["supported_features"])
                if type(item.get("supported_features")) is int else None
            ),
            "services": sorted({
                _text(service, 200) for service in item.get("services", [])
                if isinstance(service, str) and _text(service, 200)
            }),
            "service_fields": {
                service: sorted({
                    _text(field, 120) for field in fields
                    if isinstance(field, str) and _text(field, 120)
                })
                for service, fields in (item.get("service_fields") or {}).items()
                if isinstance(service, str) and isinstance(fields, list)
            },
            "properties": sorted({
                _text(name, 160) for name in item.get("properties", [])
                if isinstance(name, str) and _text(name, 160)
            }),
            "members": sorted({
                member for member in (
                    _entity_id(value) for value in item.get("members", [])
                    if isinstance(value, str)
                ) if member is not None
            }),
        }
        return {
            "subject": name,
            "external_reference": entity_id,
            "provider_metadata": metadata,
        }

    @staticmethod
    def _display(record: dict) -> str:
        metadata = record["provider_metadata"]
        details = [metadata["domain"]]
        if metadata.get("area"):
            details.append(f"Area {metadata['area']}")
        if metadata.get("device_class"):
            details.append(f"Klasse {metadata['device_class']}")
        if metadata.get("unit"):
            details.append(f"Einheit {metadata['unit']}")
        return (
            f"Home Assistant veröffentlicht „{record['subject']}“ "
            f"({record['external_reference']}) · " + " · ".join(details) + "."
        )
