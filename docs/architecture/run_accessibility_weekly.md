---
status: active
last_verified: 2026-06-04
key_files:
- scripts/run_accessibility_weekly.py
- scripts/accessibility_audit.py
claims:
- id: arch-run-accessibility-weekly-behavior
  type: unit
  claim: Weekly Accessibility Audit Runner is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - scripts/run_accessibility_weekly.py
  - scripts/accessibility_audit.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-run-accessibility-weekly-behavior
  verified: '2026-06-11'
- id: arch-run-accessibility-weekly-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-run-accessibility-weekly-source-1
  anchors:
  - type: file_exists
    path: scripts/accessibility_audit.py
- id: arch-run-accessibility-weekly-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-run-accessibility-weekly-source-2
  anchors:
  - type: file_exists
    path: scripts/run_accessibility_weekly.py
- id: arch-run-accessibility-weekly-manual-3
  type: manual
  reason: 'Tiny architecture note: source-file existence claims cover the implemented anchor surface; deeper behavior remains
    covered by linked canonical docs.'
---

# Weekly Accessibility Audit Runner

`scripts/run_accessibility_weekly.py` wraps the deterministic accessibility audit for cron-style operations. It writes `latest.*` and dated `weekly-YYYY-MM-DD.*` reports under `test-results/accessibility/`, then sends an admin email summary.

Email delivery uses Brevo directly when `BREVO_API_KEY` is available. If direct Brevo credentials are not present, the runner uses the existing internal API bridge with `INTERNAL_API_SHARED_TOKEN` and `/internal/dispatch-test-summary-email`.

Use `--dry-run` before enabling cron. Suggested weekly schedule: Monday 06:00 UTC from the dev server or admin sidecar.
