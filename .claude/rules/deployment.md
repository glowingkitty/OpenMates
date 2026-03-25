---
description: Deployment rules, Vercel debugging, and task completion summary
globs:
---

@docs/contributing/guides/git-and-deployment.md

## Vercel Failures

Use these commands — **never** `vercel logs` (fails silently on ERROR deployments):
```bash
python3 scripts/sessions.py debug-vercel          # auto-starts session + shows errors/warnings
python3 backend/scripts/debug.py vercel           # errors/warnings only (fastest)
python3 backend/scripts/debug.py vercel --all     # full build log
python3 backend/scripts/debug.py vercel --n 3     # last 3 deployments
```

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
