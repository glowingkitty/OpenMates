---
name: openmates:new-task
description: Create an OpenMates execution Task for Codex; use GitHub or Linear for explicitly requested tracker issues
user-invocable: true
argument-hint: "<description of task>"
---

## Codex execution Tasks

For Codex work, OpenMates Tasks is the execution source of truth. Use the injected
Project cache first and the globally installed CLI for scoped detail or mutations.
Use the personal dev-testing account and existing OpenMates Project
`96033196-e4b1-431e-b773-ba221e952fed`. Do not create a GitHub or Linear issue merely
to track a Codex assignment. Those trackers remain for explicitly requested issues
or existing issue references; the tracker-specific procedure below applies there.

For a new engineering Task, preserve the user's concrete goal, give it a concise
title and description, and create/link it in one mutation:

```sh
openmates tasks create --title "Repair header navigation" \
  --description "Keep the header usable with keyboard and on narrow screens." \
  --external-chat "codex:$CODEX_THREAD_ID" \
  --project 96033196-e4b1-431e-b773-ba221e952fed --json
```

An orchestrator may create unlinked assignments by omitting `--external-chat`.
The eventual worker claims its own Task. Reuse an existing matching Task instead
of duplicating it; split complex work into several concrete Tasks and dependencies.
Keep existing status/blocker fields and meaningful activity. A pending mutation
is not acknowledged ownership. Finish this Codex path here; do not run the
GitHub/Linear creation steps below unless that tracker was actually requested.

## Instructions

You are creating a new task for the OpenMates project. Your job is to take the user's raw input (which may be a brain dump, a bug report, a feature idea, or a vague note) and turn it into a well-structured task with all fields properly filled.

Use GitHub Issues by default. Use Linear only for programmatically stored/recorded product issues, marketing work, sensitive/private work, or when the user explicitly asks for Linear.

### Step 1: Parse the Input

Analyze the user's input and determine:

1. **Type**: Bug, Feature, Improvement, Research, Idea, DevOps, or Testing
2. **Title**: Clean, concise title (max 80 chars). Rules:
   - Remove prefix stacking ("Fix: Fix:" → "Fix:")
   - Start with a verb for actionable tasks ("Fix", "Add", "Implement", "Research", "Investigate")
   - For ideas/questions, use plain language without prefixes
3. **Description**: Expand the input into a structured description
4. **Priority**: Suggest based on type and keywords:
   - Bug with "broken", "crash", "fails" → High (2)
   - Security issue → Urgent (1)
   - Feature request → Medium (3)
   - Nice-to-have, idea → Low (4) or None (0)
   - Research → Medium (3)
5. **Labels**: Suggest from existing labels:
   - `Bug`, `Feature`, `Improvement`, `Idea`, `Security`, `Performance`, `Encryption`
   - `UI`, `Backend`, `DevOps`, `testing`, `docs`, `marketing`, `payment`
   - `cronjob`, `user-feedback`, `SEO`
6. **Project**: Suggest Web App or CLI based on content
7. **Milestone**: Suggest the current product line for ongoing work (for example `v0.18`) or the next minor product line for larger features (for example `v0.18`). Alpha artifact numbers such as `0.18.0-alpha.1` are package revisions, not user-facing milestones.
8. **Spec size**: Decide `none`, `inline`, or `full` using `docs/contributing/guides/spec-driven-development.md`

### Step 2: Present the Suggested Task

Show the user what will be created:

```
## New Task Preview

**Title:** Fix broken reminder creation UI
**Type:** Bug Fix
**Priority:** High (2)
**Labels:** Bug, UI
**Project:** Web App
**Milestone:** v0.18

### Description
The create reminder UI is broken — [expanded description based on user input].

### Acceptance Criteria
- [ ] Reminder creation works reliably
- [ ] UI matches Figma design

### Example Scenarios
- S-1: Given ..., when ..., then ...

### Spec Readiness
- Spec size: inline | full | none
- Full Plan path: docs/plans/<slug>/plan.yml (if needed)
```

### Step 3: Ask for Confirmation

Use `AskUserQuestion`:
- **Create** — create the task as shown
- **Edit** — let the user adjust fields before creating

### Step 4: Create the Task

For GitHub-default tasks, call `github_issue_write` with a concise title, structured body, labels, and assignees only when the user requested them.

If the task needs a full Plan, include a `Plan Readiness` section in the issue
body and tell the user to run `create-plan` before implementation. Do not
implement full-Plan work directly from a bare issue.

For Linear-only tasks, use `python3 scripts/linear.py create --team OPE --title "..." --description "..."` and add state/priority/labels when needed. Do not use Linear MCP tools.

If the task type is "Idea", automatically add the `Idea` label and set priority to None (0).

### Step 5: Report

Show the created task with its identifier and URL:
```
Created: #123 — "Title"
URL: https://github.com/glowingkitty/OpenMates/issues/123
```

For Linear-only tasks, show the `OPE-XXX` identifier returned by `scripts/linear.py`.

---

## Smart Suggestions

### Title Cleanup Rules
- `"Fix: Fix Show More chats: pagination broken"` → `"Fix: Show More chats pagination broken"`
- `"Feat: Feat: test auto-create"` → `"Feat: test auto-create linear issue"`
- `"fix it"` → Ask user to clarify. Every clarifying question must include
  `Recommendation:` with the evidence-based preferred answer and rationale plus
  `Examples:` with task-specific options or outcomes; if uncertain, recommend
  the safest reversible default and state the uncertainty.
- Questions → Keep as-is but add `Idea` label if no clear action

### Description Templates

**Bug:**
```markdown
## Problem
[What's broken]

## Expected Behavior
[What should happen]

## Steps to Reproduce
1. ...

## Related
- Files: ...
- Commits: ...

## Spec Readiness
- Spec size: none | inline | full
- Examples: S-1, S-2
- Verification: existing or proposed test files
```

**Feature:**
```markdown
## Goal
[What this feature does]

## Design
[UI/UX considerations, Figma links if mentioned]

## Acceptance Criteria
- [ ] ...

## Example Scenarios
- S-1: Given ..., when ..., then ...

## Spec Readiness
- Spec size: none | inline | full
- Full spec required before implementation: yes/no
```

**Idea:**
```markdown
## Concept
[The idea]

## Why
[Why this could be valuable]

## Open Questions
- ...
```

**Research:**
```markdown
## Question
[What we need to learn]

## Context
[Why this matters now]

## Deliverables
- [ ] Summary document / findings
- [ ] Recommendation
```

---

## Rules

- **Always show the task before creating it** — never create silently
- **Always include a description** — even if the user provided a one-liner, expand it into at least 2-3 sentences
- **Always suggest labels** — at minimum one type label (Bug/Feature/Improvement/Idea)
- **Detect duplicates** — before creating, search existing open tasks for similar titles. If a match is found, show it and ask if this is a duplicate
- **Title max 80 chars** — truncate and move detail to description if needed
- **No empty fields** — every task must have: title, description, at least 1 label, priority
- **Idea detection** — if the input is a question, starts with "maybe", "what if", "consider", "should we", add the `Idea` label automatically
