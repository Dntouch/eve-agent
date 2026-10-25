import unittest
from eve_agent.associative_trial import validate_graph, neighborhood, append_revision


class AssociativeTrialTest(unittest.TestCase):
    def setUp(self):
        self.sources = [{'id': 's', 'text': 'Observation', 'origin': {'conversation_id': 'private'}}]
        self.graph = {'nodes': [{'id': n, 'text': n, 'evidence': ['s'], 'uncertainty': 'unknown'}
                                for n in ['a', 'b', 'c', 'isolated']],
                      'edges': [{'id': str(i), 'from': a, 'to': b, 'relationship': 'freely described relation',
                                 'evidence': ['s'], 'uncertainty': 'not verified'}
                                for i, (a,b) in enumerate([('a','b'),('b','c'),('c','a')])]}

    def test_free_relationship_and_receipts_survive(self):
        graph = validate_graph(self.graph, self.sources)
        self.assertEqual(graph['edges'][0]['relationship'], 'freely described relation')
        self.assertEqual(graph['edges'][0]['receipts'][0]['origin']['conversation_id'], 'private')
        self.assertNotIn('receipts', self.graph['nodes'][0])

    def test_unknown_evidence_and_endpoints_rejected(self):
        self.graph['edges'][0]['to'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'unknown_edge_endpoint'):
            validate_graph(self.graph, self.sources)
        self.graph['edges'][0]['to'] = 'b'
        self.graph['edges'][0]['evidence'] = ['foreign']
        with self.assertRaises(Exception): validate_graph(self.graph, self.sources)

    def test_cycle_terminates_and_does_not_pull_unconnected_nodes(self):
        graph = neighborhood(validate_graph(self.graph,self.sources), ['a'])
        self.assertEqual({n['id'] for n in graph['nodes']}, {'a','b','c'})
        self.assertEqual(len(graph['edges']), 3)

    def test_revisions_preserve_previous_versions(self):
        first = append_revision([], self.graph, 'initial observation')
        self.graph['edges'][0]['uncertainty'] = 'reconsidered'
        second = append_revision(first, self.graph, 'new evidence')
        self.assertEqual(first[0]['graph']['edges'][0]['uncertainty'], 'not verified')
        self.assertEqual(second[1]['graph']['edges'][0]['uncertainty'], 'reconsidered')

    def test_unknown_seed_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError,'unknown_seed'): neighborhood(self.graph,['unknown'])
