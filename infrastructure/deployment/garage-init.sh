#!/usr/bin/env bash
# Idempotent Garage setup: node layout, bucket, application key, hard quota.
#   garage-init.sh <docker compose global args...>
# Reads S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, STORAGE_HARD_LIMIT
# from the environment.
set -euo pipefail

G=(docker compose "$@" exec -T storage /garage)

for _ in $(seq 1 30); do
  if "${G[@]}" status >/dev/null 2>&1; then break; fi
  sleep 2
done

status=$("${G[@]}" status 2>/dev/null || true)
if grep -q "NO ROLE ASSIGNED" <<<"$status"; then
  node=$("${G[@]}" node id -q 2>/dev/null | cut -d@ -f1)
  "${G[@]}" layout assign -z dc1 -c "${GARAGE_CAPACITY:-40G}" "$node" >/dev/null
  layout=$("${G[@]}" layout show 2>/dev/null || true)
  current=$(sed -n 's/.*[Cc]urrent cluster layout version: *\([0-9][0-9]*\).*/\1/p' <<<"$layout" | head -n1)
  "${G[@]}" layout apply --version $(( ${current:-0} + 1 )) >/dev/null
  echo "garage: layout applied (version $(( ${current:-0} + 1 )))"
fi

"${G[@]}" bucket info "$S3_BUCKET" >/dev/null 2>&1 || "${G[@]}" bucket create "$S3_BUCKET" >/dev/null
"${G[@]}" key info "$S3_ACCESS_KEY_ID" >/dev/null 2>&1 \
  || "${G[@]}" key import --yes -n synthcut-app "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY" >/dev/null
"${G[@]}" bucket allow --read --write --owner "$S3_BUCKET" --key "$S3_ACCESS_KEY_ID" >/dev/null
if [ -n "${STORAGE_HARD_LIMIT:-}" ]; then
  "${G[@]}" bucket set-quotas "$S3_BUCKET" --max-size "$STORAGE_HARD_LIMIT" >/dev/null
fi
echo "garage: bucket '$S3_BUCKET' ready"
