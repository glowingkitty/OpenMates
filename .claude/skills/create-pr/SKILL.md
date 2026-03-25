---
name: create-pr
description: Create a pull request from dev to main with proper formatting and draft release
user-invocable: true
disable-model-invocation: true
argument-hint: "[title]"
---

## Current State
!`git fetch origin main dev 2>/dev/null && git log --oneline origin/main..origin/dev 2>/dev/null | head -30`

## Changed Files
!`git diff --stat origin/main...origin/dev 2>/dev/null | tail -20`

## Latest Releases
!`gh release list --limit 3 2>/dev/null || echo "gh not available"`

## Instructions

**IMPORTANT: Only create a PR when the user explicitly asks.**

### Step 1 — Verify Remote Refs

ALWAYS use **remote refs** (`origin/main`, `origin/dev`) — never local refs:
```bash
git fetch origin main dev
git log --oneline origin/main..origin/dev
```
Confirm the commit count makes sense before proceeding.

### Step 2 — Categorize Changes

Group commits into:
- **Features** (`feat:`) — new user-facing functionality
- **Bug Fixes** (`fix:`) — resolved issues
- **Improvements** (`refactor:`, `perf:`, `style:`) — internal improvements

### Step 3 — Write PR Description

Write a human-readable PR description (not just a commit list):
```markdown
## Summary
<2-4 sentence overview of what this PR does and why>

## Changes
### Features
- <grouped by feature area>

### Bug Fixes
- <grouped by fix area>

### Improvements
- <grouped by improvement area>

## Testing
<what was tested and how>
```

### Step 4 — Create the PR

```bash
gh pr create --base main --head dev --title "<short descriptive title>" --body "$(cat <<'EOF'
<PR description>
EOF
)"
```

### Step 5 — Prepare a Draft Release

After the PR is created, immediately prepare a draft GitHub release. See `/create-release` skill or run it manually. Tell the user:
- The PR URL
- The draft release tag/URL
- That the draft release should be published after the PR is merged into `main`
