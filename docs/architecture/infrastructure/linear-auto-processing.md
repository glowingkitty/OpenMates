---
status: active
last_verified: 2026-09-07
key_files:
- scripts/linear-cron-setup.sh
- scripts/session-cleanup.py
- scripts/_linear_client.py
- scripts/_zellij_utils.py
- scripts/linear-cron-setup.sh
claims:
- id: arch-infrastructure-linear-auto-processing-behavior
  type: unit
  claim: Linear Auto-Processing Pipeline is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - scripts/linear-cron-setup.sh
  - scripts/session-cleanup.py
  - scripts/_linear_client.py
  - scripts/_zellij_utils.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-infrastructure-linear-auto-processing-behavior
  verified: '2026-06-11'
- id: arch-infrastructure-linear-auto-processing-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-1
  anchors:
  - type: file_exists
    path: scripts/_linear_client.py
- id: arch-infrastructure-linear-auto-processing-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-2
  anchors:
  - type: file_exists
    path: scripts/_zellij_utils.py
- id: arch-infrastructure-linear-auto-processing-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-3
  anchors:
  - type: file_exists
    path: scripts/linear-cron-setup.sh
---

# Retired Linear automatic processing

The Linear-label-to-OpenCode poller and host trigger watcher were removed on September 7, 2026 (TASK-7543). Labels no longer schedule or launch OpenCode chats. Do not reinstall their services.

`scripts/linear-cron-setup.sh` retains only the Linear archive, artifact cleanup and legacy session cleanup services. `_linear_client.py`, `_zellij_utils.py`, existing issue history and `scripts/.tmp/poller-sessions.json` are retained for manual tooling and compatibility. No historical task/worktree records are deleted by this removal.

TASK-8338 owns a future review of useful event-triggered investigations as OpenMates workflows, due September 14. No replacement scheduler is introduced here. The new `openmates-ci-coordinator` is independent and remains intact.
