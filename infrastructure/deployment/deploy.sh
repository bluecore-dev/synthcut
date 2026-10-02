#!/usr/bin/env bash
# Ship the committed HEAD to the server and activate it.
#   bash infrastructure/deployment/deploy.sh
# Refuses to run with uncommitted changes: the release name carries the commit.
#
# Activation runs detached on the server (a dropped SSH connection cannot kill
# it half-way); this script only follows its log. To re-attach:
#   ssh root@185.2.101.47 bash /opt/synthcut/releases/<release>/infrastructure/deployment/follow.sh <release>
set -euo pipefail

HOST=${SYNTHCUT_HOST:-root@185.2.101.47}
SSH=(ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=6 "$HOST")
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
"${SSH[@]}" "set -e
  mkdir -p /opt/synthcut/releases/$REL
  tar -xzf /opt/synthcut/releases/synthcut-$REL.tar.gz -C /opt/synthcut/releases/$REL
  rm -f /opt/synthcut/releases/synthcut-$REL.tar.gz
  echo $(git rev-parse HEAD) > /opt/synthcut/releases/$REL/COMMIT
  cd /opt/synthcut/releases/$REL
  nohup setsid bash -c 'bash infrastructure/deployment/activate.sh $REL > activate.log 2>&1; echo \$? > activate.exit' </dev/null >/dev/null 2>&1 &"
"${SSH[@]}" "bash /opt/synthcut/releases/$REL/infrastructure/deployment/follow.sh $REL"
