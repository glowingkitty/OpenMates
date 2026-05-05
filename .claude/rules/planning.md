---
description: Task planning, acceptance criteria, and debugging attempt limits
globs:
---

## Proactive Clarifying Questions (Mandatory)

Before planning, debugging, or writing code — ask questions first. Do not assume context.

**Protocol:** Ask up to 5 clarifying questions, **one question per message**. Wait for the user's response before asking the next question. Stop early if context is sufficiently clear to proceed confidently.

**What to ask about** (adapt naturally to the task):
- Expected vs actual behavior, reproduction steps
- Scope boundaries — what's in, what's explicitly out
- User-facing vs internal change
- Which devices, browsers, or environments matter
- Existing attempts, recent changes, or known constraints
- Priority and urgency (affects approach choice)

**When to skip:** Trivial tasks with zero ambiguity (typo fix, single-line config change, explicit "just do it" from user).

**After questions are answered:** State your understanding in 2-3 sentences and get a final confirmation before starting work.

## Pre-Planning Checks (Mandatory for Features & Integrations)

Before planning any new feature or provider implementation:
1. **Search Linear** — call `mcp__linear__list_issues` with relevant keywords across Todo/Backlog/In Progress states. Check for existing tasks, prior research, or related work that should be linked.
2. **Search docs** — check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research or decisions on the topic.
3. Only proceed to clarifying questions and implementation after both checks are done.

## Acceptance Criteria Before Implementing

Every non-trivial task needs a checklist of verifiable acceptance criteria before implementation.

## Debugging Attempt Limit

**2 tries max** with the same approach. Minor variations count as the same approach.

On the 3rd attempt:
1. STOP
2. Run `sessions.py context --doc debugging` to re-read the full guide
3. State the **new approach** and why it differs
4. Ask the user for confirmation

## Two-Commit Rule for Refactors

When moving a function between modules, ALL call sites must be updated in the same commit. Never split a refactor across commits where intermediate states break imports.

## Unexpected Failures

If you hit a failure not related to your task: STOP. Check `git log -5 -- <broken-file>`. If your session didn't change it, report to user.
