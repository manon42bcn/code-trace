import pytest

from coderag.consumer_provenance import query_context_consumers


def fixture_report(tier='preceding_scenario_step_candidate', temporal='prior_step_witness'):
    return {
        'source_repository': 'sample',
        'relations': [
            {
                'feature_path': 'features/example.feature',
                'scenario': 'scenario: A',
                'line_approx': 20,
                'resolved_text': 'consume "[CONTEXT:id]"',
            }
        ],
        'toolium': {
            'references': [
                {'kind': 'context', 'key': 'id', 'reference': '[CONTEXT:id]', 'relation_index': 0}
            ],
            'context_flow': {
                'producers': [
                    {
                        'repository': 'sample',
                        'chunk_id': 'write',
                        'symbol': 'write',
                        'key': 'id',
                        'namespace': 'toolium.storage',
                    }
                ],
                'reference_producer_links': [
                    {
                        'reference_index': 0,
                        'candidates': [
                            {
                                'producer_id': 0,
                                'tier': tier,
                                'temporal_evidence': temporal,
                                'route_classification': 'static_path_candidate',
                                'producer_step_line': 10,
                                'witness_path': [{'repository': 'sample', 'chunk_id': 'write'}],
                            }
                        ],
                    }
                ],
            },
        },
    }


def test_prior_writer_is_explained():
    result = query_context_consumers(fixture_report(), key='id')
    assert result['consumers'][0]['status'] == 'plausible_prior_producer'
    assert result['consumers'][0]['candidates'][0]['evidence']['producer_step_line'] == 10
    assert not result['consumers'][0]['runtime_verified']


def test_future_writer_is_not_prior():
    result = query_context_consumers(
        fixture_report('key_only_candidate', 'future_step_only'), only_prior=True
    )
    assert result['consumers'][0]['status'] == 'no_prior_writer_identified'
    assert not result['consumers'][0]['candidates']


def test_no_writer_does_not_claim_absence():
    report = fixture_report()
    report['toolium']['context_flow']['reference_producer_links'][0]['candidates'] = []
    assert query_context_consumers(report)['consumers'][0]['status'] == 'producer_not_identified'


def test_filter_and_bounded_results():
    r = fixture_report()
    assert query_context_consumers(r, feature='unrelated')['summary']['matching_consumers'] == 0
    assert query_context_consumers(r, scenario='A')['summary']['matching_consumers'] == 1
    with pytest.raises(ValueError, match='Los límites deben ser positivos'):
        query_context_consumers(r, max_consumers=0)


def test_invalid_source_reference_fails():
    r = fixture_report()
    r['toolium']['context_flow']['reference_producer_links'][0]['candidates'][0]['producer_id'] = 3
    with pytest.raises(ValueError, match='producer_id inválido'):
        query_context_consumers(r)
