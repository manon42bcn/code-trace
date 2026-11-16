import pytest

from coderag.generation import GenerationResult, validate_generation_result


def test_citation_evidence_type_is_normalized():
    result = GenerationResult(
        'answer', 'fake', 'model', citations=[{'chunk_id': 'a', 'evidence_type': 'invalid'}]
    )
    with pytest.raises(ValueError, match='evidence_type'):
        validate_generation_result(result, {'items': [{'chunk': {'id': 'a'}}]})


def test_citation_subrange_is_allowed():
    result = GenerationResult(
        'answer',
        'fake',
        'model',
        citations=[{'chunk_id': 'a', 'path': 'a.py', 'start_line': 3, 'end_line': 5}],
    )
    validate_generation_result(
        result,
        {
            'items': [
                {
                    'chunk': {'id': 'a'},
                    'citation': {'chunk_id': 'a', 'path': 'a.py', 'start_line': 1, 'end_line': 10},
                }
            ]
        },
    )


def test_citation_location_must_match_context():
    result = GenerationResult(
        'answer', 'fake', 'model', citations=[{'chunk_id': 'a', 'path': 'wrong.py'}]
    )
    with pytest.raises(ValueError, match='does not match'):
        validate_generation_result(
            result,
            {'items': [{'chunk': {'id': 'a'}, 'citation': {'chunk_id': 'a', 'path': 'a.py'}}]},
        )
