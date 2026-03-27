# Linear GSD Command Execution Prompt

# Placeholders replaced by scripts/linear-poller.py before passing to claude:

# {{LINEAR_IDENTIFIER}} — Linear issue identifier (e.g., OPE-42)

# {{TITLE}} — Issue title

# {{URL}} — Direct URL to the issue in Linear

# {{DATE}} — UTC timestamp of this execution session

# {{GSD_COMMAND}} — The GSD command to execute (e.g., /gsd:quick, /gsd:debug, /gsd:add-phase)

You are executing a GSD workflow command triggered by a Linear issue for the OpenMates project.
This task has been tagged for autonomous execution.

## Context

- **Date:** {{DATE}}
- **Linear Issue:** {{LINEAR_IDENTIFIER}} — {{URL}}
- **GSD Command:** `{{GSD_COMMAND}}`

## Step 1: Read the Issue

Use your **Linear MCP tools** to read the full issue {{LINEAR_IDENTIFIER}}:
- Read the title, description, and all comments
- View any attached images or screenshots
- Note the priority and labels

## Step 2: Execute

Run the following GSD command with the issue context:

```
{{GSD_COMMAND}} "{{TITLE}}"
```

### Command-Specific Guidance

**If `/gsd:quick`:**
- Execute the task end-to-end: plan, implement, commit
- Keep changes minimal and focused on the task

**If `/gsd:debug`:**
- Investigate the bug described in the issue
- Identify root cause, propose and implement a fix
- Commit with a conventional commit message referencing the Linear issue

**If `/gsd:add-phase`:**
- Add a new phase to the current milestone roadmap
- Use the issue title as the phase description
- Do NOT execute the phase — only add it to the roadmap

## Step 3: Update Linear

After completing:
- **Post a summary comment** on the Linear issue with what was done, files changed,
  commit hash, and any risks or follow-up needed
- **Update the issue status** appropriately

## Constraints

- Do NOT deploy. Only commit to the current branch.
- Do NOT modify files unrelated to the task.
- If the task is too large or risky for autonomous execution, STOP and explain why.
- If you need clarification, say so — the developer can resume this session.

Work efficiently. This is an autonomous execution — be thorough but focused.
