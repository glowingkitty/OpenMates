---
description: Task planning, acceptance criteria, and debugging attempt limits
globs:
---

## Discovery And Clarifying Questions (Mandatory)

Before planning, debugging, or writing code, perform bounded discovery first:
related specs, architecture docs, source patterns, tests, and tracker context
when relevant. Do not ask users for facts the repository can answer.

**Protocol:** State verified facts, uncertainties, scope, and non-goals. Then ask
up to 5 clarifying questions, **one question per message**. Wait for the user's
response before asking the next question. Stop early if context is sufficiently
clear to proceed confidently.

**What to ask about** (adapt naturally to the task):
- Expected vs actual behavior, reproduction steps
- Scope boundaries — what's in, what's explicitly out
- User-facing vs internal change
- Which devices, browsers, or environments matter
- Existing attempts, recent changes, or known constraints
- Priority and urgency (affects approach choice)

**When to skip:** Trivial tasks with zero ambiguity (typo fix, single-line config change, explicit "just do it" from user).

**After questions are answered:** State your evidence-backed understanding in
2-3 sentences and get a final confirmation before starting work. Do not present
an inference as a verified repository fact.

## Pre-Planning Checks (Mandatory for Features & Integrations)

Before planning any new feature or provider implementation:
1. **Search tracker entries** — use GitHub Issues by default. Use `python3 scripts/linear.py` only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues. Check for existing tasks, prior research, or related work that should be linked.
2. **Search docs** — check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research or decisions on the topic.
3. Only proceed to clarifying questions and implementation after both checks are done.

## Acceptance Criteria Before Implementing

Every non-trivial task needs a checklist of verifiable acceptance criteria before implementation.

Use the risk tiers in `docs/contributing/guides/spec-driven-development.md`.
Ordinary Tier 1 work uses a concise issue or session contract; do not require a
full YAML evidence ledger solely because work is multi-file or user-facing.

For full-spec work, required acceptance criteria need explicit verification IDs,
user confirmation, waiver, or accepted blocker records. Define the test contract
before implementation; red evidence may be flexible, but record what happened
and why.

## Debugging Attempt Limit

**2 tries max** with the same approach. Minor variations count as the same approach.

On the 3rd attempt, stop repeating that approach, load the debugging guide, and
switch to a materially different method. Continue the approved task without
asking the user unless choosing the new method requires an unresolved product,
architecture, security, privacy, migration, or rollout decision.

## Two-Commit Rule for Refactors

When moving a function between modules, ALL call sites must be updated in the same commit. Never split a refactor across commits where intermediate states break imports.

## Unexpected Failures

If you hit an unrelated failure, isolate it and check `git log -5 -- <broken-file>`.
Do not modify unrelated work. Continue the current task when possible; ask the
user only when the unrelated failure makes the current task impossible and
requires their decision.
