from coderag.storage_provenance import assess_reference, storage_view_at_write


def candidate(pid, ns='toolium.storage', temporal='prior_step_witness', line=4):
    return {
        'producer_id': pid,
        'namespace': ns,
        'temporal_evidence': temporal,
        'producer_step_line': line,
        'conditional_fallback': ns == 'behave.context',
        'nested_path_status': 'not_nested',
    }


def test_phase_specific_chainmap_view_does_not_always_mean_scenario():
    scope = {
        'scenario_layer_reachable': True,
        'feature_layer_reachable': True,
        'run_layer_reachable': True,
    }
    for hook, expected in [
        ('before_all', 'run'),
        ('before_feature', 'feature'),
        ('before_scenario', 'scenario'),
    ]:
        result = storage_view_at_write(
            candidate(0), {'path': 'features/environment.py', 'symbol': hook}, scope
        )
        assert result['write_view_layer_candidate'] == expected


def test_same_layer_later_prior_step_is_only_a_possible_overwrite():
    writers = [{'path': 'steps.py', 'symbol': 'a'}, {'path': 'steps.py', 'symbol': 'b'}]
    c = [candidate(0, line=4), candidate(1, line=7)]
    summary = assess_reference(c, writers, {'scenario_layer_reachable': True})
    assert summary['candidate_count'] == 2
    assert c[0]['provenance_assessment']['status'] == 'conditional_applicability'
    assert (
        'later_prior_step_same_layer_may_overwrite' in c[0]['provenance_assessment']['conditions']
    )
    assert c[1]['provenance_assessment']['status'] == 'plausible_prior_writer'
    assert all(not x['provenance_assessment']['effective_value_confirmed'] for x in c)


def test_priority_is_distinct_from_step_order():
    writers = [{'path': 'steps.py', 'symbol': 'first'}, {'path': 'steps.py', 'symbol': 'second'}]
    c = [candidate(0, 'toolium.run_storage', line=6), candidate(1, 'toolium.storage', line=4)]
    assess_reference(c, writers, {'scenario_layer_reachable': True, 'run_layer_reachable': True})
    assert 'higher_priority_layer_may_hide' in c[0]['provenance_assessment']['conditions']
    assert c[0]['provenance_assessment']['status'] == 'conditional_applicability'


def test_future_writer_is_not_promoted_as_prior_source():
    c = [candidate(0, temporal='future_step_only', line=None)]
    assess_reference(
        c, [{'path': 'steps.py', 'symbol': 'write'}], {'scenario_layer_reachable': True}
    )
    assert c[0]['provenance_assessment']['status'] == 'temporally_incompatible_candidate'
    assert c[0]['provenance_assessment']['runtime_verified'] is False


def test_unknown_storage_view_stays_conditional():
    c = [candidate(0)]
    assess_reference(c, [{'path': 'steps.py', 'symbol': 'write'}], {})
    assert c[0]['write_context_evidence']['write_view_layer_candidate'] == 'unknown_storage_view'
    assert c[0]['provenance_assessment']['status'] == 'conditional_applicability'
