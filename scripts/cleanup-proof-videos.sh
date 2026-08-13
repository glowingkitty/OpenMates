#!/bin/bash
# Retry pending proof-video Discord deliveries and expire disposable media
# after the manifest-owned 24-hour retry window. Retained text evidence stays.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${OPENMATES_PROOF_CLEANUP_LOCK:-/tmp/openmates-proof-video-cleanup.lock}"

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

if [ -f "$REPO_ROOT/.env" ]; then
    # Some existing values intentionally contain shell-style dollar text.
    # Match the other host cron wrappers by allowing unset expansion only
    # while loading the trusted local environment file.
    set +u
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env"
    set +a
    set -u
fi

# sessions.py publishes proof videos to the dev-smoke destination. spec_demo's
# generic sweeper intentionally uses its dedicated variable, so map it only for
# this proof-video maintenance process.
export DISCORD_WEBHOOK_SPEC_DEMOS="${DISCORD_WEBHOOK_SPEC_DEMOS:-${DISCORD_WEBHOOK_DEV_SMOKE:-}}"

find "$REPO_ROOT" -path '*/test-results/proof-videos' -type d -print0 2>/dev/null |
while IFS= read -r -d '' proof_root; do
    timeout 10m python3 "$REPO_ROOT/scripts/spec_demo.py" sweep-publications --root "$proof_root"
done
