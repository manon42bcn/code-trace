import json

from coderag.behave_reconcile import apply_reconciliation
from coderag.capability_contract import attach_capability_contract, build_capability_contract


def test_generic_python_without_gherkin_or_toolium():
    indexes = {'lib': {'chunks': [{'language': 'python'}, {'language': 'javascript'}]}}
    report = {'source_repository': 'lib', 'relations': [], 'toolium': {}}
    contract = build_capability_contract(indexes, report)
    caps = contract['capabilities']
    assert caps['python_ast']['status'] == 'available'
    assert caps['gherkin']['status'] == 'not_applicable'
    assert caps['behave_dry_run']['status'] == 'not_applicable'
    assert caps['toolium_storage']['status'] == 'not_evaluated'
    assert contract['evidence']['runtime_verified'] is False


def test_gherkin_without_dry_run_remains_not_evaluated():
    indexes = {'bdd': {'chunks': [{'language': 'gherkin'}]}}
    report = {'source_repository': 'bdd', 'relations': [{'status': 'unresolved'}], 'toolium': {}}
    contract = build_capability_contract(indexes, report)
    assert contract['capabilities']['behave_dry_run']['status'] == 'not_evaluated'
    assert contract['evidence']['resolution_counts'] == {'unresolved': 1}
    assert contract['evidence']['guarantees']['unresolved_means_planned'] is False


def test_toolium_static_evidence_no_runtime_claim():
    indexes = {'app': {'chunks': [{'language': 'python'}, {'language': 'gherkin'}]}}
    report = {
        'source_repository': 'app',
        'relations': [],
        'toolium': {
            'context_flow': {
                'producers': [{'namespace': 'toolium.storage'}],
                'consumers': [{'namespace': 'behave.context'}],
            }
        },
    }
    contract = build_capability_contract(indexes, report)
    assert contract['capabilities']['toolium_storage']['status'] == 'available'
    assert contract['capabilities']['toolium_storage']['observations'] == 1
    assert all(not item['runtime_verified'] for item in contract['capabilities'].values())


def test_optional_dry_run_enriches_capability_without_changing_resolution(tmp_path):
    indexes = {'bdd': {'chunks': [{'language': 'gherkin'}]}}
    report = {
        'source_repository': 'bdd',
        'relations': [
            {
                'feature_path': 'features/a.feature',
                'line_approx': 5,
                'text': 'hello',
                'status': 'unresolved',
            }
        ],
        'toolium': {},
    }
    attach_capability_contract(report, indexes)
    dry = tmp_path / 'run.json'
    dry.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'features/a.feature',
                        'line': 5,
                        'text': 'hello',
                        'status': 'undefined',
                    }
                ]
            }
        )
    )
    apply_reconciliation(report, dry_run_path=dry)
    assert report['relations'][0]['status'] == 'unresolved'
    assert (
        report['analysis_capabilities']['capabilities']['behave_dry_run']['status'] == 'available'
    )
    assert (
        report['analysis_capabilities']['evidence']['external_observations']['behave_dry_run']
        == 'supplied'
    )
    assert report['analysis_capabilities']['evidence']['runtime_verified'] is False
