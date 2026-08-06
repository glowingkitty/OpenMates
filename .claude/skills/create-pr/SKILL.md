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
!`git diff --stat origin/main...origin/dev 2>/dev/null`

## Prior Promotion And Markdown Sources
!`latest_pr=$(gh pr list --base main --head dev --state merged --limit 1 --json number,title,mergedAt,mergeCommit,url --jq '.[0] // empty' 2>/dev/null); latest_pr_date=$(printf '%s' "$latest_pr" | jq -r '.mergedAt // empty' 2>/dev/null | cut -dT -f1); echo "=== Latest merged dev to main PR ==="; if [ -n "$latest_pr" ]; then printf '%s\n' "$latest_pr"; else echo "None found"; fi; echo ""; echo "=== Daily Markdown summaries after boundary ==="; if [ -n "$latest_pr_date" ]; then for file in docs/releases/daily/*.md; do day=$(basename "$file" .md); [ "$day" ">" "$latest_pr_date" ] && echo "$file"; done; else ls docs/releases/daily/*.md 2>/dev/null; fi; echo ""; echo "=== Weekly Markdown summaries to inspect for overlapping post-boundary coverage ==="; ls docs/releases/weekly/*.md 2>/dev/null`

## Instructions

**IMPORTANT: Only create a PR when the user explicitly asks.**

### Step 0 — Summarize Changelog Markdown Before Asking Questions (CRITICAL)

Identify the most recent **merged** `dev` → `main` PR using `--state merged` and its `mergedAt` value. Read every compact
`docs/releases/daily/YYYY-MM-DD.md` after that merge date and every `docs/releases/weekly/YYYY-Www.md` whose covered date range overlaps the post-merge period.
Do not refresh or write release-intelligence artifacts yet.

Before asking any clarifying question, give the user one concise, source-grounded summary with these headings:

- **Released/User-Facing Changes**
- **Bug Fixes**
- **Internal/Platform Work**
- **Disabled Or Unreleased Preparation**
- **Risks And Unclear Decisions**

Use Markdown companions as the primary source. Use `origin/main..origin/dev`, changed files, companion YAML, and full commit messages only as supporting evidence or to resolve ambiguity. Do not claim a feature is released merely because its code is in `dev`.

### Step 1 — Ask Exactly Five Clarifying Questions (CRITICAL)

After presenting the changelog summary, ask exactly five clarifying questions before changing feature availability, reconciling branches, drafting the PR body, or creating the PR.

- Ask one question per assistant message and wait for the user's response before asking the next.
- Label them `Question 1 of 5` through `Question 5 of 5`.
- Include a concrete recommendation in each question and short examples when they make the decision clearer.
- Incorporate answers already provided by the user, but still ask for confirmation when the answer controls release scope or branch history.
- Cover these five decision areas, adapting the wording to the discovered changes: code inclusion versus public release-note treatment; enabled versus disabled feature readiness; `main`-only commit reconciliation; required validation/risk exceptions; and PR narrative/release emphasis.
- For branch reconciliation, inspect the `main`-only commits before making a recommendation. Recommend preserving legitimate fixes and merge history. Ask the user about ambiguous commits or behavioral conflicts rather than guessing.

After the fifth answer, summarize the confirmed decisions and provide the execution plan. Continue autonomously only when the user approves that plan.

### Step 2 — Resolve Worktree Readiness (CRITICAL)

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

### Step 3 — Verify Remote Refs And Main-Only Commits (CRITICAL)

**ALWAYS use remote refs** (`origin/main`, `origin/dev`) — never local refs. Local refs can be stale and produce wildly incorrect commit counts.

```bash
git fetch origin main dev
git rev-list --left-right --count origin/main...origin/dev
git log --format="%h %s%n%b" origin/dev..origin/main
git log --oneline origin/main..origin/dev
```

Confirm the commit count makes sense and classify every `main`-only commit before reconciling branches. If the commits are legitimate fixes or merge history and reconciliation is conflict-free, follow the user's approved strategy. Stop and ask about unexpected commits or behavioral conflicts.

### Step 4 — Refresh Release Intelligence

Before writing the PR body, always refresh the current daily changelog so the last 24 hours are represented:

```bash
today=$(date -u +%F)
python3 scripts/release_intelligence.py daily \
  --since "24 hours ago" \
  --date "$today" \
  --write \
  --output "docs/releases/daily/${today}.yml"
```

Use the most recent merged `dev` → `main` PR boundary established in Step 0. Re-read the refreshed daily Markdown companion and update the changelog summary if it materially changed.

```bash
latest_pr_date=$(gh pr list --base main --head dev --state merged --limit 1 --json mergedAt --jq '.[0].mergedAt // empty' | cut -dT -f1)
ls docs/releases/daily/*.md | while read -r file; do
  day=$(basename "$file" .md)
  [ -z "$latest_pr_date" ] || [ "$day" ">" "$latest_pr_date" ] && echo "$file"
done
```

Use the Markdown overview, grouped changes, and newsletter guidance to build the PR body. Keep unreleased/disabled-feature work out of public release/newsletter language, but include it in the PR when it is part of the code diff. Use companion YAML fields such as `sections`, `marketing_candidates`, and `unreleased_progress` only when deeper structured evidence is required.

### Step 5 — Feature Readiness Gate (CRITICAL)

Before drafting or creating the PR, run and read the deterministic feature readiness report:

```bash
latest_pr_date=$(gh pr list --base main --head dev --state merged --limit 1 --json mergedAt --jq '.[0].mergedAt // empty' | cut -dT -f1)
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

Reconcile this deterministic report with the five confirmed answers. If the report introduces a feature area that the questions did not cover, stop for a focused follow-up decision. Do not silently infer release readiness, draft the final PR body, or run `gh pr create` while any listed feature remains unclassified.

If the user says a feature is not ready, keep the code but deactivate access through the existing feature availability model:
- For platform features, remove any matching `feature_overrides.enabled` entry and/or add a `feature_overrides.disabled` entry in `backend/config/backend_config.yml`.
- For apps, skills, embeds, focus modes, or memory types, set `default_enabled: false` on the relevant `backend/apps/*/app.yml` entry.
- Re-run `python3 scripts/release_intelligence.py pr-readiness --from-ref origin/main --to-ref origin/dev --format markdown --stdout` and show the updated status before continuing.

Only continue after the user confirms that the remaining accessible features are ready for the PR.

### Step 6 — Analyze Remaining Commit Details

Use raw commit history only as supporting evidence or to fill gaps not covered by daily changelogs. Read the **full commit messages** (not just one-liners):

```bash
git log origin/main..origin/dev --format="%h %s%n%b"
```

Group commits into:
- **Features** (`feat:`) — new user-facing functionality
- **Bug Fixes** (`fix:`) — resolved issues
- **Improvements** (`refactor:`, `perf:`, `improve:`) — internal improvements
- **Other** (`docs:`, `chore:`, `build:`, `ci:`, `test:`) — maintenance

### Step 7 — One-Time Core Journeys Bootstrap (REMOVE AFTER FIRST PROMOTION)

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

### Step 8 — Write PR Description

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

## Future Release Preparation
- <briefly summarize included code for explicitly unreleased features without claiming availability>

## Other Changes
- <docs, chore, config items>
```

Only include sections that have content. Write for a developer audience — specific and clear.

### Step 9 — Create the PR

```bash
gh pr create --base main --head dev --title "<short descriptive title>" --body "$(cat <<'EOF'
<PR description>
EOF
)"
```

Present the PR URL to the user.

### Step 10 — Offer Draft Release

After PR creation, ask the user if they want a draft release prepared. If yes, use the `/create-release` skill. Tell the user:
- The PR URL
- That the draft release should be published **after** the PR is merged into `main`
