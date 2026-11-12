#!/bin/bash
# Hook: Stop
# Blocks ending the turn while this chat's CI jobs run with no `ci_coordinator.py wait`
# process (nothing would wake the chat). Logic and fail-open rules: scripts/pending_work_gate.py.
exec timeout 3 python3 "$(dirname "$0")/../../scripts/pending_work_gate.py" || exit 0
