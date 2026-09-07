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
exec python3 "$CI_CANONICAL/scripts/ci_dispatch.py" --worktree "$CI_WORKTREE" --daily "$@"
