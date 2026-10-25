"""Portable, provider-grounded EVE training packages.

The package envelope, integrity rules, import lifecycle and adapter registry
are provider independent. Provider adapters define the entry vocabulary and
ground generic knowledge against local capabilities. Packages never carry a
provider endpoint, concrete resource id, local area, device name, state,
credential, or action authorization.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Protocol

from .memory import redact_sensitive
from .memory_lifecycle import lifecycle_operation


FORMAT = "eve-training-package-v1"
LANGUAGE_PACKAGE = "language"
AMBIGUITY_PACKAGE = "ambiguities"
PORTABLE_LANGUAGE_KIND = "portable_training_language_profile"
PORTABLE_AMBIGUITY_KIND = "portable_training_ambiguity_profile"
_NAMESPACE = uuid.UUID("b967c960-c12f-45aa-9c86-f2f5cf75ddeb")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_DOMAIN = re.compile(r"^[a-z0-9_]{1,64}$")
_OPERATION = re.compile(
    r"^(?:get_state|get_camera_snapshot|get_calendar_events|"
    r"get_property\.[a-z0-9_]{1,64}|[a-z0-9_]{1,64}\.[a-z0-9_]{1,64})$"
)
_PRIVATE_KEY = re.compile(
    r"(^|_)(entity|entity_id|external_reference|endpoint|endpoint_fingerprint|area|"
    r"device|device_id|token|secret|password|credential|state|user|person|coordinates?)($|_)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: dict) -> str:
    unsigned = {key: item for key, item in value.items() if key not in {"integrity", "signature"}}
    return hashlib.sha256(_json(unsigned).encode("utf-8")).hexdigest()


def _text(value, *, limit=300, field="Text") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} fehlt")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{field} ist zu lang")
    redacted = redact_sensitive(value)
    if redacted != value or "[REDACTED]" in redacted:
        raise ValueError(f"{field} enthält möglicherweise ein Geheimnis")
    return value


def _strings(value, *, field, maximum=96, limit=160) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise ValueError(f"{field} muss eine nicht leere, begrenzte Liste sein")
    result = []
    for item in value:
        item = _text(item, limit=limit, field=field)
        if item not in result:
            result.append(item)
    return result


def _surface_map(value, *, field) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 96:
        raise ValueError(f"{field} muss ein begrenztes Objekt sein")
    result = {}
    for key, surfaces in value.items():
        key = _text(key, limit=128, field=f"{field}-Schlüssel")
        if _PRIVATE_KEY.search(key):
            raise ValueError(f"{field} enthält ein privates Feld")
        result[key] = _strings(surfaces, field=f"{field}.{key}")
    return result


class TrainingProviderAdapter(Protocol):
    """Small extension contract for existing and future EVE providers."""

    provider_id: str

    def overview(self, *, locale="de") -> dict: ...
    def preview(self, payload: dict) -> dict: ...
    def import_package(self, payload: dict) -> dict: ...
    def export(self, kind: str, *, locale="de", entry_ids=None) -> dict: ...
    def train(self, *, refresh_inventory=False, locale="de") -> dict: ...


class HomeAssistantTrainingAdapter:
    """Home Assistant adapter for the provider-independent package lifecycle."""

    provider_id = "home_assistant"

    def __init__(self, database, memory, *, home_assistant=None, inventory=None):
        self.database = database
        self.memory = memory
        self.home_assistant = home_assistant
        self.inventory = inventory

    @staticmethod
    def _metadata(payload: dict) -> dict:
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict) or set(metadata) - {
            "name", "version", "publisher", "license", "description", "homepage",
        }:
            raise ValueError("Paket-Metadaten enthalten nicht veröffentlichte Felder")
        return {
            key: _text(value, limit=500 if key == "description" else 200, field=key)
            for key, value in metadata.items()
        }

    @staticmethod
    def _language_entry(raw: dict) -> dict:
        allowed = {"id", "domain", "surfaces", "actions", "properties", "parameters", "source_version"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("Sprachprofil enthält nicht veröffentlichte Felder")
        entry_id = _text(raw.get("id"), limit=128, field="Profil-ID").casefold()
        domain = _text(raw.get("domain"), limit=64, field="Domain").casefold()
        if not _ID.fullmatch(entry_id) or not _DOMAIN.fullmatch(domain):
            raise ValueError("Profil-ID oder Domain ist ungültig")
        actions = raw.get("actions") or {}
        if not isinstance(actions, dict) or len(actions) > 96:
            raise ValueError("Aktionen müssen ein begrenztes Objekt sein")
        normalized_actions = {}
        for operation, definition in actions.items():
            operation = _text(operation, limit=130, field="Operation").casefold()
            if not _OPERATION.fullmatch(operation) or not isinstance(definition, dict) \
                    or "surfaces" not in definition or set(definition) - {"surfaces", "effect"}:
                raise ValueError("Aktion entspricht nicht dem portablen Vertrag")
            normalized_action = {
                "surfaces": _strings(definition["surfaces"], field=f"Aktion {operation}")
            }
            if definition.get("effect") is not None:
                effect = _text(definition.get("effect"), limit=16, field="Wirkung").casefold()
                if effect not in {"read", "write"}:
                    raise ValueError("Aktion enthält eine ungültige Wirkung")
                normalized_action["effect"] = effect
            normalized_actions[operation] = normalized_action
        return {
            "id": entry_id,
            "domain": domain,
            "surfaces": _strings(raw.get("surfaces"), field="Bezeichnungen"),
            "actions": normalized_actions,
            "properties": _surface_map(raw.get("properties"), field="Eigenschaften"),
            "parameters": _surface_map(raw.get("parameters"), field="Parameter"),
            "source_version": str(raw.get("source_version") or "community-v1")[:128],
        }

    @staticmethod
    def _ambiguity_entry(raw: dict) -> dict:
        allowed = {"id", "surfaces", "options", "question", "note"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("Mehrdeutigkeit enthält nicht veröffentlichte Felder")
        entry_id = _text(raw.get("id"), limit=128, field="Mehrdeutigkeits-ID").casefold()
        if not _ID.fullmatch(entry_id):
            raise ValueError("Mehrdeutigkeits-ID ist ungültig")
        options = raw.get("options")
        if not isinstance(options, list) or len(options) < 2 or len(options) > 64:
            raise ValueError("Mehrdeutigkeit benötigt zwei bis vierundsechzig Optionen")
        normalized_options = []
        for option in options:
            if not isinstance(option, dict) or set(option) - {"domain", "operations", "meaning"}:
                raise ValueError("Mehrdeutigkeitsoption ist ungültig")
            domain = _text(option.get("domain"), limit=64, field="Options-Domain").casefold()
            if not _DOMAIN.fullmatch(domain):
                raise ValueError("Options-Domain ist ungültig")
            operations = _strings(option.get("operations"), field="Options-Aktionen", maximum=32, limit=130)
            if any(not _OPERATION.fullmatch(item.casefold()) for item in operations):
                raise ValueError("Mehrdeutigkeit enthält eine ungültige Operation")
            normalized_option = {
                "domain": domain,
                "operations": [item.casefold() for item in operations],
            }
            if option.get("meaning") is not None:
                normalized_option["meaning"] = _text(
                    option.get("meaning"), limit=300, field="Bedeutung",
                )
            normalized_options.append(normalized_option)
        result = {
            "id": entry_id,
            "surfaces": _strings(raw.get("surfaces"), field="Mehrdeutige Ausdrücke"),
            "options": normalized_options,
        }
        if raw.get("question") is not None:
            result["question"] = _text(raw.get("question"), limit=500, field="Rückfrage")
        if raw.get("note") is not None:
            result["note"] = _text(raw.get("note"), limit=500, field="Notiz")
        return result

    def validate(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or set(payload) - {
            "format", "provider", "kind", "locale", "metadata", "entries", "integrity", "signature",
        }:
            raise ValueError("Trainingspaket enthält nicht veröffentlichte Felder")
        if payload.get("format") != FORMAT:
            raise ValueError("Unbekanntes Trainingspaket-Format")
        if payload.get("provider") != self.provider_id:
            raise ValueError("Trainingspaket gehört nicht zum Home-Assistant-Adapter")
        kind = str(payload.get("kind") or "")
        if kind not in {LANGUAGE_PACKAGE, AMBIGUITY_PACKAGE}:
            raise ValueError("Unbekannter Trainingspaket-Typ")
        locale = _text(payload.get("locale"), limit=16, field="Sprache").casefold()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", locale):
            raise ValueError("Ungültiger Sprachcode")
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > 500:
            raise ValueError("Trainingspaket benötigt 1 bis 500 Einträge")
        normalizer = self._language_entry if kind == LANGUAGE_PACKAGE else self._ambiguity_entry
        normalized = [normalizer(item) for item in entries]
        ids = [item["id"] for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("Trainingspaket enthält doppelte Eintrags-IDs")
        result = {
            "format": FORMAT, "provider": self.provider_id, "kind": kind, "locale": locale,
            "metadata": self._metadata(payload), "entries": normalized,
        }
        claimed = ((payload.get("integrity") or {}).get("sha256")
                   if isinstance(payload.get("integrity"), dict) else None)
        if claimed is not None and claimed != _digest(result):
            raise ValueError("Prüfsumme des Trainingspakets stimmt nicht")
        result["integrity"] = {"sha256": _digest(result)}
        signature = payload.get("signature")
        if signature is not None:
            if not isinstance(signature, dict) or set(signature) - {"algorithm", "key_id", "value"}:
                raise ValueError("Paketsignatur ist ungültig")
            result["signature"] = {
                key: _text(value, limit=4096 if key == "value" else 200, field="Signatur")
                for key, value in signature.items()
            }
        return result

    @staticmethod
    def _canonical(package: dict, entry: dict) -> str:
        publisher = package["metadata"].get("publisher", "anonymous").casefold()
        package_name = package["metadata"].get("name", "unnamed").casefold()
        return (
            f"training:{package['provider']}:{package['kind']}:{package['locale']}:"
            f"{publisher}:{package_name}:{entry['id']}"
        )

    def preview(self, payload: dict) -> dict:
        package = self.validate(payload)
        scope = f"portable:training:{package['provider']}:{package['kind']}:{package['locale']}"
        existing = {}
        with self.database.connect() as connection:
            for entry in package["entries"]:
                canonical = self._canonical(package, entry)
                row = connection.execute(
                    """SELECT payload_json,lifecycle FROM memory_claims
                       WHERE scope=? AND claim_kind='opaque_fact' AND canonical_key=?""",
                    (scope, canonical),
                ).fetchone()
                existing[canonical] = row
        counts = {"new": 0, "updated": 0, "unchanged": 0}
        for entry in package["entries"]:
            row = existing[self._canonical(package, entry)]
            if row is None:
                counts["new"] += 1
                continue
            stored = json.loads(row["payload_json"])
            if stored.get("entry") == entry and row["lifecycle"] == "active":
                counts["unchanged"] += 1
            else:
                counts["updated"] += 1
        applicable_domains = self._applicable_domains()
        entry_domains = self._entry_domains(package)
        return {
            "valid": True, "format": FORMAT, "kind": package["kind"],
            "locale": package["locale"], "metadata": package["metadata"],
            "entry_count": len(package["entries"]), "changes": counts,
            "signature": "present_unverified" if package.get("signature") else "unsigned",
            "privacy": "generic_schema_validated",
            "applicable_domains": sorted(entry_domains & applicable_domains),
            "missing_domains": sorted(entry_domains - applicable_domains),
            "requires_provider_action": False,
        }

    def _applicable_domains(self) -> set[str]:
        with self.database.connect() as connection:
            return {
                str(row[0]) for row in connection.execute(
                    """SELECT DISTINCT json_extract(payload_json,'$.provider_metadata.domain')
                       FROM memory_claims WHERE lifecycle='active' AND claim_kind='provider_binding'
                       AND json_extract(payload_json,'$.inventory_source')='home_assistant'"""
                ).fetchall() if row[0]
            }

    @staticmethod
    def _entry_domains(package: dict) -> set[str]:
        if package["kind"] == LANGUAGE_PACKAGE:
            return {item["domain"] for item in package["entries"]}
        return {option["domain"] for item in package["entries"] for option in item["options"]}

    @lifecycle_operation("memory.home_assistant_training", "package_import")
    def import_package(self, payload: dict) -> dict:
        package = self.validate(payload)
        preview = self.preview(package)
        if preview["changes"]["unchanged"] == len(package["entries"]):
            return {
                **preview, "status": "unchanged",
                "digest": package["integrity"]["sha256"],
                "grounding": self.refresh_grounding(locale=package["locale"]),
            }
        now = _now()
        package_digest = package["integrity"]["sha256"]
        source_ref = f"ha-training-package:{package_digest}"
        kind = PORTABLE_LANGUAGE_KIND if package["kind"] == LANGUAGE_PACKAGE else PORTABLE_AMBIGUITY_KIND
        scope = f"portable:training:{package['provider']}:{package['kind']}:{package['locale']}"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            observation_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,external_ref,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'user','external',?,?,?,?,?,?,?)""",
                (observation_id, source_ref,
                 f"Importiertes {package['kind']}-Trainingspaket mit {len(package['entries'])} Einträgen.",
                 _json({"digest": package_digest, "metadata": package["metadata"]}),
                 now, scope, _json({"producer": "home_assistant.training_import"}), now),
            )
            for entry in package["entries"]:
                canonical = self._canonical(package, entry)
                previous = connection.execute(
                    """SELECT id FROM memory_claims
                       WHERE scope=? AND claim_kind='opaque_fact' AND canonical_key=?""",
                    (scope, canonical),
                ).fetchone()
                claim_id = previous["id"] if previous is not None else uuid.uuid5(
                    _NAMESPACE, f"{scope}:{canonical}"
                ).hex
                claim_payload = {
                    "kind": kind, "training_format": FORMAT,
                    "provider": package["provider"],
                    "package_kind": package["kind"], "locale": package["locale"],
                    "package_digest": package_digest, "metadata": package["metadata"],
                    "entry": entry,
                }
                display = (
                    f"Portables HA-Sprachprofil {entry['domain']}: " + " · ".join(entry["surfaces"])
                    if package["kind"] == LANGUAGE_PACKAGE else
                    "Portable HA-Mehrdeutigkeit: " + " · ".join(entry["surfaces"])
                )[:2000]
                if previous is None:
                    connection.execute(
                        """INSERT INTO memory_claims
                           (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                            lifecycle,verification_policy,created_at,updated_at)
                           VALUES (?,'opaque_fact',?,?,?,?,?,'active','configuration',?,?)""",
                        (claim_id, scope, canonical,
                         f"training:{package['provider']}:{package['kind']}:{entry['id']}",
                         display, _json(claim_payload), now, now),
                    )
                else:
                    connection.execute(
                        """UPDATE memory_claims SET display_text=?,payload_json=?,lifecycle='active',
                           valid_until=NULL,verification_policy='configuration',updated_at=?
                           WHERE id=?""",
                        (display, _json(claim_payload), now, claim_id),
                    )
                evidence_id = uuid.uuid5(_NAMESPACE, f"{canonical}:{package_digest}").hex
                connection.execute(
                    """INSERT OR IGNORE INTO memory_evidence
                       (id,claim_id,observation_id,stance,evidence_type,source_ref,payload_json,
                        observed_at,created_at) VALUES (?,?,?,'supports','training_package_import',?,?,?,?)""",
                    (evidence_id, claim_id, observation_id, source_ref,
                     _json({"digest": package_digest, "entry_id": entry["id"]}), now, now),
                )
        grounding = self.refresh_grounding(locale=package["locale"])
        return {**preview, "status": "imported", "digest": package_digest, "grounding": grounding}

    def refresh_grounding(self, *, locale="de") -> dict:
        if self.home_assistant is None:
            return {"status": "not_configured"}
        provider = self.home_assistant.semantic_provider_identity()
        return self.memory.refresh_language_profiles(provider, locale=locale)

    def train(self, *, refresh_inventory=False, locale="de") -> dict:
        inventory_result = None
        if refresh_inventory:
            if self.inventory is None or not self.inventory.configured:
                raise RuntimeError("Home Assistant ist nicht verbunden")
            inventory_result = self.inventory.run()
        grounding = self.refresh_grounding(locale=locale)
        ambiguities = self.memory.sync_generated_ambiguities(locale=locale)
        return {
            "status": "completed", "effect": "read",
            "inventory": inventory_result, "grounding": grounding,
            "ambiguities": ambiguities, "llm_requests": 0,
        }

    def export(self, kind: str, *, locale="de", entry_ids=None) -> dict:
        if kind == LANGUAGE_PACKAGE:
            entries = self.memory.portable_language_profiles(locale)
        elif kind == AMBIGUITY_PACKAGE:
            self.memory.sync_generated_ambiguities(locale=locale)
            entries = self.memory.portable_ambiguities(locale)
        else:
            raise ValueError("Unbekannter Trainingspaket-Typ")
        selected = {str(item).casefold() for item in (entry_ids or []) if str(item).strip()}
        if selected:
            entries = [item for item in entries if item["id"].casefold() in selected]
        if not entries:
            raise ValueError("Für diesen Export wurden keine Trainingsdaten gefunden")
        package = {
            "format": FORMAT, "provider": self.provider_id, "kind": kind, "locale": locale,
            "metadata": {
                "name": f"EVE Home Assistant {kind}", "version": _now()[:10],
                "publisher": "local-eve", "license": "CC0-1.0",
                "description": "Portables, generisches EVE-Memory-Training ohne Haushaltsidentitäten.",
            },
            "entries": entries,
        }
        package["integrity"] = {"sha256": _digest(package)}
        return package

    def overview(self, *, locale="de") -> dict:
        profiles = self.memory.portable_language_profiles(locale)
        ambiguities = self.memory.portable_ambiguities(locale)
        applicable = self._applicable_domains()
        return {
            "format": FORMAT, "provider": self.provider_id, "locale": locale,
            "language_profiles": len(profiles), "ambiguities": len(ambiguities),
            "applicable_profiles": sum(item["domain"] in applicable for item in profiles),
            "inventory_domains": sorted(applicable),
            "package_kinds": [LANGUAGE_PACKAGE, AMBIGUITY_PACKAGE],
            "export_entries": [
                {"id": item["id"], "kind": LANGUAGE_PACKAGE,
                 "label": " · ".join(item.get("surfaces", [])[:3]) or item["domain"]}
                for item in profiles
            ] + [
                {"id": item["id"], "kind": AMBIGUITY_PACKAGE,
                 "label": " · ".join(item.get("surfaces", [])[:3]) or item["id"]}
                for item in ambiguities
            ],
            "import_modes": ["preview", "apply_and_ground"],
            "privacy": "Provider-, Entity-, Area- und Zugangsdaten sind im Paketvertrag verboten.",
        }


class TrainingPackageManager:
    """Route portable package operations to explicit provider adapters.

    Adding a future provider requires an adapter with the same small contract;
    the web API, package envelope, integrity handling and Memory provenance do
    not change.
    """

    def __init__(self, adapters: list[TrainingProviderAdapter]):
        self.adapters = {
            adapter.provider_id: adapter for adapter in adapters
            if getattr(adapter, "provider_id", None)
        }

    def _adapter(self, provider: str):
        adapter = self.adapters.get(str(provider or "").strip().casefold())
        if adapter is None:
            raise ValueError("Für diesen Provider ist kein Trainingsadapter installiert")
        return adapter

    def providers(self) -> list[dict]:
        return [
            {"id": provider, "package_kinds": self.adapters[provider].overview().get(
                "package_kinds", [LANGUAGE_PACKAGE, AMBIGUITY_PACKAGE]
            )}
            for provider in sorted(self.adapters)
        ]

    def overview(self, provider: str | None = None, *, locale="de") -> dict:
        if provider:
            return self._adapter(provider).overview(locale=locale)
        return {
            "format": FORMAT,
            "providers": [
                self.adapters[item].overview(locale=locale) for item in sorted(self.adapters)
            ],
        }

    def preview(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Trainingspaket muss ein JSON-Objekt sein")
        return self._adapter(payload.get("provider")).preview(payload)

    def import_package(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Trainingspaket muss ein JSON-Objekt sein")
        return self._adapter(payload.get("provider")).import_package(payload)

    def export(self, provider: str, kind: str, *, locale="de", entry_ids=None) -> dict:
        return self._adapter(provider).export(kind, locale=locale, entry_ids=entry_ids)

    def train(self, provider: str, *, refresh_inventory=False, locale="de") -> dict:
        return self._adapter(provider).train(
            refresh_inventory=refresh_inventory, locale=locale,
        )
