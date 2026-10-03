#!/usr/bin/env bash
# One-time server preparation. Idempotent: safe to re-run, never overwrites
# the existing .env (rotating secrets would log everyone out and orphan the
# storage key).
#
#   TELEGRAM_BOT_TOKEN=... AUTHORIZED_TELEGRAM_USER_IDS=... \
#   SYNTHCUT_DOMAIN=synthcut.example.com bash bootstrap.sh
set -euo pipefail

ROOT=/opt/synthcut
DATA=/srv/synthcut
ENV_FILE=$ROOT/shared/.env

mkdir -p "$ROOT/releases" "$ROOT/shared" \
         "$DATA/postgres" "$DATA/storage/meta" "$DATA/storage/data" \
         "$DATA/scratch" "$DATA/models" "$DATA/disk-probe" "$DATA/backups" \
         /var/www/synthcut-acme
# Containers run as uid 10001 (python image); scratch and models must be writable by it.
chown 10001:10001 "$DATA/scratch" "$DATA/models"
chmod 700 "$ROOT/shared" "$DATA/backups"

if [ -f "$ENV_FILE" ]; then
  echo ".env already exists — left untouched"
  exit 0
fi

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is required}"
: "${AUTHORIZED_TELEGRAM_USER_IDS:?AUTHORIZED_TELEGRAM_USER_IDS is required}"
: "${SYNTHCUT_DOMAIN:?SYNTHCUT_DOMAIN is required}"

hex() { openssl rand -hex "$1"; }
PG_PASS=$(hex 24)
REDIS_PASS=$(hex 24)
KEY_ID="GK$(hex 12)"
umask 077
cat > "$ENV_FILE" <<EOF
# SynthCut production environment — created $(date -u +%FT%TZ) by bootstrap.sh
ENV=prod
LOG_LEVEL=INFO
SYNTHCUT_DOMAIN=$SYNTHCUT_DOMAIN
PUBLIC_BASE_URL=https://$SYNTHCUT_DOMAIN

POSTGRES_PASSWORD=$PG_PASS
DATABASE_URL=postgresql+psycopg://synthcut:$PG_PASS@postgres:5432/synthcut
REDIS_PASSWORD=$REDIS_PASS
REDIS_URL=redis://:$REDIS_PASS@redis:6379/0

GARAGE_CONFIG=$ROOT/shared/garage.toml
GARAGE_RPC_SECRET=$(hex 32)
GARAGE_ADMIN_TOKEN=$(hex 32)
S3_ENDPOINT_INTERNAL=http://storage:3900
S3_ENDPOINT_PUBLIC=https://$SYNTHCUT_DOMAIN
S3_REGION=us-east-1
S3_BUCKET=synthcut-media
S3_ACCESS_KEY_ID=$KEY_ID
S3_SECRET_ACCESS_KEY=$(hex 32)
# Hard ceiling enforced by Garage itself, above the app-level quota.
STORAGE_HARD_LIMIT=30GiB

TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET=$(hex 24)
TELEGRAM_BOT_USERNAME=${TELEGRAM_BOT_USERNAME:-synthcut_bot}
AUTHORIZED_TELEGRAM_USER_IDS=$AUTHORIZED_TELEGRAM_USER_IDS
SESSION_SECRET=$(hex 32)

# The disk is shared with other live services (ADR-0001).
MAX_UPLOAD_BYTES=53687091200
STORAGE_QUOTA_BYTES=26843545600
DISK_RESERVE_BYTES=8589934592
EOF
chmod 600 "$ENV_FILE"
echo "created $ENV_FILE"
