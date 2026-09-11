---
name: fix-tests
description: Fix the specified failing tests with bounded investigation and isolated CI verification.
user-invocable: true
---

Identify the requested failing spec and its first useful error. Reuse existing
CI results; load only the relevant test, implementation and contract. Obtain the
bound workspace before editing. Record the expected behavior, then fix the cause
and maintain relevant E2E assertions. Do not weaken coverage to get a pass.

Run focused local checks and the relevant isolated CI selection with
`ci_coordinator.py submit` and `wait <id>`. Do not create a separate debug campaign
or require coordinator approval for already-authorized work. Reassess after two
unsuccessful attempts with the same approach. Ask before unrelated infrastructure
repair, uncertain behavior changes, or expanding the original task. Preserve
useful evidence and keep the OpenMates Task status accurate. Shared policy:
`.claude/rules/testing.md` and `AGENTS.md`.
