# Local development. Production: infrastructure/deployment/deploy.sh
TEST_DB ?= postgresql+psycopg://$(USER)@localhost:5432/synthcut_test

.PHONY: sync lint fmt test test-unit test-integration openapi web-build web-dev deploy

sync:            ## install the Python workspace
	uv sync --all-packages

lint:
	uv run ruff check . && uv run ruff format --check .
	cd apps/mini-app && npx tsc --noEmit

fmt:
	uv run ruff format . && uv run ruff check . --fix

test-unit:
	uv run pytest tests/unit -q
	cd apps/mini-app && npx vitest run

test-integration:  ## needs local PostgreSQL + Redis; S3 is an in-process moto server
	SYNTHCUT_TEST_DATABASE_URL=$(TEST_DB) uv run pytest tests -q

test: test-integration

openapi:         ## regenerate docs/openapi.json and the Mini App's TS types
	uv run python -m synthcut_api.openapi > docs/openapi.json
	cd apps/mini-app && npx openapi-typescript ../../docs/openapi.json -o src/api/schema.gen.ts

web-build:
	cd apps/mini-app && npm run build

web-dev:
	cd apps/mini-app && npm run dev

deploy:
	bash infrastructure/deployment/deploy.sh
