#!/usr/bin/env bash
# Stream a release's activation log until activation ends; exit with its status.
# Safe to re-run after a dropped SSH connection — activation itself keeps going.
#   bash follow.sh <release-name>
set -u
DIR=/opt/synthcut/releases/${1:?usage: follow.sh <release-name>}
LOG=$DIR/activate.log
n=0
while :; do
  if [ -f "$LOG" ]; then
    m=$(wc -l < "$LOG")
    if [ "$m" -gt "$n" ]; then
      sed -n "$((n + 1)),${m}p" "$LOG"
      n=$m
    fi
  fi
  if [ -f "$DIR/activate.exit" ]; then
    m=$(wc -l < "$LOG")
    if [ "$m" -gt "$n" ]; then sed -n "$((n + 1)),${m}p" "$LOG"; fi
    exit "$(cat "$DIR/activate.exit")"
  fi
  sleep 2
done
