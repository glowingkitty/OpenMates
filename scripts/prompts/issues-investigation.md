# Reported Issues Investigation Prompt

#

# Placeholders replaced by scripts/\_issues_checker.py before passing to claude:

# {{DATE}} — UTC date of the check (YYYY-MM-DD)

# {{ISSUE_COUNT}} — number of unresolved open issues

# {{ISSUES_JSON}} — JSON array of issue objects with id/title/description/created_at fields

# {{GIT_LOG}} — recent git log (last 7 days, oneline format)

You are investigating open user-reported issues for the OpenMates project that have not yet been resolved via a git commit.

## Context

- **Date:** {{DATE}}
- **Open unresolved issues:** {{ISSUE_COUNT}}
- **Recent git activity (last 7 days):**

```
{{GIT_LOG}}
```

## Unresolved Issues

```json
{{ISSUES_JSON}}
```

## Your Task

For each issue:

1. **Understand the problem** — read the title and description carefully. Identify what the user was trying to do, what went wrong, and what the expected behaviour was.

2. **Locate the relevant code** — search the codebase for the component, route, or service most likely responsible. Use the issue description as your guide.

3. **Diagnose the root cause** — explain what is likely causing the issue. Be specific: which file, function, or logic path is at fault.

4. **Propose a concrete fix** — write the actual code change needed. Include the file path, the current code (if relevant), and the corrected version. Keep changes minimal and focused.

5. **Assess risk** — briefly note if the fix could have side effects on other parts of the system.

Work through all issues. Prioritise by severity (data loss / auth / billing > UX > cosmetic).

After diagnosing and proposing fixes, implement the most critical fix if you are confident in it. For others, leave a clear TODO comment in the relevant file so the next developer knows exactly what to do.
