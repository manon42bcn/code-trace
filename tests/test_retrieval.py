import pytest

from coderag.retrieval import RetrievalConfig, retrieve


def test_configured_retrieval_defaults():
    results = retrieve({'chunks': []}, {'nodes': []}, 'query')
    assert results == []
    assert RetrievalConfig().semantic_profile == 'default'
    assert RetrievalConfig.from_mapping({'limit': 10}).limit == 10


def test_retrieval_config_validates_limits():
    with pytest.raises(ValueError, match='limit must be positive'):
        RetrievalConfig(limit=0)
