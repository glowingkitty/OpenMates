# Codebase Health Audit Prompt

#

# Placeholders replaced by scripts/\_audit_helper.py before passing to opencode:

# {{DATE}} — UTC date of the audit (YYYY-MM-DD)

# {{CHANGED_FILES}} — newline-separated list of files changed since last audit

# {{CHANGED_FILE_COUNT}} — number of changed files

# {{LAST_AUDIT_DATE}} — date of the previous audit (or "first run" if none)

# {{LAST_AUDIT_SUMMARY}} — top findings from the previous audit (or "N/A")

# {{GIT_SHA}} — current git HEAD SHA

You are performing a bi-weekly codebase health audit for the OpenMates project.

## Audit Context

- **Date:** {{DATE}}
- **Current HEAD:** {{GIT_SHA}}
- **Files changed since last audit ({{LAST_AUDIT_DATE}}):** {{CHANGED_FILE_COUNT}} files
- **Previous audit top findings:**
  > {{LAST_AUDIT_SUMMARY}}

## Changed Files Since Last Audit

```
{{CHANGED_FILES}}
```

## Your Task

Analyse the changed files and the broader codebase context to identify the **top 5 highest-impact improvements** the team should make right now.

Consider all dimensions:

- **Security** — exposed secrets, injection vulnerabilities, missing auth checks, unsafe dependencies
- **Performance** — N+1 queries, missing indexes, unnecessary re-renders, large bundle sizes, slow API paths
- **Reliability** — silent error swallowing, missing retry logic, race conditions, uncovered edge cases
- **Code quality** — duplicated logic, overly complex functions, missing type annotations, dead code
- **Architecture** — module boundary violations, growing files that should be split, missing abstractions

## Output Format

For each finding:

### #N — [Category]: [Short title]

**File(s):** `path/to/file.ts:line`
**Impact:** [Why this matters — what breaks or degrades without fixing it]
**Current code:**

```
[relevant snippet, max 10 lines]
```

**Suggested fix:**

```
[corrected version]
```

**Effort:** [S / M / L]

---

After listing the top 5, implement the **#1 finding** if it is S or M effort and you are confident the fix is correct. For others, leave a `// TODO(audit-{{DATE}}): <description>` comment at the relevant location so it shows up in future searches.

Be specific, not generic. "Add error handling" is not a finding. "The `processWebhook()` function in `backend/apps/payments/webhook.py:87` swallows all exceptions with a bare `except: pass`, meaning failed payments are silently ignored" is a finding.
