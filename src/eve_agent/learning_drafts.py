"""Evidence-addressed episode drafts. Models choose meaning; code checks receipts.

Drafts are deliberately separate from retrievable claims: an unchecked model
answer must never become a verified fact merely by being repeated during learning.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def episode_context(database, turn_id):
    with database.connect() as c:
        turn = c.execute('SELECT * FROM turns WHERE id=?', (turn_id,)).fetchone()
        if turn is None:
            raise KeyError(turn_id)
        end = c.execute('SELECT ordinal FROM messages WHERE id=?',
                        (turn['assistant_message_id'] or turn['user_message_id'],)).fetchone()
        messages = [dict(r) for r in c.execute(
            'SELECT id,role,content,metadata_json FROM messages '
            'WHERE conversation_id=? AND ordinal<=? ORDER BY ordinal',
            (turn['conversation_id'], end[0]))]
        claims = [dict(r) for r in c.execute(
            'SELECT * FROM memory_claims ORDER BY updated_at DESC,id')]
        relations = [dict(r) for r in c.execute('SELECT * FROM memory_relations ORDER BY id')]
    # The caller selects relevant claims; all message sources remain addressable.
    return {'turn_id': turn_id, 'conversation_id': turn['conversation_id'],
            'messages': messages, 'claims': claims, 'relations': relations}


def draft_context(episode, claim_ids=()):
    selected = set(claim_ids)
    return {
        'turn_id': episode['turn_id'], 'conversation_id': episode['conversation_id'],
        'origins': [{'message_id': m['id'], 'conversation_source': source}
                    for m in episode['messages']
                    if (source := json.loads(m['metadata_json'] or '{}').get('conversation_source'))],
        'messages': [{'id': m['id'], 'role': m['role'], 'content': m['content']}
                     for m in episode['messages']],
        'claims': [{**c, 'version': fingerprint(c)} for c in episode['claims'] if c['id'] in selected],
        'relations': [{**r, 'version': fingerprint(r)} for r in episode['relations']
                      if r['from_claim_id'] in selected or r['to_claim_id'] in selected],
    }


DRAFT_INSTRUCTION = (
    'Produce a reviewable learning draft for this conversation episode. Return JSON with lessons and relations arrays. '
    'Each lesson has key, text, topics (search labels, preserving technical terms from the sources), '
    'kind (encounter, semantic, instruction), and evidence. Do not output status or authority; '
    'the store derives source labels from exact text and source roles, without deciding meaning. '
    'Evidence items should contain only message_id, not manually copied quotes. Omit quote to cite the original entire message, which the store resolves automatically. If selecting a quote, copy it exactly, preserving Markdown and line breaks. '
    'Preserve encountered technical terms in topics even when the readable summary abstracts them; '
    'do not silently equate terms or lose the original vocabulary. '
    'An encounter records what was discussed, not that its contents are true. Extract reusable concepts separately '
    'as semantic lessons; your own earlier answers are unverified, not independent factual sources. '
    'Distinguish a user statement, a question, an assistant proposal and a later contextual confirmation. '
    'A readable paraphrase is a derived lesson, never a verbatim instruction. '
    'When a user confirms an assistant proposal, cite both that proposal and the later confirmation. '
    'Write readable lessons in the conversation language. Prefer a few distinct new lessons over restating every turn. '
    'A brief confirmation applies only to its actual referent, never every earlier assistant assertion. '
    'Each relation has from_key (a lesson key), target_id (a published claim ID), type '
    '(refines, applies_to, about, supersedes), rationale, and evidence. '
    'Supersedes requires evidence that the old statement ceases to hold; broader scope alone is insufficient. '
    'Do not infer that a topic is public because it is general knowledge; preserve the private conversation origin. '
    'Track corrections across the episode: do not retain a retracted assistant assumption as a current rule. '
    'An earlier assistant assumption contradicted by a later user correction is historical context, '
    'not current knowledge. Preserve it only as a historical error in an encounter if relevant. '
    'No draft grants permission or changes existing memory. Do not invent sources or claim IDs.'
)


def _validate_draft(raw, context):
    """Validate source identity, exact quotes and epistemic structure, not meaning."""
    if not isinstance(raw, dict) or set(raw) != {'lessons', 'relations'}:
        raise ValueError('draft_requires_lessons_and_relations')
    sources = {m['id']: m for m in context['messages']}
    claims = {c['id']: c for c in context['claims']}
    result = deepcopy(raw)
    if not isinstance(result['lessons'], list) or not isinstance(result['relations'], list):
        raise ValueError('draft_arrays_required')

    def evidence(items):
        if not isinstance(items, list) or not items:
            raise ValueError('evidence_required')
        roles = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('invalid_evidence')
            source = sources.get(item.get('message_id'))
            if source is not None and 'quote' not in item:
                item['quote'] = source['content']
            quote = item.get('quote')
            if source is None or not isinstance(quote, str) or not quote.strip() or quote not in source['content']:
                raise ValueError('exact_source_quote_required')
            roles.add(source['role'])
        return roles

    keys = set()
    for lesson in result['lessons']:
        key = lesson.get('key')
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError('unique_lesson_key_required')
        keys.add(key)
        if not isinstance(lesson.get('text'), str) or not lesson['text'].strip():
            raise ValueError('lesson_text_required')
        if lesson.get('kind') not in {'encounter', 'semantic', 'instruction'}:
            raise ValueError('invalid_lesson_kind')
        status = lesson.get('status')
        if status is None:
            cited = [sources.get(e.get('message_id'), {}) for e in lesson.get('evidence', [])
                     if isinstance(e, dict)]
            roles = {m.get('role') for m in cited}
            if lesson['kind'] == 'encounter':
                status = 'observed_conversation'
            elif roles == {'user'} and any(lesson['text'] in m.get('content', '') for m in cited):
                status = 'explicit_user'
            elif roles == {'user'}:
                status = 'user_supported_inference'
            elif 'user' in roles:
                status = 'mixed_sources'
            else:
                status = 'unverified'
            lesson['status'] = status
        if status not in {'observed_conversation', 'explicit_user', 'user_supported_inference', 'dialog_supported', 'mixed_sources', 'unverified'}:
            raise ValueError('invalid_lesson_status')
        roles = evidence(lesson.get('evidence'))
        topics = lesson.get('topics', [])
        if not isinstance(topics, list) or any(not isinstance(t, str) or not t.strip() for t in topics):
            raise ValueError('topics_must_be_nonempty_strings')
        # Search labels may abstract the source wording. Track literal occurrences
        # separately; a label never proves that two concepts are equivalent.
        lesson['topic_sources'] = {
            topic: [e['message_id'] for e in lesson['evidence']
                    if topic.casefold() in sources[e['message_id']]['content'].casefold()]
            for topic in topics
        }
        if status == 'observed_conversation' and lesson['kind'] != 'encounter':
            raise ValueError('conversation_observation_is_not_world_knowledge')
        if status == 'explicit_user' and roles != {'user'}:
            raise ValueError('explicit_user_requires_user_sources_only')
        if status == 'explicit_user' and not any(
                lesson['text'] in item['quote'] for item in lesson['evidence']):
            raise ValueError('explicit_user_text_must_be_quoted')
        if status == 'user_supported_inference' and 'user' not in roles:
            raise ValueError('user_inference_requires_user_source')
        if status == 'mixed_sources' and not {'user', 'assistant'} <= roles:
            raise ValueError('mixed_sources_requires_both_speakers')
        if status == 'dialog_supported' and not {'user', 'assistant'} <= roles:
            raise ValueError('dialog_support_requires_both_speakers')
        if status == 'dialog_supported':
            order = {m['id']: i for i, m in enumerate(context['messages'])}
            cited = [sources[e['message_id']] for e in lesson['evidence']]
            if not any(order[u['id']] > order[a['id']] for u in cited for a in cited
                       if u['role'] == 'user' and a['role'] == 'assistant'):
                raise ValueError('dialog_confirmation_must_follow_proposal')
        # The model must not claim verified world knowledge from its own answer.
        if roles <= {'assistant'} and lesson['kind'] != 'encounter' and status != 'unverified':
            raise ValueError('assistant_only_knowledge_is_unverified')
    for relation in result['relations']:
        if relation.get('from_key') not in keys or relation.get('target_id') not in claims:
            raise ValueError('published_relation_endpoints_required')
        if relation.get('type') not in {'refines', 'applies_to', 'about', 'supersedes'}:
            raise ValueError('invalid_relation_type')
        if not isinstance(relation.get('rationale'), str) or not relation['rationale'].strip():
            raise ValueError('relation_rationale_required')
        evidence(relation.get('evidence'))
    return {'status': 'draft', 'conversation_id': context['conversation_id'],
            'turn_id': context['turn_id'], 'source_fingerprint': fingerprint(context),
            'origins': deepcopy(context.get('origins', [])),
            'validated_structure_only': True, **result}


def validate_draft(raw, context):
    """Report all independently invalid lessons so revision fixes the full draft."""
    errors = []
    if isinstance(raw, dict) and isinstance(raw.get('lessons'), list):
        for index, lesson in enumerate(raw['lessons']):
            try:
                _validate_draft({'lessons': [lesson], 'relations': []}, context)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                errors.append('/lessons/' + str(index) + ': ' + str(error))
    if errors:
        raise ValueError('; '.join(errors))
    return _validate_draft(raw, context)


class LearningDraftStore:
    """Append-only drafts in native observations, excluded from factual retrieval."""

    def __init__(self, database):
        self.database = database

    def save(self, draft, context):
        import uuid
        from datetime import datetime, timezone
        if draft.get('source_fingerprint') != fingerprint(context):
            raise ValueError('draft_source_changed')
        current = draft_context(episode_context(self.database, context['turn_id']),
                                [claim['id'] for claim in context['claims']])
        if fingerprint(current) != fingerprint(context):
            raise ValueError('draft_message_source_changed')
        checked = validate_draft({'lessons': draft['lessons'], 'relations': draft['relations']}, context)
        observation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'eve-learning-draft:' + fingerprint(checked)))
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as c:
            turn = c.execute('SELECT conversation_id,assistant_message_id,user_message_id FROM turns WHERE id=?', (context['turn_id'],)).fetchone()
            if turn is None or turn['conversation_id'] != context['conversation_id']:
                raise ValueError('draft_turn_conversation_mismatch')
            end = c.execute('SELECT ordinal FROM messages WHERE id=?',
                            (turn['assistant_message_id'] or turn['user_message_id'],)).fetchone()[0]
            # Recheck the original receipts; a stale or synthetic context cannot
            # silently acquire the authority of a persisted conversation.
            for message in context['messages']:
                source = c.execute('SELECT conversation_id,role,content,ordinal FROM messages WHERE id=?',
                                   (message['id'],)).fetchone()
                if (source is None or source['conversation_id'] != context['conversation_id']
                        or source['ordinal'] > end
                        or source['role'] != message['role'] or source['content'] != message['content']):
                    raise ValueError('draft_message_source_changed')
            c.execute('INSERT OR IGNORE INTO memory_observations '
                      '(id,source_role,source_type,turn_id,external_ref,structured_value_json,'
                      'observed_at,scope,metadata_json,created_at) '
                      "VALUES (?,'assistant','turn',?,?,?,?,?,?,?)",
                      (observation_id, context['turn_id'], 'learning-draft:' + observation_id,
                       json.dumps(checked, ensure_ascii=False), now,
                       'conversation:' + context['conversation_id'],
                       json.dumps({'kind': 'learning_draft', 'draft_only': True,
                                   'source_fingerprint': checked['source_fingerprint']}), now))
        return {'status': 'draft', 'observation_id': observation_id}

    def inspect(self, observation_id):
        with self.database.connect() as c:
            row = c.execute("SELECT structured_value_json FROM memory_observations WHERE id=? "
                            "AND json_extract(metadata_json,'$.kind')='learning_draft'",
                            (observation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def search(self, conversation_id, query):
        """Search drafts only inside the caller's explicitly selected episode space."""
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError('conversation_required')
        if not isinstance(query, str) or not query.strip():
            raise ValueError('query_required')
        with self.database.connect() as c:
            rows = c.execute("SELECT id,structured_value_json FROM memory_observations "
                             "WHERE scope=? AND json_extract(metadata_json,'$.kind')='learning_draft' "
                             'ORDER BY created_at,id', ('conversation:' + conversation_id,)).fetchall()
        return [{'observation_id': row['id'], 'draft': json.loads(row['structured_value_json'])}
                for row in rows if query.casefold() in row['structured_value_json'].casefold()]


def draft_response_format(context):
    """Constrain transport and published references, never the meaning of a lesson."""
    evidence = {'type': 'array', 'minItems': 1, 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['message_id'],
        'properties': {'message_id': {'type': 'string', 'enum': [m['id'] for m in context['messages']]}}}}
    lesson = {'type': 'object', 'additionalProperties': False,
              'required': ['key', 'text', 'topics', 'kind', 'evidence'], 'properties': {
                  'key': {'type': 'string'}, 'text': {'type': 'string'},
                  'topics': {'type': 'array', 'items': {'type': 'string'}},
                  'kind': {'enum': ['encounter', 'semantic', 'instruction']}, 'evidence': evidence}}
    relation = {'type': 'object', 'additionalProperties': False,
                'required': ['from_key', 'target_id', 'type', 'rationale', 'evidence'], 'properties': {
                    'from_key': {'type': 'string'}, 'target_id': {'type': 'string'},
                    'type': {'enum': ['refines', 'applies_to', 'about', 'supersedes']},
                    'rationale': {'type': 'string'}, 'evidence': evidence}}
    relations = {'type': 'array', 'items': relation}
    if context['claims']:
        relation['properties']['target_id']['enum'] = [c['id'] for c in context['claims']]
    else:
        relations['maxItems'] = 0
    return {'type': 'json_schema', 'json_schema': {'name': 'learning_episode_draft', 'strict': True,
        'schema': {'type': 'object', 'additionalProperties': False, 'required': ['lessons', 'relations'],
                   'properties': {'lessons': {'type': 'array', 'items': lesson}, 'relations': relations}}}}
