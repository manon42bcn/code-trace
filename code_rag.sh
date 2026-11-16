# bin/sh

rm -rf code-rag && \
mv $(ls -d */ | grep code-rag) code-rag && \
cd code-rag && \
uv sync --extra parsers --group dev && \
uv run python -m coderag index --config config.json --repo toolium && \
uv run python -m coderag index --config config.json --repo toolium-telefonica && \
uv run python -m coderag index --config config.json --repo toolium-examples && \
uv run python -m coderag index --config config.json --repo aicc-tests && \
uv run python -m coderag link --config config.json --repo toolium && \
uv run python -m coderag link --config config.json --repo toolium-telefonica && \
uv run python -m coderag link --config config.json --repo toolium-examples && \
uv run python -m coderag link --config config.json --repo aicc-tests --behave-dry-run ~/Downloads/dry-run.json && \
uv run python -m coderag provenance \
  indexes/aicc-tests.relationships.json \
  --key dataset_id \
  --namespace toolium.storage \
  --max-depth 4 \
  --max-nodes 100 \
  --max-pairs 100 \
  --output reports/provenance-dataset-id.json
uv run python -m coderag provenance \
  indexes/aicc-tests.relationships.json \
  --key evaluation_id \
  --namespace toolium.storage \
  --max-depth 4 \
  --max-nodes 100 \
  --max-pairs 100 \
  --output reports/provenance-evaluation-id.json
uv run python -m coderag provenance \
  indexes/aicc-tests.relationships.json \
  --key microfrontend_id \
  --namespace toolium.storage \
  --max-depth 4 \
  --max-nodes 100 \
  --max-pairs 100 \
  --output reports/provenance-microfrontend-id.json

uv run pytest -q