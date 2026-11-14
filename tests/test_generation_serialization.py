import json

from coderag.generation import Claim, GenerationResult
from coderag.generation_serialization import generation_result_dict


def test_generation_result_serializes_as_json_data():
    result = GenerationResult(
        'answer',
        'fake',
        'model',
        claims=[Claim('fact', 'static_candidate', ['a'])],
        citations=[{'chunk_id': 'a'}],
    )
    data = generation_result_dict(result)
    assert data['claims'][0]['citations'] == ['a']
    assert json.loads(json.dumps(data))['answer'] == 'answer'
