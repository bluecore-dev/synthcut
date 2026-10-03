#!/usr/bin/env bash
# Activate one release on the server:
#   build images → nginx + TLS certificate → storage config/init → migrate →
#   start → health check.
# If the new release does not become healthy, the previous one is started again.
#
#   activate.sh <release-name>          (run by deploy.sh; the release is already unpacked)
set -euo pipefail

REL=${1:?usage: activate.sh <release-name>}
ROOT=/opt/synthcut
DIR=$ROOT/releases/$REL
ENV_FILE=$ROOT/shared/.env
SITE=/etc/nginx/sites-available/synthcut
KEEP_RELEASES=5

[ -d "$DIR" ] || { echo "no such release: $DIR" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE — run bootstrap.sh first" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
DOMAIN=${SYNTHCUT_DOMAIN:?SYNTHCUT_DOMAIN missing from .env}

compose() { # compose <release-dir> <release-name> <args...>
  local dir=$1 rel=$2
  shift 2
  SYNTHCUT_RELEASE=$rel docker compose --project-directory "$dir" -f "$dir/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

PREV_DIR=$(readlink -f "$ROOT/current" 2>/dev/null || true)
PREV=$( [ -n "$PREV_DIR" ] && basename "$PREV_DIR" || true )
log() { printf '\n== %s\n' "$*"; }

log "build $REL"
compose "$DIR" "$REL" build migrate web

log "nginx + certificate (before the bot registers its webhook)"
install_site() { # install_site <template>; restores the previous file if nginx -t fails
  local template=$1 backup=""
  if [ -f "$SITE" ]; then backup=$(mktemp); cp "$SITE" "$backup"; fi
  sed "s/__DOMAIN__/$DOMAIN/g" "$template" > "$SITE.tmp"
  if [ -f "$SITE" ] && cmp -s "$SITE.tmp" "$SITE"; then rm -f "$SITE.tmp" "$backup"; return 0; fi
  mv "$SITE.tmp" "$SITE"
  ln -sfn "$SITE" /etc/nginx/sites-enabled/synthcut
  if nginx -t 2>/tmp/synthcut-nginx-test.log; then
    systemctl reload nginx
    rm -f "$backup"
    echo "nginx: $(basename "$template") installed"
  else
    cat /tmp/synthcut-nginx-test.log >&2
    if [ -n "$backup" ]; then mv "$backup" "$SITE"; else rm -f "$SITE" /etc/nginx/sites-enabled/synthcut; fi
    echo "nginx config rejected — previous config restored, other sites untouched" >&2
    exit 1
  fi
}
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  install_site "$DIR/infrastructure/nginx/synthcut.acme.conf"
  certbot certonly --webroot -w /var/www/synthcut-acme -d "$DOMAIN" \
    --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
fi
install_site "$DIR/infrastructure/nginx/synthcut.conf"

log "storage config"
STORAGE_CONFIG_CHANGED=0
if ! cmp -s "$DIR/infrastructure/garage/garage.toml" "$ROOT/shared/garage.toml"; then
  install -m 644 "$DIR/infrastructure/garage/garage.toml" "$ROOT/shared/garage.toml"
  STORAGE_CONFIG_CHANGED=1
fi

log "infrastructure (postgres, redis, garage)"
compose "$DIR" "$REL" up -d postgres redis storage
if [ "$STORAGE_CONFIG_CHANGED" = 1 ] && [ -n "$PREV" ]; then
  compose "$DIR" "$REL" restart storage
fi
SYNTHCUT_RELEASE=$REL bash "$DIR/infrastructure/deployment/garage-init.sh" \
  --project-directory "$DIR" -f "$DIR/docker-compose.yml" --env-file "$ENV_FILE"

log "speech model"
# Jobs only read local weights; a failed download must not block a deploy, the
# transcription jobs then fail with a clear reason until the next activation.
install -d -o 10001 -g 10001 "${DATA_ROOT:-/srv/synthcut}/models"
compose "$DIR" "$REL" run --rm --no-deps -T worker-cpu python -m synthcut_worker.speech.fetch \
  || echo "WARNING: speech model not fetched — transcription will fail until it is" >&2

log "migrate + start"
if ! compose "$DIR" "$REL" up -d --remove-orphans; then
  echo "start failed" >&2
  if [ -n "$PREV" ]; then compose "$PREV_DIR" "$PREV" up -d --remove-orphans || true; fi
  exit 1
fi

log "health check"
healthy=0
for _ in $(seq 1 40); do
  if curl -fsS -m 5 http://127.0.0.1:3400/api/v1/ready >/dev/null 2>&1 \
     && curl -fsS -m 5 http://127.0.0.1:3403/telegram/health >/dev/null 2>&1 \
     && curl -fsS -m 5 -o /dev/null http://127.0.0.1:3401/; then
    healthy=1
    break
  fi
  sleep 3
done
if [ "$healthy" != 1 ]; then
  echo "release $REL is not healthy" >&2
  compose "$DIR" "$REL" ps >&2 || true
  compose "$DIR" "$REL" logs --tail 40 api bot >&2 || true
  if [ -n "$PREV" ]; then
    log "rolling back to $PREV"
    compose "$PREV_DIR" "$PREV" up -d --remove-orphans
  fi
  exit 1
fi
ln -sfn "$DIR" "$ROOT/current"
echo "release $REL is live"

log "prune old releases (keep $KEEP_RELEASES)"
mapfile -t releases < <(find "$ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
count=${#releases[@]}
for ((i = 0; i < count - KEEP_RELEASES; i++)); do
  old=${releases[$i]}
  if [ "$old" = "$REL" ] || [ "$old" = "$PREV" ]; then continue; fi
  rm -rf -- "${ROOT:?}/releases/${old:?}"
  docker image rm "synthcut/app:$old" "synthcut/web:$old" >/dev/null 2>&1 || true
  echo "pruned $old"
done
echo "done: $REL"
