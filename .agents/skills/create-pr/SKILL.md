---
name: openmates:pullrequest
description: Create a pull request from dev to main with proper formatting and draft release
user-invocable: true
disable-model-invocation: false
argument-hint: "[title]"
---

## Current State (Remote Refs)
!`git fetch origin main dev 2>/dev/null && echo "=== Commit count (main-ahead : dev-ahead) ===" && git rev-list --left-right --count origin/main...origin/dev && echo "" && echo "=== Commits on dev not in main ===" && git log --oneline origin/main..origin/dev`

## Changed Files
!`git diff --stat origin/main...origin/dev 2>/dev/null | tail -30`

## Latest Releases
!`gh release list --limit 3 2>/dev/null || echo "gh not available"`

## Instructions

**IMPORTANT: Only create a PR when the user explicitly asks.**

### Step 1 — Verify Remote Refs (CRITICAL)

**ALWAYS use remote refs** (`origin/main`, `origin/dev`) — never local refs. Local refs can be stale and produce wildly incorrect commit counts.

```bash
git fetch origin main dev
git rev-list --left-right --count origin/main...origin/dev
git log --oneline origin/main..origin/dev
```

The output above already did this. Confirm the commit count makes sense before proceeding. If something looks off, tell the user and stop.

### Step 2 — Analyze All Commits

Read the **full commit messages** (not just one-liners):

```bash
git log origin/main..origin/dev --format="%h %s%n%b"
```

Group commits into:
- **Features** (`feat:`) — new user-facing functionality
- **Bug Fixes** (`fix:`) — resolved issues
- **Improvements** (`refactor:`, `perf:`, `improve:`) — internal improvements
- **Other** (`docs:`, `chore:`, `build:`, `ci:`, `test:`) — maintenance

### Step 3 — Write PR Description

Write a **human-readable** PR description — not a commit dump. Structure:

```markdown
## Summary
<2-4 sentence overview of what this PR does and why>

## Features
- <grouped by feature area>

## Bug Fixes
- <grouped by fix area>

## Improvements
- <grouped by improvement area>

## Other Changes
- <docs, chore, config items>
```

Only include sections that have content. Write for a developer audience — specific and clear.

### Step 4 — Create the PR

```bash
gh pr create --base main --head dev --title "<short descriptive title>" --body "$(cat <<'EOF'
<PR description>
EOF
)"
```

Present the PR URL to the user.

### Step 5 — Offer Draft Release

After PR creation, ask the user if they want a draft release prepared. If yes, use the `/create-release` skill. Tell the user:
- The PR URL
- That the draft release should be published **after** the PR is merged into `main`
