#!/usr/bin/env bash
# Run the whole test suite on the server against real PostgreSQL 16, Redis and
# Garage in an isolated, disposable compose project. Never touches production.
#   bash infrastructure/deployment/test-stack.sh [pytest args...]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
F="$HERE/docker-compose.test.yml"
C=(docker compose -p synthcut-test -f "$F")

cleanup() { "${C[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${C[@]}" build tests
"${C[@]}" up -d postgres redis storage
S3_BUCKET=synthcut-test \
S3_ACCESS_KEY_ID=GK000000000000000000000001 \
S3_SECRET_ACCESS_KEY=0000000000000000000000000000000000000000000000000000000000000002 \
  bash "$HERE/garage-init.sh" -p synthcut-test -f "$F"
"${C[@]}" run --rm tests pytest -q -p no:cacheprovider tests "$@"
