"""Exact action experiences and causal dialog decisions in Memory V2.

Only the LLM assesses meaning and relevant context. This module validates
structured evidence, identities and state transitions; it never parses language.
"""
from __future__ import annotations

import json
import hashlib
import re
import time
import unicodedata
import uuid
from contextlib import nullcontext
from copy import deepcopy
from typing import Protocol
from .memory_lifecycle import lifecycle_operation, set_connection_lifecycle_origin
from .storage import _now, _safe_json

SCOPE = 'semantic_links'
ACTION_SCOPE = 'semantic_actions'
SIMILARITY_RELATION_SCOPE = 'semantic_similarity_relations'
LANGUAGE_RELATION_SCOPE = 'semantic_language_relations'
LINK_POLICY = 'llm_declared_equivalence_v1'
CONTEXT_KEYS = ('conversation_id', 'history', 'focus', 'pending', 'task_active')
POLICY = 'independent_resolved_plans_v1'
EXACT_REPLAY_POLICY = 'single_verified_execution_exact_utterance_v1'
SIMILARITY_POLICY = 'order_independent_structural_token_v2'
LANGUAGE_RELATION_POLICY = 'explicit_user_language_relations_v1'
MINIMUM_UNDECLARED_TOKEN_SIMILARITY = .5
ACTION_TARGET_POLICY = 'provider_binding_relations_v1'
ACTION_RESOURCE_POLICY = 'explicit_action_resource_relation_v1'
_RELATION_NAMESPACE = uuid.UUID('d989a9de-4c5c-4fb6-9402-65eaf7924edc')


def surface_tokens(text):
    """Formal Unicode word normalization without linguistic interpretation."""
    return re.findall(r'\w+', unicodedata.normalize('NFKC', str(text)).casefold())


def character_similarity(left, right):
    """Normalized Levenshtein similarity; this is not semantic confidence."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for index, left_character in enumerate(left, 1):
        current = [index]
        for right_index, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_character != right_character),
            ))
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def structural_token_variant(left, right):
    """Allow conservative changes inside one word, never shared suffixes alone."""
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 4:
        return False
    # Covers inflection and affixes (fahr/fahre, runter/herunter) while
    # rejecting different compounds that merely share a long ending such as
    # Waschmaschine/Spülmaschine. Semantic equivalence remains learnable via
    # an explicit positive relation.
    return shorter in longer or left[:4] == right[:4]


def _maximum_weight_pairs(left, right, score):
    """Return a deterministic maximum-weight one-to-one token assignment."""
    size = max(len(left), len(right))
    if not size:
        return [], 1.0
    weights = [[score(a, b) if i < len(left) and j < len(right) else 0.0
                for j, b in enumerate(right + [''] * (size - len(right)))]
               for i, a in enumerate(left + [''] * (size - len(left)))]
    # Hungarian assignment for minimum cost (1 - weight), O(n^3).
    u, v, p, way = [0.0] * (size + 1), [0.0] * (size + 1), [0] * (size + 1), [0] * (size + 1)
    for row in range(1, size + 1):
        p[0] = row
        minimum, used, column = [float('inf')] * (size + 1), [False] * (size + 1), 0
        while True:
            used[column] = True
            current_row, delta, next_column = p[column], float('inf'), 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                cost = 1.0 - weights[current_row - 1][candidate - 1] - u[current_row] - v[candidate]
                if cost < minimum[candidate]:
                    minimum[candidate], way[candidate] = cost, column
                if minimum[candidate] < delta:
                    delta, next_column = minimum[candidate], candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    u[p[candidate]] += delta
                    v[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if p[column] == 0:
                break
        while True:
            previous = way[column]
            p[column] = p[previous]
            column = previous
            if column == 0:
                break
    assignment = [0] * size
    for column in range(1, size + 1):
        if p[column]:
            assignment[p[column] - 1] = column - 1
    pairs = [dict(learned_token=left[row], input_token=right[column], similarity=weights[row][column])
             for row, column in enumerate(assignment) if row < len(left) and column < len(right)]
    return pairs, sum(weights[row][column] for row, column in enumerate(assignment)) / size


def identity(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def action_identity(plan):
    return identity({'effect': plan.get('effect'), 'actions': plan.get('actions')})


def authoritative_interpretation(payload):
    """Return whether an interpretation may block automatic corroboration."""
    return (payload.get('strong_semantic_evidence') is True
            or payload.get('confirmation') in {'confirmed', 'corroborated'})


def assessment_conditions(assessment, context, utterance, plan):
    """Validate an LLM declaration, without judging the text in its basis."""
    if not isinstance(assessment, dict):
        return None
    keys = assessment.get('context_keys')
    if (assessment.get('status') not in {'resolved', 'uncertain'}
            or not isinstance(keys, list) or any(k not in CONTEXT_KEYS or k not in context for k in keys)
            or len(set(keys)) != len(keys)
            or not isinstance(assessment.get('uncertainties'), list)
            or not isinstance(assessment.get('basis'), str) or not assessment['basis'].strip()
            or assessment.get('user_grounding') not in {'explicit', 'contextual', 'unknown'}
            or not isinstance(assessment.get('utterance_quote'), str)
            or not assessment['utterance_quote'] or assessment['utterance_quote'] not in utterance):
        return None
    if (plan.get('target_from_context') is True or assessment['user_grounding'] == 'contextual') and not set(keys) & {'focus', 'history', 'pending'}:
        return None
    return {k: context[k] for k in keys}


class SemanticLinkProvider(Protocol):
    def semantic_provider_identity(self) -> dict: ...
    def verify_semantic_plan(self, plan: dict) -> str: ...


class SemanticLinks:
    def __init__(self, database, similarity_config=None, composition_config=None):
        self.database = database
        self.configure_similarity(similarity_config or {})
        from .differential_semantics import DifferentialSemantics
        self.differential = DifferentialSemantics(database, composition_config or {})
        self.sync_action_relations()

    @staticmethod
    def _inventory_scope(provider):
        if not isinstance(provider, dict) or provider.get('provider') != 'home_assistant':
            return None
        endpoint = str(provider.get('endpoint') or '')
        return 'provider:home-assistant:' + hashlib.sha256(endpoint.encode()).hexdigest()[:16]

    def _ensure_action_targets(self, c, group_id, group, *, now=None):
        """Materialize only exact action-to-provider bindings already present in Memory."""
        scope = self._inventory_scope(group.get('binding'))
        resources = sorted({str(item) for item in group.get('resources', []) if item})
        if scope is None or not resources:
            return []
        placeholders = ','.join('?' for _ in resources)
        bindings = c.execute(
            """SELECT id,json_extract(payload_json,'$.external_reference') entity_id
               FROM memory_claims WHERE scope=? AND lifecycle='active'
               AND claim_kind='provider_binding'
               AND json_extract(payload_json,'$.inventory_source')='home_assistant'
               AND json_extract(payload_json,'$.external_reference') IN (""" + placeholders + ')',
            (scope, *resources),
        ).fetchall()
        by_entity = {row['entity_id']: row['id'] for row in bindings}
        if set(by_entity) != set(resources):
            return []
        now = now or _now()
        relation_ids = []
        for entity_id in resources:
            target_id = by_entity[entity_id]
            relation_id = uuid.uuid5(
                _RELATION_NAMESPACE, f'action-target:{group_id}:{target_id}'
            ).hex
            existing = c.execute(
                """SELECT id FROM memory_relations WHERE from_claim_id=? AND to_claim_id=?
                   AND relation_type='refines'""", (group_id, target_id),
            ).fetchone()
            if existing is None:
                evidence = self._evidence(
                    c, group_id, 'semantic_action_target_binding',
                    {'representation_id': group_id, 'provider_binding_claim_id': target_id,
                     'entity_id': entity_id, 'policy': ACTION_TARGET_POLICY},
                    group.get('origin_ref') or f'memory:{group_id}',
                )
                c.execute(
                    """INSERT INTO memory_relations
                       (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
                       VALUES (?,?,?,'refines',?,?)""",
                    (relation_id, group_id, target_id, evidence, now),
                )
            else:
                relation_id = existing['id']
            relation_ids.append(relation_id)
        if (group.get('target_relation_policy') != ACTION_TARGET_POLICY
                or group.get('target_relation_ids') != relation_ids):
            group['target_relation_policy'] = ACTION_TARGET_POLICY
            group['target_relation_ids'] = relation_ids
            c.execute('UPDATE memory_claims SET payload_json=?,updated_at=? WHERE id=?',
                      (identity(group), now, group_id))
        return relation_ids

    def _inventory_has_bindings(self, c, provider):
        scope = self._inventory_scope(provider)
        if scope is None:
            return False
        return c.execute(
            """SELECT 1 FROM memory_claims WHERE scope=? AND lifecycle='active'
               AND claim_kind='provider_binding'
               AND json_extract(payload_json,'$.inventory_source')='home_assistant' LIMIT 1""",
            (scope,),
        ).fetchone() is not None

    @lifecycle_operation('memory.semantic_links', 'semantic_action_relation_sync')
    def sync_action_relations(self, provider=None):
        """Backfill explicit relation carriers from persisted, exact claim identities."""
        if self.database is None:
            return {'groups': 0, 'target_relations': 0}
        groups = targets = 0
        with self.database.connect() as c:
            rows = c.execute(
                """SELECT id,payload_json FROM memory_claims
                   WHERE scope=? AND lifecycle='active' ORDER BY id""", (ACTION_SCOPE,),
            ).fetchall()
            for row in rows:
                group = json.loads(row['payload_json'])
                if provider is not None and group.get('binding') != provider:
                    continue
                relation_ids = self._ensure_action_targets(c, row['id'], group)
                groups += 1
                targets += len(relation_ids)
        return {'groups': groups, 'target_relations': targets}

    def configure_composition(self, config):
        return self.differential.configure(config)

    def composition_settings(self):
        return self.differential.settings()

    def composition_lookup(self, utterance, context, provider):
        return self.differential.lookup(utterance, context, provider)

    def configure_similarity(self, config):
        if not isinstance(config, dict):
            raise ValueError('Similarity configuration must be an object')
        enabled = config.get('enabled', True)
        mode = config.get('mode', 'active')
        threshold = config.get('threshold', .85)
        if type(enabled) is not bool or mode not in {'active', 'shadow'}:
            raise ValueError('Invalid similarity mode')
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not .5 <= float(threshold) <= 1:
            raise ValueError('Similarity threshold must be between 0.5 and 1.0')
        normalized = {'enabled': enabled, 'mode': mode, 'threshold': round(float(threshold), 6),
                      'policy': SIMILARITY_POLICY}
        normalized['version'] = hashlib.sha256(identity(normalized).encode()).hexdigest()[:12]
        self.similarity_config = normalized
        return dict(normalized)

    def similarity_settings(self):
        return dict(self.similarity_config)

    @staticmethod
    def _surface(text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Language-relation surfaces must be non-empty strings')
        tokens = surface_tokens(text)
        if not tokens or len(tokens) > 16 or len(text) > 160:
            raise ValueError('Language-relation surface exceeds its bounds')
        return {'text': text.strip(), 'tokens': tokens, 'key': identity(tokens)}

    @staticmethod
    def _surface_is_explicit(surface, utterance):
        tokens = surface_tokens(utterance)
        wanted = surface['tokens']
        return any(tokens[index:index + len(wanted)] == wanted
                   for index in range(len(tokens) - len(wanted) + 1))

    @staticmethod
    def _relation_context(context, context_keys):
        if (not isinstance(context, dict) or not isinstance(context_keys, list)
                or len(set(context_keys)) != len(context_keys)
                or any(key not in CONTEXT_KEYS or key not in context for key in context_keys)):
            raise ValueError('Invalid language-relation context')
        return {key: context[key] for key in context_keys}

    def language_relations(self, context=None, provider=None, *, include_history=False, limit=24):
        """Return a bounded structured projection for the planner and Brainwatch."""
        limit = min(100, max(1, int(limit)))
        states = "('active','retired','invalid')" if include_history else "('active')"
        with self.database.connect() as c:
            rows = c.execute(f'''SELECT id,lifecycle,created_at,updated_at,display_text,payload_json
                FROM memory_claims WHERE scope=? AND lifecycle IN {states}
                ORDER BY updated_at DESC,id DESC LIMIT ?''',
                (LANGUAGE_RELATION_SCOPE, limit)).fetchall()
            result = []
            for row in rows:
                payload = json.loads(row['payload_json'])
                conditions = payload.get('context') if isinstance(payload.get('context'), dict) else {}
                if context is not None and any(key not in context or context[key] != value
                                               for key, value in conditions.items()):
                    continue
                binding = payload.get('provider')
                if binding is not None and provider is not None and binding != provider:
                    continue
                token_labels = {
                    identity(tokens): label
                    for tokens, label in zip(
                        payload.get('surface_tokens', []), payload.get('surfaces', []), strict=False)
                }
                payload['correction_options'] = [
                    {'index': index, 'surfaces': [
                        token_labels.get(identity(edge[0]), edge[0]),
                        token_labels.get(identity(edge[1]), edge[1]),
                    ]}
                    for index, edge in enumerate(payload.get('edges', []))
                    if isinstance(edge, list) and len(edge) == 2
                ]
                result.append(dict(id=row['id'], lifecycle=row['lifecycle'],
                    created_at=row['created_at'], updated_at=row['updated_at'],
                    display_text=row['display_text'], **payload))
            return result

    @lifecycle_operation("memory.semantic_links", "explicit_action_resource_relation")
    def record_action_resource_relation(self, resource_surface, action_reference, *,
                                        provider, source_ref, basis, user_utterance):
        """Bind a proven action representation to an inventoried provider executor.

        The model only selects a published action reference and copies the provider
        identity from the current utterance.  This method proves the technical
        identity and, for Home Assistant scenes, requires the scene members to be
        exactly the resources of the existing action representation.
        """
        resource = self._surface(resource_surface)
        if (not self._surface_is_explicit(resource, user_utterance)
                or not isinstance(action_reference, dict)
                or not isinstance(provider, dict) or not provider
                or not source_ref or not isinstance(basis, str) or not basis.strip()):
            raise ValueError('Invalid explicit action-resource relation')
        representation_id = action_reference.get('representation_id')
        if not representation_id:
            raise ValueError('Action representation is unavailable')
        scope = self._inventory_scope(provider)
        if scope is None:
            raise ValueError('Action resource provider is unsupported')
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            group_row = c.execute(
                "SELECT payload_json FROM memory_claims WHERE id=? AND scope=? AND lifecycle='active'",
                (representation_id, ACTION_SCOPE),
            ).fetchone()
            if group_row is None:
                raise ValueError('Action representation is unavailable')
            group = json.loads(group_row['payload_json'])
            if group.get('binding') != provider:
                raise ValueError('Action representation provider differs')
            binding_rows = c.execute(
                """SELECT id,payload_json FROM memory_claims
                   WHERE scope=? AND lifecycle='active' AND claim_kind='provider_binding'
                   AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                   AND json_extract(payload_json,'$.external_reference')=?
                   ORDER BY updated_at DESC,id""",
                (scope, resource['text']),
            ).fetchall()
            if len(binding_rows) != 1:
                return {'status': 'unresolved' if not binding_rows else 'ambiguous',
                        'relation_id': None, 'representation_id': representation_id}
            binding_id = binding_rows[0]['id']
            binding = json.loads(binding_rows[0]['payload_json'])
            metadata = binding.get('provider_metadata') or {}
            services = set(metadata.get('services') or [])
            if metadata.get('domain') != 'scene' or 'scene.turn_on' not in services:
                return {'status': 'unsupported', 'relation_id': None,
                        'representation_id': representation_id, 'resource_identity': resource['text']}
            action_resources = set(group.get('resources') or [])
            scene_members = set(metadata.get('members') or [])
            if not action_resources or scene_members != action_resources:
                return {'status': 'resource_mismatch', 'relation_id': None,
                        'representation_id': representation_id, 'resource_identity': resource['text'],
                        'action_resources': sorted(action_resources),
                        'resource_members': sorted(scene_members)}
            logical = {
                'relation_kind': 'action_resource',
                'representation_id': representation_id,
                'resource_binding_claim_id': binding_id,
                'resource_identity': resource['text'],
                'provider': provider,
            }
            relation_key = hashlib.sha256(identity(logical).encode()).hexdigest()
            existing = c.execute(
                """SELECT id FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.relation_key')=?
                   ORDER BY updated_at DESC,id DESC LIMIT 1""",
                (LANGUAGE_RELATION_SCOPE, relation_key),
            ).fetchone()
            if existing:
                self._evidence(c, existing['id'], 'explicit_action_resource_relation_reaffirmed',
                               {'basis': basis, 'user_utterance': user_utterance}, source_ref)
                return {'status': 'reaffirmed', 'relation_id': existing['id'],
                        'relation_kind': 'action_resource',
                        'representation_id': representation_id,
                        'resource_identity': resource['text'],
                        'resource_binding_claim_id': binding_id}
            now, relation_id = _now(), str(uuid.uuid4())
            executor_action = {
                'type': 'call_service', 'entity_id': resource['text'],
                'service': 'scene.turn_on', 'data': {},
            }
            payload = _safe_json({
                **logical, 'kind': 'explicit_action_resource_relation',
                'relation_key': relation_key, 'surfaces': [resource['text']],
                'surface_tokens': [resource['tokens']], 'polarity': 'positive',
                'executor_action': executor_action,
                'original_actions': group.get('actions', []),
                'resource_members': sorted(scene_members),
                'origin_turn_ref': source_ref, 'user_evidence': user_utterance,
                'basis': basis, 'confirmation': 'confirmed', 'validity': 'valid',
                'policy': ACTION_RESOURCE_POLICY,
                'dependencies': [representation_id, binding_id],
            })
            # These are database claim identities, not credentials. Some stable
            # inventory IDs are long hexadecimal hashes and therefore resemble
            # secrets to the generic text redactor; retain only these proven
            # internal references after all user/provider text was sanitized.
            payload['representation_id'] = representation_id
            payload['resource_binding_claim_id'] = binding_id
            payload['dependencies'] = [representation_id, binding_id]
            c.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES (?,'alias',?,?,?,?, 'active','dynamic',?,?)""",
                (relation_id, LANGUAGE_RELATION_SCOPE, relation_key,
                 f"{group.get('representation', {}).get('meaning', representation_id)} → {resource['text']}",
                 identity(payload), now, now),
            )
            evidence_id = self._evidence(c, relation_id, 'explicit_action_resource_relation', {
                'basis': basis, 'user_utterance': user_utterance,
                'representation_id': representation_id,
                'resource_binding_claim_id': binding_id,
                'resource_identity': resource['text'],
                'member_identity_validated': True,
            }, source_ref)
            for target_id in (representation_id, binding_id):
                c.execute(
                    """INSERT OR IGNORE INTO memory_relations
                       (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
                       VALUES (?,?,?,'refines',?,?)""",
                    (str(uuid.uuid4()), relation_id, target_id, evidence_id, now),
                )
            return {'status': 'stored', 'relation_id': relation_id,
                    'relation_kind': 'action_resource',
                    'representation_id': representation_id,
                    'resource_identity': resource['text'],
                    'resource_binding_claim_id': binding_id}

    def apply_action_resource_executor(self, hit, provider):
        """Use a currently valid explicit executor relation for a semantic hit."""
        if not isinstance(hit, dict):
            return hit
        representation_id = hit.get('action_representation_id') or hit.get('representation_id')
        if not representation_id:
            return hit
        scope = self._inventory_scope(provider)
        if scope is None:
            return hit
        with self.database.connect() as c:
            rows = c.execute(
                """SELECT relation.id,relation.payload_json,binding.id binding_id,
                          binding.payload_json binding_payload
                   FROM memory_claims relation
                   JOIN memory_relations rr ON rr.from_claim_id=relation.id
                        AND rr.relation_type='refines'
                   JOIN memory_claims binding ON binding.id=rr.to_claim_id
                   WHERE relation.scope=? AND relation.lifecycle='active'
                     AND json_extract(relation.payload_json,'$.relation_kind')='action_resource'
                     AND json_extract(relation.payload_json,'$.polarity')='positive'
                     AND json_extract(relation.payload_json,'$.representation_id')=?
                     AND binding.scope=? AND binding.lifecycle='active'
                     AND binding.claim_kind='provider_binding'
                   ORDER BY relation.updated_at DESC,relation.id""",
                (LANGUAGE_RELATION_SCOPE, representation_id, scope),
            ).fetchall()
            valid = []
            for row in rows:
                relation = json.loads(row['payload_json'])
                binding = json.loads(row['binding_payload'])
                metadata = binding.get('provider_metadata') or {}
                if (relation.get('provider') == provider
                        and row['binding_id'] == relation.get('resource_binding_claim_id')
                        and binding.get('external_reference') == relation.get('resource_identity')
                        and metadata.get('domain') == 'scene'
                        and 'scene.turn_on' in set(metadata.get('services') or [])
                        and set(metadata.get('members') or []) == set(relation.get('resource_members') or [])):
                    valid.append((row['id'], relation))
            if len(valid) != 1:
                return hit
            relation_id, relation = valid[0]
            resolved = deepcopy(hit)
            plan = deepcopy(resolved.get('plan') or {})
            plan['actions'] = [deepcopy(relation['executor_action'])]
            plan['action_resource_relation_id'] = relation_id
            plan['action_resource_policy'] = ACTION_RESOURCE_POLICY
            resolved['plan'] = plan
            resolved['action_resource_relation_id'] = relation_id
            relation_ids = list(resolved.get('memory_relation_ids') or [])
            relation_ids.extend(row['id'] for row in c.execute(
                "SELECT id FROM memory_relations WHERE from_claim_id=? ORDER BY id", (relation_id,)
            ).fetchall())
            resolved['memory_relation_ids'] = list(dict.fromkeys(relation_ids))
            return resolved

    def _resolve_resource_surface(self, connection, source, context, provider):
        """Resolve an exact declared surface only through confirmed technical experiences."""
        rows = connection.execute('''SELECT id,display_text,payload_json FROM memory_claims
            WHERE scope=? AND lifecycle='active'
            AND json_extract(payload_json,'$.validity')='valid'
            AND json_extract(payload_json,'$.provider_validated')=1
            AND json_extract(payload_json,'$.technical_status')='success'
            AND json_extract(payload_json,'$.confirmation') IN ('confirmed','corroborated')
            AND json_extract(payload_json,'$.action_link_status') IN ('created','linked')
            ORDER BY updated_at DESC,id''', (SCOPE,)).fetchall()
        matches = []
        for row in rows:
            payload = json.loads(row['payload_json'])
            if payload.get('provider') != provider or any(
                    key not in context or context[key] != value
                    for key, value in payload.get('context', {}).items()):
                continue
            learned = surface_tokens(row['display_text'])
            wanted = source['tokens']
            if not any(learned[index:index + len(wanted)] == wanted
                       for index in range(len(learned) - len(wanted) + 1)):
                continue
            resources = sorted({action.get('entity_id') for action in payload.get('plan', {}).get('actions', [])
                                if isinstance(action, dict) and action.get('entity_id')})
            if len(resources) == 1:
                matches.append({'claim_id': row['id'], 'resource_identity': resources[0]})
        identities = {item['resource_identity'] for item in matches}
        if not matches:
            return {'status': 'unresolved', 'matches': []}
        if len(identities) != 1:
            return {'status': 'ambiguous', 'matches': matches}
        return {'status': 'resolved', 'resource_identity': next(iter(identities)),
                'matches': matches}

    @lifecycle_operation("memory.semantic_links", "explicit_language_relation")
    def record_language_relation(self, relation_kind, *, surfaces=None, source_surface=None,
                                 new_surface=None, polarity='positive', context=None,
                                 context_keys=None, provider=None, source_ref, basis,
                                 user_utterance):
        """Persist one explicit user declaration without interpreting its wording."""
        if (relation_kind not in {'surface_equivalence', 'resource_alias'}
                or polarity not in {'positive', 'negative'} or not source_ref
                or not isinstance(basis, str) or not basis.strip()
                or not isinstance(user_utterance, str) or not user_utterance.strip()):
            raise ValueError('Invalid explicit language relation')
        conditions = self._relation_context(context or {}, context_keys or [])
        if relation_kind == 'surface_equivalence':
            if not isinstance(surfaces, list) or not 2 <= len(surfaces) <= 8:
                raise ValueError('A surface equivalence requires two to eight surfaces')
            normalized = [self._surface(item) for item in surfaces]
            unique = []
            for item in normalized:
                if item['key'] not in {known['key'] for known in unique}:
                    unique.append(item)
            if len(unique) < 2 or any(not self._surface_is_explicit(item, user_utterance) for item in unique):
                raise ValueError('Declared surfaces must occur explicitly in the user message')
            edges = [[unique[0]['tokens'], item['tokens']] for item in unique[1:]]
            surface_values = [item['text'] for item in unique]
            provider_binding = None
        else:
            if polarity != 'positive' or not isinstance(provider, dict) or not provider:
                raise ValueError('A resource alias requires a positive provider-bound declaration')
            source, alias = self._surface(source_surface), self._surface(new_surface)
            if source['key'] == alias['key'] or any(
                    not self._surface_is_explicit(item, user_utterance) for item in (source, alias)):
                raise ValueError('Alias surfaces must be different and explicit')
            unique = [source, alias]
            edges = [[alias['tokens'], source['tokens']]]
            surface_values = [source['text'], alias['text']]
            provider_binding = provider
        logical = {'relation_kind': relation_kind, 'edges': edges, 'context': conditions,
                   'provider': provider_binding}
        relation_key = hashlib.sha256(identity(logical).encode()).hexdigest()
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            resource_identity = None
            source_claim_ids = []
            if relation_kind == 'resource_alias':
                resolution = self._resolve_resource_surface(c, unique[0], context or {}, provider)
                if resolution['status'] != 'resolved':
                    return {'status': resolution['status'], 'relation_id': None,
                            'matches': resolution.get('matches', [])}
                resource_identity = resolution['resource_identity']
                source_claim_ids = [item['claim_id'] for item in resolution['matches']]
                conflicting = c.execute('''SELECT id,payload_json FROM memory_claims
                    WHERE scope=? AND lifecycle='active'
                    AND json_extract(payload_json,'$.relation_kind')='resource_alias'
                    AND json_extract(payload_json,'$.polarity')='positive' ''',
                    (LANGUAGE_RELATION_SCOPE,)).fetchall()
                alias_key = unique[1]['key']
                for row in conflicting:
                    payload = json.loads(row['payload_json'])
                    if (payload.get('provider') == provider and payload.get('context') == conditions
                            and payload.get('surface_keys', [None, None])[-1] == alias_key
                            and payload.get('resource_identity') != resource_identity):
                        return {'status': 'conflict', 'relation_id': None,
                                'conflicting_relation_id': row['id']}
            active = c.execute('''SELECT id,payload_json FROM memory_claims
                WHERE scope=? AND lifecycle='active'
                AND json_extract(payload_json,'$.relation_key')=?
                ORDER BY updated_at DESC,id DESC''',
                (LANGUAGE_RELATION_SCOPE, relation_key)).fetchall()
            parsed = [(row, json.loads(row['payload_json'])) for row in active]
            same = next(((row, payload) for row, payload in parsed
                         if payload.get('polarity') == polarity
                         and payload.get('resource_identity') == resource_identity), None)
            if same:
                self._evidence(c, same[0]['id'], 'explicit_language_relation_reaffirmed',
                    {'basis': basis, 'user_utterance': user_utterance}, source_ref)
                return {'status': 'reaffirmed', 'relation_id': same[0]['id'],
                        'relation_kind': relation_kind, 'resource_identity': resource_identity}
            now, relation_id = _now(), str(uuid.uuid4())
            version_row = c.execute('''SELECT MAX(CAST(json_extract(payload_json,'$.version') AS INTEGER))
                FROM memory_claims WHERE scope=?
                AND json_extract(payload_json,'$.relation_key')=?''',
                (LANGUAGE_RELATION_SCOPE, relation_key)).fetchone()
            version = int(version_row[0] or 0) + 1
            payload = _safe_json({
                'kind': 'explicit_language_relation', 'relation_kind': relation_kind,
                'relation_key': relation_key, 'polarity': polarity, 'surfaces': surface_values,
                'surface_tokens': [item['tokens'] for item in unique],
                'surface_keys': [item['key'] for item in unique], 'edges': edges,
                'context': conditions, 'provider': provider_binding,
                'resource_identity': resource_identity, 'source_claim_ids': source_claim_ids,
                'origin_turn_ref': source_ref, 'user_evidence': user_utterance,
                'basis': basis, 'confirmation': 'confirmed', 'validity': 'valid',
                'version': version, 'policy': LANGUAGE_RELATION_POLICY,
                'dependencies': source_claim_ids,
            })
            display = (' ↔ '.join(surface_values) if relation_kind == 'surface_equivalence'
                       else f'{surface_values[1]} → {resource_identity}')
            c.execute('''INSERT INTO memory_claims
                (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                 verification_policy,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'active','dynamic',?,?)''',
                (relation_id, 'alias' if relation_kind == 'resource_alias' else 'opaque_fact',
                 LANGUAGE_RELATION_SCOPE, f'{relation_key}:{version}:{relation_id}', display,
                 identity(payload), now, now))
            evidence_id = self._evidence(c, relation_id, 'explicit_language_relation', {
                'relation_kind': relation_kind, 'polarity': polarity, 'surfaces': surface_values,
                'basis': basis, 'user_utterance': user_utterance,
                'resolved_resource': resource_identity, 'source_claim_ids': source_claim_ids,
            }, source_ref, 'supports' if polarity == 'positive' else 'contradicts')
            for row, _previous in parsed:
                c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (now, row['id']))
                c.execute("INSERT OR IGNORE INTO memory_relations VALUES (?,?,?,'supersedes',?,?)",
                          (str(uuid.uuid4()), relation_id, row['id'], evidence_id, now))
            for claim_id in source_claim_ids:
                c.execute("INSERT OR IGNORE INTO memory_relations VALUES (?,?,?,'refines',?,?)",
                          (str(uuid.uuid4()), relation_id, claim_id, evidence_id, now))
            return {'status': 'stored', 'relation_id': relation_id,
                    'relation_kind': relation_kind, 'resource_identity': resource_identity,
                    'version': version, 'source_claim_ids': source_claim_ids}

    @lifecycle_operation("memory.semantic_links", "language_relation_correction")
    def correct_language_relation(self, relation_id, *, source_ref, basis, undo=False,
                                  edge_indexes=None):
        """Version an explicit correction, or undo exactly its latest version."""
        if not relation_id or not source_ref or not isinstance(basis, str) or not basis.strip():
            raise ValueError('Relation, source and basis are required')
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM memory_claims WHERE id=? AND scope=?',
                            (relation_id, LANGUAGE_RELATION_SCOPE)).fetchone()
            if row is None:
                raise KeyError(relation_id)
            if row['lifecycle'] != 'active':
                raise ValueError('Language relation is not active')
            payload = json.loads(row['payload_json'])
            now = _now()
            if undo:
                previous = c.execute('''SELECT c.id,c.lifecycle,r.relation_type FROM memory_relations r
                    JOIN memory_claims c ON c.id=r.to_claim_id
                    WHERE r.from_claim_id=? AND r.relation_type IN ('supersedes','contradicts')
                    AND c.scope=?
                    ORDER BY r.created_at DESC,r.id DESC LIMIT 1''',
                    (relation_id, LANGUAGE_RELATION_SCOPE)).fetchone()
                if payload.get('polarity') != 'negative' or previous is None:
                    raise ValueError('Only an active language-relation correction can be undone')
                c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (now, relation_id))
                if previous['lifecycle'] == 'retired':
                    c.execute("UPDATE memory_claims SET lifecycle='active',updated_at=? WHERE id=?",
                              (now, previous['id']))
                self._evidence(c, relation_id, 'explicit_language_relation_undo',
                    {'restored_relation_id': previous['id'] if previous else None, 'basis': basis},
                    source_ref, 'contradicts' if payload.get('polarity') == 'positive' else 'supports')
                return {'status': 'undone', 'relation_id': relation_id,
                        'restored_relation_id': previous['id'] if previous else None,
                        'relation_kind': payload.get('relation_kind'),
                        'surfaces': payload.get('surfaces', [])}
            new_id = str(uuid.uuid4())
            corrected = dict(payload)
            targeted = False
            if edge_indexes is not None:
                edges = payload.get('edges', [])
                if (not isinstance(edge_indexes, list) or not edge_indexes
                        or len(set(edge_indexes)) != len(edge_indexes)
                        or any(type(index) is not int or index < 0 or index >= len(edges)
                               for index in edge_indexes)):
                    raise ValueError('Correction edge does not belong to the referenced relation')
                selected_edges = [edges[index] for index in edge_indexes]
                targeted = len(selected_edges) < len(payload.get('edges', []))
                selected_tokens = []
                for edge in selected_edges:
                    for tokens in edge:
                        if tokens not in selected_tokens:
                            selected_tokens.append(tokens)
                token_labels = {
                    identity(tokens): label
                    for tokens, label in zip(
                        payload.get('surface_tokens', []), payload.get('surfaces', []), strict=False)
                }
                corrected.update(
                    surfaces=[token_labels.get(identity(tokens), ' '.join(tokens))
                              for tokens in selected_tokens],
                    surface_tokens=selected_tokens,
                    surface_keys=[identity(tokens) for tokens in selected_tokens],
                    edges=selected_edges,
                    parent_relation_id=relation_id,
                    corrected_edge_indexes=edge_indexes,
                )
            version_row = c.execute('''SELECT MAX(CAST(json_extract(payload_json,'$.version') AS INTEGER))
                FROM memory_claims WHERE scope=?
                AND json_extract(payload_json,'$.relation_key')=?''',
                (LANGUAGE_RELATION_SCOPE, payload['relation_key'])).fetchone()
            corrected.update(polarity='negative', version=int(version_row[0] or 0) + 1,
                             origin_turn_ref=source_ref, basis=basis, confirmation='confirmed',
                             validity='valid')
            c.execute('''INSERT INTO memory_claims
                (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                 verification_policy,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'active','dynamic',?,?)''',
                (new_id, row['claim_kind'], LANGUAGE_RELATION_SCOPE,
                 f"{payload['relation_key']}:{corrected['version']}:{new_id}",
                 row['display_text'] + ' · gesperrt', identity(_safe_json(corrected)), now, now))
            evidence_id = self._evidence(c, new_id, 'explicit_language_relation_correction',
                {'corrected_relation_id': relation_id, 'basis': basis,
                 'edge_indexes': edge_indexes, 'surfaces': corrected.get('surfaces'),
                 'targeted': targeted},
                source_ref, 'contradicts')
            relation_type = 'contradicts' if targeted else 'supersedes'
            if not targeted:
                c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?",
                          (now, relation_id))
            c.execute("INSERT INTO memory_relations VALUES (?,?,?,?,?,?)",
                      (str(uuid.uuid4()), new_id, relation_id, relation_type, evidence_id, now))
            return {'status': 'corrected', 'relation_id': new_id,
                    'superseded_relation_id': relation_id if not targeted else None,
                    'contradicted_relation_id': relation_id if targeted else None,
                    'targeted': targeted, 'version': corrected['version'],
                    'relation_kind': corrected.get('relation_kind'),
                    'surfaces': corrected.get('surfaces', []),
                    'edge_indexes': edge_indexes or []}

    @staticmethod
    def _relation_pair(left, right):
        if not isinstance(left, str) or not left.strip() or not isinstance(right, str) or not right.strip():
            raise ValueError('Relation units must be non-empty strings')
        left_tokens, right_tokens = surface_tokens(left), surface_tokens(right)
        if len(left_tokens) != 1 or len(right_tokens) != 1 or left_tokens == right_tokens:
            raise ValueError('A relation requires two different single surface tokens')
        return tuple(sorted((left_tokens[0], right_tokens[0])))

    def _active_similarity_relations(self, connection, representation_id):
        rows = connection.execute('''SELECT id,payload_json FROM memory_claims
            WHERE scope=? AND lifecycle='active'
            AND json_extract(payload_json,'$.representation_id')=?''',
            (SIMILARITY_RELATION_SCOPE, representation_id)).fetchall()
        relations = {}
        for row in rows:
            payload = json.loads(row['payload_json'])
            pair = tuple(payload.get('pair', []))
            if len(pair) == 2:
                relations.setdefault(pair, []).append(dict(id=row['id'], **payload))
        return relations

    def _active_similarity_recognitions(self, connection, representation_id):
        rows = connection.execute('''SELECT id,payload_json FROM memory_claims
            WHERE scope=? AND lifecycle='active'
            AND json_extract(payload_json,'$.representation_id')=?
            AND json_extract(payload_json,'$.kind')='recognition' ''',
            (SIMILARITY_RELATION_SCOPE, representation_id)).fetchall()
        return [dict(id=row['id'], **json.loads(row['payload_json'])) for row in rows]

    @lifecycle_operation("memory.semantic_links", "similarity_recognition_correction")
    def record_similarity_recognition(self, input_formulation, learned_claim_id, polarity, *,
                                      source_ref, basis, source_turn_id=None,
                                      source_message_id=None, _connection=None):
        """Version one explicit decision about a concrete similarity recognition."""
        if (polarity not in {'positive', 'negative'} or not source_ref or not str(basis).strip()
                or not isinstance(input_formulation, str) or not input_formulation.strip()
                or not isinstance(learned_claim_id, str) or not learned_claim_id):
            raise ValueError('Explicit recognition, source and basis are required')
        input_tokens = surface_tokens(input_formulation)
        if not input_tokens:
            raise ValueError('Recognition formulation is empty')
        with nullcontext(_connection) if _connection is not None else self.database.connect() as c:
            learned = c.execute('''SELECT lifecycle,payload_json FROM memory_claims
                WHERE id=? AND scope=?''', (learned_claim_id, SCOPE)).fetchone()
            if learned is None:
                raise KeyError(learned_claim_id)
            learned_payload = json.loads(learned['payload_json'])
            representation_id = learned_payload.get('action_representation_id')
            if (learned['lifecycle'] != 'active' or learned_payload.get('validity') != 'valid'
                    or not representation_id):
                raise ValueError('Recognition target is unavailable')
            key = identity({'kind': 'recognition', 'representation_id': representation_id,
                            'learned_claim_id': learned_claim_id, 'input_tokens': input_tokens})
            active = [item for item in self._active_similarity_recognitions(c, representation_id)
                      if item.get('learned_claim_id') == learned_claim_id
                      and item.get('input_tokens') == input_tokens]
            same = next((item for item in active if item.get('polarity') == polarity), None)
            if same:
                self._evidence(c, same['id'], 'semantic_similarity_recognition_reaffirmed',
                               {'polarity': polarity, 'basis': basis}, source_ref)
                relation_id = same['id']
            else:
                now, relation_id = _now(), str(uuid.uuid4())
                payload = _safe_json(dict(
                    kind='recognition', polarity=polarity, representation_id=representation_id,
                    learned_claim_id=learned_claim_id, input_formulation=str(input_formulation),
                    input_tokens=input_tokens, basis=str(basis), policy=SIMILARITY_POLICY,
                    validity='valid', created_from='explicit_correction'))
                c.execute('''INSERT INTO memory_claims
                    (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                     verification_policy,created_at,updated_at)
                    VALUES (?,'opaque_fact',?,?,?,?, 'active','dynamic',?,?)''',
                    (relation_id, SIMILARITY_RELATION_SCOPE,
                     identity({'identity': key, 'version': relation_id}),
                     f'{input_formulation} -> {learned_claim_id}: {polarity}', identity(payload), now, now))
                evidence_id = self._evidence(c, relation_id,
                    'semantic_similarity_recognition_positive' if polarity == 'positive'
                    else 'semantic_similarity_recognition_negative',
                    {'polarity': polarity, 'basis': basis, 'learned_claim_id': learned_claim_id},
                    source_ref, 'supports' if polarity == 'positive' else 'contradicts')
                c.execute("INSERT INTO memory_relations VALUES (?,?,?,'refines',?,?)",
                          (str(uuid.uuid4()), relation_id, representation_id, evidence_id, now))
                for previous in active:
                    c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?",
                              (now, previous['id']))
                    c.execute("INSERT OR IGNORE INTO memory_relations VALUES (?,?,?,'supersedes',?,?)",
                              (str(uuid.uuid4()), relation_id, previous['id'], evidence_id, now))
            if source_turn_id or source_message_id:
                c.execute('''UPDATE memory_evidence SET source_turn_id=COALESCE(?,source_turn_id),
                    source_message_id=COALESCE(?,source_message_id) WHERE claim_id=? AND source_ref=?''',
                    (source_turn_id, source_message_id, relation_id, source_ref))
            return relation_id

    @lifecycle_operation("memory.semantic_links", "similarity_relation_correction")
    def record_similarity_relation(self, left, right, polarity, *, source_ref,
                                   representation_id=None, basis='', source_turn_id=None,
                                   source_message_id=None, user_utterance=None, _connection=None):
        if polarity not in {'positive', 'negative'} or not source_ref or not str(basis).strip():
            raise ValueError('Explicit relation, source and basis are required')
        pair = self._relation_pair(left, right)
        if user_utterance is not None and not set(pair).issubset(surface_tokens(user_utterance)):
            raise ValueError('Relation units are not explicit in the user utterance')
        with nullcontext(_connection) if _connection is not None else self.database.connect() as c:
            if representation_id is None:
                rows = c.execute('''SELECT DISTINCT json_extract(payload_json,'$.action_representation_id') representation_id,
                    display_text FROM memory_claims WHERE scope=? AND lifecycle='active'
                    AND json_extract(payload_json,'$.validity')='valid'
                    AND json_extract(payload_json,'$.confirmation') IN ('confirmed','corroborated')
                    AND json_extract(payload_json,'$.action_link_status') IN ('created','linked')''', (SCOPE,)).fetchall()
                candidates = {row['representation_id'] for row in rows if row['representation_id'] and
                              (pair[0] in surface_tokens(row['display_text']) or pair[1] in surface_tokens(row['display_text']))}
                if len(candidates) != 1:
                    raise ValueError('Relation reference is ambiguous or not learned')
                representation_id = candidates.pop()
            group = c.execute("SELECT 1 FROM memory_claims WHERE id=? AND scope=? AND lifecycle='active'",
                              (representation_id, ACTION_SCOPE)).fetchone()
            if group is None:
                raise ValueError('Action representation is unavailable')
            known = c.execute('''SELECT display_text FROM memory_claims WHERE scope=?
                AND json_extract(payload_json,'$.action_representation_id')=?
                AND lifecycle IN ('active','candidate','retired')''', (SCOPE, representation_id)).fetchall()
            vocabulary = {token for row in known for token in surface_tokens(row['display_text'])}
            if not set(pair) & vocabulary:
                raise ValueError('Relation does not reference a learned surface unit')
            active = self._active_similarity_relations(c, representation_id).get(pair, [])
            same = next((item for item in active if item.get('polarity') == polarity), None)
            if same:
                self._evidence(c, same['id'], 'semantic_similarity_relation_reaffirmed',
                               {'pair': pair, 'polarity': polarity, 'basis': basis}, source_ref)
                relation_id = same['id']
            else:
                now, relation_id = _now(), str(uuid.uuid4())
                payload = _safe_json(dict(pair=list(pair), polarity=polarity,
                    representation_id=representation_id, basis=str(basis), policy=SIMILARITY_POLICY,
                    validity='valid', created_from='explicit_correction'))
                c.execute('''INSERT INTO memory_claims
                    (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                     verification_policy,created_at,updated_at)
                    VALUES (?,'opaque_fact',?,?,?,?, 'active','dynamic',?,?)''',
                    (relation_id, SIMILARITY_RELATION_SCOPE,
                     identity({'representation_id': representation_id, 'pair': pair,
                               'version': relation_id}),
                     f'{pair[0]} {"=" if polarity == "positive" else "!="} {pair[1]}',
                     identity(payload), now, now))
                evidence_id = self._evidence(c, relation_id,
                    'semantic_similarity_positive' if polarity == 'positive' else 'semantic_similarity_negative',
                    {'pair': pair, 'polarity': polarity, 'basis': basis}, source_ref,
                    'supports' if polarity == 'positive' else 'contradicts')
                c.execute("INSERT INTO memory_relations VALUES (?,?,?,'refines',?,?)",
                          (str(uuid.uuid4()), relation_id, representation_id, evidence_id, now))
                for previous in active:
                    c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (now, previous['id']))
                    c.execute("INSERT OR IGNORE INTO memory_relations VALUES (?,?,?,'supersedes',?,?)",
                              (str(uuid.uuid4()), relation_id, previous['id'], evidence_id, now))
            if source_turn_id or source_message_id:
                c.execute('''UPDATE memory_evidence SET source_turn_id=COALESCE(?,source_turn_id),
                    source_message_id=COALESCE(?,source_message_id) WHERE claim_id=? AND source_ref=?''',
                    (source_turn_id, source_message_id, relation_id, source_ref))
            return relation_id

    @lifecycle_operation("memory.semantic_links", "similarity_relation_retracted")
    def retract_similarity_relation(self, relation_id, *, source_ref, _connection=None):
        if not relation_id or not source_ref:
            raise ValueError('Relation and source are required')
        with nullcontext(_connection) if _connection is not None else self.database.connect() as c:
            row = c.execute('SELECT lifecycle,payload_json FROM memory_claims WHERE id=? AND scope=?',
                            (relation_id, SIMILARITY_RELATION_SCOPE)).fetchone()
            if row is None:
                raise KeyError(relation_id)
            if row['lifecycle'] != 'active':
                raise ValueError('Relation is not active')
            payload = json.loads(row['payload_json'])
            c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (_now(), relation_id))
            evidence_payload = {key: payload[key] for key in (
                'kind', 'pair', 'polarity', 'learned_claim_id', 'input_tokens') if key in payload}
            self._evidence(c, relation_id, 'semantic_similarity_relation_retracted',
                           evidence_payload, source_ref,
                           'contradicts' if payload['polarity'] == 'positive' else 'supports')
            previous = c.execute('''SELECT c.id FROM memory_relations r JOIN memory_claims c ON c.id=r.to_claim_id
                WHERE r.from_claim_id=? AND r.relation_type='supersedes'
                AND c.scope=? AND c.lifecycle='retired' ORDER BY r.created_at DESC LIMIT 1''',
                (relation_id, SIMILARITY_RELATION_SCOPE)).fetchone()
            if previous:
                c.execute("UPDATE memory_claims SET lifecycle='active',updated_at=? WHERE id=?", (_now(), previous['id']))
            return dict(id=relation_id, status='retired', restored_relation_id=previous['id'] if previous else None)

    def similarity_lookup(self, utterance, context, provider):
        started = time.perf_counter()
        settings = self.similarity_settings()
        base = dict(policy=SIMILARITY_POLICY, config=settings, input_tokens=surface_tokens(utterance))
        if not settings['enabled']:
            return {**base, 'status': 'disabled', 'hit': None, 'candidate_count': 0,
                    'duration_ms': (time.perf_counter() - started) * 1000}
        query = base['input_tokens']
        if not query or len(query) > 64 or len(str(utterance)) > 4096 or any(len(token) > 64 for token in query):
            return {**base, 'status': 'fallback', 'reason': 'input_bound', 'hit': None, 'candidate_count': 0,
                    'duration_ms': (time.perf_counter() - started) * 1000}
        with self.database.connect() as c:
            rows = c.execute('''SELECT c.id,c.display_text,c.payload_json,g.lifecycle group_lifecycle
                FROM memory_claims c JOIN memory_claims g
                  ON g.id=json_extract(c.payload_json,'$.action_representation_id')
                WHERE c.scope=? AND c.lifecycle='active' AND g.scope=? AND g.lifecycle='active'
                AND json_extract(c.payload_json,'$.validity')='valid'
                AND json_extract(c.payload_json,'$.strong_semantic_evidence')=1
                AND json_extract(c.payload_json,'$.technical_status')='success'
                AND json_extract(c.payload_json,'$.confirmation') IN ('confirmed','corroborated')
                AND json_extract(c.payload_json,'$.action_link_status') IN ('created','linked')
                ORDER BY c.updated_at DESC,c.id LIMIT 1001''', (SCOPE, ACTION_SCOPE)).fetchall()
            truncated = len(rows) > 1000
            candidates = []
            checked = 0
            negative_relation_present = False
            unsafe_token_substitution_present = False
            relation_cache = {}
            recognition_cache = {}
            for row in rows[:1000]:
                payload = json.loads(row['payload_json'])
                if payload.get('provider') != provider or any(
                        key not in context or context[key] != value for key, value in payload.get('context', {}).items()):
                    continue
                checked += 1
                representation_id = payload.get('action_representation_id')
                if representation_id not in relation_cache:
                    relation_cache[representation_id] = self._active_similarity_relations(c, representation_id)
                    recognition_cache[representation_id] = self._active_similarity_recognitions(c, representation_id)
                relations = relation_cache[representation_id]
                recognitions = [item for item in recognition_cache[representation_id]
                                if item.get('learned_claim_id') == row['id']
                                and item.get('input_tokens') == query]
                if any(item.get('polarity') == 'negative' for item in recognitions):
                    negative_relation_present = True
                    continue
                learned_tokens = surface_tokens(row['display_text'])
                blocked_pairs = [pair for pair, values in relations.items()
                                 if any(item.get('polarity') == 'negative' for item in values)
                                 and ((pair[0] in learned_tokens and pair[1] in query)
                                      or (pair[1] in learned_tokens and pair[0] in query))]
                if blocked_pairs:
                    negative_relation_present = True
                def relation_score(left, right):
                    pair = tuple(sorted((left, right)))
                    known = relations.get(pair, [])
                    if any(item.get('polarity') == 'negative' for item in known):
                        return -1.0
                    if any(item.get('polarity') == 'positive' for item in known):
                        return 1.0
                    return character_similarity(left, right)
                pairs, score = _maximum_weight_pairs(learned_tokens, query, relation_score)
                positive_recognition = any(
                    item.get('polarity') == 'positive' for item in recognitions
                )
                if positive_recognition:
                    score = 1.0
                blocked = [pair for pair in pairs if pair['similarity'] < 0]
                if blocked:
                    continue
                unsafe_pairs = [
                    pair for pair in pairs
                    if 0 <= pair['similarity']
                    and not any(
                        item.get('polarity') == 'positive'
                        for item in relations.get(tuple(sorted((
                            pair['learned_token'], pair['input_token'],
                        ))), [])
                    )
                    and (
                        pair['similarity'] < MINIMUM_UNDECLARED_TOKEN_SIMILARITY
                        or not structural_token_variant(
                            pair['learned_token'], pair['input_token'],
                        )
                    )
                ]
                if unsafe_pairs and not positive_recognition:
                    unsafe_token_substitution_present = True
                    continue
                if score + 1e-12 < settings['threshold']:
                    continue
                candidates.append(dict(id=row['id'], utterance=row['display_text'], score=score,
                    pairs=pairs, representation_id=representation_id, plan=payload['plan'],
                    action_representation_id=representation_id, context=payload['context'],
                    confirmation=payload['confirmation'], validity=payload['validity'],
                    provider=payload['provider'],
                    action_link_status=payload.get('action_link_status')))
        representations = {item['representation_id'] for item in candidates}
        status = 'hit' if len(representations) == 1 else 'ambiguous' if len(representations) > 1 else 'fallback'
        selected = max(candidates, key=lambda item: (item['score'], item['id'])) if status == 'hit' else None
        match = {**base, 'status': 'shadow_hit' if status == 'hit' and settings['mode'] == 'shadow' else status,
                 'reason': 'unique_released_representation' if status == 'hit' else
                           'multiple_representations' if status == 'ambiguous' else
                           'unsafe_token_substitution' if unsafe_token_substitution_present else
                           'below_threshold_or_blocked',
                 'hit': selected if status == 'hit' and settings['mode'] == 'active' else None,
                 'shadow_candidate': selected if status == 'hit' and settings['mode'] == 'shadow' else None,
                 'candidate_count': len(candidates), 'representation_count': len(representations),
                 'checked_count': checked, 'negative_relation_present': negative_relation_present,
                 'unsafe_token_substitution_present': unsafe_token_substitution_present,
                 'truncated': truncated, 'duration_ms': (time.perf_counter() - started) * 1000}
        return match

    def _evidence(self, connection, claim_id, kind, value, source_ref, stance='supports'):
        now = _now()
        evidence_id = str(uuid.uuid4())
        connection.execute(
            '''INSERT INTO memory_evidence
            (id,claim_id,stance,evidence_type,source_ref,payload_json,observed_at,created_at)
            VALUES (?,?,?,?,?,?,?,?)''',
            (evidence_id, claim_id, stance, kind, source_ref, identity(_safe_json(value)), now, now),
        )
        return evidence_id

    @staticmethod
    def _update(c, claim_id, payload, lifecycle):
        c.execute('UPDATE memory_claims SET payload_json=?,lifecycle=?,updated_at=? WHERE id=?',
                  (identity(payload), lifecycle, _now(), claim_id))

    @lifecycle_operation("memory.semantic_links", "semantic_experience_learned")
    def learn(self, utterance, context, provider, plan, result, *, source_ref,
              provider_validated=False, supersedes=None, interpretation_utterance=None,
              published_actions=None, differential_evidence=None,
              exact_replay_authorized=False, provenance_root=None):
        if not source_ref or not plan.get('actions') or plan.get('clarification'):
            return None
        if plan.get('replay_safe') is False:
            return None
        if plan.get('context_required') or plan.get('effect') not in {'read', 'write'}:
            return None
        if any(not isinstance(a, dict) or not a.get('entity_id') for a in plan['actions']):
            return None
        claim_id, now = str(uuid.uuid4()), _now()
        assessment = plan.get('semantic_learning')
        conditions = assessment_conditions(assessment, context, interpretation_utterance or utterance, plan)
        strong = bool(conditions is not None and assessment['status'] == 'resolved'
                      and not assessment['uncertainties'] and assessment['user_grounding'] != 'unknown'
                      and provider_validated is True and result.get('status') == 'success'
                      and not plan.get('contextual_authorization'))
        payload = _safe_json(dict(
            utterance=utterance, context=context if conditions is None else conditions,
            original_context=context, interpretation_utterance=interpretation_utterance or utterance, provider=provider, plan=plan,
            semantic_assessment=assessment, assessment_valid=conditions is not None,
            strong_semantic_evidence=strong, origin_ref=source_ref,
            differential_provenance_root=source_ref if provenance_root is None else provenance_root,
            differential_origin='composition' if differential_evidence else 'planner_experience',
            differential_evidence=differential_evidence,
            provider_validated=provider_validated is True,
            technical_status=result.get('status', 'unknown'), confirmation='unconfirmed',
            usability='candidate', validity='valid',
            resource_status='validated_at_execution' if provider_validated else 'unknown',
            replay_authorization='runtime_revalidation_required', uses=0, failures=0,
            last_success=now if result.get('status') == 'success' else None, version=1))
        if payload['utterance'] != utterance or payload['original_context'] != context or payload['plan'] != plan:
            return None
        with self.database.connect() as c:
            c.execute('''INSERT INTO memory_claims
            (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
             verification_policy,created_at,updated_at)
            VALUES (?,'opaque_fact',?,?,?,?,'candidate','dynamic',?,?)''',
                      (claim_id, SCOPE, claim_id, utterance, identity(payload), now, now))
            self._evidence(c, claim_id, 'llm_interpretation', dict(plan=plan, context=context), source_ref)
            self._evidence(c, claim_id, 'provider_result', result, source_ref)
            if provider_validated:
                self._evidence(c, claim_id, 'provider_validation', {'validated': True}, source_ref)
            if conditions is not None:
                self._evidence(c, claim_id, 'llm_context_conditions',
                               {'conditions': conditions, 'assessment': assessment}, source_ref)
            if supersedes:
                old = c.execute('SELECT payload_json FROM memory_claims WHERE id=? AND scope=?', (supersedes, SCOPE)).fetchone()
                if old is None or json.loads(old[0]).get('invalidation_reason') != 'user_contradiction':
                    raise ValueError('Correction must reference an invalidated experience')
                payload['version'] = json.loads(old[0])['version'] + 1
                c.execute("INSERT INTO memory_relations VALUES (?,?,?,'supersedes',NULL,?)",
                          (str(uuid.uuid4()), claim_id, supersedes, now))
            if strong:
                self._corroborate(c, claim_id, payload)
                if exact_replay_authorized is True and payload.get('confirmation') == 'unconfirmed':
                    # The model interpretation, provider validation and verified
                    # execution jointly authorize only the byte-exact utterance.
                    # Similarity and composition retain their stronger,
                    # independent-evidence policies.
                    payload.update(
                        confirmation='operationally_grounded',
                        usability='automatic',
                        automatic_policy=EXACT_REPLAY_POLICY,
                        replay_authorization='exact_utterance_only',
                    )
                    self._evidence(c, claim_id, 'exact_replay_release', {
                        'policy': EXACT_REPLAY_POLICY,
                        'provider_validated': True,
                        'technical_status': 'success',
                    }, source_ref)
            self._link_action(c, claim_id, payload, published_actions or [])
            if (payload.get('usability') == 'automatic'
                    and payload.get('action_link_status') not in {'created', 'linked'}):
                # Technical success cannot overrule an explicit semantic
                # conflict or missing action membership. Keep the experience
                # inspectable, but require fresh model planning.
                payload.update(
                    confirmation='unconfirmed', usability='candidate',
                    replay_authorization='runtime_revalidation_required',
                )
            self._update(c, claim_id, payload, 'active' if payload['usability'] == 'automatic' else 'candidate')
        self.differential.refresh_claim(claim_id)
        return claim_id

    def action_candidates(self, provider, *, context, effect=None, resources=None,
                          representation_ids=None, limit=12):
        """Publish bounded existing meanings for the already-needed planner.

        Selection is technical (provider, exact context conditions, resources),
        never similarity between utterances. No membership implies usability.
        """
        limit = min(24, max(1, int(limit)))
        if self._inventory_scope(provider) is not None:
            self.sync_action_relations(provider)
        with self.database.connect() as c:
            where = """g.scope=? AND g.lifecycle='active'
                AND json_extract(g.payload_json,'$.binding.provider')=?
                AND json_extract(g.payload_json,'$.binding.endpoint') IS ?
                AND EXISTS (SELECT 1 FROM memory_claims m
                    JOIN memory_relations membership ON membership.from_claim_id=m.id
                        AND membership.to_claim_id=g.id AND membership.relation_type='refines'
                    WHERE m.scope=? AND m.lifecycle IN ('active','candidate')
                    AND json_extract(m.payload_json,'$.action_representation_id')=g.id
                    AND json_extract(m.payload_json,'$.validity')='valid'
                    AND json_extract(m.payload_json,'$.strong_semantic_evidence')=1
                    AND json_extract(m.payload_json,'$.action_link_status') IN ('created','linked'))"""
            args = [ACTION_SCOPE, provider.get('provider'), provider.get('endpoint'), SCOPE]
            if effect:
                where += " AND json_extract(g.payload_json,'$.representation.effect')=?"; args.append(effect)
            if resources:
                selected=list(resources)[:64]
                where += " AND EXISTS (SELECT 1 FROM json_each(g.payload_json,'$.resources') r WHERE r.value IN ("+','.join('?' for _ in selected)+"))"
                args.extend(selected)
            if representation_ids:
                selected_ids = list(dict.fromkeys(str(item) for item in representation_ids if item))[:64]
                if not selected_ids:
                    return []
                where += " AND g.id IN (" + ','.join('?' for _ in selected_ids) + ")"
                args.extend(selected_ids)
            rows = c.execute('SELECT g.id,g.payload_json FROM memory_claims g WHERE '+where+' ORDER BY g.updated_at DESC,g.id LIMIT ?',(*args,limit*4)).fetchall()
            published = []
            for row in rows:
                group = json.loads(row['payload_json'])
                if group.get('binding') != provider or (effect and group['representation']['effect'] != effect):
                    continue
                if any(k not in context or context[k] != v for k,v in group['context'].items()):
                    continue
                if resources and not set(resources) & set(group['resources']):
                    continue
                target_relations = c.execute("""SELECT r.id relation_id,b.id claim_id,
                        json_extract(b.payload_json,'$.external_reference') entity_id
                    FROM memory_relations r JOIN memory_claims b ON b.id=r.to_claim_id
                    WHERE r.from_claim_id=? AND r.relation_type='refines'
                    AND b.lifecycle='active' AND b.claim_kind='provider_binding'
                    ORDER BY entity_id,r.id""", (row['id'],)).fetchall()
                if (self._inventory_has_bindings(c, provider)
                        and {item['entity_id'] for item in target_relations} != set(group['resources'])):
                    continue
                anchors = c.execute("""SELECT m.id,m.lifecycle,m.payload_json,
                        membership.id membership_relation_id
                    FROM memory_claims m JOIN memory_relations membership
                      ON membership.from_claim_id=m.id AND membership.to_claim_id=?
                     AND membership.relation_type='refines'
                    WHERE m.scope=? AND m.lifecycle IN ('active','candidate')
                    AND json_extract(m.payload_json,'$.action_representation_id')=?
                    AND json_extract(m.payload_json,'$.validity')='valid'
                    AND json_extract(m.payload_json,'$.strong_semantic_evidence')=1
                    AND json_extract(m.payload_json,'$.action_link_status') IN ('created','linked')
                    ORDER BY m.updated_at DESC,m.id LIMIT 4""", (row['id'],SCOPE,row['id'])).fetchall()
                examples = [dict(claim_id=r['id'], utterance=json.loads(r['payload_json'])['utterance'],
                            context=json.loads(r['payload_json'])['context'], lifecycle=r['lifecycle'],
                            confirmation=json.loads(r['payload_json'])['confirmation'],
                            membership_relation_id=r['membership_relation_id']) for r in anchors]
                if not examples:
                    continue
                published.append(dict(representation_id=row['id'], representation=group['representation'],
                    provider=group['binding'], actions=group['actions'], conditions=group['context'],
                    examples=examples,
                    target_relations=[dict(relation_id=item['relation_id'], claim_id=item['claim_id'],
                                           entity_id=item['entity_id']) for item in target_relations],
                    evidence_policy=LINK_POLICY, replay_authorization='per_formulation_only'))
                if len(published) == limit:
                    break
            if representation_ids:
                order = {str(value): index for index, value in enumerate(representation_ids)}
                published.sort(key=lambda item: order.get(item['representation_id'], len(order)))
            return published

    def _link_action(self, c, claim_id, payload, published):
        declaration = (payload.get('semantic_assessment') or {}).get('action_link')
        payload['action_link_status'] = 'insufficient_evidence'
        reason = 'missing_explicit_llm_equivalence'
        def unavailable(code, *, conflict=False):
            payload['action_link_status'] = 'conflict' if conflict else 'insufficient_evidence'
            payload['action_link_reason'] = code
            if declaration is None:
                return
            self._evidence(c, claim_id, 'semantic_action_conflict' if conflict else 'semantic_action_unlinked',
                           {'reason':code, 'declaration':declaration}, payload['origin_ref'],
                           'contradicts' if conflict else 'supports')
        if not payload['strong_semantic_evidence'] or not isinstance(declaration, dict):
            unavailable(reason); return
        kind = declaration.get('kind')
        if (kind not in {'new','existing'} or not isinstance(declaration.get('basis'),str)
                or not declaration['basis'].strip() or len(declaration['basis']) > 2000):
            unavailable('insufficient_llm_declaration'); return
        # Previously rejected meanings never regain membership through a group.
        rejected = c.execute("""SELECT payload_json FROM memory_claims WHERE scope=? AND display_text=?
            AND json_extract(payload_json,'$.invalidation_reason')='user_contradiction'""",
            (SCOPE,payload['utterance'])).fetchall()
        if any(json.loads(r[0])['provider']==payload['provider'] and
               action_identity(json.loads(r[0])['plan'])==action_identity(payload['plan']) for r in rejected):
            unavailable('prior_user_contradiction',conflict=True); return
        now = _now()
        if kind == 'new':
            meaning = declaration.get('meaning')
            if (not isinstance(meaning,str) or not meaning.strip() or len(meaning)>512
                    or declaration.get('representation_id') or declaration.get('anchor_claim_id')):
                unavailable('invalid_new_representation'); return
            group_id = str(uuid.uuid4())
            group = _safe_json(dict(representation={'meaning':meaning,'effect':payload['plan']['effect']},
                binding=payload['provider'], actions=payload['plan']['actions'], context=payload['context'],
                resources=sorted({a['entity_id'] for a in payload['plan']['actions']}),
                origin_claim_id=claim_id, origin_ref=payload['origin_ref'], policy=LINK_POLICY,
                execution_authorization='none'))
            c.execute("""INSERT INTO memory_claims
                (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,verification_policy,created_at,updated_at)
                VALUES (?,'opaque_fact',?,?,?,?,'active','dynamic',?,?)""",
                (group_id,ACTION_SCOPE,group_id,meaning,identity(group),now,now))
            self._evidence(c,group_id,'semantic_action_origin',{'claim_id':claim_id,'declaration':declaration},payload['origin_ref'])
            payload['action_link_status'] = 'created'
        else:
            group_id, anchor_id = declaration.get('representation_id'), declaration.get('anchor_claim_id')
            match = next((g for g in published if g.get('representation_id') == group_id
                          and any(e.get('claim_id')==anchor_id for e in g.get('examples',[]))),None)
            if match is None:
                unavailable('reference_not_published'); return
            row = c.execute("SELECT payload_json FROM memory_claims WHERE scope=? AND id=? AND lifecycle='active'",
                            (ACTION_SCOPE,group_id)).fetchone()
            anchor = c.execute("SELECT payload_json,lifecycle FROM memory_claims WHERE scope=? AND id=?",(SCOPE,anchor_id)).fetchone()
            if not row or not anchor:
                unavailable('reference_missing',conflict=True); return
            group, reference = json.loads(row[0]), json.loads(anchor[0])
            if (reference.get('action_representation_id') != group_id or reference['validity']!='valid'
                    or not reference.get('strong_semantic_evidence') or reference['confirmation']=='contradicted'
                    or reference.get('action_link_status') not in {'created','linked'}
                    or reference['origin_ref']==payload['origin_ref']):
                unavailable('anchor_invalid',conflict=True); return
            if (group['binding']!=payload['provider'] or reference['provider']!=payload['provider']
                    or group['context']!=payload['context'] or reference['context']!=payload['context']
                    or identity(group['actions'])!=identity(payload['plan']['actions'])
                    or group['representation']['effect']!=payload['plan']['effect']
                    or action_identity(reference['plan'])!=action_identity(payload['plan'])):
                unavailable('operational_or_context_mismatch',conflict=True); return
            # The declaration references a published meaning + concrete prior
            # interpretation; equal provider calls are only a safety constraint.
            self._evidence(c,group_id,'semantic_action_support',
                           {'claim_id':claim_id,'anchor_claim_id':anchor_id,'declaration':declaration},payload['origin_ref'])
            payload['action_link_status'] = 'linked'
        evidence = self._evidence(c,claim_id,'semantic_action_membership',
            {'representation_id':group_id,'policy':LINK_POLICY,'declaration':declaration,
             'operational_identity_validated':True,'context':payload['context']},payload['origin_ref'])
        membership_relation_id = uuid.uuid5(
            _RELATION_NAMESPACE, f'action-membership:{claim_id}:{group_id}'
        ).hex
        c.execute("""INSERT OR IGNORE INTO memory_relations
            (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
            VALUES (?,?,?,'refines',?,?)""",
            (membership_relation_id,claim_id,group_id,evidence,now))
        target_relation_ids = self._ensure_action_targets(c, group_id, group, now=now)
        payload.update(action_representation_id=group_id, action_representation=group['representation'],
                       action_link_policy=LINK_POLICY,
                       action_membership_relation_id=membership_relation_id)
        if target_relation_ids:
            payload.update(action_target_relation_ids=target_relation_ids,
                           action_target_relation_policy=ACTION_TARGET_POLICY)

    def _invalidate_membership(self, c, claim_id, payload, source_ref, reason):
        if payload.get('action_representation_id') and payload.get('action_link_status')!='invalid':
            payload['action_link_status'] = 'invalid'
            self._evidence(c,claim_id,'semantic_action_membership_invalidated',
                {'representation_id':payload['action_representation_id'],'reason':reason},source_ref,'contradicts')
            self._evidence(c,payload['action_representation_id'],'semantic_action_member_invalidated',
                {'claim_id':claim_id,'reason':reason},source_ref,'contradicts')

    def _corroborate(self, c, claim_id, payload):
        rows = c.execute('SELECT id,lifecycle,payload_json FROM memory_claims WHERE scope=? AND display_text=? AND id<>?',
                         (SCOPE, payload['utterance'], claim_id)).fetchall()
        peers = [(r, json.loads(r['payload_json'])) for r in rows]
        signature = action_identity(payload['plan'])
        # A repudiated interpretation cannot regain automatic usability by repetition.
        if any(p['provider'] == payload['provider'] and p.get('invalidation_reason') == 'user_contradiction'
               and action_identity(p['plan']) == signature for _, p in peers):
            return
        relevant = [(r, p) for r, p in peers if p['provider'] == payload['provider']
                    and p['context'] == payload['context'] and p['validity'] == 'valid'
                    and r['lifecycle'] in {'candidate', 'active'}]
        conflicting = [
            (r, p) for r, p in relevant
            if authoritative_interpretation(p) and action_identity(p['plan']) != signature
        ]
        if conflicting:
            self._evidence(c, claim_id, 'conflicting_interpretations',
                           {'claim_ids': [r['id'] for r, _ in conflicting]}, payload['origin_ref'])
            return
        support = [(r, p) for r, p in relevant if p.get('strong_semantic_evidence') is True
                   and p.get('origin_ref') and p['origin_ref'] != payload['origin_ref']]
        if not support:
            return
        payload.update(confirmation='corroborated', usability='automatic', automatic_policy=POLICY)
        evidence_id = self._evidence(c, claim_id, 'automatic_release',
            {'policy': POLICY, 'supporting_claim_ids': [r['id'] for r, _ in support]}, payload['origin_ref'])
        for r, p in relevant:
            c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (_now(), r['id']))
            c.execute("INSERT INTO memory_relations VALUES (?,?,?,'refines',?,?)",
                      (str(uuid.uuid4()), claim_id, r['id'], evidence_id, _now()))

    def experience(self, claim_id):
        with self.database.connect() as c:
            row = c.execute('SELECT id,lifecycle,created_at,payload_json FROM memory_claims WHERE scope=? AND id=?', (SCOPE,claim_id)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            return dict(id=row['id'],lifecycle=row['lifecycle'],created_at=row['created_at'],**json.loads(row['payload_json']))

    def export(self):
        with self.database.connect() as c:
            rows = c.execute('SELECT * FROM memory_claims WHERE scope=? ORDER BY created_at,id', (SCOPE,)).fetchall()
            return [dict(id=r['id'], lifecycle=r['lifecycle'], created_at=r['created_at'],
                         **json.loads(r['payload_json']), evidence=[dict(e) for e in c.execute(
                             'SELECT * FROM memory_evidence WHERE claim_id=? ORDER BY created_at', (r['id'],))],
                         relations=[dict(e) for e in c.execute(
                             'SELECT * FROM memory_relations WHERE from_claim_id=? OR to_claim_id=?', (r['id'], r['id']))]) for r in rows]

    @lifecycle_operation("memory.semantic_links", "semantic_decision")
    def decide(self, claim_id, *, confirmed, source_ref, supersedes=None, context_independent=False,
               decision_evidence=None, _connection=None):
        if type(confirmed) is not bool or not source_ref:
            raise ValueError('Explicit decision and source reference required')
        with nullcontext(_connection) if _connection is not None else self.database.connect() as c:
            row = c.execute('SELECT * FROM memory_claims WHERE id=? AND scope=?', (claim_id, SCOPE)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            p = json.loads(row['payload_json'])
            if confirmed and (p['validity'] != 'valid' or row['lifecycle'] == 'retired'):
                raise ValueError('Invalid or superseded link requires a new interpretation')
            if supersedes:
                old = c.execute('SELECT payload_json FROM memory_claims WHERE id=? AND scope=?', (supersedes, SCOPE)).fetchone()
                if old is None:
                    raise KeyError(supersedes)
                p['version'] = json.loads(old[0])['version'] + 1
                c.execute("UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id=?", (_now(), supersedes))
                c.execute("INSERT INTO memory_relations VALUES (?,?,?,'supersedes',NULL,?)",
                          (str(uuid.uuid4()), claim_id, supersedes, _now()))
            if context_independent:
                if not confirmed:
                    raise ValueError('Context release requires confirmation')
                if set(p['context']) & {'history','focus'}:
                    self._invalidate_membership(c,claim_id,p,source_ref,'explicit_context_conditions_changed')
                p['context'] = {k: v for k, v in p['context'].items() if k not in {'history', 'focus'}}
                self._evidence(c, claim_id, 'user_context_release',
                    {'released_conditions': ['history', 'focus']}, source_ref)
            p.update(confirmation='confirmed' if confirmed else 'contradicted',
                     usability='explicit' if confirmed else 'blocked')
            if not confirmed:
                p.update(validity='invalid', invalidation_reason='user_contradiction')
                self._invalidate_membership(c,claim_id,p,source_ref,'user_contradiction')
            evidence_id = self._evidence(c, claim_id, 'user_confirmation' if confirmed else 'user_correction',
                {'confirmed': confirmed, 'dialog_decision': decision_evidence}, source_ref,
                'supports' if confirmed else 'contradicts')
            self._update(c, claim_id, p, 'active' if confirmed else 'invalid')
            if not confirmed:
                # Retired corroborating observations and their active descendants
                # describe the same exact experience; propagate a causal contradiction.
                signature = action_identity(p['plan'])
                others = c.execute('SELECT id,payload_json FROM memory_claims WHERE scope=? AND display_text=? AND id<>?',
                                   (SCOPE, p['utterance'], claim_id)).fetchall()
                for r in others:
                    peer = json.loads(r['payload_json'])
                    if (peer['provider'] == p['provider'] and peer['context'] == p['context']
                            and action_identity(peer['plan']) == signature):
                        peer.update(validity='invalid', confirmation='contradicted', usability='blocked',
                                    invalidation_reason='user_contradiction')
                        self._invalidate_membership(c,r['id'],peer,source_ref,'user_contradiction')
                        self._update(c, r['id'], peer, 'invalid')
                        self._evidence(c, r['id'], 'user_correction',
                            {'causal_claim_id': claim_id, 'causal_evidence_id': evidence_id}, source_ref, 'contradicts')
                        self.differential.refresh_claim(r['id'], _connection=c)
            self.differential.refresh_claim(claim_id, _connection=c)

    @lifecycle_operation("memory.semantic_links", "execution_feedback")
    def execution_feedback(self, conversation_id, assistant_message_id, decision, explanation=None):
        """Apply or retract explicit UI feedback for one persisted action turn.

        The message/turn/claim relationship is derived from trusted persistence;
        callers never choose the claim.  Undo reverts only fields changed by this
        feedback, so later technical counters remain intact.
        """
        if decision not in {'correct', 'incorrect', 'undo'}:
            raise ValueError('Feedback must be correct, incorrect or undo')
        if explanation is not None:
            if not isinstance(explanation, str):
                raise ValueError('Feedback explanation must be text')
            explanation = explanation.strip()
            if not explanation:
                explanation = None
            elif decision != 'incorrect':
                raise ValueError('Only incorrect feedback accepts an explanation')
            elif len(explanation) > 1000:
                raise ValueError('Feedback explanation is too long')
        conversation_id, assistant_message_id = str(conversation_id), str(assistant_message_id)
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            message = c.execute('''SELECT m.*,t.id AS persisted_turn_id,u.content AS user_content
                FROM messages m LEFT JOIN turns t ON t.assistant_message_id=m.id
                LEFT JOIN messages u ON u.id=t.user_message_id
                WHERE m.id=? AND m.conversation_id=? AND m.role='assistant' ''',
                (assistant_message_id, conversation_id)).fetchone()
            if message is None:
                raise KeyError(assistant_message_id)
            lifecycle_turn_id = message['turn_id'] or message['persisted_turn_id']
            set_connection_lifecycle_origin(
                c,
                trace_id=lifecycle_turn_id,
                turn_id=lifecycle_turn_id,
                conversation_id=conversation_id,
                operation_id=f"semantic-feedback:{assistant_message_id}:{decision}",
                producer="memory.semantic_links",
                reason_code="execution_feedback",
            )
            metadata = json.loads(message['metadata_json'])
            current_feedback = metadata.get('semantic_feedback')

            if decision == 'undo':
                if not isinstance(current_feedback, dict) or current_feedback.get('status') != 'active':
                    raise ValueError('No action feedback to undo')
                claim_id = current_feedback.get('claim_id')
                source_ref = current_feedback.get('source_ref')
                record = c.execute('''SELECT payload_json FROM memory_evidence
                    WHERE claim_id=? AND source_ref=? AND evidence_type='ui_execution_feedback'
                    ORDER BY created_at DESC,id DESC LIMIT 1''', (claim_id, source_ref)).fetchone()
                if record is None:
                    raise ValueError('Feedback transaction is incomplete')
                transaction = json.loads(record['payload_json'])
                if (transaction.get('conversation_id') != conversation_id
                        or transaction.get('assistant_message_id') != assistant_message_id):
                    raise ValueError('Feedback transaction does not belong to this message')
                for before, after in zip(transaction.get('before', []), transaction.get('after', []), strict=True):
                    if before.get('id') != after.get('id'):
                        raise ValueError('Feedback transaction is inconsistent')
                    row = c.execute('SELECT lifecycle,payload_json FROM memory_claims WHERE id=? AND scope=?',
                                    (before['id'], SCOPE)).fetchone()
                    if row is None:
                        raise ValueError('Feedback target no longer exists')
                    payload = json.loads(row['payload_json'])
                    before_payload, after_payload = before['payload'], after['payload']
                    missing = object()
                    changed = {key for key in set(before_payload) | set(after_payload)
                               if before_payload.get(key, missing) != after_payload.get(key, missing)}
                    for key in changed:
                        if payload.get(key, missing) != after_payload.get(key, missing):
                            raise ValueError('Semantic state changed after feedback')
                        if key in before_payload:
                            payload[key] = before_payload[key]
                        else:
                            payload.pop(key, None)
                    if row['lifecycle'] != after['lifecycle']:
                        raise ValueError('Semantic lifecycle changed after feedback')
                    self._update(c, before['id'], payload, before['lifecycle'])
                undo_ref = f'ui-feedback-undo:{assistant_message_id}:{uuid.uuid4().hex}'
                for relation_id in transaction.get('created_similarity_relation_ids', []):
                    relation = c.execute('SELECT lifecycle FROM memory_claims WHERE id=? AND scope=?',
                                         (relation_id, SIMILARITY_RELATION_SCOPE)).fetchone()
                    if relation is not None and relation['lifecycle'] == 'active':
                        self.retract_similarity_relation(relation_id, source_ref=undo_ref, _connection=c)
                c.execute('DELETE FROM memory_evidence WHERE source_ref=?', (source_ref,))
                self._evidence(c, claim_id, 'ui_execution_feedback_retracted', {
                    'conversation_id': conversation_id,
                    'assistant_message_id': assistant_message_id,
                    'retracted_source_ref': source_ref,
                }, undo_ref)
                c.execute('''UPDATE memory_evidence SET source_turn_id=?,source_message_id=?
                    WHERE source_ref=?''',
                    (message['turn_id'] or message['persisted_turn_id'], assistant_message_id, undo_ref))
                metadata.pop('semantic_feedback', None)
                c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                          (identity(metadata), assistant_message_id))
                for snapshot in transaction.get('before', []):
                    self.differential.refresh_claim(snapshot['id'], _connection=c)
                return {'decision': None, 'can_undo': False}

            if current_feedback:
                if (decision == 'incorrect' and explanation
                        and current_feedback.get('status') == 'active'
                        and current_feedback.get('decision') == 'incorrect'):
                    claim_id = current_feedback.get('claim_id')
                    source_ref = current_feedback.get('source_ref')
                    if not claim_id or not source_ref:
                        raise ValueError('Feedback transaction is incomplete')
                    self._evidence(c, claim_id, 'ui_execution_feedback_explanation', {
                        'conversation_id': conversation_id,
                        'assistant_message_id': assistant_message_id,
                        'explanation': explanation,
                    }, source_ref, 'contradicts')
                    c.execute('''UPDATE memory_evidence SET source_turn_id=?,source_message_id=?
                        WHERE claim_id=? AND source_ref=? AND evidence_type='ui_execution_feedback_explanation'
                        AND source_turn_id IS NULL''',
                        (lifecycle_turn_id, assistant_message_id, claim_id, source_ref))
                    current_feedback['explanation'] = explanation
                    metadata['semantic_feedback'] = current_feedback
                    c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                              (identity(metadata), assistant_message_id))
                    return {'decision': decision, 'can_undo': True,
                            'explanation': explanation}
                raise ValueError('Action feedback already exists')
            details = metadata.get('turn_state_details')
            if (metadata.get('turn_state') != 'operational_resolved'
                    or not isinstance(details, dict)
                    or details.get('operational_execution') is not True):
                raise ValueError('Message is not a successfully executed action')
            claim_id = details.get('semantic_link_candidate_id') or details.get('semantic_link_id')
            turn_id = message['turn_id'] or message['persisted_turn_id']
            if not claim_id or not turn_id:
                raise ValueError('Message has no semantic action reference')
            claim = c.execute('SELECT lifecycle,display_text,payload_json FROM memory_claims WHERE id=? AND scope=?',
                              (claim_id, SCOPE)).fetchone()
            if claim is None:
                raise KeyError(claim_id)
            if c.execute('''SELECT 1 FROM memory_evidence WHERE claim_id=?
                    AND source_turn_id=? AND evidence_type IN ('provider_result','reuse_result') LIMIT 1''',
                    (claim_id, turn_id)).fetchone() is None:
                raise ValueError('Claim is not linked to this executed turn')

            main_payload = json.loads(claim['payload_json'])
            similarity = details.get('semantic_similarity')
            dynamic_feedback = (isinstance(similarity, dict)
                                and similarity.get('semantic_reuse') == 'similarity'
                                and similarity.get('learned_claim_id') == claim_id
                                and similarity.get('action_representation_id')
                                    == main_payload.get('action_representation_id'))
            affected_ids = [claim_id]
            if decision == 'incorrect' and not dynamic_feedback:
                peers = c.execute('SELECT id,payload_json FROM memory_claims WHERE scope=? AND display_text=? AND id<>?',
                                  (SCOPE, claim['display_text'], claim_id)).fetchall()
                signature = action_identity(main_payload['plan'])
                affected_ids.extend(r['id'] for r in peers if
                    (lambda p: p['provider'] == main_payload['provider']
                     and p['context'] == main_payload['context']
                     and action_identity(p['plan']) == signature)(json.loads(r['payload_json'])))

            def snapshots(ids):
                result = []
                for item_id in ids:
                    row = c.execute('SELECT lifecycle,payload_json FROM memory_claims WHERE id=? AND scope=?',
                                    (item_id, SCOPE)).fetchone()
                    if row is None:
                        raise ValueError('Feedback target no longer exists')
                    result.append({'id': item_id, 'lifecycle': row['lifecycle'],
                                   'payload': json.loads(row['payload_json'])})
                return result

            before = snapshots(affected_ids)
            source_ref = f'ui-feedback:{assistant_message_id}:{uuid.uuid4().hex}'
            created_similarity_relation_ids = []
            if dynamic_feedback:
                if not message['user_content']:
                    raise ValueError('Similarity feedback has no persisted user formulation')
                relation_ref = source_ref + ':similarity'
                previous_ids = {
                    item['id'] for item in self._active_similarity_recognitions(
                        c, main_payload['action_representation_id'])
                    if item.get('learned_claim_id') == claim_id
                    and item.get('input_tokens') == surface_tokens(message['user_content'])
                    and item.get('polarity') == ('positive' if decision == 'correct' else 'negative')
                }
                relation_id = self.record_similarity_recognition(
                    message['user_content'], claim_id,
                    'positive' if decision == 'correct' else 'negative',
                    source_ref=relation_ref,
                    basis='Explizite Bewertung der ausgeführten dynamischen Zuordnung.',
                    source_turn_id=turn_id, source_message_id=assistant_message_id, _connection=c)
                if relation_id not in previous_ids:
                    created_similarity_relation_ids.append(relation_id)
                # A false similarity decision invalidates only this recognition.
                # The learned source action remains valid for its original formulation.
                if decision == 'correct':
                    self.decide(claim_id, confirmed=True, source_ref=source_ref,
                                decision_evidence={'source': 'action_feedback_ui', 'decision': decision,
                                                   'recognition_relation_id': relation_id,
                                                   'conversation_id': conversation_id,
                                                   'assistant_message_id': assistant_message_id}, _connection=c)
            else:
                self.decide(claim_id, confirmed=decision == 'correct', source_ref=source_ref,
                            decision_evidence={'source': 'action_feedback_ui', 'decision': decision,
                                               'conversation_id': conversation_id,
                                               'assistant_message_id': assistant_message_id}, _connection=c)
            after = snapshots(affected_ids)
            self._evidence(c, claim_id, 'ui_execution_feedback', {
                'conversation_id': conversation_id,
                'assistant_message_id': assistant_message_id,
                'decision': decision,
                'before': before,
                'after': after,
                'dynamic_similarity': dynamic_feedback,
                'created_similarity_relation_ids': created_similarity_relation_ids,
                'explanation': explanation,
            }, source_ref, 'supports' if decision == 'correct' else 'contradicts')
            c.execute('''UPDATE memory_evidence SET source_turn_id=?,source_message_id=?
                WHERE source_ref=?''', (turn_id, assistant_message_id, source_ref))
            feedback = {'status': 'active', 'decision': decision, 'claim_id': claim_id,
                        'source_ref': source_ref, 'created_at': _now()}
            if explanation:
                feedback['explanation'] = explanation
            metadata['semantic_feedback'] = feedback
            c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                      (identity(metadata), assistant_message_id))
            response = {'decision': decision, 'can_undo': True}
            if explanation:
                response['explanation'] = explanation
            return response

    @lifecycle_operation("memory.semantic_links", "semantic_lookup_corroboration")
    def lookup(self, utterance, context, provider):
        if self._inventory_scope(provider) is not None:
            self.sync_action_relations(provider)
        with self.database.connect() as c:
            def relation_grounded(claim_id, payload):
                representation_id = payload.get('action_representation_id')
                if not representation_id:
                    return True
                membership = c.execute(
                    """SELECT 1 FROM memory_relations r JOIN memory_claims g ON g.id=r.to_claim_id
                       WHERE r.from_claim_id=? AND r.to_claim_id=? AND r.relation_type='refines'
                       AND g.scope=? AND g.lifecycle='active'""",
                    (claim_id, representation_id, ACTION_SCOPE),
                ).fetchone()
                if membership is None:
                    return False
                if not self._inventory_has_bindings(c, provider):
                    return True
                targets = {str(action.get('entity_id')) for action in payload['plan'].get('actions', [])
                           if isinstance(action, dict) and action.get('entity_id')}
                rows = c.execute(
                    """SELECT json_extract(binding.payload_json,'$.external_reference') entity_id
                       FROM memory_relations r JOIN memory_claims binding ON binding.id=r.to_claim_id
                       WHERE r.from_claim_id=? AND r.relation_type='refines'
                       AND binding.lifecycle='active' AND binding.claim_kind='provider_binding'""",
                    (representation_id,),
                ).fetchall()
                return targets == {row['entity_id'] for row in rows}
            rows = c.execute("SELECT id,lifecycle,created_at,payload_json FROM memory_claims WHERE scope=? AND lifecycle IN ('active','candidate') AND display_text=? ORDER BY created_at,id", (SCOPE, utterance)).fetchall()
            compatible = [(r['id'], r['lifecycle'], r['created_at'], json.loads(r['payload_json'])) for r in rows]
            compatible = [(i, state, created_at, p) for i, state, created_at, p in compatible if p['utterance'] == utterance
                          and all(k in context and context[k] == v for k, v in p['context'].items())
                          and p['provider'] == provider and p['validity'] == 'valid']
            matches = [(i, p) for i, state, _created_at, p in compatible if state == 'active'
                       and p['confirmation'] in {
                           'confirmed', 'corroborated', 'operationally_grounded',
                       }
                       and (
                           (
                               p['confirmation'] == 'confirmed'
                               and (
                                   p.get('action_link_status') not in {'created', 'linked'}
                                   or relation_grounded(i, p)
                               )
                           )
                           or (
                               p.get('action_link_status') in {'created', 'linked'}
                               and relation_grounded(i, p)
                           )
                       )]
            if not matches:
                strong = [(i, created_at, p) for i, state, created_at, p in compatible
                          if state == 'candidate' and p.get('strong_semantic_evidence') is True
                          and p.get('action_link_status') in {'created', 'linked'}
                          and relation_grounded(i, p)]
                signatures = {action_identity(p['plan']) for _i, _created_at, p in strong}
                origins = {p.get('origin_ref') for _i, _created_at, p in strong if p.get('origin_ref')}
                if len(signatures) == 1 and len(origins) >= 2:
                    claim_id, _created_at, payload = strong[-1]
                    self._corroborate(c, claim_id, payload)
                    if payload.get('confirmation') == 'corroborated':
                        self._update(c, claim_id, payload, 'active')
                        matches = [(claim_id, payload)]
            if len(matches) != 1:
                return None
            signature = action_identity(matches[0][1]['plan'])
            if any(authoritative_interpretation(p) and p.get('assessment_valid')
                   and (action_identity(p['plan']) != signature
                        or p.get('semantic_assessment', {}).get('uncertainties'))
                   for _, _, _, p in compatible):
                return None
            claim_id, selected = matches[0]
            relation_ids = []
            representation_id = selected.get('action_representation_id')
            if representation_id:
                relation_ids = [row['id'] for row in c.execute(
                    """SELECT id FROM memory_relations
                       WHERE (from_claim_id=? AND to_claim_id=? AND relation_type='refines')
                          OR (from_claim_id=? AND relation_type='refines')
                       ORDER BY id""",
                    (claim_id, representation_id, representation_id),
                ).fetchall()]
            return dict(id=claim_id, **selected, memory_relation_ids=relation_ids)

    @lifecycle_operation("memory.semantic_links", "semantic_execution_result")
    def feedback(self, claim_id, result, *, source_ref, invalid_reason=None):
        if invalid_reason not in {None, 'resource_missing', 'service_missing'}:
            raise ValueError('Invalid technical invalidation reason')
        with self.database.connect() as c:
            row = c.execute('SELECT lifecycle,payload_json FROM memory_claims WHERE id=? AND scope=?', (claim_id, SCOPE)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            p = json.loads(row['payload_json'])
            p['technical_status'] = result.get('status', 'unknown')
            if p['technical_status'] == 'success':
                p['uses'] += 1
                p['last_success'] = _now()
            else:
                p['failures'] += 1
            if invalid_reason:
                p.update(validity='invalid', resource_status='invalid', usability='blocked', invalidation_reason=invalid_reason)
                self._invalidate_membership(c,claim_id,p,source_ref,invalid_reason)
            self._update(c, claim_id, p, 'invalid' if invalid_reason else row['lifecycle'])
            self._evidence(c, claim_id, 'reuse_result', result, source_ref)
            self.differential.refresh_claim(claim_id, _connection=c)

    def attach_turn_provenance(self, source_ref, turn_id, user_message_id):
        with self.database.connect() as c:
            c.execute("""UPDATE memory_evidence SET source_turn_id=?,
                source_message_id=CASE WHEN evidence_type IN ('user_confirmation','user_correction','llm_interpretation',
                                      'explicit_language_relation','explicit_language_relation_reaffirmed',
                                      'explicit_language_relation_correction','explicit_language_relation_undo',
                                      'explicit_action_resource_relation',
                                      'explicit_action_resource_relation_reaffirmed')
                                      THEN ? ELSE source_message_id END
                WHERE source_ref=? AND claim_id IN (SELECT id FROM memory_claims WHERE scope IN (?,?,?,?))""",
                      (turn_id, user_message_id, source_ref, SCOPE, ACTION_SCOPE,
                       SIMILARITY_RELATION_SCOPE, LANGUAGE_RELATION_SCOPE))

    def record_occurrence(self, claim_id, *, conversation_id, turn_ref, utterance, similarity=None):
        with self.database.connect() as c:
            self._evidence(c, claim_id, 'dialog_occurrence',
                           {'conversation_id': conversation_id, 'utterance': utterance,
                            'similarity': _safe_json(similarity) if similarity else None}, turn_ref)

    def dialog_references(self, conversation_id, *, limit=24):
        if not conversation_id:
            return []
        with self.database.connect() as c:
            rows = c.execute('''SELECT e.source_ref,e.payload_json,c.id,c.payload_json AS claim_payload,c.lifecycle,c.updated_at
                FROM memory_evidence e JOIN memory_claims c ON c.id=e.claim_id
                WHERE c.scope=? AND e.evidence_type='dialog_occurrence'
                AND json_extract(e.payload_json,'$.conversation_id')=?
                ORDER BY e.created_at DESC,e.id DESC LIMIT ?''', (SCOPE, conversation_id, limit)).fetchall()
            return [dict(link_id=r['id'], occurrence_ref=r['source_ref'], lifecycle=r['lifecycle'], version=json.loads(r['claim_payload']).get('version',1),
                         claim_updated_at=r['updated_at'], interaction_status='completed', expects_feedback=False,
                         utterance=json.loads(r['payload_json'])['utterance'],
                         similarity=json.loads(r['payload_json']).get('similarity'),
                         plan={k: v for k, v in json.loads(r['claim_payload'])['plan'].items()
                               if k in {'effect', 'actions', 'interpreted_target'}},
                         technical_status=json.loads(r['claim_payload'])['technical_status']) for r in rows]

    def execution_corrections(self, provider, *, limit=12):
        """Publish bounded user explanations for later semantic replanning."""
        limit = min(24, max(1, int(limit)))
        with self.database.connect() as c:
            resolved_rows = c.execute('''SELECT id,created_at,payload_json FROM memory_claims
                WHERE scope=? AND lifecycle IN ('active','candidate')
                AND json_extract(payload_json,'$.validity')='valid'
                AND json_extract(payload_json,'$.technical_status')='success'
                ORDER BY created_at DESC,id DESC LIMIT 256''', (SCOPE,)).fetchall()
            resolved = [
                (row['created_at'], json.loads(row['payload_json'])) for row in resolved_rows
            ]
            rows = c.execute('''SELECT e.id,e.claim_id,e.source_ref,e.evidence_type,
                    e.payload_json,e.created_at,c.payload_json AS claim_payload
                FROM memory_evidence e JOIN memory_claims c ON c.id=e.claim_id
                WHERE c.scope=? AND c.lifecycle='invalid'
                AND json_extract(c.payload_json,'$.invalidation_reason')='user_contradiction'
                AND e.evidence_type IN ('ui_execution_feedback','ui_execution_feedback_explanation')
                ORDER BY e.created_at DESC,e.id DESC LIMIT ?''',
                (SCOPE, limit * 8)).fetchall()
            published = []
            seen = set()
            for row in rows:
                key = (row['claim_id'], row['source_ref'])
                if key in seen:
                    continue
                evidence = json.loads(row['payload_json'])
                explanation = evidence.get('explanation')
                if not isinstance(explanation, str) or not explanation.strip():
                    continue
                claim = json.loads(row['claim_payload'])
                if claim.get('provider') != provider:
                    continue
                if any(
                    created_at > row['created_at']
                    and payload.get('provider') == provider
                    and payload.get('utterance') == claim.get('utterance')
                    for created_at, payload in resolved
                ):
                    # A later provider-verified interpretation for the exact
                    # formulation has incorporated this correction.
                    continue
                plan = claim.get('plan') if isinstance(claim.get('plan'), dict) else {}
                published.append({
                    'correction_id': row['id'],
                    'rejected_utterance': claim.get('utterance'),
                    'explanation': explanation.strip(),
                    'rejected_plan': {
                        key: deepcopy(plan[key]) for key in (
                            'effect', 'actions', 'interpreted_target',
                        ) if key in plan
                    },
                    'created_at': row['created_at'],
                })
                seen.add(key)
                if len(published) == limit:
                    break
            return published

    def apply_dialog_decision(self, decision, *, utterance, conversation_id, source_ref, published):
        if not isinstance(decision, dict) or decision.get('type') not in {'confirm', 'contradict'}:
            raise ValueError('No concrete semantic decision')
        evidence = decision.get('causal_evidence')
        if (decision.get('reason') != 'explicit_feedback'
                or not isinstance(decision.get('basis'), str) or not decision['basis'].strip()
                or type(decision.get('replan')) is not bool
                or decision.get('current_turn_ref') != source_ref or not source_ref
                or decision.get('user_quote') != utterance or not utterance
                or not isinstance(evidence, dict) or evidence.get('feedback_only') is not True
                or evidence.get('explicit_evaluation') is not True or evidence.get('uncertainties') != []
                or decision.get('clarification') is not None
                or decision['type']=='confirm' and decision['replan']):
            raise ValueError('Insufficient causal feedback evidence')
        key = (decision.get('link_id'), decision.get('occurrence_ref'))
        reference = next((r for r in published if (r['link_id'], r['occurrence_ref'])==key), None)
        if not reference or key[1]==source_ref or evidence.get('antecedent_quote')!=reference['utterance']:
            raise ValueError('Decision reference is not a published causal occurrence')
        # Revalidate the exact occurrence and claim snapshot inside the mutation
        # transaction; never redirect a retired reference to a different claim.
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM memory_evidence WHERE source_ref=? LIMIT 1", (source_ref,)).fetchone():
                raise ValueError('Current turn already applied a feedback decision')
            row=c.execute("SELECT lifecycle,payload_json,updated_at FROM memory_claims WHERE id=? AND scope=?",(key[0],SCOPE)).fetchone()
            occurrence=c.execute("""SELECT 1 FROM memory_evidence WHERE claim_id=? AND source_ref=?
                AND evidence_type='dialog_occurrence' AND json_extract(payload_json,'$.conversation_id')=?
                AND json_extract(payload_json,'$.utterance')=?""",(key[0],key[1],conversation_id,reference['utterance'])).fetchone()
            if not row or not occurrence:
                raise ValueError('Missing or foreign feedback reference')
            payload=json.loads(row['payload_json'])
            if (row['lifecycle']!=reference.get('lifecycle') or row['updated_at']!=reference.get('claim_updated_at')
                    or payload.get('version',1)!=reference.get('version')
                    or row['lifecycle'] not in {'candidate','active','retired'} or payload.get('validity')!='valid'
                    or decision['type']=='confirm' and row['lifecycle']=='retired'):
                raise ValueError('Stale or inadmissible feedback reference')
            similarity = reference.get('similarity')
            dynamic = (isinstance(similarity, dict)
                       and similarity.get('semantic_reuse') == 'similarity'
                       and similarity.get('learned_claim_id') == key[0]
                       and similarity.get('action_representation_id')
                           == payload.get('action_representation_id'))
            if dynamic:
                relation_id = self.record_similarity_recognition(
                    reference['utterance'], key[0],
                    'positive' if decision['type'] == 'confirm' else 'negative',
                    source_ref=source_ref, basis=decision['basis'], _connection=c)
                if decision['type'] == 'confirm':
                    self.decide(key[0], confirmed=True, source_ref=source_ref + ':claim',
                        decision_evidence={**decision, 'recognition_relation_id': relation_id,
                                           'conversation_id': conversation_id,
                                           'user_utterance': utterance}, _connection=c)
            else:
                self.decide(key[0], confirmed=decision['type']=='confirm', source_ref=source_ref,
                    decision_evidence={**decision,'conversation_id':conversation_id,'user_utterance':utterance}, _connection=c)
        return key[0]

    def maintenance_report(self):
        records, groups = self.export(), {}
        for r in records:
            if r['lifecycle'] == 'active':
                groups.setdefault(identity([r['utterance'], r['context'], r['provider']]), []).append(r['id'])
        return {
            'records': len(records), 'confirmed': sum(r['lifecycle'] == 'active' for r in records),
            'automatic': sum(r['lifecycle'] == 'active' and r.get('usability') == 'automatic' for r in records),
            'candidates': sum(r['lifecycle'] == 'candidate' for r in records),
            'invalidated': sum(r['lifecycle'] == 'invalid' for r in records),
            'successful_uses': sum(r['uses'] for r in records), 'failed_uses': sum(r['failures'] for r in records),
            'conflicting_groups': [ids for ids in groups.values() if len(ids) > 1],
            'provider_references': [dict(id=r['id'], provider=r['provider'],
                                        resources=[a['entity_id'] for a in r['plan']['actions']])
                                    for r in records if r['lifecycle'] == 'active'],
        }
