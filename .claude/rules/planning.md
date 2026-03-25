---
description: Task planning, acceptance criteria, and debugging attempt limits
globs:
---

## State Understanding Before Acting

Before planning or writing code, state your interpretation of the task and wait for confirmation:
- For bugs: expected vs actual behavior, which system is responsible
- For features: what it does, how it fits the architecture

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
