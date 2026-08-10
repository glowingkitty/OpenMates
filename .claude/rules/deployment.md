---
description: Deployment rules, Vercel debugging, and task completion summary
globs:
---

@docs/contributing/guides/git-and-deployment.md

## Alpha Versioning

OpenMates alpha releases use fixed minor trains. Product UI shows `v0.X`, npm
and GHCR use `0.X.0-alpha.N` / `v0.X.0-alpha.N`, and PyPI uses `0.X.0aN`.
Use `python3 scripts/bump_alpha_version_line.py --minor X` for product-line
bumps. Do not create `0.X.N-alpha` patch trains.

## Vercel Failures

Use these commands — **never** `vercel logs` (fails silently on ERROR deployments):
```bash
python3 scripts/sessions.py debug-vercel          # auto-starts session + shows errors/warnings
python3 backend/scripts/debug.py vercel           # errors/warnings only (fastest)
python3 backend/scripts/debug.py vercel --failed  # latest ERROR/CANCELED deployment and full error log
python3 backend/scripts/debug.py vercel --all     # full build log
python3 backend/scripts/debug.py vercel --n 3     # last 3 deployments
```

First separate real failed deployments from noisy red warnings on READY builds.
Node deprecation notices, app-metadata exclusions, and Svelte warnings can appear
in red without failing the deployment. For Dependabot npm preview failures, check
whether `scripts/vercel_ignore_build.py` should skip the preview before install;
do not spawn repeated fix sessions for non-dev dependency-update branches unless
the branch is intentionally being validated.

If a dependency update raises a package `engines.node` floor above the configured
Vercel runtime, either move Vercel to the supported Node major or keep the preview
ignored by the deterministic preflight. Vercel Node runtime changes should be
made in Project Settings or via a specific `package.json` major such as `24.x`;
avoid broad ranges like `>=18` for selecting the Vercel build runtime.

## Vercel Deployment — Wait Before Testing

ALWAYS wait for Vercel deployment to complete before browser-based verification:
1. After deploy, check: `python3 backend/scripts/debug.py vercel`
2. Do NOT test until status is **Ready**
3. If build fails, fix the error first

## Task Completion Summary

Deploy FIRST, then write the summary. The `Commit:` field requires a real SHA.

```
## Task Summary
Type: <Bug Fix | Feature | Refactor | Docs | Test>
Commit: <short-sha from deploy output>
Goal: <1-2 sentences>

Broken Flow (Before): (bug fixes only)
Flow After:
Changes: | File | Change | Why |
Testing:
Risks:
Architecture & Key Functions Touched: (omit if cosmetic)
```
