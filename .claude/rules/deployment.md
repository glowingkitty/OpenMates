---
paths:
  - "scripts/promote_production_webapp.py"
  - "scripts/bump_alpha_version_line.py"
  - "deployment/**"
---
# Deployment

- Dev: `sessions.py deploy` publishes the scoped diff to `dev` after checks.
  Standard type prefixes; preserve contract trailers. For frontend readiness use
  `sessions.py wait-deploy --commit <sha>`; a pushed commit is not a live frontend.
- Failed check: inspect the focused error, keep the receipt, never bypass a
  relevant safety check.
- Alpha versions: `scripts/bump_alpha_version_line.py`. Vercel failures:
  `backend/scripts/debug.py vercel --failed`; warnings on a Ready build are fine.
- Production web releases need a real browser startup check: keep automatic
  domain assignment disabled, build with `--skip-domain`, then after backend
  compatibility checks run `python3 scripts/promote_production_webapp.py
  --deployment <id> --expected-version <version> --out <private-evidence-dir>`.
  Never use raw alias/promote commands. Emergency restores repeat the check.
  Production is not done without a passing browser receipt.
