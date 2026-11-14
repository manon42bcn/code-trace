import json

from coderag.behave_reconcile import apply_reconciliation


def test_dependency_definition_diagnostic(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            [
                {
                    'location': 'features/x.feature:1',
                    'elements': [
                        {
                            'steps': [
                                {
                                    'location': 'features/x.feature:5',
                                    'name': 'an api step',
                                    'match': {
                                        'location': (
                                            '../.venv/lib/python3.11/site-packages/'
                                            'example/steps/api.py:10'
                                        )
                                    },
                                    'result': {'status': 'untested'},
                                }
                            ]
                        }
                    ],
                }
            ]
        )
    )
    report = {
        'relations': [
            {
                'feature_path': 'acceptance/features/x.feature',
                'line_approx': 5,
                'text': 'an api step',
                'status': 'unresolved',
                'reason': 'no_matching_definition_in_configured_scopes',
            }
        ]
    }
    apply_reconciliation(report, dry_run_path=dp)
    diagnostic = report['relations'][0]['implementation_evidence']['discrepancy_diagnostic']
    assert diagnostic['category'] == 'dependency_scope_or_pattern_match'
    assert diagnostic['definition_origins'] == ['installed_dependency']
    assert diagnostic['conclusion_verified'] is False
    assert report['behave_reconciliation']['diagnostic_categories'] == {
        'dependency_scope_or_pattern_match': 1
    }


def test_local_definition_diagnostic(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'features/x.feature',
                        'line': 8,
                        'text': 'a step',
                        'match': {'location': 'common/steps/a.py:8'},
                        'status': 'untested',
                    }
                ]
            }
        )
    )
    report = {
        'relations': [
            {
                'feature_path': 'acceptance/features/x.feature',
                'line_approx': 8,
                'text': 'a step',
                'status': 'unresolved',
            }
        ]
    }
    apply_reconciliation(report, dry_run_path=dp)
    assert (
        report['relations'][0]['implementation_evidence']['discrepancy_diagnostic']['category']
        == 'local_scope_or_pattern_match'
    )


def test_undefined_diagnostic_is_not_planned(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'features/x.feature',
                        'line': 8,
                        'text': 'a step',
                        'match': None,
                        'status': 'undefined',
                    }
                ]
            }
        )
    )
    report = {
        'relations': [
            {
                'feature_path': 'acceptance/features/x.feature',
                'line_approx': 8,
                'text': 'a step',
                'status': 'resolved_local',
            }
        ]
    }
    apply_reconciliation(report, dry_run_path=dp)
    ev = report['relations'][0]['implementation_evidence']
    assert ev['implementation_status'] == 'unknown'
    assert (
        ev['discrepancy_diagnostic']['category']
        == 'runtime_registration_or_source_version_difference'
    )
