PYTHON ?= .venv/bin/python
CONFIG ?= config.json
FORMAT_PATHS ?= .
LINT_PATHS ?= .
PROVIDER_ARGS ?=
EVALUATION_ARGS ?=
EVALUATION_PROFILE ?= lexical
EVALUATION_DATASET ?= evaluations/real_questions.json
EVALUATION_OUTPUT ?= indexes/real-evaluation.json
CHAT_ARGS ?=
SKILL_ARGS ?=
JSON_PATHS ?=
# Example: make indexes REPOS="aicc-tests toolium-examples"
REPO_ARGS = $(foreach repo,$(REPOS),--repo "$(repo)")

.PHONY: chat setup indexes indexes-incremental indexes-plan format format-check lint lint-python lint-json hooks-install hooks-run check-provider doctor evaluate-real skills-install skills-update skills-status

setup:
	uv sync --group dev

indexes:
	$(PYTHON) scripts/build_indexes.py --config "$(CONFIG)" $(REPO_ARGS)

indexes-incremental:
	$(PYTHON) scripts/build_indexes.py --config "$(CONFIG)" $(REPO_ARGS) --incremental

indexes-plan:
	$(PYTHON) scripts/build_indexes.py --config "$(CONFIG)" $(REPO_ARGS) --dry-run

# Override FORMAT_PATHS to format only the files being edited.
format:
	$(PYTHON) -m ruff format $(FORMAT_PATHS)

format-check:
	$(PYTHON) -m ruff format --check $(FORMAT_PATHS)

lint: lint-python lint-json

lint-python:
	$(PYTHON) -m ruff check $(LINT_PATHS)

lint-json:
	$(PYTHON) scripts/lint_json.py $(JSON_PATHS)

hooks-install:
	$(PYTHON) -m pre_commit install --install-hooks

hooks-run:
	$(PYTHON) -m pre_commit run --all-files

check-provider:
	$(PYTHON) -m codetrace check-provider --config "$(CONFIG)" $(PROVIDER_ARGS)

doctor:
	$(PYTHON) -m codetrace doctor --config "$(CONFIG)" $(REPO_ARGS)

evaluate-real:
	$(PYTHON) -m codetrace evaluate-real --config "$(CONFIG)" --dataset "$(EVALUATION_DATASET)" --profile "$(EVALUATION_PROFILE)" --output "$(EVALUATION_OUTPUT)" $(EVALUATION_ARGS)

skills-install:
	$(PYTHON) scripts/manage_skills.py install $(SKILL_ARGS)

skills-update:
	$(PYTHON) scripts/manage_skills.py update $(SKILL_ARGS)

skills-status:
	$(PYTHON) scripts/manage_skills.py status $(SKILL_ARGS)

chat:
	$(PYTHON) -m codetrace chat --config "$(CONFIG)" $(CHAT_ARGS)
