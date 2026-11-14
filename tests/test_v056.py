import json

from coderag.behave_links import _pattern_regex, build_behave_relations
from coderag.repo_links import _outline_rows, _variants, build_repository_links


def test_quoted_fields_cannot_cross_quotes():
    short = _pattern_regex('the response body is validated against the JSON schema "{schema}"')
    long = _pattern_regex(
        'the response body is validated against the JSON schema "{schema}" in "{folder}"'
    )
    text = (
        'the response body is validated against the JSON schema '
        '"microfrontends_get" in "agent_builder"'
    )
    assert not short.fullmatch(text)
    assert long.fullmatch(text)
    assert short.fullmatch(
        'the response body is validated against the JSON schema "microfrontends_get"'
    )


def test_outline_rows_multiple_examples():
    content = (
        'Scenario Outline: codes\n Given the response status code is '
        '"<status_code>"\n Examples: first\n | status_code | description |'
        '\n | 200 | ok |\n Examples: other\n | status_code |\n | 404 |\n '
    )
    rows = _outline_rows(content)
    assert rows == [{'status_code': '200', 'description': 'ok'}, {'status_code': '404'}]
    assert _variants('the response status code is "<status_code>"', rows) == [
        'the response status code is "200"',
        'the response status code is "404"',
    ]


def test_outline_link_numeric_type(tmp_path):
    chunks = [
        {
            'id': 'f',
            'path': 'features/codes.feature',
            'language': 'gherkin',
            'strategy': 'gherkin_ast',
            'symbol': 'scenario_outline: codes',
            'start_line': 1,
            'content': (
                'Scenario Outline: codes\n Given the response status code is '
                '"<status_code>"\n Examples: status\n | status_code |\n | 200 |\n |'
                ' 404 |'
            ),
        },
        {
            'id': 'd',
            'path': 'features/steps/status.py',
            'language': 'python',
            'strategy': 'python_ast',
            'symbol': 'status',
            'start_line': 1,
            'content': (
                '@given(\'the response status code is "{code:d}"\')\ndef '
                'status(context, code):\n pass'
            ),
        },
    ]
    data = {'chunks': chunks, 'behave_relations': build_behave_relations(chunks)}
    (tmp_path / 'indexes').mkdir(exist_ok=True)
    (tmp_path / 'indexes/example.chunks.json').write_text(json.dumps(data))
    config = {'repositories': {'example': {}}}
    result = build_repository_links(config, tmp_path / 'cfg.json', 'example')
    assert result['summary']['resolved_local'] == 2
    assert result['summary']['step_occurrences'] == 1
    assert result['summary']['evaluated_cases'] == 2
    assert [r['example_row'] for r in result['relations']] == [1, 2]
    assert result['relations'][0]['outline_variants'] == 2


def test_outline_nonnumeric_does_not_match_d(tmp_path):
    chunks = [
        {
            'id': 'f',
            'path': 'features/codes.feature',
            'language': 'gherkin',
            'strategy': 'gherkin_ast',
            'symbol': 'scenario_outline: codes',
            'start_line': 1,
            'content': (
                'Scenario Outline: codes\n Given code "<status_code>"\n Examples: '
                'status\n | status_code |\n | bad |'
            ),
        },
        {
            'id': 'd',
            'path': 'features/steps/status.py',
            'language': 'python',
            'strategy': 'python_ast',
            'symbol': 'status',
            'start_line': 1,
            'content': '@given(\'code "{code:d}"\')\ndef status(context, code):\n pass',
        },
    ]
    (tmp_path / 'indexes').mkdir(exist_ok=True)
    (tmp_path / 'indexes/example.chunks.json').write_text(
        json.dumps({'chunks': chunks, 'behave_relations': build_behave_relations(chunks)})
    )
    result = build_repository_links(
        {'repositories': {'example': {}}}, tmp_path / 'cfg.json', 'example'
    )
    assert result['summary']['unresolved'] == 1
