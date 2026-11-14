import json

import pytest

from coderag.rag_dataset import load_rag_dataset


def test_load_rag_dataset(tmp_path):
    path = tmp_path / 'dataset.json'
    path.write_text(json.dumps([{'query': 'What?', 'relevant_citations': ['a']}]))
    assert load_rag_dataset(path)[0]['query'] == 'What?'


def test_invalid_rag_dataset_is_rejected(tmp_path):
    path = tmp_path / 'dataset.json'
    path.write_text(json.dumps({'query': 'What?'}))
    with pytest.raises(ValueError, match='RAG dataset must be a list'):
        load_rag_dataset(path)
