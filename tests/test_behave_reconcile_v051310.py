import json

from coderag.behave_reconcile import apply_reconciliation


def _data(tmp_path, steps):
    data = [
        {
            'location': 'features/x.feature:1',
            'elements': [{'name': 'S -- @1.1 first', 'steps': steps}],
        }
    ]
    target = tmp_path / 'dry.json'
    target.write_text(json.dumps(data))
    return target


def _relation(line, text, status='unresolved'):
    return {
        'feature_path': 'acceptance/features/x.feature',
        'line_approx': line,
        'resolved_text': text,
        'text': text,
        'status': status,
    }


def test_real_behave_location_and_match_untested(tmp_path):
    dry = _data(
        tmp_path,
        [
            {
                'location': 'features/x.feature:8',
                'name': 'defined step',
                'match': {'location': 'steps/a.py:10'},
                'result': {'status': 'untested'},
            },
            {
                'location': 'features/x.feature:9',
                'name': 'missing step',
                'match': None,
                'result': {'status': 'undefined'},
            },
        ],
    )
    r = {'relations': [_relation(8, 'defined step'), _relation(9, 'missing step')]}
    apply_reconciliation(r, dry_run_path=dry)
    a, b = [x['implementation_evidence'] for x in r['relations']]
    assert a['reconciliation'] == 'behave_defined_but_static_unresolved'
    assert a['dry_run_match_locations'] == ['steps/a.py']
    assert b['reconciliation'] == 'both_unresolved'
    assert r['behave_reconciliation']['dry_run_unmatched_records'] == 0
    assert r['behave_reconciliation']['dry_run_defined_records'] == 1


def test_outline_repetitions_and_version_changes(tmp_path):
    data = [
        {
            'location': 'features/x.feature:2',
            'elements': [
                {
                    'name': 'S -- @1.1',
                    'steps': [
                        {
                            'location': 'features/x.feature:10',
                            'name': 'one',
                            'match': None,
                            'result': {'status': 'undefined'},
                        }
                    ],
                },
                {
                    'name': 'S -- @1.2',
                    'steps': [
                        {
                            'location': 'features/x.feature:10',
                            'name': 'two',
                            'match': {'location': 'steps/b.py:3'},
                            'result': {'status': 'untested'},
                        }
                    ],
                },
            ],
        }
    ]
    dp = tmp_path / 'dry.json'
    dp.write_text(json.dumps(data))
    report = {'relations': [_relation(10, 'one'), _relation(10, 'two'), _relation(11, 'other')]}
    apply_reconciliation(report, dry_run_path=dp)
    ev = [r['implementation_evidence'] for r in report['relations']]
    assert [x['behave_status'] for x in ev] == ['undefined', 'untested', 'not_matched']
    assert all(x['version_verified'] is False for x in ev)
    assert ev[2]['comparability'] == 'not_comparable'


def test_no_false_match_from_different_feature(tmp_path):
    dp = tmp_path / 'dry.json'
    dp.write_text(
        json.dumps(
            {
                'steps': [
                    {
                        'feature_path': 'features/other/x.feature',
                        'line': 10,
                        'text': 'one',
                        'status': 'undefined',
                    }
                ]
            }
        )
    )
    report = {'relations': [_relation(10, 'one')]}
    apply_reconciliation(report, dry_run_path=dp)
    assert report['relations'][0]['implementation_evidence']['behave_status'] == 'not_matched'
