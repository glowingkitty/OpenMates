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

## Worktree Readiness Snapshot
!`python3 scripts/sessions.py worktree release-readiness --target origin/dev 2>/dev/null || true`

## Latest Releases
!`gh release list --limit 3 2>/dev/null || echo "gh not available"`

## Release Intelligence Snapshot
!`today=$(date -u +%F); python3 scripts/release_intelligence.py daily --since "24 hours ago" --date "$today" --write --output "docs/releases/daily/${today}.yml" >/tmp/create-pr-release-intelligence.out 2>/tmp/create-pr-release-intelligence.err && echo "Refreshed docs/releases/daily/${today}.md and companion YAML" || { echo "Daily release intelligence refresh failed"; cat /tmp/create-pr-release-intelligence.err; }; latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' 2>/dev/null | cut -dT -f1); if [ -n "$latest_pr_date" ]; then echo "Daily summaries since last dev→main PR (${latest_pr_date}):"; ls docs/releases/daily/*.md 2>/dev/null | while read -r file; do day=$(basename "$file" .md); [ "$day" ">" "$latest_pr_date" ] && echo "$file"; done; else echo "No previous dev→main PR date found; use available daily summaries plus origin/main..origin/dev."; ls docs/releases/daily/*.md 2>/dev/null | tail -14; fi`

## Feature Readiness Snapshot
!`latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' 2>/dev/null | cut -dT -f1); if [ -n "$latest_pr_date" ]; then next_daily_date=$(date -u -d "${latest_pr_date} +1 day" +%F); python3 scripts/release_intelligence.py pr-readiness --from-ref origin/main --to-ref origin/dev --daily-start-date "$next_daily_date" --format markdown --stdout; else python3 scripts/release_intelligence.py pr-readiness --from-ref origin/main --to-ref origin/dev --format markdown --stdout; fi`

## Instructions

**IMPORTANT: Only create a PR when the user explicitly asks.**

### Step 0 — Resolve Worktree Readiness (CRITICAL)

Before release intelligence or PR drafting, fetch `dev` and run reconciliation readiness against its exact remote commit:

```bash
git fetch origin dev
python3 scripts/sessions.py worktree release-readiness --target origin/dev
```

The gate blocks stale, blocked, orphaned, malformed, unique unresolved, and unclassified worktrees. Do not merge or delete
worktree content manually to bypass it. Run the reported `sessions.py worktree reconcile` action and stop when meaningful unique
work still needs an operator decision.

Recent active work may remain outside this release only after the user explicitly confirms the exclusion. Rerun with one flag
per confirmed session, for example:

```bash
python3 scripts/sessions.py worktree release-readiness \
  --target origin/dev \
  --exclude-active 253b
```

Record the excluded session IDs in the PR preparation summary, rerun the gate after any cleanup or deploy, and continue only
when it reports `Ready: yes` for the final exact `origin/dev` commit.

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

Then identify the most recent prior `dev` → `main` PR and read every compact `docs/releases/daily/YYYY-MM-DD.md` after that PR date. Use these Gemini interpretations as the primary source for the PR description. Consult the companion YAML only for deterministic feature readiness or details absent from Markdown.

```bash
latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' | cut -dT -f1)
ls docs/releases/daily/*.md | while read -r file; do
  day=$(basename "$file" .md)
  [ -z "$latest_pr_date" ] || [ "$day" ">" "$latest_pr_date" ] && echo "$file"
done
```

Use the Markdown overview, grouped changes, and newsletter guidance to build the PR body. Keep unreleased/disabled-feature work out of public release/newsletter language, but include it in the PR when it is part of the code diff. Use companion YAML fields such as `sections`, `marketing_candidates`, and `unreleased_progress` only when deeper structured evidence is required.

### Step 3 — Feature Readiness Gate (CRITICAL)

Before drafting or creating the PR, run and read the deterministic feature readiness report:

```bash
latest_pr_date=$(gh pr list --base main --head dev --state all --limit 1 --json createdAt --jq '.[0].createdAt // empty' | cut -dT -f1)
if [ -n "$latest_pr_date" ]; then
  next_daily_date=$(date -u -d "${latest_pr_date} +1 day" +%F)
  python3 scripts/release_intelligence.py pr-readiness \
    --from-ref origin/main \
    --to-ref origin/dev \
    --daily-start-date "$next_daily_date" \
    --format markdown \
    --stdout
else
  python3 scripts/release_intelligence.py pr-readiness \
    --from-ref origin/main \
    --to-ref origin/dev \
    --format markdown \
    --stdout
fi
```

Use this report to list every changed user-facing or potentially user-facing feature area, especially default-disabled platform features and app/skill/provider work such as projects, tasks, plans, workflows, teams, Revolut Business finance, and code image-to-HTML/image-to-code.

You must then ask the user which listed features are ready for public deployment, which should stay disabled, and which must be deactivated before the PR. Stop here until the user explicitly confirms how to handle the readiness list. Do not draft the final PR body and do not run `gh pr create` before this confirmation.

If the user says a feature is not ready, keep the code but deactivate access through the existing feature availability model:
- For platform features, remove any matching `feature_overrides.enabled` entry and/or add a `feature_overrides.disabled` entry in `backend/config/backend_config.yml`.
- For apps, skills, embeds, focus modes, or memory types, set `default_enabled: false` on the relevant `backend/apps/*/app.yml` entry.
- Re-run `python3 scripts/release_intelligence.py pr-readiness --from-ref origin/main --to-ref origin/dev --format markdown --stdout` and show the updated status before continuing.

Only continue after the user confirms that the remaining accessible features are ready for the PR.

### Step 4 — Analyze Remaining Commit Details

Use raw commit history only as supporting evidence or to fill gaps not covered by daily changelogs. Read the **full commit messages** (not just one-liners):

```bash
git log origin/main..origin/dev --format="%h %s%n%b"
```

Group commits into:
- **Features** (`feat:`) — new user-facing functionality
- **Bug Fixes** (`fix:`) — resolved issues
- **Improvements** (`refactor:`, `perf:`, `improve:`) — internal improvements
- **Other** (`docs:`, `chore:`, `build:`, `ci:`, `test:`) — maintenance

### One-Time Core Journeys Bootstrap (REMOVE AFTER FIRST PROMOTION)

This temporary gate applies only while `.github/workflows/release-core-journeys.yml` is absent from `origin/main`.

First check the remote base branch:

```bash
git fetch origin main dev
git cat-file -e origin/main:.github/workflows/release-core-journeys.yml 2>/dev/null
```

If the command succeeds, the first promotion has landed. Before continuing, remove this entire `One-Time Core Journeys Bootstrap` section from `.claude/skills/create-pr/SKILL.md`, run `python3 scripts/sync_agent_parity.py`, validate with `python3 scripts/sync_agent_parity.py --check`, and deploy that instruction-only cleanup to `dev` through `scripts/sessions.py deploy`. Then restart the PR flow against the new exact `origin/dev` SHA.

If the command fails, GitHub cannot dispatch the new workflow yet. After all feature-readiness changes are finalized and deployed, run the one-time bootstrap against the exact current `origin/dev` commit:

```bash
FULL_DEV_SHA=$(git rev-parse origin/dev)
python3 scripts/prepare_release_candidate.py \
  --session <SESSION_ID> \
  --expected-commit "$FULL_DEV_SHA"
python3 scripts/tests.py run \
  --core-journeys \
  --gate-deploy \
  --expected-commit "$FULL_DEV_SHA" \
  --max-concurrent 4 \
  --no-fail-fast
```

Require reachability, signup, billing, and chat to all pass for that same full SHA. Stop and report failures instead of creating the PR. Do not enable a required branch-protection check during this first advisory promotion.

Include this unchecked post-merge item in the PR body so the temporary instruction cannot be forgotten:

```markdown
## Post-Merge Cleanup
- [ ] Confirm the core-journeys workflow exists on `origin/main`, then rerun the `create-pr` skill so its one-time bootstrap instructions remove themselves from `dev`.
```

Do not remove this section before the first PR is merged: doing so changes `origin/dev` and invalidates the exact-SHA bootstrap evidence.

### Step 5 — Write PR Description

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

### Step 6 — Create the PR

```bash
gh pr create --base main --head dev --title "<short descriptive title>" --body "$(cat <<'EOF'
<PR description>
EOF
)"
```

Present the PR URL to the user.

### Step 7 — Offer Draft Release

After PR creation, ask the user if they want a draft release prepared. If yes, use the `/create-release` skill. Tell the user:
- The PR URL
- That the draft release should be published **after** the PR is merged into `main`
