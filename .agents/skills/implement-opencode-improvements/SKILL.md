---
name: implement-opencode-improvements
description: User-triggered workflow for revalidating and implementing selected recommendations from a saved OpenCode improvement report.
user-invocable: true
argument-hint: "[report path or recommendation IDs]"
---

# Implement OpenCode Improvements

Use this skill only after an explicit user request in an interactive chat. It is
never a cron target and must not infer authorization from the existence of a
report or Discord notification.

## Workflow

1. Start or reuse a feature session before any edit:
   `python3 scripts/sessions.py start --mode feature --task "Implement selected OpenCode improvement recommendations"`.
2. Load the requested report under
   `logs/nightly-reports/opencode-improvements/`, defaulting to `latest.json`.
   Reject paths outside that directory, malformed JSON, failed analysis status,
   or reports without recommendations.
3. Show the recommendation IDs, priorities, target files, expected benefits,
   and risks. Use IDs supplied by the user; otherwise ask the user to select the
   recommendations to implement. Report generation is not implementation consent.
4. Revalidate every selected recommendation against the current checkout:
   compare `subject_commit` with `HEAD`, reread each target, inspect relevant
   transcript evidence when available, search for duplicate safeguards, and
   consult current official documentation for external contracts.
5. Reject or narrow stale, weak, conflicting, unsafe, already-fixed, or
   overfitted recommendations. Explain every rejected item instead of silently
   substituting a different change.
6. Apply the smallest valid change. Follow canonical ownership:
   - Skills and subagents are authored under `.claude/` and synchronized with
     `python3 scripts/sync_agent_parity.py`.
   - Shared hooks are changed through the canonical Claude hook or
     `.codex/hooks/claude-hook-bridge.sh`, not duplicated per runtime.
   - OpenCode-only configuration belongs in `opencode.json` or `.opencode/` only
     when the behavior is genuinely runtime-specific.
   - Repeated objective failures should become focused tests, audits, or hooks
     instead of longer always-loaded instructions.
7. Escalate to an executable spec before implementation when a selected change
   affects security, privacy, auth, billing, sync, migrations, APIs, background
   jobs, cron behavior, or another Tier 2 boundary.
8. Run the narrow tests named in the report plus the applicable parity checks:
   `python3 scripts/sync_agent_parity.py --check`,
   `python3 scripts/audit_agent_tooling_parity.py`,
   `python3 scripts/audit_opencode_output_quality.py`, and
   `python3 scripts/audit_opencode_automation_budget.py --all`.
9. Review the diff and use the normal `scripts/sessions.py deploy` flow only
   after selected changes and verification pass. Never deploy rejected or
   unselected recommendations.

## Output

List the report path, selected IDs, implemented changes, rejected or deferred
items with reasons, changed files, exact checks, and deployed commit when one was
created.
