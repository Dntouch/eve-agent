"""Structural learning transport contract. No task words or interpretation rules."""
from copy import deepcopy
import json
import re

EVIDENCE_SOURCES = frozenset({'user_message', 'provider_result'})
CLAIM_KINDS = frozenset({'opaque_fact', 'provider_binding', 'alias'})
SCOPE_PATTERN = r'^(?:user|household|project|provider|device|legacy|conversation):[a-z0-9][a-z0-9.:-]*$'
DECISIONS = frozenset({'no_persist', 'create_active', 'create_candidate', 'append_supporting_evidence',
    'append_contradicting_evidence', 'create_competing_claim', 'supersede_claim', 'refine_claim', 'undetermined'})
EVIDENCE_CONTRACT = {
    'required': ['source_type', 'source_id'],
    'source_type': sorted(EVIDENCE_SOURCES),
    'optional': ['stance', 'property', 'external_reference', 'result_pointer', 'observed_value'],
    'required_by_source_type': {},
    'provider_result_alternatives': [
        {'required': ['result_pointer', 'observed_value'], 'root': 'original tool result',
         'result_pointer': 'RFC6901 pointer; empty selects root',
         'observed_value': 'exact JSON value at pointer, preserving its JSON type'},
        {'required': ['property', 'external_reference'], 'mode': 'resource_binding'},
    ],
    'provider_result_binding': {'external_reference': 'value present in the tool result',
                                'property': 'key in the object containing that reference'},
}


PROVENANCE_CONTRACT = {
    'user_statement': {'authority': 'user_direct', 'epistemic_kind': 'user_statement',
                       'grounding': 'User reports a fact or corrected fact, not requested assistant behavior; applicability=query even when the fact is durable.'},
    'user_instruction': {'authority': 'user_direct', 'epistemic_kind': 'user_instruction',
                         'grounding': 'User explicitly requests assistant behavior; copy verbatim current user text. A quotation of a reported fact is not an instruction.'},
    'tool_observation': {'epistemic_kind': 'tool_observation',
                         'grounding': 'cited tool result value; not a general procedure'},
    'inferred_procedure': {'authority': 'model_inference', 'epistemic_kind': 'inferred_procedure',
                          'decision_type': 'create_candidate',
                          'grounding': 'model derives a procedure from the request and observations'},
    'user_request': 'Defines the requested result; does not automatically author the technical method.',
    'assistant_context': 'Unverified explanation, not user wording or execution proof.',
}


def learning_response_format(*, batch=False, contexts=None):
    """Constrain the envelope and reference shape, not the model's judgement."""
    proposal = {'type': 'object', 'required': ['decision_type', 'memory_worthy', 'reason_code', 'uncertainty',
        'clarification_recommended', 'authority', 'temporal_class', 'change_type', 'claim', 'evidence',
        'matched_claim_ids', 'relations'], 'properties': {
        'decision_type': {'enum': sorted(DECISIONS)},
        'memory_worthy': {'type': ['boolean', 'null']}, 'reason_code': {'type': 'string'},
        'uncertainty': {'type': ['number', 'null']}, 'clarification_recommended': {'type': 'boolean'},
        'authority': {'type': ['string', 'null'], 'description': 'Origin of this claim, distinct from candidate/active status. user_direct: user wording; model_inference: derived claim.'}, 'temporal_class': {'type': ['string', 'null']},
        'change_type': {'type': ['string', 'null']},
        'matched_claim_ids': {'type': 'array', 'items': {'type': 'string'}},
        'relations': {'type': 'array', 'items': {'type': 'object'}},
        'claim': {'type': ['object', 'null'], 'required': ['kind', 'scope', 'canonical_key', 'display_text', 'payload'], 'properties': {
            'kind': {'enum': sorted(CLAIM_KINDS)},
            'scope': {'type': 'string', 'pattern': SCOPE_PATTERN},
            'canonical_key': {'type': 'string', 'pattern': r'^(?:v2:|alias:|provider_binding:)'},
            'slot_key': {'type': ['string', 'null']}, 'display_text': {'type': 'string',
                'description': 'For payload.epistemic_kind=user_instruction copy a verbatim substring of the current user_message; explanations belong in reason_code.'},
            'payload': {'type': 'object', 'properties': {'applicability': {'enum': ['query', 'always'],
                'description': 'always: assistant behavior explicitly requested across topics; query: topical retrieval, including durable user-reported facts. Permanence of a fact does not mean always.'}, 'epistemic_kind': {'type': 'string',
                'description': 'user_statement: user reports a fact or correction; user_instruction: user explicitly requests assistant behavior, not merely a verbatim quotation; tool_observation: observed value; inferred_procedure: derived candidate. Other knowledge kinds remain allowed.'}}},
        }},
        'evidence': {'type': 'array', 'items': {'type': 'object',
            'required': ['source_type', 'source_id'], 'properties': {
                'source_type': {'enum': sorted(EVIDENCE_SOURCES)},
                'source_id': {'type': 'string'},
                'stance': {'type': 'string'},
                'property': {'type': ['string', 'null']},
                'external_reference': {'type': ['string', 'null']},
                'result_pointer': {'type': ['string', 'null'], 'description': 'RFC6901 path into original tool result; empty selects root, null means unused.'},
                'observed_value': {'description': 'Original JSON value at result_pointer; preserve type, e.g. boolean true rather than string true.'},
            }}},
    }}
    from .conversation_semantics import formulation_schema
    semantic_schema = formulation_schema()
    semantic_schema['type'] = ['object', 'null']
    proposal['properties']['semantic_formulation'] = semantic_schema
    proposal['properties']['semantic_learning_reason'] = {'type': 'string'}
    proposal['properties']['decision_type']['description'] = (
        'General knowledge decision only. If only a semantic formulation is learned, use no_persist '
        'with claim=null, evidence=[], matched_claim_ids=[] and relations=[]. Semantic action matching '
        'belongs only in semantic_formulation.assessment.action_link, never in the general append decision.')
    if any((context.get('semantic_learning') or {}).get('available') for context in contexts or []):
        proposal['required'] += ['semantic_formulation', 'semantic_learning_reason']
    if contexts and len(contexts) == 1:
        semantic_context = contexts[0].get('semantic_learning') or {}
        if semantic_context.get('executions'):
            semantic_schema['properties']['call_references']['items']['enum'] = sorted(semantic_context['executions'])
        if semantic_context.get('observations'):
            semantic_schema['properties']['evidence']['items']['properties']['call_reference']['enum'] = sorted(semantic_context['observations'])
        if semantic_context.get('available'):
            declaration_schema = semantic_schema['properties']['assessment']['properties']['action_link']
            candidates = semantic_context.get('action_candidates', [])
            declaration_schema['anyOf'] = [
                {'properties': {'kind': {'const': 'existing'},
                                'representation_id': {'const': item['representation_id']},
                                'anchor_claim_id': {'enum': [e['claim_id'] for e in item['examples']]}},
                 'required': ['representation_id', 'anchor_claim_id']}
                for item in candidates if item.get('examples')
            ] + declaration_schema['anyOf'][1:]
    source_ids = set()
    claim_ids = set()
    for context in contexts or []:
        user = context.get('user_message') or {}
        if user.get('id'):
            source_ids.add(user['id'])
        for tool in context.get('tool_events') or []:
            reference = tool.get('evidence_reference') or {}
            if reference.get('source_id'):
                source_ids.add(reference['source_id'])
        for candidate in context.get('claim_candidates') or []:
            if candidate.get('id'):
                claim_ids.add(candidate['id'])
    if source_ids:
        proposal['properties']['evidence']['items']['properties']['source_id']['enum'] = sorted(source_ids)
    if claim_ids:
        proposal['properties']['matched_claim_ids']['items']['enum'] = sorted(claim_ids)
    schema = {'type': 'object', 'required': ['turns'], 'properties': {
        'turns': {'type': 'array', 'items': {'type': 'object', 'required': ['turn_id', 'proposal'],
            'properties': {'turn_id': {'type': 'string'}, 'proposal': deepcopy(proposal)}}},
    }} if batch else proposal
    if batch and contexts:
        # These are exact request references/cardinality, not resource caps.
        entries = []
        for context in contexts:
            entries.append({'type': 'object', 'required': ['turn_id', 'proposal'], 'properties': {
                'turn_id': {'enum': [context['turn_id']]},
                'proposal': learning_response_format(contexts=[context])['json_schema']['schema'],
            }})
        schema['properties']['turns'].update({
            'minItems': len(contexts), 'maxItems': len(contexts), 'items': {'anyOf': entries},
        })
    return {'type': 'json_schema', 'json_schema': {'name': 'conversation_learning' if batch else 'shadow_learning',
                                                 'schema': schema}}


def parse_learning_json(raw):
    """Accept one complete JSON value, optionally wrapped in one Markdown fence."""
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, flags=re.S | re.I)
    return json.loads(fence.group(1) if fence else text)
