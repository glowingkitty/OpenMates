#!/bin/bash
# Hook: PreToolUse(Agent|Task) / UserPromptSubmit / SessionStart
# Refuses new sub-agents and new prompts while the shared dev server is
# overloaded (MemAvailable / load / memory PSI, with hysteresis); SessionStart
# gets a wait instruction. Thresholds: scripts/host_load_guard.py.
# Usage: host-load-gate.sh pre-agent|prompt|session-start
# -I -S: stdlib only, no site/user packages, keeps the hook well under 50 ms.
exec python3 -I -S "$(dirname "$0")/../../scripts/host_load_guard.py" hook --event "$1"
