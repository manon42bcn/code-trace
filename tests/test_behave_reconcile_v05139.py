import json

import pytest

from coderag.behave_reconcile import apply_reconciliation


def _report():
    return {
        'relations': [
            {
                'feature_path': 'acceptance/features/a.feature',
                'line_approx': 9,
                'text': 'step A',
                'resolved_text': 'step A',
                'status': 'unresolved',
            },
            {
                'feature_path': 'acceptance/features/a.feature',
                'line_approx': 10,
                'text': 'step B',
                'resolved_text': 'step B',
                'status': 'resolved_external',
            },
            {
                'feature_path': 'acceptance/features/a.feature',
                'line_approx': 11,
                'text': 'step C',
                'resolved_text': 'step C',
                'status': 'unresolved',
            },
        ]
    }


def test_dry_run_and_explicit_plan_are_separate(tmp_path):
    dry = [
        {
            'uri': '/repo/acceptance/features/a.feature',
            'elements': [
                {
                    'name': 'scenario',
                    'steps': [
                        {'line': 9, 'name': 'step A', 'result': {'status': 'undefined'}},
                        {'line': 10, 'name': 'step B', 'result': {'status': 'undefined'}},
                        {'line': 11, 'name': 'step C', 'result': {'status': 'skipped'}},
                    ],
                }
            ],
        }
    ]
    plan = {
        'steps': [
            {
                'feature_path': 'acceptance/features/a.feature',
                'line': 9,
                'implementation_status': 'planned',
            }
        ]
    }
    dp, pp = tmp_path / 'dry.json', tmp_path / 'plan.json'
    dp.write_text(json.dumps(dry))
    pp.write_text(json.dumps(plan))
    report = apply_reconciliation(_report(), dry_run_path=dp, plan_path=pp)
    a, b, c = [r['implementation_evidence'] for r in report['relations']]
    assert a['implementation_status'] == 'planned'
    assert a['reconciliation'] == 'both_unresolved'
    assert b['implementation_status'] == 'unknown'
    assert b['reconciliation'] == 'static_resolved_but_behave_not_defined'
    assert c['behave_status'] == 'skipped'
    assert c['reconciliation'] == 'no_detected_conflict'
    assert report['behave_reconciliation']['dry_run_unmatched_records'] == 0
    assert report['relations'][0]['status'] == 'unresolved'


def test_absent_dry_run_and_unmatched_do_not_claim_undefined(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'other/features/x.feature',
                        'line': 9,
                        'text': 'step A',
                        'status': 'undefined',
                    }
                ]
            }
        )
    )
    report = apply_reconciliation(_report(), dry_run_path=dp)
    assert all(
        x['implementation_evidence']['behave_status'] == 'not_matched' for x in report['relations']
    )
    assert report['behave_reconciliation']['dry_run_unmatched_records'] == 1
    report = apply_reconciliation(_report(), plan_path=None)
    assert 'implementation_evidence' not in report['relations'][0]


def test_plan_requires_explicit_classification(tmp_path):
    pp = tmp_path / 'plan.json'
    pp.write_text(json.dumps({'steps': [{'feature_path': 'a.feature', 'line': 4}]}))
    with pytest.raises(ValueError, match='implementation_status'):
        apply_reconciliation(_report(), plan_path=pp)


def test_multiple_dry_run_statuses_are_not_forced(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'acceptance/features/a.feature',
                        'line': 9,
                        'text': 'step A',
                        'status': 'undefined',
                    },
                    {
                        'feature_path': 'acceptance/features/a.feature',
                        'line': 9,
                        'text': 'step A',
                        'status': 'skipped',
                    },
                ]
            }
        )
    )
    r = apply_reconciliation(_report(), dry_run_path=dp)
    assert r['relations'][0]['implementation_evidence']['behave_status'] == 'ambiguous_dry_run'
