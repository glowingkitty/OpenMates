---
description: Scoped dev deployment and exact-commit readiness
globs:
---

Use `sessions.py deploy` for the isolated task diff. It infers the current binding
or accepts explicit `--session`, runs relevant checks and publishes to `dev`.
Keep messages concise and meaningful. Use standard type prefixes; preserve
contract trailers for contract-governed changes. Deploy-docs is an optional
reference command, not a prerequisite for each deployment.

Use `sessions.py wait-deploy --commit <sha>` when frontend readiness is needed.
Wait inside that process; do not run repeated model sleep/status loops. Tests
run in isolated GitHub CI using the exact candidate/harness, independently of
Vercel readiness. A manually requested dev-browser check needs the matching Ready
deployment. A pushed commit is not yet proof that the frontend is live.

If a check fails, inspect its focused error and retain the receipt. Reassess
after two failed attempts; ask before expanding into unrelated infrastructure
repair or uncertain behavior. Never bypass a failing relevant safety check.
Report outcome, commit and relevant verification without a mandatory template.

Alpha version changes use `scripts/bump_alpha_version_line.py`; do not invent
patch-version trains. For Vercel failure diagnosis use `backend/scripts/debug.py
vercel --failed`, with full logs only when needed. Routine warnings on a Ready
build do not warrant a new repair task.
