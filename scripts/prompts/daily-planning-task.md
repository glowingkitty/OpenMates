You are planning the implementation of a Linear task. Do NOT make code changes — research and plan only.

## Task: {{LINEAR_ID}} — {{TASK_TITLE}}

**Status:** {{TASK_STATUS}} | **Labels:** {{TASK_LABELS}}

### Description

{{TASK_DESCRIPTION}}

### Recent Comments

{{TASK_COMMENTS}}

### Meeting Context

{{MEETING_CONTEXT}}

---

## Instructions

1. **Research the codebase** — use Glob, Grep, and Read to understand what's involved
2. **Identify files to modify** — list exact paths with line ranges
3. **Find existing patterns to reuse** — search for similar implementations, shared utilities, and conventions
4. **Assess complexity** — estimate the scope: how many files, what risks, any dependencies
5. **Write a structured plan** to `scripts/.tmp/daily-plan-{{LINEAR_ID}}.md`

## Plan Structure

Your plan file should include:

```markdown
# Plan: {{LINEAR_ID}} — {{TASK_TITLE}}

## Context
Why this change is needed and what it addresses.

## Approach
The implementation strategy in 3-5 sentences.

## Files to Modify
| File | Change | Why |
|------|--------|-----|

## Existing Code to Reuse
- Function/pattern X in path/to/file.ts:NN — does Y

## Risks & Dependencies
- Risk 1: ...
- Dependency: ...

## Verification
How to test the changes end-to-end.
```
