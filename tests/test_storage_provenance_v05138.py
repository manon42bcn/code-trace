from coderag.storage_provenance import storage_view_at_write


def candidate(temporal='prior_step_witness', namespace='toolium.storage'):
    return {'namespace': namespace, 'temporal_evidence': temporal}


def test_preceding_step_provides_candidate_step_phase():
    producer = {'path': 'steps/api.py', 'symbol': 'make_token'}
    scope = {'scenario_layer_reachable': True}
    result = storage_view_at_write(candidate(), producer, scope)
    assert result['writer_phase_candidate'] == 'scenario_steps_or_background'
    assert result['phase_evidence'] == 'prior_gherkin_step_witness'
    assert result['write_view_layer_candidate'] == 'scenario'
    assert result['runtime_verified'] is False


def test_key_only_candidate_remains_unknown_with_explicit_reason():
    producer = {'path': 'steps/api.py', 'symbol': 'make_token'}
    result = storage_view_at_write(
        candidate(temporal='not_ordered_in_scenario'), producer, {'scenario_layer_reachable': True}
    )
    assert result['write_view_layer_candidate'] == 'unknown_storage_view'
    assert 'no_prior_step_or_hook_phase_witness' in result['unknown_view_diagnostics']


def test_prior_step_without_hook_is_unknown_not_run_scope():
    result = storage_view_at_write(candidate(), {'path': 'steps.py', 'symbol': 'step'}, {})
    assert result['write_view_layer_candidate'] == 'unknown_storage_view'
    assert 'scenario_hook_not_reachable' in result['unknown_view_diagnostics']


def test_phase_specific_hook_writer_still_maps_to_run_or_feature():
    for phase, layer in [('before_all', 'run'), ('before_feature', 'feature')]:
        result = storage_view_at_write(
            candidate(temporal='not_ordered_in_scenario'),
            {'path': 'env/environment.py', 'symbol': phase},
            {f'{layer}_layer_reachable': True},
        )
        assert result['writer_phase_candidate'] == phase
        assert result['write_view_layer_candidate'] == layer


def test_future_writer_remains_temporally_incompatible():
    result = storage_view_at_write(
        candidate(temporal='future_step_only'),
        {'path': 'steps.py', 'symbol': 'producer'},
        {'scenario_layer_reachable': True},
    )
    assert result['write_view_layer_candidate'] == 'unknown_storage_view'
    assert result['writer_phase_candidate'] == 'future_scenario_step'
