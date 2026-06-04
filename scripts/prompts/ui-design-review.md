# UI Design Review — {{DATE}}

You are running a read-only UI design/code review for OpenMates.

## Operating Rules

- Do not edit files, commit, deploy, or start other sessions.
- The current codebase is the source of truth. You must inspect actual files under the paths below before making recommendations.
- Recent git commits are only prioritization context. Do not base findings only on commit messages.
- Return a concise prioritized report in this OpenCode chat.

## Context

- Date: {{DATE}}
- HEAD: {{GIT_SHA}}
- Recent context window: {{RECENT_SINCE}}

## Current Codebase Inventory

{{CODEBASE_INVENTORY}}

## Recent UI-Related Git Context

```text
{{RECENT_CHANGES}}
```

## Required Source Inspection

Inspect representative current files from each category before reporting:

- `frontend/packages/ui/src/components/**`
- `frontend/packages/ui/src/styles/**`
- `frontend/packages/ui/src/tokens/**`
- `frontend/apps/web_app/src/routes/**`
- `apple/OpenMates/Sources/**`
- `DESIGN.md`
- `.claude/rules/frontend.md`
- `.claude/rules/settings-ui.md`
- `.claude/rules/apple-ui.md`

## Review Goals

Find the top important changes we should consider to:

- Further unify web app and Apple app UI code.
- Reduce redundancy across components, styles, tokens, and Swift primitives.
- Improve readability and maintainability.
- Ensure design standards are followed consistently.
- Recommend hooks/lints only when repeated patterns in current code or recent commits justify automation.

## Checks

- Hardcoded colors, spacing, typography, radii, shadows, or icon names where tokens/components should be used.
- Similar UI patterns implemented multiple ways across Svelte, CSS, and Swift.
- Settings UI screens not using canonical settings elements.
- Swift UI files missing or drifting from web-source comments.
- Places where web tokens and generated Swift tokens are not being used consistently.
- Components with unclear boundaries, duplicated state logic, or avoidable complexity.
- Review feedback that could be prevented by a small hook, lint, or static audit.

## Output Format

```markdown
# UI Design Review — {{DATE}}

## Score: X/100

## Top Recommendations
| # | Priority | Area | Recommendation | Evidence | Suggested Fix | Hook/Lint? |
|---|----------|------|----------------|----------|---------------|------------|

## Cross-App Unification Opportunities
- ...

## Redundancy / Readability Improvements
- ...

## Design Standards Risks
- ...

## Hook Recommendations
- Only list hooks/lints that are justified by repeated current-code or recent-commit patterns.

## What Looks Good
- ...
```

Keep the report to the top 10 actionable recommendations. Include exact file paths and, where possible, line references.
