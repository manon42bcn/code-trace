from coderag.structured_generation import parse_generation_json


def test_parse_string_citations_as_objects():
    result = parse_generation_json('{"answer":"ok","citations":["a"]}', provider='fake', model='m')
    assert result.citations == [{'chunk_id': 'a'}]


def test_parse_structured_generation_json():
    result = parse_generation_json(
        (
            '{"answer":"ok","claims":[{"text":"fact","certainty":"static_candid'
            'ate","citations":["a"]}],"citations":[{"chunk_id":"a","path":"a.py'
            '","start_line":1}],"limitations":[]}'
        ),
        provider='fake',
        model='m',
    )
    assert result.answer == 'ok'
    assert result.claims[0].citations == ['a']
    assert result.citations[0]['chunk_id'] == 'a'
