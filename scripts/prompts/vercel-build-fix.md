# Vercel Build Failure Fix Prompt
#
# Placeholders replaced by scripts/_deploy_checker_helper.py before passing to opencode:
# {{DATE}}           — UTC datetime of the failure detection (ISO 8601)
# {{DEPLOY_ID}}      — Vercel deployment ID (e.g. dpl_abc123)
# {{DEPLOY_URL}}     — Vercel deployment URL (e.g. openmates-abc123.vercel.app)
# {{GIT_SHA}}        — short git SHA that triggered the failing deployment
# {{GIT_BRANCH}}     — git branch (always "dev")
# {{COMMIT_MESSAGE}} — commit message that triggered the build
# {{COMMIT_AUTHOR}}  — author of the triggering commit
# {{BUILD_LOG}}      — Vercel build log (errors/warnings)

You are fixing a Vercel build failure for the OpenMates project.

## Deployment Context

- **Detected at:** {{DATE}}
- **Deployment ID:** {{DEPLOY_ID}}
- **Deployment URL:** {{DEPLOY_URL}}
- **Branch:** `{{GIT_BRANCH}}`
- **Triggering commit:** `{{GIT_SHA}}` — {{COMMIT_MESSAGE}}
- **Author:** {{COMMIT_AUTHOR}}

## Vercel Build Log (errors and warnings)

```
{{BUILD_LOG}}
```

## Your Task

1. **Identify the root cause** of the build failure from the log above. Be specific — file path, line number, and error type.

2. **Cross-reference the triggering commit** — run `git show {{GIT_SHA}}` to see exactly what changed and confirm it caused the failure.

3. **Fix the build error** — make the minimal targeted change(s) necessary to resolve the failure. Do not refactor unrelated code.

4. **Verify locally before committing** — for frontend changes, run `pnpm -C frontend/apps/web_app build` (or the relevant build command) to confirm the fix compiles cleanly. For backend changes, run `python -m py_compile` on affected files.

5. **Commit and push using sessions.py deploy** — follow the standard deploy workflow:
   ```bash
   python3 scripts/sessions.py deploy-docs
   python3 scripts/sessions.py deploy --session <ID> --title "fix: resolve Vercel build failure from {{GIT_SHA}}" --message "Fixes build failure in deployment {{DEPLOY_ID}}.\n\nRoot cause: <brief description>" --end
   ```

6. **Do not** add workarounds, suppress errors, or change build config unless the error is genuinely a misconfiguration. Fix the actual code issue.

Be direct. Start with the root cause, then fix it. No preamble.
