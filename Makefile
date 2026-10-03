# Local development. Production: infrastructure/deployment/deploy.sh
TEST_DB ?= postgresql+psycopg://$(USER)@localhost:5432/synthcut_test

.PHONY: sync lint fmt test test-unit test-integration openapi motion-types motion-bundle web-build web-dev deploy

sync:            ## install the Python workspace
	uv sync --all-packages

lint:
	uv run ruff check . && uv run ruff format --check .
	cd apps/mini-app && npx tsc --noEmit
	cd apps/remotion && npx tsc --noEmit

fmt:
	uv run ruff format . && uv run ruff check . --fix

test-unit:
	uv run pytest tests/unit -q
	cd apps/mini-app && npx vitest run
	cd apps/remotion && npx vitest run

test-integration:  ## needs local PostgreSQL + Redis; S3 is an in-process moto server
	SYNTHCUT_TEST_DATABASE_URL=$(TEST_DB) uv run pytest tests -q

test: test-integration

openapi:         ## regenerate docs/openapi.json and the Mini App's TS types
	uv run python -m synthcut_api.openapi > docs/openapi.json
	cd apps/mini-app && npx openapi-typescript ../../docs/openapi.json -o src/api/schema.gen.ts

motion-types:    ## regenerate the Remotion prop types from the Python registry
	uv run python -m synthcut_timeline.schema > apps/remotion/src/generated/schema.json
	cd apps/remotion && npm run gen:types

motion-bundle:   ## bundle the Remotion app and fetch headless Chrome (local renders / tests)
	cd apps/remotion && npm ci && npm run bundle && npx remotion browser ensure

web-build:
	cd apps/mini-app && npm run build

web-dev:
	cd apps/mini-app && npm run dev

deploy:
	bash infrastructure/deployment/deploy.sh
