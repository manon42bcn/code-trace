import json

from coderag.behave_links import build_behave_relations
from coderag.repo_links import build_repository_links


def test_distinct_outline_rows_not_ambiguous(tmp_path):
    chunks = [
        {
            'id': 'scenario',
            'path': 'features/handoff.feature',
            'language': 'gherkin',
            'symbol': 'scenario_outline: handoff',
            'start_line': 1,
            'content': (
                'Scenario Outline: handoff\n Then the handoff suggestion <handoff> '
                'in the response\n Examples:\n | handoff |\n | is present |\n | is '
                'not present |'
            ),
        },
        {
            'id': 'yes',
            'path': 'features/steps/a.py',
            'language': 'python',
            'strategy': 'python_ast',
            'symbol': 'yes',
            'start_line': 1,
            'content': (
                '@then("the handoff suggestion is present in the response")\ndef yes(context): pass'
            ),
        },
        {
            'id': 'no',
            'path': 'features/steps/b.py',
            'language': 'python',
            'strategy': 'python_ast',
            'symbol': 'no',
            'start_line': 1,
            'content': (
                '@then("the handoff suggestion is not present in the response")\n'
                'def no(context): pass'
            ),
        },
    ]
    (tmp_path / 'indexes').mkdir(exist_ok=True)
    (tmp_path / 'indexes/r.chunks.json').write_text(
        json.dumps({'chunks': chunks, 'behave_relations': build_behave_relations(chunks)})
    )
    result = build_repository_links({'repositories': {'r': {}}}, tmp_path / 'config.json', 'r')
    assert result['summary']['step_occurrences'] == 1
    assert result['summary']['evaluated_cases'] == 2
    assert result['summary']['ambiguous'] == 0
    assert [x['definitions'][0]['function'] for x in result['relations']] == ['yes', 'no']
    assert [x['example_row'] for x in result['relations']] == [1, 2]


def test_out_of_scope_reason(tmp_path):
    chunks = [
        {
            'id': 'f',
            'path': 'web_behave/features/x.feature',
            'language': 'gherkin',
            'symbol': 'scenario: S',
            'start_line': 1,
            'content': 'Scenario: S\n Given login',
        },
        {
            'id': 'fn',
            'path': 'another_behave/steps/auth.py',
            'language': 'python',
            'strategy': 'python_ast',
            'symbol': 'login',
            'start_line': 1,
            'content': '@given("login")\ndef login(context): pass',
        },
    ]
    (tmp_path / 'indexes').mkdir(exist_ok=True)
    (tmp_path / 'indexes/r.chunks.json').write_text(
        json.dumps({'chunks': chunks, 'behave_relations': build_behave_relations(chunks)})
    )
    res = build_repository_links({'repositories': {'r': {}}}, tmp_path / 'c.json', 'r')
    assert res['relations'][0]['reason'] == 'matching_definition_outside_local_scope'
