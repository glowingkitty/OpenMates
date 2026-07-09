---
name: create-pr
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

## Release Intelligence Snapshot
!`today=$(date -u +%F); yesterday=$(date -u -d '24 hours ago' +%F); python3 scripts/release_intelligence.py daily --since "24 hours ago" --date "$today" --write --output "docs/releases/daily/${today}.yml" >/tmp/create-pr-release-intelligence.out 2>/tmp/create-pr-release-intelligence.err && echo "Refreshed docs/releases/daily/${today}.yml" || { echo "Daily release intelligence refresh failed"; cat /tmp/create-pr-release-intelligence.err; }; latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' 2>/dev/null | cut -dT -f1); if [ -n "$latest_pr_date" ]; then echo "Daily changelogs since last dev→main PR (${latest_pr_date}):"; ls docs/releases/daily/*.yml 2>/dev/null | while read -r file; do day=$(basename "$file" .yml); [ "$day" ">" "$latest_pr_date" ] && echo "$file"; done; else echo "No previous dev→main PR date found; use available daily changelogs plus origin/main..origin/dev."; ls docs/releases/daily/*.yml 2>/dev/null | tail -14; fi`

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

### Step 2 — Refresh And Read Release Intelligence

Before writing the PR body, always refresh the current daily changelog so the last 24 hours are represented:

```bash
today=$(date -u +%F)
python3 scripts/release_intelligence.py daily \
  --since "24 hours ago" \
  --date "$today" \
  --write \
  --output "docs/releases/daily/${today}.yml"
```

Then identify the most recent prior `dev` → `main` PR and read every `docs/releases/daily/YYYY-MM-DD.yml` after that PR date. Use those daily changelogs as the primary source for the PR description because they already separate released-ready, dev-only, internal, and disabled-feature work.

```bash
latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' | cut -dT -f1)
ls docs/releases/daily/*.yml | while read -r file; do
  day=$(basename "$file" .yml)
  [ -z "$latest_pr_date" ] || [ "$day" ">" "$latest_pr_date" ] && echo "$file"
done
```

Use `llm_summary`, `sections`, `marketing_candidates`, and `unreleased_progress` from those files to build the PR body. Keep unreleased/disabled-feature work out of public release/newsletter language, but include it in the PR when it is part of the code diff.

### Step 3 — Analyze Remaining Commit Details

Use raw commit history only as supporting evidence or to fill gaps not covered by daily changelogs. Read the **full commit messages** (not just one-liners):

```bash
git log origin/main..origin/dev --format="%h %s%n%b"
```

Group commits into:
- **Features** (`feat:`) — new user-facing functionality
- **Bug Fixes** (`fix:`) — resolved issues
- **Improvements** (`refactor:`, `perf:`, `improve:`) — internal improvements
- **Other** (`docs:`, `chore:`, `build:`, `ci:`, `test:`) — maintenance

### Step 4 — Write PR Description

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

### Step 5 — Create the PR

```bash
gh pr create --base main --head dev --title "<short descriptive title>" --body "$(cat <<'EOF'
<PR description>
EOF
)"
```

Present the PR URL to the user.

### Step 6 — Offer Draft Release

After PR creation, ask the user if they want a draft release prepared. If yes, use the `/create-release` skill. Tell the user:
- The PR URL
- That the draft release should be published **after** the PR is merged into `main`
