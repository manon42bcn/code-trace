import json

from coderag.rag_report import save_rag_report


def test_rag_report_is_versioned_and_reproducible(tmp_path):
    path = tmp_path / 'rag.json'
    save_rag_report(
        path,
        query='What?',
        retrieval_config={'limit': 10},
        generation_config={'provider': 'none'},
        context_metrics={'coverage': 1},
        answer_metrics={'citation_recall': 1},
    )
    data = json.loads(path.read_text())
    assert data['schema_version'] == 1
    assert data['generation_config']['provider'] == 'none'
