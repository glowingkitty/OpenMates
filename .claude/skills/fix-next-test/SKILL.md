---
name: fix-next-test
description: Fix one relevant failing test with bounded investigation and isolated CI verification.
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
useful evidence and keep the OpenMates Task status accurate. Always retrieve
web/CLI E2E recordings (use `result <id>` after a failed wait), run the receipt's
`codex_evidence_command`, and include all returned video links in the final chat,
including failure/retry recordings. Report missing capture/upload failures
explicitly; retry media delivery without rerunning passing tests. Shared policy:
`.claude/rules/testing.md` and `AGENTS.md`.
