---
description: Task tracking workflow — GitHub Issues by default, Linear only for retained internal categories
globs:
---

## Task Tracking Workflow

Use GitHub Issues as the default task tracker for OpenMates work. Use Linear only for work that must remain in Linear because it is programmatically created/stored, marketing-related, sensitive/private, or already explicitly provided as a Linear issue.

## Tracker Selection

Create or update a GitHub Issue for:

- Public bugs that do not include private user data.
- Product, documentation, CLI, app, skill, infrastructure, and developer-experience work that can be open source.
- Contributor-friendly tasks, implementation proposals, cleanup tasks, and roadmap discussions.
- Any general task that is not clearly in a Linear-only category.

Keep or create a Linear issue only for:

- Programmatically stored or recorded product issues, such as user bug reports created by the app/admin tooling.
- Marketing work and marketing planning.
- Sensitive/private tasks that should not be public on GitHub.
- Existing Linear issues that the user explicitly references by ID or URL.

Do not use the Linear MCP. Linear operations must go through `python3 scripts/linear.py`, which uses the Linear API and supports `.env`, environment variables, and OpenMates Vault credentials.

## When A GitHub Issue Is Provided

1. Read the issue with GitHub tools before code work.
2. If GitHub MCP auth fails, use `gh issue list` or `gh issue view --json ...` with the `glowingkitty/OpenMates` repo.
3. Read comments and labels for prior context.
4. If `gh issue view --comments` fails on deprecated Projects Classic fields, retry with explicit JSON fields such as `number,title,state,labels,body,comments,updatedAt,url`.
5. If the task needs progress tracking, post a concise pickup comment with the session ID.
6. Post milestone comments only for significant discoveries, blockers, or completion.
7. After deploy, post a concise summary comment with the commit hash and move/label the issue according to the repo's issue workflow when applicable.

## Creating Or Updating GitHub Issues

Use GitHub Issues for public tracker work unless the task clearly belongs in Linear under the rules above.

Preferred creation paths:

- Use GitHub MCP issue tools when they are authenticated and available.
- If MCP auth fails, use the GitHub API via `gh api`, for example:
  ```bash
  gh api repos/glowingkitty/OpenMates/issues --method POST \
    --field title="Short actionable title" \
    --field labels[]=enhancement \
    --field body="Issue body" \
    --jq .html_url
  ```
- For long issue bodies, prefer a safe temporary file under `scripts/.tmp/` or `/tmp/opencode/` and pass it through `gh api --input` or command substitution. Do not store private data in the temp file.

Avoid these patterns:

- Avoid `gh issue create --body-file - <<'EOF' ... EOF`; local safety hooks may misclassify this heredoc form as an unsafe deploy/git mutation.
- Avoid broad raw `gh` mutations when a narrower GitHub MCP or `gh api` endpoint is available.

Reading and commenting:

- Use `gh issue list --repo glowingkitty/OpenMates --search "keywords" --state all` when MCP issue search is unavailable.
- Use `gh issue view <number> --repo glowingkitty/OpenMates --json number,title,state,labels,body,comments,updatedAt,url` when regular issue view fails.
- Use `gh api repos/glowingkitty/OpenMates/issues/<number>/comments --method POST --field body="..."` for comments if GitHub MCP commenting is unavailable.

Keep GitHub issue bodies and comments free of private user data, secrets, payment details, raw logs with identifiers, and credentials.

## When A Linear Issue Is Provided

1. Read the issue before code work:
   ```bash
   python3 scripts/linear.py get OPE-123 --comments
   ```
2. Move it to In Progress and add `claude-is-working` before code work:
   ```bash
   python3 scripts/linear.py update OPE-123 --state "In Progress" --add-label claude-is-working
   ```
3. Post a pickup comment with the session ID:
   ```bash
   python3 scripts/linear.py comment OPE-123 --body "Picked up in session <session-id>."
   ```
4. Post milestone comments only for significant discoveries, blockers, or completion.
5. After deploy, post a summary comment with the commit hash and update status:
   ```bash
   python3 scripts/linear.py comment OPE-123 --body "Completed in <commit>. Summary: ..."
   python3 scripts/linear.py update OPE-123 --state "In Review" --remove-label claude-is-working
   ```

Use `Done` instead of `In Review` only when the task is self-contained and confirmed complete.

## When No Issue Is Provided

Search first; never auto-create tracker entries without confirmation unless the user explicitly asked you to create one.

1. Decide the tracker from the Tracker Selection rules above.
2. For GitHub-default work, search GitHub Issues for related open issues before creating a new one.
3. For Linear-only work, search Linear with:
   ```bash
   python3 scripts/linear.py search "keywords" --team OPE --state Todo --state "In Progress" --state Backlog
   ```
4. If a clear match exists, use it and add the new sub-work as a checkbox/comment.
5. If no clear match exists, ask whether to create a GitHub Issue or, for Linear-only categories, a Linear issue.

## Linear Migration Review

When reviewing existing Linear tasks for migration:

- Move to GitHub Issues: public product/dev/docs/tasks that do not include sensitive data and are not marketing or programmatically recorded issues.
- Keep in Linear: marketing, app-recorded user reports, sensitive/private work, and tasks tied to internal automation.
- Delete/archive from Linear: stale duplicates, completed work that no longer needs history, abandoned ideas with no actionable next step, and tasks superseded by newer GitHub/Linear entries.
- Review one issue at a time. Do not bulk-delete or bulk-migrate without explicit confirmation.
- Preserve useful history by linking the old Linear ID in the new GitHub Issue body when migrating.

## Rules

- Do not use `mcp__linear__*` tools. They are intentionally not part of the workflow.
- Do not put private user data, secrets, payment details, or sensitive logs in GitHub Issues.
- Keep comments concise: pickup, one milestone/blocker if useful, and completion.
- Prefer GitHub Issues for transparency unless the task clearly matches a Linear-only category.
