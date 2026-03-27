# Linear Comment-Triggered Resume Prompt

# Placeholders replaced by scripts/linear-poller.py before passing to claude:

# {{LINEAR_IDENTIFIER}} — Linear issue identifier (e.g., OPE-42)

The developer left new comments on Linear issue {{LINEAR_IDENTIFIER}}.

## Instructions

Use your **Linear MCP tools** to read the latest comments on issue {{LINEAR_IDENTIFIER}},
then continue working based on what the developer said.

- If they're asking you to **implement a fix** you previously proposed, go ahead and do it.
- If they're providing **clarification or additional context**, use it to refine your approach.
- If they're asking a **question**, answer it based on your investigation.
- If they're saying the issue is **resolved or to stop**, acknowledge and wrap up.

After completing:
- **Post a summary comment** on the Linear issue with what was done
- **Update the issue status** if work is complete
