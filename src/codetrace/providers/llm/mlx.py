"""Local generation from an installed MLX LM model directory."""

from __future__ import annotations

from pathlib import Path

from ...generation import GenerationResult
from ...generation_config import GenerationSetupError
from ...latency import timed
from ...structured_generation import parse_generation_json


class MLXProvider:
    """Run MLX LM in-process and reuse the loaded model for subsequent requests."""

    provider = 'mlx'

    def __init__(self, *, model: str, max_tokens: int):
        """Validate the model directory and defer loading weights until generation."""
        self.model = model
        self.max_tokens = max_tokens
        model_path = Path(model).expanduser()
        if not model_path.is_dir() or not (model_path / 'config.json').is_file():
            raise GenerationSetupError(
                'Set CODETRACE_GENERATION_MODEL to a local MLX LM model directory '
                'containing config.json'
            )
        # Pass an existing absolute path so MLX LM does not resolve a Hub model ID.
        self._model_path = model_path.resolve()
        self._loaded = None
        self.last_timings = {}

    def generate(self, prompt: str, *, metadata=None) -> GenerationResult:  # noqa: ARG002 - Provider interface
        """Apply the chat template and decode the completion as structured JSON."""
        self.last_timings = {}
        # Keep the optional runtime out of CodeTrace's import path for other providers.
        try:
            from mlx_lm import generate, load
        except (ImportError, OSError, RuntimeError) as exc:
            raise GenerationSetupError(
                'MLX generation requires Apple silicon and MLX LM. Install with uv sync --extra mlx'
            ) from exc

        if self._loaded is None:
            try:
                with timed(self.last_timings, 'mlx_model_load_seconds'):
                    self._loaded = load(self._model_path)
            except (OSError, ValueError, RuntimeError) as exc:
                raise GenerationSetupError('Cannot load the local MLX LM model') from exc

        model, tokenizer = self._loaded
        try:
            if tokenizer.chat_template:
                prompt = tokenizer.apply_chat_template(
                    [{'role': 'user', 'content': prompt}], add_generation_prompt=True
                )
            with timed(self.last_timings, 'mlx_inference_seconds'):
                text = generate(
                    model, tokenizer, prompt=prompt, max_tokens=self.max_tokens, verbose=False
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError('MLX could not generate a completion with the local model') from exc
        try:
            return parse_generation_json(text, provider=self.provider, model=self.model)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError('MLX returned invalid structured generation JSON') from exc
