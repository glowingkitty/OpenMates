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

Current phase: **Alpha** (v0.x.x-alpha). Check the latest tag:
```bash
gh release list --limit 3
```

Version bump decision:
| Change type | Bump | Example |
|-------------|------|---------|
| New features | Minor | v0.8.0-alpha → v0.9.0-alpha |
| Bug fixes only | Patch | v0.8.0-alpha → v0.8.1-alpha |
| Breaking changes | Major | v0.8.0-alpha → v1.0.0-alpha |

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
