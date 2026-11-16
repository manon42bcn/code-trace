PYTHON ?= pyenv exec python
.DEFAULT_GOAL := test

.PHONY: test

test:
	sh scripts/test.sh

# Setup targets are available until the checkout is cleaned.
ifneq ($(wildcard scripts/configure_repository.py),)
INIT_STAMP := .template-setup/init
INIT_RELEASE_STAMP := .template-setup/init-release

.PHONY: init clean-template

$(INIT_STAMP):
	@echo "Run make init successfully in this checkout before cleaning." >&2
	@exit 1

clean-template: $(INIT_STAMP)
	@set -- .github/workflows/*.yml .github/workflows/*.yaml; for workflow do if test -f "$$workflow"; then exit 0; fi; done; false || { echo "Set up project CI before cleaning." >&2; exit 1; }
	@! git grep --no-index -q -E 'Validate policy tooling|test_policies|configure_repository|policies/' -- .github/workflows || { echo "Replace the template CI with project CI before cleaning." >&2; exit 1; }
	@if [ -f "$(INIT_RELEASE_STAMP)" ]; then \
		if git ls-files --error-unmatch -- .env >/dev/null 2>&1; then \
			echo ".env is tracked. Remove it from version control before cleaning." >&2; exit 1; fi; \
		rm -f -- .env; fi
	rm -f -- policies/main-merge-owner.json policies/protected-branches.json \
		policies/release-tag-creation.json policies/release-tag-protection.json \
		policies/sensitive-file-reviews.json scripts/configure_repository.py scripts/init_release.py tests/test_policies.py \
		.env.example STEP_GUIDE.md REQUIREMENTS.md README.md docs/repository-setup.md docs/release-automation.md \
		docs/live-validation.md docs/images/branching-model.svg examples/release-toolium.json
	@for directory in policies tests docs/images examples; do \
		if [ -d "$$directory" ]; then rmdir "$$directory" 2>/dev/null || :; fi; done
	@rm -f -- "$(INIT_STAMP)" "$(INIT_RELEASE_STAMP)"
	@if [ -d .template-setup ]; then rmdir .template-setup; fi
	rm -f -- Makefile

init:
	@set -eu; set -a; if [ -f .env ]; then . ./.env; fi; set +a; \
		if [ -n "$${GH_ADMIN_TOKEN:-}" ]; then export GH_TOKEN="$$GH_ADMIN_TOKEN"; fi; \
		$(PYTHON) scripts/init_release.py $(RELEASE_INIT_ARGS); \
		mkdir -p .template-setup; \
		touch "$(INIT_STAMP)"; \
		if [ "$${RELEASE_AUTOMATION_ENABLED:-false}" = true ]; then touch "$(INIT_RELEASE_STAMP)"; fi

endif
