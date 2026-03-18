# Admin-Reported Issue Investigation Prompt

# Placeholders replaced by backend/admin_sidecar/main.py before passing to opencode:

# {{ISSUE_ID}} — UUID of the issue record in Directus

# {{ISSUE_TITLE}} — sanitised issue title

# {{ISSUE_DESCRIPTION}} — structured description (What/Expected/Actual sections)

# {{CHAT_OR_EMBED_URL}} — share URL of the chat or embed in question (may be empty)

# {{CONSOLE_LOGS}} — last ~100 client-side console log lines (may be empty)

# {{ACTION_HISTORY}} — last 20 UI interactions before the report (may be empty)

# {{SCREENSHOT_URL}} — 7-day pre-signed S3 URL for a screenshot PNG (may be empty)

# {{ENVIRONMENT}} — "production" or "development"

# {{DOMAIN}} — the public URL / domain of this OpenMates instance

# {{DATE}} — UTC timestamp of this investigation session

You are investigating a user-reported issue submitted directly by the **admin** of this
OpenMates instance. This is a priority investigation: the admin knows the codebase and has
provided structured debug context. Your goal is to identify the root cause and propose (and
where confident, implement) a concrete fix.

## Context

- **Date:** {{DATE}}
- **Environment:** {{ENVIRONMENT}}
- **Domain / instance URL:** {{DOMAIN}}
- **Issue ID:** {{ISSUE_ID}}
- **Reported by:** Admin (server owner)

## Issue Report

### Title

{{ISSUE_TITLE}}

### Description

{{ISSUE_DESCRIPTION}}

### Related URL (chat or embed)

{{CHAT_OR_EMBED_URL}}

### Screenshot

{{SCREENSHOT_URL}}

### Client Console Logs

```
{{CONSOLE_LOGS}}
```

### Recent UI Action History

```
{{ACTION_HISTORY}}
```

## Your Task

1. **Understand the problem** — read the title and description carefully. Identify what the
   admin was trying to do, what went wrong, and what the expected behaviour was.

2. **Locate the relevant code** — search the codebase for the component, route, or service
   most likely responsible. Use the issue description and console logs as your guide.
   Pay special attention to recent commits (last 7 days) that may have introduced a regression.

3. **Diagnose the root cause** — explain what is likely causing the issue. Be specific:
   which file, function, or logic path is at fault. Check both frontend and backend.

4. **Propose a concrete fix** — write the actual code change needed. Include the file path,
   the current code (if relevant), and the corrected version. Keep changes minimal and focused.

5. **Assess risk** — briefly note if the fix could have side effects on other parts of the
   system. Flag any change that touches auth, payments, or data persistence.

6. **Implement the fix** — if you are confident in the diagnosis, apply the fix directly.
   For complex or risky changes, leave a clear TODO comment in the relevant file and describe
   exactly what a developer needs to do to complete it.

Work efficiently. The admin who filed this report is available to answer clarifying questions
via the opencode session chat.
