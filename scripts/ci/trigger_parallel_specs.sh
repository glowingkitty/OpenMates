#!/usr/bin/env bash
# scripts/ci/trigger_parallel_specs.sh
#
# Triggers one GitHub Actions workflow run per Playwright spec file.
# GitHub queues runs beyond its concurrent job limit (20 for free tier).
#
# Usage:
#   ./scripts/ci/trigger_parallel_specs.sh                    # All specs, mocks enabled
#   ./scripts/ci/trigger_parallel_specs.sh --record            # Record fixtures (real LLMs)
#   ./scripts/ci/trigger_parallel_specs.sh --no-mocks          # Real LLMs, no recording
#   ./scripts/ci/trigger_parallel_specs.sh --spec chat-flow.spec.ts  # Single spec
#
# Each spec is assigned an account (1-10) in round-robin to avoid session collisions.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="playwright-spec.yml"
BRANCH="dev"
MAX_ACCOUNTS=10
USE_MOCKS="true"
RECORD_FIXTURES="false"
SINGLE_SPEC=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --record)       RECORD_FIXTURES="true"; USE_MOCKS="false"; shift ;;
    --no-mocks)     USE_MOCKS="false"; shift ;;
    --spec)         SINGLE_SPEC="$2"; shift 2 ;;
    *)              echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Discover specs
SPEC_DIR="$PROJECT_ROOT/frontend/apps/web_app/tests"
if [[ -n "$SINGLE_SPEC" ]]; then
  SPECS=("$SINGLE_SPEC")
else
  SPECS=()
  while IFS= read -r f; do
    SPECS+=("$(basename "$f")")
  done < <(find "$SPEC_DIR" -name '*.spec.ts' -type f | sort)
fi

echo "Triggering ${#SPECS[@]} spec(s) via $WORKFLOW"
echo "  Mocks: $USE_MOCKS | Record: $RECORD_FIXTURES"
echo ""

ACCOUNT=1
TRIGGERED=0
for spec in "${SPECS[@]}"; do
  echo "  [$ACCOUNT] $spec"
  gh workflow run "$WORKFLOW" \
    --ref "$BRANCH" \
    -f "spec=$spec" \
    -f "account=$ACCOUNT" \
    -f "use_mocks=$USE_MOCKS" \
    -f "record_fixtures=$RECORD_FIXTURES" &

  ACCOUNT=$(( (ACCOUNT % MAX_ACCOUNTS) + 1 ))
  TRIGGERED=$((TRIGGERED + 1))

  # Small delay to avoid GitHub API rate limiting
  if (( TRIGGERED % 10 == 0 )); then
    sleep 2
  fi
done

wait  # Wait for all gh workflow run commands to finish dispatching
echo ""
echo "Dispatched $TRIGGERED workflow runs. GitHub will queue beyond 20 concurrent."
echo "Monitor: gh run list --workflow=$WORKFLOW --limit 20"
