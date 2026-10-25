import unittest
from copy import deepcopy
from eve_agent.dependency_trial import review_candidates,apply_review


class DependencyTrialTest(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':i,'text':i,'uncertainty':'unknown','evidence':['s'],'depends_on':d}
                   for i,d in [('root',[]),('child',['root']),('grandchild',['child']),('other',[])]]

    def test_only_directed_dependents_are_selected(self):
        self.assertEqual(review_candidates(self.rows,['child']),['child','grandchild'])
        self.assertEqual(review_candidates(self.rows,['root']),['root','child','grandchild'])

    def test_cycle_terminates(self):
        self.rows[0]['depends_on']=['grandchild']
        self.assertEqual(review_candidates(self.rows,['root']),['root','child','grandchild'])

    def test_unaffected_records_are_byte_equivalent_and_input_unchanged(self):
        before=deepcopy(self.rows);update={**self.rows[1],'text':'Reconsidered'}
        result=apply_review(self.rows,{'reviewed_ids':['child','grandchild'],'updates':[update]},
                            ['child','grandchild'],[{'id':'s'}])
        self.assertEqual(self.rows,before)
        self.assertEqual(result[0],before[0]);self.assertEqual(result[3],before[3])
        self.assertEqual(result[1]['text'],'Reconsidered')

    def test_foreign_updates_and_incomplete_reviews_rejected(self):
        with self.assertRaises(ValueError):
            apply_review(self.rows,{'reviewed_ids':[],'updates':[]},['root'],[{'id':'s'}])
        with self.assertRaises(Exception):
            apply_review(self.rows,{'reviewed_ids':['root'],'updates':[self.rows[3]]},['root'],[{'id':'s'}])

    def test_unknown_dependencies_rejected(self):
        self.rows[1]['depends_on']=['missing']
        with self.assertRaisesRegex(ValueError,'unknown_dependency'):
            review_candidates(self.rows,['root'])

    def test_learned_dependencies_must_reference_generated_memories(self):
        from eve_agent.dependency_trial import validate_learned
        self.assertEqual(validate_learned(self.rows,[{'id':'s'}]), self.rows)
        self.rows[0]['depends_on'] = ['invented']
        with self.assertRaisesRegex(ValueError,'unknown_dependency'):
            validate_learned(self.rows,[{'id':'s'}])
