---
name: create-release
description: Create a draft GitHub release with proper versioning and release notes
user-invocable: true
disable-model-invocation: true
argument-hint: "[tag]"
---

## Current Releases
!`gh release list --limit 5 2>/dev/null || echo "gh not available"`

## Open PRs to Main
!`gh pr list --state open --base main --json title,number 2>/dev/null || echo "none"`

## Instructions

**IMPORTANT: Only create a release when the user explicitly asks**, or as part of a PR workflow.

### Step 1 — Determine Version

Current phase: **`0.x`, under active development**. Product UI shows short product lines such as `v0.33`; release tags and package/image artifacts use exact prerelease-train versions such as `v0.33.0-alpha.0`, `v0.33.0-alpha.1`, and `v0.33.0-alpha.2`. Check the latest tag:
```bash
gh release list --limit 3
```

Version bump decision:
| Change type | Bump | Example |
|-------------|------|---------|
| New features | Minor product line | v0.33 → v0.33 |
| Bug fixes / repeated dev publishes | Prerelease artifact | v0.33.0-alpha.0 → v0.33.0-alpha.1 |
| Breaking changes | Major | v0.33 → v1.0 |

### Step 2 — Write Release Notes

Generate the contract trace for the commits included in the release and include
its implemented contract versions, verified assertions, and approved exceptions
in the release metadata/notes:

```bash
python3 scripts/specifications.py release-summary --git-range <previous-tag>..<target> --json
```

Write human-readable notes aimed at **users and contributors** (not a commit dump):

```markdown
## Overview
<1-3 sentence overview>

## New Features
- <feature descriptions>

## Bug Fixes
- <fix descriptions>

## Improvements
- <notable internal improvements affecting UX>
```

### Step 3 — Create Draft Pre-Release

```bash
gh release create <tag> \
  --target main \
  --title "<tag>: <short description>" \
  --notes "$(cat <<'EOF'
<release notes>
EOF
)" \
  --draft \
  --prerelease
```

### After Creation

Tell the user:
- The draft release tag and URL
- That it should be **published after the PR is merged into `main`**. The
  owner's merge is his go-ahead for production (owner, 23 Nov): once merged,
  update production with `/update-prod-server` and verify it; never ask again
- To publish: `gh release edit <tag> --draft=false`
