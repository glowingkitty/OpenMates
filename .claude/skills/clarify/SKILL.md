---
name: openmates:clarify
description: Run a structured 5-round Q&A to fully understand a bug or feature request before writing any code. Outputs a Task Brief with user flow, acceptance criteria, scope, edge cases, affected areas, and open questions. Use at the start of any non-trivial session.
user-invocable: true
argument-hint: "<bug description | feature idea | Linear issue ID>"
---

## Instructions

You are gathering everything needed to fully understand a task before writing a single line of code. Your job is to ask exactly **one question per round**, wait for the user's answer, then move to the next round. After 5 rounds you output a structured **Task Brief**.

---

### Before Round 1 — Detect Context

Parse the argument:

- If it looks like a Linear issue ID (`OPE-\d+`), call `mcp__linear__get_issue` + `mcp__linear__extract_images` + `mcp__linear__list_comments` to pre-load context before asking questions. Use what you learn to skip rounds whose answers are already clear.
- Otherwise treat the argument as a free-text description and note what's already known.

Identify the task type from context:
- **Bug** — something is broken or behaving incorrectly
- **Feature** — new capability or user-facing behavior to add
- **Refactor / improvement** — internal change with no new user-facing behavior

Announce the task type and start Round 1.

---

### Rounds 1–5 — Adaptive Questions

Ask the highest-value unknown question for each round. Adapt based on what you already know — if a round's topic was already answered, skip it and move to the next unknown. The default question for each round is below; adjust wording naturally.

| Round | Topic | Default question |
|-------|-------|-----------------|
| 1 | **Core goal / problem** | "What's the main behavior that's broken (or needs to be added)? Be as specific as possible — what exactly happens vs. what should happen." |
| 2 | **User flow** | "Walk me through the exact steps — what does the user do, in what order, and what happens at each step?" |
| 3 | **Scope and constraints** | "What's explicitly out of scope for this task? Any specific environments, browsers, user types, or technical constraints I should know about?" |
| 4 | **Context and root cause** | "Do you have a hypothesis about *why* this happens (for bugs), or know which files/components are likely involved? Any recent changes or related issues?" |
| 5 | **Acceptance criteria and done definition** | "How will you know this is finished? What's the ideal outcome — what should be true once this is done?" |

**Rules for asking questions:**
- One question per round. Never bundle two questions in one message.
- Keep the question short — one or two sentences.
- If the user's answer to an earlier round already covers a later round's topic, skip that round and ask the next unknown question instead. Still complete exactly 5 rounds total (or fewer if all topics are covered).
- Do not rephrase or repeat a question the user already answered.

---

### After Round 5 — Output the Task Brief

Synthesize everything into this structured markdown block. Omit sections that are genuinely not applicable (e.g. "Actual Behavior" for a feature), but include all others even if brief.

````markdown
## Task Brief

**Type:** Bug Fix | Feature | Refactor | Improvement

**Priority:** P1 Critical | P2 High | P3 Medium | P4 Low
*(infer from: data loss / broken for all users = P1; broken for some users = P2; degraded UX = P3; nice-to-have = P4)*

**User Impact:** [Who is affected, how many, and how severely]

---

### Problem Statement
[1–2 sentences. What is broken or missing, and why it matters.]

---

### Expected Behavior / User Flow
1. User does X
2. System responds with Y
3. ...

### Actual Behavior / User Flow *(bugs only)*
1. User does X
2. System does Z instead — [what's wrong]

---

### Scope
**In scope:**
- ...

**Out of scope:**
- ...

---

### Acceptance Criteria
- [ ] ...
- [ ] ...

---

### Edge Cases
- ...

---

### Affected Areas *(known or suspected)*
- **Files / components:** ...
- **Services / routes:** ...
- **Related issues / recent changes:** ...

---

### Non-Functional Requirements
- Performance: ...
- Security: ...
- Accessibility / i18n: ...
*(omit lines that are not applicable)*

---

### Testing Approach
[How to verify this is working — which existing spec to extend, or what a new spec would test]

---

### Open Questions
- [Anything still unresolved after 5 rounds]
````

---

### After the Brief

1. **If task type is Bug:** suggest running `/reproduce-first` as the next step.
2. **If task type is Feature:** suggest running `/new-task` to create a Linear issue from the brief, or remind the user to link an existing one.
3. **If a Linear issue was loaded in context:** offer to update its description with the Task Brief via `mcp__linear__save_issue`.

---

## Rules

- **Never write any code during this skill.** Clarification only.
- **One question per round.** Bundling questions defeats the purpose.
- **5 rounds maximum.** Do not extend. Anything unresolved lands in Open Questions.
- **Adapt, don't interrogate.** If the user's answers make a round's topic obvious, skip gracefully.
- **The brief is the deliverable.** It should be complete enough to hand to another engineer with no prior context.
- **Always infer priority.** Never leave it blank — make an explicit call and explain it in one phrase.
