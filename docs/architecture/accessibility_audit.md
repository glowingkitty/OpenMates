---
status: active
last_verified: 2026-06-04
key_files:
- scripts/accessibility_audit.py
- test-results/accessibility/
claims:
- id: arch-accessibility-audit-behavior
  type: unit
  claim: Accessibility Audit is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - scripts/accessibility_audit.py
  - test-results/accessibility/
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-accessibility-audit-behavior
  verified: '2026-06-11'
- id: arch-accessibility-audit-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-accessibility-audit-source-1
  anchors:
  - type: file_exists
    path: scripts/accessibility_audit.py
- id: arch-accessibility-audit-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-accessibility-audit-source-2
  anchors:
  - type: file_exists
    path: test-results/accessibility/
- id: arch-accessibility-audit-manual-3
  type: manual
  reason: 'Tiny architecture note: source-file existence claims cover the implemented anchor surface; deeper behavior remains
    covered by linked canonical docs.'
---

# Accessibility Audit

`scripts/accessibility_audit.py` runs deterministic static accessibility checks for the web and Apple apps. It is Linux-safe and does not require Playwright, Xcode, package installs, or a running app server.

The script writes JSON and Markdown reports under `test-results/accessibility/`. It is intended as a repeatable baseline for trend tracking and regression detection, not as a replacement for browser axe scans, keyboard E2E tests, simulator checks, VoiceOver checks, or manual assistive-technology testing.

Use `--fail-on <severity>` only after a baseline is accepted. Initially, weekly runs should report all findings while gating only new critical/high regressions in a separate comparison step.
