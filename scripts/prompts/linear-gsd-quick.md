# Linear GSD Quick Execution Prompt

# Placeholders replaced by scripts/linear-poller.py before passing to claude:

# {{LINEAR_IDENTIFIER}} — Linear issue identifier (e.g., OPE-42)

# {{TITLE}} — Issue title

# {{URL}} — Direct URL to the issue in Linear

# {{DATE}} — UTC timestamp of this execution session

You are executing a task from Linear for the OpenMates project. This task has been
tagged for autonomous GSD quick execution — meaning you should investigate AND implement
the change, not just investigate.

## Context

- **Date:** {{DATE}}
- **Linear Issue:** {{LINEAR_IDENTIFIER}} — {{URL}}

## Step 1: Read the Issue

Use your **Linear MCP tools** to read the full issue {{LINEAR_IDENTIFIER}}:
- Read the title, description, and all comments
- View any attached images or screenshots
- Note the priority and labels

## Step 2: Execute

1. **Understand the task** — from the issue details, determine exactly what needs to be done.

2. **Locate the relevant code** — search the codebase for the files that need to change.

3. **Implement the change** — make the actual code changes. Follow project conventions
   from CLAUDE.md. Keep changes minimal and focused on the task.

4. **Verify** — run any relevant tests or checks to confirm the change works.

5. **Commit** — commit the changes with a conventional commit message that references
   the Linear issue: `fix(LINEAR_ID): description` or `feat(LINEAR_ID): description`.

## Step 3: Post Findings

When done, use the `save_comment` Linear MCP tool to post a summary on the issue with:
- What was changed and why
- Files modified
- Commit hash
- Any risks or follow-up needed

Do NOT update the issue status or labels — the pipeline handles that automatically.

## Constraints

- Do NOT deploy. Only commit to the current branch.
- Do NOT modify files unrelated to the task.
- If the task is too large or risky for autonomous execution, STOP and explain why.
  Recommend `/gsd:quick --discuss` or `/gsd:plan-phase` instead.
- If you need clarification, say so — the developer can resume this session.

Work efficiently. This is an autonomous execution — be thorough but focused.
