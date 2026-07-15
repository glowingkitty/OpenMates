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

Current phase: **Alpha**. Product UI shows short product lines such as `v0.15`; release tags and package/image artifacts use exact alpha-train versions such as `v0.15.0-alpha.0`, `v0.15.0-alpha.1`, and `v0.15.0-alpha.2`. Check the latest tag:
```bash
gh release list --limit 3
```

Version bump decision:
| Change type | Bump | Example |
|-------------|------|---------|
| New features | Minor product line | v0.15 → v0.16 |
| Bug fixes / repeated dev publishes | Alpha artifact | v0.15.0-alpha.0 → v0.15.0-alpha.1 |
| Breaking changes | Major | v0.15 → v1.0 |

### Step 2 — Write Release Notes

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
- That it should be **published after the PR is merged into `main`**
- To publish: `gh release edit <tag> --draft=false`
