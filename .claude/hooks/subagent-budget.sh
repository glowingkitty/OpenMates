#!/usr/bin/env bash
# subagent-budget: thin wrapper; logic and tests live in scripts/subagent_budget.py (fails open).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/scripts/subagent_budget.py"
