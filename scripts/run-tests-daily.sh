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
# This explicitly authorized health layer uses the deployed dev email service.
# Dispatch only: credentials and probing stay inside the ephemeral GitHub runner.
# A dispatch failure must remain visible without suppressing isolated daily CI.
mkdir -p "$CI_CANONICAL/logs/nightly-reports"
if timeout 30 gh -R glowingkitty/OpenMates workflow run signup-email-live-smoke.yml --ref dev; then
  printf '%s\n' '{"dispatch":"acknowledged","verification":"pending"}' > "$CI_CANONICAL/logs/nightly-reports/signup-email-live-dispatch.json"
else
  printf '%s\n' '{"dispatch":"failed","verification":"not_run"}' > "$CI_CANONICAL/logs/nightly-reports/signup-email-live-dispatch.json"
  echo 'Live signup-email health dispatch failed; see GitHub access/workflow availability. Continuing isolated daily tests.' >&2
fi
exec python3 "$CI_CANONICAL/scripts/ci_dispatch.py" --worktree "$CI_WORKTREE" --daily "$@"
