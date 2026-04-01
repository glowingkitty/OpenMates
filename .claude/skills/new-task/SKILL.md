---
name: openmates:new-task
description: Create a well-structured Linear task with smart field suggestions based on input
user-invocable: true
argument-hint: "<description of task>"
---

## Instructions

You are creating a new Linear task for the OpenMates project. Your job is to take the user's raw input (which may be a brain dump, a bug report, a feature idea, or a vague note) and turn it into a well-structured task with all fields properly filled.

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
7. **Milestone**: Suggest v0.8.1 alpha (stability/UI fixes) or v0.9.0 alpha (features) based on scope

### Step 2: Present the Suggested Task

Show the user what will be created:

```
## New Task Preview

**Title:** Fix broken reminder creation UI
**Type:** Bug Fix
**Priority:** High (2)
**Labels:** Bug, UI
**Project:** Web App
**Milestone:** v0.8.1 alpha

### Description
The create reminder UI is broken — [expanded description based on user input].

### Acceptance Criteria
- [ ] Reminder creation works reliably
- [ ] UI matches Figma design
```

### Step 3: Ask for Confirmation

Use `AskUserQuestion`:
- **Create** — create the task as shown
- **Edit** — let the user adjust fields before creating

### Step 4: Create the Task

Call `mcp__linear__save_issue` with all fields:
```
title, team: "OpenMates", description, priority, labels, project, milestone
```

If the task type is "Idea", automatically add the `Idea` label and set priority to None (0).

### Step 5: Report

Show the created task with its identifier and URL:
```
Created: OPE-XXX — "Title"
URL: https://linear.app/openmates/issue/OPE-XXX/...
```

---

## Smart Suggestions

### Title Cleanup Rules
- `"Fix: Fix Show More chats: pagination broken"` → `"Fix: Show More chats pagination broken"`
- `"Feat: Feat: test auto-create"` → `"Feat: test auto-create linear issue"`
- `"fix it"` → Ask user to clarify
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
```

**Feature:**
```markdown
## Goal
[What this feature does]

## Design
[UI/UX considerations, Figma links if mentioned]

## Acceptance Criteria
- [ ] ...
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
