#!/bin/bash
# Hook: PreToolUse(Agent|Task) / UserPromptSubmit / SessionStart
# While the shared dev server is overloaded (memory pressure / OOM floor / load,
# with hysteresis): refuses new sub-agents, holds new prompts until the host
# recovers (at most 9 min, then lets them run; never refuses a prompt), and
# gives SessionStart a wait instruction. Thresholds: scripts/host_load_guard.py.
# Usage: host-load-gate.sh pre-agent|prompt|session-start
# -I -S: stdlib only, no site/user packages, keeps the hook well under 50 ms.
exec python3 -I -S "$(dirname "$0")/../../scripts/host_load_guard.py" hook --event "$1"
