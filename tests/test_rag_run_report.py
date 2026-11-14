import json

from coderag.generation import GenerationResult
from coderag.rag_run_report import save_rag_run_report


def test_rag_run_report_serializes_result_without_secrets(tmp_path):
    path = tmp_path / 'run.json'
    result = {'answer': GenerationResult('answer', 'fake', 'model'), 'generated': True}
    save_rag_run_report(
        path,
        query='What?',
        result=result,
        context={'items': []},
        retrieval_config={'limit': 10},
        generation_config={'provider': 'anthropic', 'api_key': 'secret', 'token': 'secret'},
    )
    data = json.loads(path.read_text())
    assert data['answer']['answer'] == 'answer'
    assert 'api_key' not in data['generation_config']
    assert 'token' not in data['generation_config']
