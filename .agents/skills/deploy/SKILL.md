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
and isolated CI. Always download, upload and link existing web/CLI E2E recordings
in the final chat response as required by the testing rule, including failures
and retries. Run the receipt's `codex_evidence_command`; report missing capture or
upload failure explicitly. Extra edited/captioned proof production follows the
accepted scope. Preserve explicitly required product-contract checks.

For frontend readiness use `sessions.py wait-deploy --commit <sha>` and wait on
the process, not a model-driven polling loop. Report the outcome, commit and
verification. End/cleanup is optional maintenance, not another completion gate.
Inspect focused failures and ask before expanding into unrelated repair work.
