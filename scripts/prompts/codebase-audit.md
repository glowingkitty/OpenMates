You are doing a bi-weekly codebase health audit for the OpenMates project.

**Date:** {{DATE}} | **HEAD:** {{GIT_SHA}} | **Last audit:** {{LAST_AUDIT_DATE}}

## Recent commits (last 2 weeks)

```
{{GIT_LOG}}
```

## Previous audit findings (for context — don't repeat already-fixed items)

{{LAST_AUDIT_SUMMARY}}

## Your task

Explore the codebase and find the **top 5 highest-impact improvements** to make right now. Use your file reading tools to look at the actual code before making findings — don't guess from filenames alone.

Cover any mix of: security vulnerabilities, performance bottlenecks, reliability gaps (silent failures, missing error handling, race conditions), code quality, architecture problems.

For each finding, provide:

- **File + line number**
- **Why it matters** (what breaks or degrades without fixing it)
- **Current code snippet** (max 10 lines)
- **Suggested fix**
- **Effort: S / M / L**

After listing all 5: implement the **#1 finding** if it is S or M effort and you are confident the fix is correct. For all others, add a `# TODO(audit-{{DATE}}):` comment at the relevant location.

Be specific. "Add error handling" is not a finding. "The `process_webhook()` function at `backend/apps/payments/webhook.py:87` swallows all exceptions with a bare `except: pass`, meaning failed payments are silently ignored" is a finding.
