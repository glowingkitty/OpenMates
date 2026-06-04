# Apple Code Parity Review — {{DATE}}

You are running a read-only Apple/web parity review for OpenMates.

## Operating Rules

- Do not edit files, commit, deploy, or start other sessions.
- The current web and Apple codebases are the source of truth. You must inspect actual files before making recommendations.
- Recent web commits are prioritization context only; verify every finding against current source.
- This review must be Linux-safe. Do not require Xcode, simulator, or macOS-only commands.

## Context

- Date: {{DATE}}
- HEAD: {{GIT_SHA}}
- Recent context window: {{RECENT_SINCE}}

## Current Codebase Inventory

{{CODEBASE_INVENTORY}}

## Recent Web/Apple Git Context

```text
{{RECENT_CHANGES}}
```

## Required Source Inspection

Inspect current files from:

- `apple/SVELTE_SWIFT_COUNTERPARTS.md`
- `scripts/apple_parity_audit.py`
- `test-results/apple-parity-inventory.json` if present
- `.claude/rules/apple-ui.md`
- `frontend/packages/ui/src/components/**`
- `frontend/packages/ui/src/styles/**`
- `frontend/packages/ui/src/tokens/**`
- `apple/OpenMates/Sources/**`

## Review Goals

Find the current top Apple parity gaps and recommend changes based on the actual source state.

Prioritize recent web UI changes that likely require Apple review, but also inspect broader current parity state.

## Checks

- Web components/styles/tokens changed recently without corresponding Swift review.
- Missing or stale mappings in `apple/SVELTE_SWIFT_COUNTERPARTS.md`.
- Swift UI files with visual output missing required web-source comment blocks.
- Hardcoded Swift colors, spacing, typography, or strings that violate Apple UI rules.
- Missing generated token usage.
- Missing Apple accessibility identifiers for important web `data-testid`s.
- Embeds or chat UI parity drift between Svelte/CSS and Swift.
- Apple parity inventory warnings and missing counterpart paths.

## Output Format

```markdown
# Apple Parity Review — {{DATE}}

## Score: X/100

## Top Parity Gaps
| # | Priority | Web Source | Apple Source | Gap | Evidence | Suggested Fix |
|---|----------|------------|--------------|-----|----------|---------------|

## Recent Web Changes Needing Apple Follow-Up
- ...

## Inventory / Mapping Issues
- ...

## Token & Design Rule Violations
- ...

## What Looks Good
- ...
```

Keep the report to the top 10 actionable parity recommendations. Include exact file paths and, where possible, line references.
