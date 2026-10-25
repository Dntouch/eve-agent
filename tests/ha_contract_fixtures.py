"""Complete synthetic model outputs, never runtime normalization defaults."""
def provider_plan(actions=(), *, quote='fixture', effect='read', **overrides):
    result = dict(effect=effect, interpreted_target='Fixture target', contextual_authorization=False,
        target_from_context=False, confirmed_remembered_binding_ids=[], live_verification_required=False,
        context_required=False, clarification=None, actions=list(actions), semantic_learning={
            'status':'resolved','context_keys':[], 'user_grounding':'explicit','uncertainties':[],
            'utterance_quote':quote,'basis':'Fixture explicit request and provider evidence',
            'action_link':{'kind':'none','representation_id':'','anchor_claim_id':'','meaning':'','basis':''}})
    result.update(overrides)
    return result
