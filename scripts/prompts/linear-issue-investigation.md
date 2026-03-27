# Linear Issue Investigation Prompt

# Placeholders replaced by scripts/linear-poller.py before passing to claude:

# {{LINEAR_IDENTIFIER}} — Linear issue identifier (e.g., OPE-42)

# {{TITLE}} — Issue title

# {{URL}} — Direct URL to the issue in Linear

# {{DATE}} — UTC timestamp of this investigation session

You are investigating a Linear issue submitted to the OpenMates project. This is a
priority investigation: Linear issues are created by the admin/developer who knows the
codebase. Your goal is to identify the root cause and propose (and where confident,
implement) a concrete fix.

## Context

- **Date:** {{DATE}}
- **Linear Issue:** {{LINEAR_IDENTIFIER}} — {{URL}}

## Step 1: Read the Issue

Use your **Linear MCP tools** to read the full issue {{LINEAR_IDENTIFIER}}:
- Read the title, description, and all comments
- View any attached images or screenshots — these provide critical visual context
- Note the priority and labels

## Step 2: Investigate

1. **Understand the problem** — from the issue description, comments, and any screenshots,
   identify what the reporter was trying to do, what went wrong, and what the expected
   behaviour was.

2. **Locate the relevant code** — search the codebase for the component, route, or service
   most likely responsible. Use the issue description as your guide.
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

## Step 3: Post Findings

When done, use the `save_comment` Linear MCP tool to post a concise summary of your
findings on the issue. Include: root cause, fix applied (if any), and any follow-up needed.
Do NOT update the issue status or labels — the pipeline handles that automatically.

## GSD Command Recommendation

Based on the nature of this issue, recommend the appropriate GSD workflow command for the
developer to run next:

- Bug/error/broken behavior → `/gsd:debug`
- New feature/addition → `/gsd:quick` (small) or `/gsd:execute-phase` (roadmap)
- Refactor/cleanup → `/gsd:quick`
- Default (unclear) → `/gsd:debug`

Include the recommendation in your findings comment.

Work efficiently. The developer who filed this issue is available to answer clarifying
questions via the claude session chat.
