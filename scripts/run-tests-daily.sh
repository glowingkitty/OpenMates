#!/usr/bin/env bash
# Canonical CI forwarding for the retired test launcher.
# Local focused units remain local; daily units and application E2E use GitHub.
# Resolve the shared dispatcher before any account or shared-dev preflight.
# See docs/architecture/isolated-github-tests.md.
set -euo pipefail
CI_WORKTREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CI_COMMON="$(git -C "$CI_WORKTREE" rev-parse --path-format=absolute --git-common-dir)"
CI_CANONICAL="$(dirname "$CI_COMMON")"
if [[ ! -f "$CI_CANONICAL/scripts/ci_dispatch.py" ]]; then
  echo 'Canonical isolated CI dispatcher unavailable; shared-dev fallback is forbidden.' >&2
  exit 2
fi
# Real Brevo health is dev-host CLI only; ordinary product CI stays isolated.
# Failure is reported locally and must not suppress the normal daily CI dispatch.
if ! timeout 240 python3 "$CI_CANONICAL/scripts/signup_email_live_smoke.py" --dev-host \
  --run-id "$(date -u +%F)" \
  --receipt "$CI_CANONICAL/logs/nightly-reports/signup-email-receipts/$(date -u +%F)" \
  --report "$CI_CANONICAL/logs/nightly-reports/signup-email-live-smoke.json"; then
  echo 'Dev-host signup email health failed; inspect the redacted local report. Continuing isolated daily tests.' >&2
fi
set +e
python3 "$CI_CANONICAL/scripts/ci_dispatch.py" --worktree "$CI_WORKTREE" --daily "$@"
dispatch_status=$?
set -e
if [[ "$dispatch_status" -ne 0 ]]; then
  # A selection/preflight abort is a real nightly failure even when no CI job
  # or legacy last-run.json exists. The notifier deduplicates channel sends.
  python3 "$CI_CANONICAL/scripts/daily_ci_notification.py" --send || true
fi
exit "$dispatch_status"
