---
status: active
last_verified: 2026-06-04
key_files:
  - scripts/run_accessibility_weekly.py
  - scripts/accessibility_audit.py
---

# Weekly Accessibility Audit Runner

`scripts/run_accessibility_weekly.py` wraps the deterministic accessibility audit for cron-style operations. It writes `latest.*` and dated `weekly-YYYY-MM-DD.*` reports under `test-results/accessibility/`, then sends an admin email summary.

Email delivery uses Brevo directly when `BREVO_API_KEY` is available. If direct Brevo credentials are not present, the runner uses the existing internal API bridge with `INTERNAL_API_SHARED_TOKEN` and `/internal/dispatch-test-summary-email`.

Use `--dry-run` before enabling cron. Suggested weekly schedule: Monday 06:00 UTC from the dev server or admin sidecar.
