import json

from coderag.retrieval_report import save_retrieval_report


def test_retrieval_report_is_reproducible(tmp_path):
    path = tmp_path / 'report.json'
    payload = save_retrieval_report(
        path,
        metadata={'model_id': 'test'},
        evaluation={'metrics': {'mrr': 1.0}},
        queries=[{'term': 'order', 'relevant_chunk_ids': ['a']}],
    )
    assert payload['schema_version'] == 1
    assert json.loads(path.read_text())['metadata']['model_id'] == 'test'
