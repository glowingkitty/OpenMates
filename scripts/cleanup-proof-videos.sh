#!/bin/bash
# Expire old pending proof-video disposable media after the manifest-owned retry
# window. Proof media is embedded in agent responses, not sent to Discord.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# After cutover every scheduled/manual cleanup joins the elected host owner.
DISK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" configured-check --repository "$DISK_REPO_ROOT"; then
    DISK_CONFIGURATION_STATUS=0
else
    DISK_CONFIGURATION_STATUS=$?
fi
if [ "$DISK_CONFIGURATION_STATUS" -eq 0 ]; then
    if ! python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" owner-check; then
        exec python3 "$DISK_REPO_ROOT/scripts/disk_coordinator.py" maintenance --repository "$DISK_REPO_ROOT" --kind proof
    fi
elif [ "$DISK_CONFIGURATION_STATUS" -ne 3 ]; then
    echo "Disk coordinator state is uncertain; refusing independent cleanup." >&2
    exit 1
fi

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

find "$REPO_ROOT" -path '*/test-results/proof-videos' -type d -print0 2>/dev/null |
while IFS= read -r -d '' proof_root; do
    timeout 10m python3 "$REPO_ROOT/scripts/spec_demo.py" sweep-expired --root "$proof_root"
done
