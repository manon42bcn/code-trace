import pytest

from coderag.embeddings import EmbeddingMetadata, validate_vectors


def test_embedding_metadata_is_versioned():
    metadata = EmbeddingMetadata('local-test', 3, 'config-1')
    assert metadata.contract_version == '1'
    assert metadata.text_version == 'v1'


def test_invalid_metadata_is_rejected():
    with pytest.raises(ValueError, match='invalid embedding metadata'):
        EmbeddingMetadata('', 3, 'config-1')
    with pytest.raises(ValueError, match='invalid embedding metadata'):
        EmbeddingMetadata('local-test', 0, 'config-1')


def test_vectors_must_match_metadata():
    metadata = EmbeddingMetadata('local-test', 3, 'config-1')
    validate_vectors([[1, 2, 3]], metadata)
    with pytest.raises(ValueError, match='embedding dimension'):
        validate_vectors([[1, 2]], metadata)
    with pytest.raises(ValueError, match='embedding values must be numeric'):
        validate_vectors([[1, 'bad', 3]], metadata)
