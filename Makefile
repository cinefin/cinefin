# Cinefin task runner. Same verbs as cinefin-playout's Makefile so both repos
# drive identically: setup / lint / format / test / build / check / release.
#
# Python & Poetry commands run from backend/, the SvelteKit SPA from frontend/
# (repo layout: see CLAUDE.md). CI installs the toolchains, then runs
# `make setup check` — byte-for-byte the same steps you run locally.
.DEFAULT_GOAL := help
.PHONY: help setup lint format build test check wheel release clean

BACKEND  := backend
FRONTEND := frontend

help: ## List targets
	@grep -hE '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend + frontend dependencies
	cd $(BACKEND) && poetry install
	cd $(FRONTEND) && npm ci

lint: ## Ruff lint + format check, and the strict svelte-check gate
	cd $(BACKEND) && poetry run ruff check cinefin/ manage.py ../contrib
	cd $(BACKEND) && poetry run ruff format --check cinefin/ ../contrib
	cd $(FRONTEND) && npm run check

format: ## Auto-format Python (ruff) and the SPA (prettier)
	cd $(BACKEND) && poetry run ruff format cinefin/ ../contrib
	cd $(FRONTEND) && npm run format

build: ## Build the SvelteKit SPA (served by Django at /app)
	cd $(FRONTEND) && npm run build

test: ## Run the backend test suite
	cd $(BACKEND) && poetry run pytest -q

check: build lint test ## Everything CI runs: SPA build + lint + tests

wheel: ## Build the pip/pipx wheel (SPA + collected static bundled in)
	packaging/pip/build-wheel.sh

release: ## Tag + push a release (private/Gitea side): make release VERSION=vX.Y.Z
	scripts/release.sh $(VERSION)

clean: ## Remove build artifacts
	rm -rf $(FRONTEND)/build $(BACKEND)/dist $(BACKEND)/cinefin/spa
