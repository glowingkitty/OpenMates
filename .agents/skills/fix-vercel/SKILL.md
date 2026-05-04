---
name: fix-vercel
description: Check and fix a Vercel deployment failure
user-invocable: true
---

## Instructions

You are diagnosing and fixing a Vercel deployment failure. Follow this exact sequence:

### Step 1: Check Deployment Status

```bash
python3 backend/scripts/debug.py vercel --n 2
```

If the latest deployment is **Ready**, report success and stop.

If the latest deployment is **ERROR** or **CANCELED**, continue to Step 2.

### Step 2: Get Full Build Logs

```bash
python3 backend/scripts/debug.py vercel --all
```

Read the output carefully. Common failure categories:

| Category | Signs | Typical Fix |
|----------|-------|-------------|
| **TypeScript error** | `TS2xxx`, `Type error:` | Fix the type error in the indicated file |
| **Import error** | `Cannot find module`, `does not provide an export` | Fix the import path or add the missing export |
| **Build OOM** | `JavaScript heap out of memory` | Check for circular imports or oversized assets |
| **Svelte compile** | `Error compiling`, `a11y-`, `svelte(...)` | Fix the Svelte component error |
| **Missing env var** | `VITE_` prefixed var undefined | Check `frontend/apps/web_app/.env` and Vercel project settings |
| **Dependency issue** | `ERR_PNPM_`, `peer dep`, `Could not resolve` | Check `package.json` and lockfile consistency |
| **Adapter error** | `adapter-vercel`, `serverless function` | Check `svelte.config.js` and route prerender settings |

### Step 3: Identify Root Cause

1. Extract the **first error** from the build log — later errors are often cascading failures
2. Check `git log -5 -- <broken-file>` to find the commit that introduced it
3. Read the broken file and understand the issue before editing

### Step 4: Fix

Apply the minimal fix needed. Do NOT refactor surrounding code.

After fixing, run the deployment doc check:
```bash
python3 scripts/sessions.py deploy-docs
```

### Step 5: Deploy the Fix

Use the `/deploy` skill to commit and push. The commit message should be:
```
fix: <what broke> (Vercel build)
```

### Step 6: Verify

Wait for the new deployment, then check status:
```bash
python3 backend/scripts/debug.py vercel --status-only
```

If still failing, go back to Step 2 with the new error. **2 tries max** with the same approach — if the same fix doesn't work twice, reassess.

### Rules

- **Never use `vercel logs`** — it fails silently on ERROR deployments
- **Never run `pnpm build` locally** — use Vercel's build output as the source of truth
- **Fix the first error first** — cascading errors resolve themselves
- If the failure is caused by a commit from another session, report it to the user instead of fixing blindly
