"""Exact-ID, evidence-backed Memory-v2 writes. Meaning is chosen by the model."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .memory import redact_sensitive
from .memory_lifecycle import lifecycle_operation
from .transport_access import transport_metadata
from .storage import _safe_json


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def version(row):
    return hashlib.sha256(encoded(dict(row)).encode()).hexdigest()


def identity(kind, reference):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'eve-memory-revision:' + kind + ':' + reference))


class MemoryRevision:
    def __init__(self, database):
        self.database = database

    def inspect(self, claim_id):
        with self.database.connect() as c:
            row = c.execute('SELECT * FROM memory_claims WHERE id=?', (claim_id,)).fetchone()
            if row is None:
                return {'status': 'not_found', 'claim_id': claim_id}
            evidence = [dict(r) for r in c.execute(
                'SELECT e.*,o.metadata_json AS observation_metadata,o.external_ref AS observation_reference '
                'FROM memory_evidence e LEFT JOIN memory_observations o ON o.id=e.observation_id '
                'WHERE e.claim_id=? ORDER BY e.created_at,e.id', (claim_id,))]
            relations = [dict(r) for r in c.execute(
                'SELECT * FROM memory_relations WHERE from_claim_id=? OR to_claim_id=?', (claim_id,claim_id))]
            decisions = [dict(r) for r in c.execute(
                'SELECT d.* FROM memory_learning_decisions d JOIN memory_learning_decision_claims l '
                'ON l.decision_id=d.id WHERE l.claim_id=? ORDER BY d.created_at', (claim_id,))]
        item = dict(row)
        item['payload'] = json.loads(item.pop('payload_json'))
        return {'status': 'found', 'claim': item, 'version': version(row),
                'evidence': evidence, 'relations': relations, 'decisions': decisions}

    @staticmethod
    def _writable_by_actor(c, target, source):
        # Local interface and the verified bot owner retain their existing authority.
        if not source or source.get('transport') != 'chatto':
            return True
        if source.get('sender_id') and source.get('sender_id') == source.get('owner_id'):
            return True
        if not source.get('sender_id') or not source.get('server_url'):
            return False
        # Ownership comes from persisted provenance, never from claim wording or tool arguments.
        row = c.execute(
            "SELECT o.metadata_json,m.metadata_json AS message_metadata FROM memory_evidence e "
            "JOIN memory_observations o ON o.id=e.observation_id LEFT JOIN messages m ON m.id=o.message_id "
            "WHERE e.claim_id=? AND o.source_role='user' AND e.stance='supports' ORDER BY e.created_at,e.id LIMIT 1",
            (target['id'],)).fetchone()
        if row is None:
            return False
        owner = json.loads(row['metadata_json'] or '{}').get('conversation_source')
        if not owner:
            owner = json.loads(row['message_metadata'] or '{}').get('conversation_source')
        return bool(owner and all(owner.get(k) == source.get(k) for k in ('transport','server_url','sender_id')))

    @lifecycle_operation('memory.revise', 'direct_revision')
    def revise(self, parameters, *, source_reference, user_text, conversation_id, turn_id, trace_id=None):
        """Caller supplies current input independently of model-authored parameters."""
        p = parameters
        if not source_reference or p.get('source_reference') != source_reference:
            return {'status': 'denied', 'reason': 'current_user_source_required'}
        quote = p.get('evidence_quote')
        if not isinstance(quote,str) or not quote.strip() or quote not in user_text:
            return {'status': 'needs_clarification', 'reason': 'verbatim_user_evidence_required'}
        action = p.get('action')
        if action not in {'correct','temporal_change','retract','refine','relate','contradict'}:
            return {'status': 'denied', 'reason': 'unsupported_revision_action'}
        if not p.get('mutation_id') or not p.get('target_id') or not p.get('expected_version'):
            return {'status': 'needs_clarification', 'reason': 'inspect_target_and_supply_version'}
        replacement = p.get('replacement')
        if action in {'correct','temporal_change','refine'}:
            if not isinstance(replacement,dict) or not isinstance(replacement.get('display_text'),str) or not replacement['display_text'].strip() or not isinstance(replacement.get('payload'),dict):
                return {'status': 'needs_clarification', 'reason': 'replacement_required'}
            if replacement['payload'].get('epistemic_kind') == 'user_instruction' and replacement['display_text'] not in user_text:
                return {'status': 'needs_clarification', 'reason': 'instruction_requires_verbatim_user_wording'}
        if action == 'temporal_change':
            try:
                effective = datetime.fromisoformat(p.get('effective_at','').replace('Z','+00:00'))
                if effective.tzinfo is None:
                    raise ValueError()
                if effective > datetime.now(timezone.utc):
                    return {'status': 'needs_clarification', 'reason': 'future_transition_requires_scheduling'}
            except (ValueError,TypeError):
                return {'status': 'needs_clarification', 'reason': 'effective_at_with_timezone_required'}
        if action == 'relate' and p.get('relation_type') not in {'refines','contradicts'}:
            return {'status': 'denied', 'reason': 'use_correct_for_supersession'}
        source = transport_metadata()
        now = datetime.now(timezone.utc).isoformat()
        signature = hashlib.sha256(encoded({'parameters':p,'source':source_reference,'actor':source}).encode()).hexdigest()
        decision_id = identity('decision', source_reference + ':' + p['mutation_id'])
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT metadata_json FROM memory_learning_decisions WHERE id=?', (decision_id,)).fetchone()
            if prior:
                metadata = json.loads(prior[0])
                if metadata.get('request_signature') != signature:
                    return {'status':'conflict','reason':'mutation_id_reused_with_different_request'}
                return {**metadata['result'],'replayed':True}
            target = c.execute('SELECT * FROM memory_claims WHERE id=?', (p['target_id'],)).fetchone()
            if target is None:
                return {'status':'conflict','reason':'target_not_found'}
            if version(target) != p['expected_version']:
                return {'status':'conflict','reason':'target_changed','current_version':version(target)}
            if target['lifecycle'] not in {'active','candidate'}:
                return {'status':'conflict','reason':'target_no_longer_current'}
            if target['claim_kind'] == 'provider_binding':
                return {'status':'denied','reason':'provider_binding_requires_verified_provider_evidence'}
            if replacement and action in {'correct','temporal_change','refine'}:
                previous_payload = json.loads(target['payload_json'])
                if target['lifecycle'] == 'active' and replacement['payload'].get('epistemic_kind') == 'inferred_procedure':
                    return {'status':'needs_clarification','reason':'inference_cannot_replace_active_user_knowledge'}
                if replacement['payload'].get('subject') != previous_payload.get('subject'):
                    return {'status':'denied','reason':'subject_change_requires_new_claim'}
            if not self._writable_by_actor(c,target,source):
                return {'status':'denied','reason':'target_owned_by_another_actor_or_unknown'}
            related = None
            if action == 'relate':
                related = c.execute('SELECT * FROM memory_claims WHERE id=?', (p.get('related_id'),)).fetchone()
                if related is None or related['id'] == target['id'] or version(related) != p.get('related_version'):
                    return {'status':'conflict','reason':'inspect_distinct_related_target_and_version'}
                if related['scope'] != target['scope']:
                    return {'status':'denied','reason':'relation_scope_mismatch'}
                if not self._writable_by_actor(c,related,source):
                    return {'status':'denied','reason':'related_target_owned_by_another_actor_or_unknown'}
            try:
                self.database.assert_runtime_self_knowledge_writable(c,claim_ids=[target['id']] + ([related['id']] if related else []))
            except PermissionError:
                return {'status':'denied','reason':'runtime_owned_memory'}
            observation_id = identity('observation',decision_id)
            metadata = {'direct_revision':True,'conversation_id':conversation_id,'source_turn_reference':turn_id,
                        'conversation_source':source,'source_reference':source_reference}
            c.execute('INSERT INTO memory_observations(id,source_role,source_type,external_ref,excerpt,structured_value_json,observed_at,scope,metadata_json,created_at) '
                      "VALUES (?,'user','user_message',?,?,?,?,?,?,?)",
                      (observation_id,'working_memory:'+source_reference,redact_sensitive(quote),
                       encoded({'content':redact_sensitive(user_text)}),now,'conversation:'+conversation_id,encoded(metadata),now))
            new_id = None
            relation_type = None
            if replacement and action in {'correct','temporal_change','refine'}:
                new_id = identity('claim',decision_id)
                new_key = target['canonical_key'] + ':revision:' + new_id
                c.execute('INSERT INTO memory_claims(id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,valid_from,verification_policy,created_at,updated_at) '
                          'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                          (new_id,target['claim_kind'],target['scope'],new_key,target['slot_key'],redact_sensitive(replacement['display_text']),
                           encoded(_safe_json(replacement['payload'])),target['lifecycle'],p.get('effective_at') if action=='temporal_change' else target['valid_from'],
                           target['verification_policy'],now,now))
                relation_type = 'refines' if action=='refine' else 'supersedes'
            evidence_ids=[]
            for claim_id,stance in ([(new_id,'supports')] if new_id else []) + [(target['id'],'contradicts' if action in {'correct','retract','contradict'} else 'supports')]:
                evidence_id=identity('evidence',decision_id+':'+claim_id)
                c.execute('INSERT INTO memory_evidence(id,claim_id,observation_id,stance,evidence_type,source_ref,excerpt,payload_json,observed_at,created_at) '
                          "VALUES (?,?,?,?,'user_message',?,?,?,?,?)",
                          (evidence_id,claim_id,observation_id,stance,'working_memory:'+source_reference,redact_sensitive(quote),encoded({'action':action}),now,now))
                evidence_ids.append(evidence_id)
            relation_id=None
            if relation_type or related:
                relation_type=relation_type or p['relation_type']
                from_id,to_id=(new_id,target['id']) if new_id else (target['id'],related['id'])
                existing=c.execute('SELECT id FROM memory_relations WHERE from_claim_id=? AND to_claim_id=? AND relation_type=?',(from_id,to_id,relation_type)).fetchone()
                relation_id=existing[0] if existing else identity('relation',decision_id)
                if not existing:
                    c.execute('INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at) VALUES (?,?,?,?,?,?)',
                              (relation_id,from_id,to_id,relation_type,evidence_ids[0],now))
            if action in {'correct','temporal_change','retract','refine'}:
                state='invalid' if action=='retract' else 'retired'
                c.execute('UPDATE memory_claims SET lifecycle=?,valid_until=?,updated_at=? WHERE id=?',
                          (state,p.get('effective_at') if action=='temporal_change' else now,now,target['id']))
            decision_type={'correct':'supersede_claim','temporal_change':'supersede_claim','retract':'append_contradicting_evidence',
                           'refine':'refine_claim','relate':'append_supporting_evidence','contradict':'append_contradicting_evidence'}[action]
            result={'status':'applied','decision_id':decision_id,'target_id':target['id'],'claim_id':new_id,
                    'relation_id':relation_id,'evidence_ids':evidence_ids,'action':action}
            record={'request_signature':signature,'result':result,'direct_revision':True,'action':action,
                    'before_version':p['expected_version'],'source_reference':source_reference,'conversation_source':source,
                    'source_turn_reference':turn_id}
            c.execute('INSERT INTO memory_learning_decisions(id,observation_id,decision_type,method,rationale,metadata_json,created_at) '
                      "VALUES (?,?,?,'direct_revision',?,?,?)",
                      (decision_id,observation_id,decision_type,redact_sensitive(p.get('reason','')),encoded(record),now))
            for claim_id in [target['id']] + ([new_id] if new_id else []) + ([related['id']] if related else []):
                c.execute('INSERT INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)',(decision_id,claim_id))
            return result

    def attach_turn(self, turn_id, user_message_id):
        with self.database.connect() as c:
            rows=c.execute("SELECT id FROM memory_observations WHERE json_extract(metadata_json,'$.direct_revision')=1 "
                           "AND json_extract(metadata_json,'$.source_turn_reference')=?",(turn_id,)).fetchall()
            for row in rows:
                c.execute('UPDATE memory_observations SET turn_id=?,message_id=? WHERE id=?',(turn_id,user_message_id,row[0]))
                c.execute('UPDATE memory_evidence SET source_turn_id=?,source_message_id=? WHERE observation_id=?',(turn_id,user_message_id,row[0]))
