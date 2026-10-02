#!/usr/bin/env bash
# Ship the committed HEAD to the server and activate it.
#   bash infrastructure/deployment/deploy.sh
# Refuses to run with uncommitted changes: the release name carries the commit.
set -euo pipefail

HOST=${SYNTHCUT_HOST:-root@185.2.101.47}
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is dirty — commit first" >&2
  exit 1
fi

REL="$(date -u +%Y%m%d-%H%M%S)-$(git rev-parse --short=8 HEAD)"
TARBALL="${TMPDIR:-/tmp}/synthcut-$REL.tar.gz"
git archive --format=tar.gz -o "$TARBALL" HEAD
echo "release $REL ($(du -h "$TARBALL" | cut -f1))"

scp -q "$TARBALL" "$HOST:/opt/synthcut/releases/synthcut-$REL.tar.gz"
rm -f "$TARBALL"
ssh "$HOST" "set -e
  mkdir -p /opt/synthcut/releases/$REL
  tar -xzf /opt/synthcut/releases/synthcut-$REL.tar.gz -C /opt/synthcut/releases/$REL
  rm -f /opt/synthcut/releases/synthcut-$REL.tar.gz
  echo $(git rev-parse HEAD) > /opt/synthcut/releases/$REL/COMMIT
  bash /opt/synthcut/releases/$REL/infrastructure/deployment/activate.sh $REL"
