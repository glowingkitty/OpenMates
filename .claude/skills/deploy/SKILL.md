---
name: deploy
description: Publish the scoped task diff to dev with repository checks and coordination.
user-invocable: true
---

Use `python3 scripts/sessions.py deploy --title "type: description"
--message "Why and relevant verification"`; pass `--session` for SSH/manual work.
The helper infers the current binding and scoped diff. Use `prepare-deploy` only
when the intended file scope needs inspection. Existing user authorization for
implementation includes scoped dev deployment; production and destructive
operations retain their specific approval boundaries.

Update relevant E2E coverage and run the checks appropriate to the change, subject
to explicit user waivers. Follow `.claude/rules/testing.md` for bounded debugging
and isolated CI. Do not impose extra Specification/Plan/video gates on a routine
fix; preserve explicitly required product-contract checks.

For frontend readiness use `sessions.py wait-deploy --commit <sha>` and wait on
the process, not a model-driven polling loop. Report the outcome, commit and
verification. End/cleanup is optional maintenance, not another completion gate.
Inspect focused failures and ask before expanding into unrelated repair work.
