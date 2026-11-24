"""Use a downloaded Jina Code Embeddings MLX package on the local machine."""

from pathlib import Path
from runpy import run_path

from ...embeddings import EmbeddingMetadata, validate_vectors

DIMENSIONS = 256
MAX_LENGTH = 1024
BATCH_SIZE = 8
REQUIRED_FILES = ('config.json', 'model.py', 'model.safetensors', 'tokenizer.json')


class MLXJinaProvider:
    def __init__(self, model_id):
        self.path = Path(model_id.removeprefix('mlx:'))
        self.metadata = EmbeddingMetadata(model_id, DIMENSIONS, f'jina-mlx-nl2code-{MAX_LENGTH}-v1')
        self._loaded = None

    def _encode(self, texts, prompt_type):
        if not texts:
            return []
        if self._loaded is None:
            import json

            try:
                import mlx.core as mx
                from tokenizers import Tokenizer
            except ImportError as exc:
                raise ValueError(
                    'Jina embeddings require access to Metal, MLX and the tokenizers package'
                ) from exc

            if any(not (self.path / name).is_file() for name in REQUIRED_FILES):
                raise ValueError('Set CODETRACE_EMBEDDING_MODEL to a downloaded Jina MLX directory')
            config = json.loads((self.path / 'config.json').read_text(encoding='utf-8'))
            model_class = run_path(str(self.path / 'model.py')).get('JinaCodeEmbeddingModel')
            if model_class is None:
                raise ValueError('This MLX embedding adapter requires a Jina Code Embeddings model')
            model = model_class(config)
            model.load_weights(list(mx.load(str(self.path / 'model.safetensors')).items()))
            mx.eval(model.parameters())
            self._loaded = model, Tokenizer.from_file(str(self.path / 'tokenizer.json'))
        model, tokenizer = self._loaded
        # The upstream encoder pads every batch to its longest input.
        order = sorted(range(len(texts)), key=lambda position: len(texts[position]))
        vectors = [[] for _ in texts]
        for start in range(0, len(texts), BATCH_SIZE):
            positions = order[start : start + BATCH_SIZE]
            result = model.encode(
                [texts[position] for position in positions],
                tokenizer,
                task='nl2code',
                prompt_type=prompt_type,
                truncate_dim=self.metadata.dimensions,
                max_length=MAX_LENGTH,
            )
            for position, vector in zip(positions, result.tolist(), strict=True):
                vectors[position] = vector
        validate_vectors(vectors, self.metadata)
        return vectors

    def embed_documents(self, texts):
        return self._encode(texts, 'passage')

    def embed_query(self, text):
        try:
            return self._encode([text], 'query')[0]
        finally:
            if self._loaded is not None:
                import mlx.core as mx

                # Release embedding weights before the chat generates its answer.
                self._loaded = None
                mx.clear_cache()
