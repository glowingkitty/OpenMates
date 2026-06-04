---
status: active
last_verified: 2026-06-04
key_files:
  - scripts/accessibility_audit.py
  - test-results/accessibility/
---

# Accessibility Audit

`scripts/accessibility_audit.py` runs deterministic static accessibility checks for the web and Apple apps. It is Linux-safe and does not require Playwright, Xcode, package installs, or a running app server.

The script writes JSON and Markdown reports under `test-results/accessibility/`. It is intended as a repeatable baseline for trend tracking and regression detection, not as a replacement for browser axe scans, keyboard E2E tests, simulator checks, VoiceOver checks, or manual assistive-technology testing.

Use `--fail-on <severity>` only after a baseline is accepted. Initially, weekly runs should report all findings while gating only new critical/high regressions in a separate comparison step.
