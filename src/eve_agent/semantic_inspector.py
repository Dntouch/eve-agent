"""Passive, bounded projections of semantic memory and measured turn traces."""
import json
import re
import uuid
from contextlib import closing
from urllib.parse import urlsplit, urlunsplit

from .brainwatch import BrainwatchInspector
from .semantic_links import (
    SemanticLinks, SCOPE, ACTION_SCOPE, SIMILARITY_RELATION_SCOPE,
    LANGUAGE_RELATION_SCOPE,
)
from .storage import _safe_json


_PUBLIC_SECRET_KEY = re.compile(r"^(?:token|access_token|refresh_token|client_secret|api[_-]?key|authorization|password|passwd|passwort|secret|cookie)$", re.I)
_PUBLIC_URL = re.compile(r"https?://[^\s<>\"']+")


def public(value):
    if isinstance(value, str):
        def safe_url(match):
            try:
                url=urlsplit(match.group(0))
                host=url.hostname or ''
                if ':' in host:host='['+host+']'
                if url.port:host+=':'+str(url.port)
                return urlunsplit((url.scheme,host,url.path,'',''))
            except ValueError:
                return '[REDACTED URL]'
        return _safe_json(_PUBLIC_URL.sub(safe_url,value))
    if isinstance(value, dict):
        result = {k: '[REDACTED]' if _PUBLIC_SECRET_KEY.match(str(k)) else public(v) for k, v in value.items()}
        if 'endpoint' in result:
            try:
                url = urlsplit(str(result['endpoint']))
                result['endpoint'] = f'{url.scheme}://{url.hostname or ""}'
            except ValueError:
                result['endpoint'] = '[REDACTED]'
        return _safe_json(result)
    if isinstance(value, list):
        return [public(v) for v in value]
    return _safe_json(value)


def turn_semantics(turn):
    events = [s for s in turn.get('steps', []) if s.get('component') == 'semantic_links']
    calls = turn.get('llm_calls')
    planners = None if calls is None else sum(str(c.get('role', '')).endswith('_planner') for c in calls)
    execution_planners = None if calls is None else sum(c.get('role') in {'turn_planner', 'home_assistant_planner'} for c in calls)
    has = lambda op, status=None: any(e.get('operation') == op and (status is None or e.get('status') == status) for e in events)
    direct = any(e.get('operation') == 'reuse' and e.get('status') == 'without_planner' and e.get('details', {}).get('outcome') == 'success' for e in events) and planners == 0 and not has('reuse', 'planner_fallback') and turn.get('status') == 'success'
    route = (('Neuplanning nach Provider-Invalidierung' if planners else 'Provider-Invalidierung · Neuauflösung noch nicht gemessen') if has('invalidate', 'resource_missing') or has('invalidate', 'service_missing') else
             'Planner-Fallback nach Lookup' if has('reuse', 'planner_fallback') or has('lookup', 'hit') and execution_planners else
             'Direkte Wiederverwendung ohne Planner' if direct else 'Direkte Wiederverwendung mit weiteren Planner-Aufrufen' if any(e.get('operation')=='reuse' and e.get('status')=='without_planner' and e.get('details',{}).get('outcome')=='success' for e in events) and execution_planners == 0 and planners else 'Wiederverwendung fehlgeschlagen oder noch laufend' if has('reuse', 'without_planner') else 'Normale LLM-Planung' if planners else 'Keine semantische Ausführung')
    labels = {'experience': 'Erfahrung gesammelt', 'automatic_release': 'Automatisch freigegeben',
              'explicit_confirmation': 'Explizit bestätigt', 'user_correction': 'Korrigiert',
              'similarity_correction': 'Dynamische Zuordnung korrigiert',
              'invalidate': 'Invalidiert', 'context_conditions': 'Kontextbedingungen dokumentiert',
              'language_relation': 'Explizite Sprachbeziehung verarbeitet'}
    learning = list(dict.fromkeys(labels[e['operation']] for e in events if e.get('operation') in labels))
    if has('reuse', 'without_planner'):
        learning.append('Vorhandene Erfahrung um Nutzungsevidenz ergänzt')
    tokens = {}
    for key in ('prompt_tokens', 'completion_tokens'):
        tokens[key] = None if calls is None or any(c.get(key) is None for c in calls) else sum(c[key] for c in calls)
    bypasses = {e.get('details', {}).get('planner') for e in events if e.get('operation')=='planner_bypass' and e.get('status')=='skipped'} - {None}
    dialog_events = [e for e in events if e.get("operation") in {"dialog_decision", "feedback_reference", "learning_clarification", "explicit_confirmation", "user_correction"}]
    link_events = [e for e in events if e.get('operation')=='action_link']
    used = next((e.get('details', {}) for e in reversed(events) if e.get('operation') in {'reuse', 'action_link'}), {})
    similarity_event = next((e for e in reversed(events)
                             if e.get('operation') == 'similarity_lookup'), None)
    similarity_details = (similarity_event or {}).get('details', {})
    composition_event = next((e for e in reversed(events)
                              if e.get('operation') == 'composition_lookup'), None)
    composition_details = (composition_event or {}).get('details', {})
    language_event = next((e for e in reversed(events)
                           if e.get('operation') == 'language_relation'), None)
    dialog_labels = {('dialog_decision','regular_planning'):'Reguläre Dialogentscheidung',
        ('dialog_decision','feedback_recognized'):'Explizites Feedback laut Planner',
        ('dialog_decision','rejected'):'Feedback-Entscheidung verworfen · kausale Evidenz unzureichend oder widersprüchlich',
        ('feedback_reference','validated'):'Feedback-Referenz validiert',
        ('explicit_confirmation','applied'):'Bestätigung angewendet', ('user_correction','applied'):'Korrektur angewendet'}
    return public(dict(dialog_statuses=list(dict.fromkeys(dialog_labels[(e['operation'],e['status'])] for e in dialog_events if (e['operation'],e['status']) in dialog_labels)), dialog_decisions=dialog_events, formulation=used.get('utterance'), action_representation_id=used.get('action_representation_id'),
                       evidence_kind=used.get('evidence_kind'), membership_status=used.get('membership_status'),
                       invalidations=sum(e.get('operation') in {'invalidate', 'user_correction'} for e in events),
                       semantic_reuse=used.get('semantic_reuse') or composition_details.get('semantic_reuse') or similarity_details.get('semantic_reuse'),
                       threshold=used.get('threshold') if used.get('threshold') is not None else similarity_details.get('threshold'),
                       similarity=used.get('similarity') if used.get('similarity') is not None else similarity_details.get('similarity'),
                       config_version=used.get('config_version') or composition_details.get('composition_config_version') or similarity_details.get('config_version'),
                       candidate_count=used.get('candidate_count') if used.get('candidate_count') is not None else similarity_details.get('candidate_count'),
                       checked_count=used.get('checked_count') if used.get('checked_count') is not None else similarity_details.get('checked_count'),
                       negative_relation_present=similarity_details.get('negative_relation_present', False),
                       ambiguity_conflict=(similarity_event or {}).get('status') == 'ambiguous',
                       composition=dict(
                           status=(composition_event or {}).get('status'),
                           reason=composition_details.get('composition_reason'),
                           mode=composition_details.get('composition_mode'),
                           hypotheses=composition_details.get('composition_hypothesis_count'),
                           candidate_count=composition_details.get('composition_candidate_count'),
                           evidence_quality=composition_details.get('composition_missing_evidence'),
                           conflicts=composition_details.get('composition_conflicts'),
                           truncated=composition_details.get('composition_truncated'),
                           execution_authorized=composition_details.get('semantic_reuse') == 'composition',
                           model_requests=composition_details.get('model_requests'),
                           prompt_tokens=composition_details.get('prompt_tokens'),
                           completion_tokens=composition_details.get('completion_tokens'),
                           duration_ms=composition_details.get('composition_duration_ms'),
                           language_relation_ids=composition_details.get('explicit_language_relation_ids', []),
                           language_mappings=composition_details.get('explicit_language_mappings', []),
                       ) if composition_event else None,
                       language_learning=(language_event or {}).get('details') if language_event else None,
                       direct_execution=bool(direct),
                       planner_entrypoints_avoided=len(bypasses) if direct and bypasses else None,
                       linking=dict(created=sum(e.get('status')=='created' for e in link_events), linked=sum(e.get('status')=='linked' for e in link_events),
                                    insufficient=sum(e.get('status')=='insufficient_evidence' for e in link_events), conflicts=sum(e.get('status')=='conflict' for e in link_events)), route=route, learning=learning or ['Keine neue Lernaktivität'], lookup_hit=has('lookup', 'hit') or has('similarity_lookup', 'hit'),
                       planner_free_execution=direct, planner_calls=planners, execution_planner_calls=execution_planners, llm_calls=None if calls is None else len(calls),
                       **tokens, duration_ms=turn.get('duration_ms'), events=events,
                       measured_calls=calls, measurement='Aktuelle Turn-Telemetrie; keine berechnete Kostenersparnis'))


class SemanticInspector(BrainwatchInspector):
    def composition(self, settings, limit=30):
        limit = min(100, max(1, int(limit)))
        with closing(self._connect()) as db:
            counts = {row['status']: row['count'] for row in db.execute(
                "SELECT status,COUNT(*) count FROM semantic_differential_hypotheses GROUP BY status")}
            hypotheses = []
            for row in db.execute("""SELECT * FROM semantic_differential_hypotheses
                ORDER BY updated_at DESC,id LIMIT ?""", (limit,)).fetchall():
                item = dict(row)
                item['value'] = json.loads(item.pop('value_json'))
                item['payload'] = json.loads(item.pop('payload_json'))
                item['dependencies'] = [dict(dep) for dep in db.execute(
                    "SELECT experience_id,provenance_root,stance FROM semantic_differential_dependencies "
                    "WHERE hypothesis_id=? ORDER BY stance,experience_id LIMIT 100", (row['id'],))]
                item['versions'] = [dict(version, payload=json.loads(version['payload_json']))
                    for version in db.execute("SELECT version,status,payload_json,created_at "
                    "FROM semantic_differential_hypothesis_versions WHERE hypothesis_id=? "
                    "ORDER BY version DESC LIMIT 20", (row['id'],))]
                for version in item['versions']:
                    version.pop('payload_json', None)
                hypotheses.append(item)
            evaluations = []
            for row in db.execute("""SELECT * FROM semantic_differential_evaluations
                ORDER BY created_at DESC,id LIMIT ?""", (limit,)).fetchall():
                item = dict(row)
                item['candidate_plan'] = json.loads(item.pop('candidate_plan_json')) if item['candidate_plan_json'] else None
                item['hypothesis_ids'] = json.loads(item.pop('hypothesis_ids_json'))
                item['details'] = json.loads(item.pop('details_json'))
                evaluations.append(item)
            language_relations = []
            for row in db.execute("""SELECT * FROM memory_claims WHERE scope=?
                ORDER BY updated_at DESC,id DESC LIMIT ?""",
                (LANGUAGE_RELATION_SCOPE, limit)).fetchall():
                item = self._item(row)
                item['display_text'] = row['display_text']
                item['evidence'] = [
                    dict(entry, payload=json.loads(entry['payload_json']))
                    for entry in map(dict, db.execute("""SELECT evidence_type,stance,source_ref,
                        source_turn_id,source_message_id,payload_json,created_at
                        FROM memory_evidence WHERE claim_id=?
                        ORDER BY created_at DESC,id DESC LIMIT 10""", (row['id'],)))
                ]
                item['relations'] = [dict(entry) for entry in db.execute(
                    """SELECT * FROM memory_relations WHERE from_claim_id=? OR to_claim_id=?
                       ORDER BY created_at DESC,id DESC LIMIT 30""", (row['id'], row['id']))]
                language_relations.append(item)
        return public({'settings': settings, 'counts': counts, 'hypotheses': hypotheses,
                       'evaluations': evaluations, 'language_relations': language_relations,
                       'language_relation_scope': LANGUAGE_RELATION_SCOPE,
                       'policy': 'differential_one_field_contrast_v1'})

    def similarity(self, settings, limit=30):
        limit = min(100, max(1, int(limit)))
        with closing(self._connect()) as db:
            relation_rows = db.execute('''SELECT * FROM memory_claims WHERE scope=?
                ORDER BY updated_at DESC,id LIMIT ?''',
                (SIMILARITY_RELATION_SCOPE, limit)).fetchall()
            relations = []
            for row in relation_rows:
                item = self._item(row)
                item['display_text'] = row['display_text']
                evidence = db.execute('''SELECT evidence_type,source_ref,source_turn_id,
                    source_message_id,created_at,payload_json FROM memory_evidence
                    WHERE claim_id=? ORDER BY created_at DESC,id DESC LIMIT 5''', (row['id'],)).fetchall()
                item['evidence'] = [dict(**{k: value for k, value in dict(entry).items()
                                                if k != 'payload_json'},
                                         payload=json.loads(entry['payload_json'])) for entry in evidence]
                relations.append(item)
            recognition_rows = db.execute('''SELECT e.claim_id,e.source_ref,e.source_turn_id,
                    e.source_message_id,e.created_at,e.payload_json,c.display_text,c.payload_json claim_payload
                FROM memory_evidence e JOIN memory_claims c ON c.id=e.claim_id
                WHERE c.scope=? AND e.evidence_type='reuse_result'
                AND json_type(e.payload_json,'$.semantic_similarity')='object'
                ORDER BY e.created_at DESC,e.id DESC LIMIT ?''', (SCOPE, limit)).fetchall()
            decision_rows = db.execute('''SELECT id,updated_at,payload_json FROM memory_claims
                WHERE scope=? AND lifecycle='active'
                AND json_extract(payload_json,'$.kind')='recognition'
                ORDER BY updated_at DESC,id DESC LIMIT ?''',
                (SIMILARITY_RELATION_SCOPE, min(400, limit * 4))).fetchall()
            recognition_decisions = {}
            for decision_row in decision_rows:
                decision = json.loads(decision_row['payload_json'])
                key = (decision.get('learned_claim_id'),
                       str(decision.get('input_formulation') or '').strip().casefold())
                recognition_decisions.setdefault(key, public(dict(
                    relation_id=decision_row['id'], polarity=decision.get('polarity'),
                    updated_at=decision_row['updated_at'])))
            recognitions = []
            for row in recognition_rows:
                result, claim = json.loads(row['payload_json']), json.loads(row['claim_payload'])
                similarity = result.get('semantic_similarity', {})
                input_formulation = similarity.get('input_formulation')
                user_decision = recognition_decisions.get(
                    (row['claim_id'], str(input_formulation or '').strip().casefold()))
                relevant = [{key: item.get(key) for key in (
                    'id', 'lifecycle', 'kind', 'pair', 'polarity', 'learned_claim_id', 'input_tokens')}
                    for item in relations
                    if item.get('representation_id') == similarity.get('action_representation_id')]
                recognitions.append(public(dict(
                    claim_id=row['claim_id'], learned_formulation=row['display_text'],
                    user_formulation=input_formulation, user_decision=user_decision,
                    similarity=similarity.get('similarity'), threshold=similarity.get('threshold'),
                    action_representation_id=similarity.get('action_representation_id'),
                    pairs=similarity.get('pairs', []), direct_execution=similarity.get('direct_execution'),
                    relevant_relations=relevant,
                    provider=claim.get('provider'), result_status=result.get('status'),
                    source_ref=row['source_ref'], source_turn_id=row['source_turn_id'],
                    source_message_id=row['source_message_id'], created_at=row['created_at'])))
        return public(dict(settings=settings, relations=relations, recognitions=recognitions,
                           relation_scope=SIMILARITY_RELATION_SCOPE))

    def summary(self):
        with closing(self._connect()) as db:
            counts = dict(db.execute("""SELECT COUNT(*) experiences,
                COALESCE(SUM(lifecycle='candidate'),0) candidates,
                COALESCE(SUM(lifecycle='active' AND json_extract(payload_json,'$.confirmation')='corroborated'),0) automatic_active,
                COALESCE(SUM(lifecycle='active' AND json_extract(payload_json,'$.confirmation')='confirmed'),0) explicit_active,
                COALESCE(SUM(lifecycle='invalid'),0) invalid,
                COALESCE(SUM(json_extract(payload_json,'$.uses')),0) successful_direct_uses
                FROM memory_claims WHERE scope=?""", (SCOPE,)).fetchone())
            counts['corrections'] = db.execute("SELECT COUNT(*) FROM memory_evidence e JOIN memory_claims c ON c.id=e.claim_id WHERE c.scope=? AND e.evidence_type='user_correction'", (SCOPE,)).fetchone()[0]
            counts['version_relations'] = db.execute("SELECT COUNT(*) FROM memory_relations r JOIN memory_claims c ON c.id=r.from_claim_id JOIN memory_claims t ON t.id=r.to_claim_id WHERE c.scope=? AND t.scope=?", (SCOPE,SCOPE)).fetchone()[0]
            counts['action_representations'] = db.execute('SELECT COUNT(*) FROM memory_claims WHERE scope=?',(ACTION_SCOPE,)).fetchone()[0]
            differential = dict(db.execute("""SELECT COUNT(*) differential_hypotheses,
                COALESCE(SUM(status='released'),0) differential_released,
                COALESCE(SUM(status IN ('blocked','truncated')),0) differential_blocked
                FROM semantic_differential_hypotheses""").fetchone())
            counts.update(differential)
            counts.update(dict(db.execute("""SELECT COUNT(*) language_relations,
                COALESCE(SUM(lifecycle='active' AND json_extract(payload_json,'$.polarity')='positive'),0)
                    language_relations_active,
                COALESCE(SUM(lifecycle='active' AND json_extract(payload_json,'$.polarity')='negative'),0)
                    language_relations_blocked,
                COALESCE(SUM(json_extract(payload_json,'$.relation_kind')='resource_alias'),0)
                    resource_alias_versions
                FROM memory_claims WHERE scope=?""", (LANGUAGE_RELATION_SCOPE,)).fetchone()))
            counts.update(dict(db.execute("""SELECT COUNT(DISTINCT CASE WHEN json_extract(payload_json,'$.action_link_status') IN ('created','linked') AND lifecycle!='invalid' THEN display_text END) linked_formulations,
                COALESCE(SUM(json_extract(payload_json,'$.action_link_status')='insufficient_evidence'),0) unlinked_experiences,
                COALESCE(SUM(json_extract(payload_json,'$.action_link_status')='conflict'),0) link_conflicts,
                COALESCE(SUM(json_extract(payload_json,'$.action_link_status')='invalid'),0) invalid_memberships
                FROM memory_claims WHERE scope=?""",(SCOPE,)).fetchone()))
            daily = [dict(r) for r in db.execute("""SELECT substr(e.created_at,1,10) day,e.evidence_type,COUNT(*) count FROM memory_evidence e
                JOIN memory_claims c ON c.id=e.claim_id WHERE c.scope=? AND e.evidence_type IN ('llm_interpretation','automatic_release','reuse_result','user_correction')
                GROUP BY day,e.evidence_type ORDER BY day DESC LIMIT 120""", (SCOPE,))]
        return dict(stock=counts, daily_evidence=daily, historical_telemetry=dict(available=False,
                    planner_fallbacks=None, planner_free_proportion=None, llm_calls=None, tokens=None, duration_ms=None,
                    reason='Turn-Telemetrie ist nicht dauerhaft gespeichert. Tageswerte zählen persistierte Evidenzen, keine vollständigen Turns.'),
                    count_kind='Bestand: Erfahrungen und Zustände; historische Zähler: erfolgreiche Wiederverwendungen und Evidenzereignisse')

    def actions(self, query='', cursor=0, limit=20):
        if len(query)>300:
            raise ValueError('Ungültiger Filter')
        cursor,limit=max(0,int(cursor)),min(50,max(1,int(limit)))
        needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with closing(self._connect()) as db:
            rows=db.execute("SELECT * FROM memory_claims WHERE scope=? AND display_text LIKE ? ESCAPE '\\' ORDER BY created_at DESC,id LIMIT ? OFFSET ?",(ACTION_SCOPE,needle,limit+1,cursor)).fetchall()
            items=[]
            for row in rows[:limit]:
                group=self._item(row)
                stats=dict(db.execute("""SELECT COUNT(*) experiences,COUNT(DISTINCT display_text) formulations,
                    COALESCE(SUM(lifecycle='active' AND json_extract(payload_json,'$.action_link_status') IN ('created','linked')),0) directly_usable,
                    COALESCE(SUM(json_extract(payload_json,'$.action_link_status')='invalid'),0) invalid_memberships,
                    COALESCE(SUM(json_extract(payload_json,'$.uses')),0) reuse_successes
                    FROM memory_claims WHERE scope=? AND json_extract(payload_json,'$.action_representation_id')=?""",(SCOPE,row['id'])).fetchone())
                items.append(dict(id=row['id'],representation=group['representation'],context=group['context'],**stats))
        return dict(items=items,next_cursor=cursor+limit if len(rows)>limit else None)

    def action_detail(self, representation_id, cursor=0, limit=20, evidence_cursor=0):
        cursor,limit=max(0,int(cursor)),min(50,max(1,int(limit)))
        evidence_cursor=max(0,int(evidence_cursor))
        with closing(self._connect()) as db:
            row=db.execute('SELECT * FROM memory_claims WHERE scope=? AND id=?',(ACTION_SCOPE,representation_id)).fetchone()
            if row is None:
                raise KeyError(representation_id)
            members=db.execute("SELECT * FROM memory_claims WHERE scope=? AND json_extract(payload_json,'$.action_representation_id')=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?",(SCOPE,representation_id,limit+1,cursor)).fetchall()
            evidence=[dict(r) for r in db.execute('SELECT * FROM memory_evidence WHERE claim_id=? ORDER BY created_at,id LIMIT ? OFFSET ?',(representation_id,limit+1,evidence_cursor))]
            for e in evidence:
                e['payload']=json.loads(e.pop('payload_json'))
        return public(dict(item=self._item(row),members=[dict(id=r['id'],lifecycle=r['lifecycle'],**{k:json.loads(r['payload_json']).get(k) for k in ('utterance','context','plan','confirmation','uses','action_link_status','invalidation_reason','version')}) for r in members[:limit]],
            next_cursor=cursor+limit if len(members)>limit else None,evidence=evidence[:limit],next_evidence_cursor=evidence_cursor+limit if len(evidence)>limit else None,
            replay_policy='Gruppenzugehörigkeit ist keine Freigabe. Nur die konkrete Formulierung kann bestätigt oder automatisch corroboriert sein.'))

    def listing(self, query='', status='', action_link_status='', cursor=0, limit=20):
        link_filters = {'', 'usable', 'created', 'linked', 'insufficient_evidence', 'conflict', 'invalid'}
        if (len(query) > 300 or status not in {'','candidate','active','invalid','retired'}
                or action_link_status not in link_filters):
            raise ValueError('Ungültiger Filter')
        cursor, limit = max(0, int(cursor)), min(50, max(1, int(limit)))
        needle = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = "scope=? AND (display_text LIKE ? ESCAPE '\\' OR payload_json LIKE ? ESCAPE '\\')"
        params = [SCOPE, needle, needle]
        if status:
            where += ' AND lifecycle=?'; params.append(status)
        if action_link_status == 'usable':
            where += " AND json_extract(payload_json,'$.action_link_status') IN ('created','linked')"
        elif action_link_status:
            where += " AND json_extract(payload_json,'$.action_link_status')=?"
            params.append(action_link_status)
        with closing(self._connect()) as db:
            rows = db.execute(f'SELECT id,lifecycle,created_at,updated_at,payload_json FROM memory_claims WHERE {where} ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (*params,limit+1,cursor)).fetchall()
        items = []
        with closing(self._connect()) as db:
            for row in rows[:limit]:
                item = self._item(row)
                latest = db.execute("SELECT created_at,payload_json FROM memory_evidence WHERE claim_id=? AND evidence_type='reuse_result' ORDER BY created_at DESC,id DESC LIMIT 1", (row['id'],)).fetchone()
                failure = db.execute("SELECT created_at,payload_json FROM memory_evidence WHERE claim_id=? AND evidence_type IN ('reuse_result','provider_result') AND json_extract(payload_json,'$.status')!='success' ORDER BY created_at DESC,id DESC LIMIT 1", (row['id'],)).fetchone()
                item['last_use'] = latest['created_at'] if latest else None
                item['last_failure'] = public(dict(at=failure['created_at'], result=json.loads(failure['payload_json']))) if failure else None
                items.append({k: item.get(k) for k in ('id','lifecycle','created_at','updated_at','utterance','provider','plan','context','confirmation','uses','last_success','last_use','last_failure','failures','invalidation_reason','technical_status','action_representation_id','action_link_status')})
        return dict(items=items, next_cursor=cursor+limit if len(rows)>limit else None)

    @staticmethod
    def _item(row):
        p = json.loads(row['payload_json'])
        return public(dict(id=row['id'], lifecycle=row['lifecycle'], created_at=row['created_at'], updated_at=row['updated_at'], **p))

    def detail(self, claim_id, cursor=0, limit=30, relation_cursor=0):
        cursor, limit = max(0,int(cursor)), min(50,max(1,int(limit)))
        relation_cursor = max(0, int(relation_cursor))
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM memory_claims WHERE id=? AND scope=?',(claim_id,SCOPE)).fetchone()
            if row is None: raise KeyError(claim_id)
            evidence = [dict(r) for r in db.execute('SELECT * FROM memory_evidence WHERE claim_id=? ORDER BY created_at,id LIMIT ? OFFSET ?', (claim_id,limit+1,cursor))]
            for e in evidence: e['payload'] = json.loads(e.pop('payload_json'))
            relations = [dict(r) for r in db.execute('SELECT * FROM memory_relations WHERE from_claim_id=? OR to_claim_id=? ORDER BY created_at,id LIMIT 51 OFFSET ?',(claim_id,claim_id,relation_cursor))]
        return public(dict(item=self._item(row), evidence=evidence[:limit], next_cursor=cursor+limit if len(evidence)>limit else None,
                           relations=relations[:50], relations_truncated=len(relations)>50, next_relation_cursor=relation_cursor+50 if len(relations)>50 else None,
                           rejection_policy='Ablehnung betrifft diesen Claim und identische Erfahrungen mit gleichem Provider, Kontext und Aktionsplan. Evidenzen bleiben erhalten.'))

    def reject(self, database, claim_id, payload):
        if (not isinstance(payload, dict) or type(payload.get('confirmed')) is not bool
                or payload != {'confirmed': True, 'claim_id': claim_id}):
            raise ValueError('Explizite Bestätigung und passende Claim-ID erforderlich')
        # Scope validation before the existing decision policy writes any evidence.
        self.detail(claim_id, limit=1)
        reference = 'brainwatch:user:' + str(uuid.uuid4())
        SemanticLinks(database).decide(claim_id, confirmed=False, source_ref=reference,
                                     decision_evidence={'source':'brainwatch','decision':'reject','selected_claim_id':claim_id})
        return dict(claim_id=claim_id, source_ref=reference, status='invalid', policy='Identische Erfahrungen gemäß bestehender Widerspruchspolicy ebenfalls invalidiert')
