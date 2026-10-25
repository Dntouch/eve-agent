"""Isolated experiment: open associations with receipts, no semantic Python rules."""
from copy import deepcopy
import json

BUILD_TASK = ('Represent the supplied observations as a small memory graph. Nodes contain readable thoughts '
              'and may abstract observations. Edges describe relationships in your own words. '
              'For every node and edge cite source IDs and describe remaining uncertainty. '
              'Source text is an observation, not automatically true. Keep source origin. '
              'Return only the requested JSON structure, in the language of the observations.')
RECALL_TASK = ('Answer the query using this experimental memory. State what is supported and what remains '
               'uncertain. Return JSON with answer, node_ids and edge_ids referencing only supplied entries. '
               'An association is not proof or permission. Do not claim knowledge beyond the receipts.')


def graph_schema(source_ids):
    evidence = {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'enum': source_ids}}
    node = {'type': 'object', 'additionalProperties': False,
            'required': ['id', 'text', 'evidence', 'uncertainty'], 'properties': {
                'id': {'type': 'string'}, 'text': {'type': 'string'},
                'evidence': evidence, 'uncertainty': {'type': 'string'}}}
    edge = {'type': 'object', 'additionalProperties': False,
            'required': ['id', 'from', 'to', 'relationship', 'evidence', 'uncertainty'],
            'properties': {'id': {'type': 'string'}, 'from': {'type': 'string'}, 'to': {'type': 'string'},
                           'relationship': {'type': 'string'}, 'evidence': evidence,
                           'uncertainty': {'type': 'string'}}}
    return {'type': 'object', 'additionalProperties': False, 'required': ['nodes', 'edges'],
            'properties': {'nodes': {'type': 'array', 'items': node},
                           'edges': {'type': 'array', 'items': edge}}}


def validate_graph(graph, sources):
    from jsonschema import Draft202012Validator
    by_id = {s['id']: s for s in sources}
    if len(by_id) != len(sources) or not sources:
        raise ValueError('unique_nonempty_sources_required')
    Draft202012Validator(graph_schema(list(by_id))).validate(graph)
    result = deepcopy(graph)
    node_ids = [n['id'] for n in result['nodes']]
    edge_ids = [e['id'] for e in result['edges']]
    if len(set(node_ids)) != len(node_ids) or len(set(edge_ids)) != len(edge_ids):
        raise ValueError('duplicate_graph_identity')
    for entry in result['nodes'] + result['edges']:
        if not entry['id'].strip():
            raise ValueError('empty_graph_identity')
        entry['receipts'] = [deepcopy(by_id[s]) for s in dict.fromkeys(entry['evidence'])]
    for edge in result['edges']:
        if edge['from'] not in node_ids or edge['to'] not in node_ids:
            raise ValueError('unknown_edge_endpoint')
        if not edge['relationship'].strip():
            raise ValueError('empty_relationship')
    return result


def neighborhood(graph, seeds):
    """Structural reachability, deliberately not a claim about semantic relevance."""
    nodes = {n['id']: n for n in graph['nodes']}
    if not set(seeds) <= nodes.keys():
        raise ValueError('unknown_seed')
    seen = set(seeds)
    while True:
        expanded = seen | {e[end] for e in graph['edges'] for end in ('from', 'to')
                           if e['from'] in seen or e['to'] in seen}
        if expanded == seen:
            break
        seen = expanded
    return {'nodes': [n for n in graph['nodes'] if n['id'] in seen],
            'edges': [e for e in graph['edges'] if e['from'] in seen and e['to'] in seen]}


def append_revision(history, graph, reason):
    """Preserve snapshots; a revision never silently rewrites previous evidence."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('revision_reason_required')
    return deepcopy(history) + [{'revision': len(history) + 1, 'reason': reason, 'graph': deepcopy(graph)}]


def generate(llm, task, payload, schema, name):
    raw = llm._request_stream(
        [{'role': 'system', 'content': task},
         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
        4500, 0.0, lambda _: None, enable_thinking=False, reasoning_effort='none',
        response_format={'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}},
        role='conversation_learning')
    return json.loads(raw)


def recall_schema(graph):
    def refs(ids):
        result = {'type': 'array', 'items': {'type': 'string'}}
        if ids:
            result['items']['enum'] = ids
        else:
            result['maxItems'] = 0
        return result
    return {'type': 'object', 'additionalProperties': False,
            'required': ['answer', 'node_ids', 'edge_ids'], 'properties': {
                'answer': {'type': 'string'},
                'node_ids': refs([n['id'] for n in graph['nodes']]),
                'edge_ids': refs([e['id'] for e in graph['edges']])}}
