---
name: opencode-workflow-review
description: Manually run a weekly or on-demand OpenCode agentic coding workflow quality review when workflow quality feels worse; produces reports only and hands selected fixes to implement-opencode-improvements.
user-invocable: true
argument-hint: "[hours, default 168]"
---

# OpenCode Workflow Review

Use this skill when the user asks for a weekly OpenCode workflow review, says
agentic coding quality has gotten worse, or wants workflow-improvement data from
recent OpenCode chats, commits, tests, and deterministic reports.

This skill is report-only. It may create or refresh gitignored local reports,
but it must not edit tracked files, commit, deploy, or implement a
recommendation. Use `implement-opencode-improvements` only after the user
explicitly selects recommendation IDs to implement.

## Default Interval

- Use 168 hours unless the user gives a different bounded interval.
- Clamp manual intervals to 1 through 168 hours because the underlying runner
  enforces that limit.
- Prefer `--dry-run-notify` for manual runs so Discord is not spammed while the
  local report is still written.

## Workflow

1. Run the manual Luna report. The hook treats this exact report-only,
   `--dry-run-notify` command as a bounded root control-plane operation, so an
   unmapped chat does not need a repository worktree:
   `python3 scripts/opencode_chat_improvement_review.py --hours 168 --dry-run-notify`
2. Read the generated report:
   `logs/nightly-reports/opencode-improvements/latest.md` and `latest.json`.
3. Gather supporting deterministic context where available:
   `python3 scripts/audit_opencode_output_quality.py --json --telemetry-days 7`
   `python3 scripts/audit_agent_tooling_parity.py --json`
   `python3 scripts/audit_opencode_spec_workflow.py`
   `python3 scripts/audit_opencode_automation_budget.py --all`
   `python3 scripts/tests.py status --json`
   `python3 scripts/tests.py triage --json`
4. Inspect recent local reports under `logs/nightly-reports/` for warning/error
   statuses, especially test, worktree, stale-code, and prior OpenCode
   improvement summaries.
5. Inspect recent workflow-tooling commits with a bounded git log, for example:
   `git log --oneline --since="7 days ago" -- .opencode .claude .agents scripts docs`
6. Compare the new recommendations with recent commits and existing safeguards.
   Mark items as likely open, likely addressed, duplicate, stale, or weak.
7. Return a concise report with the fresh report path, period, model, analysis
   session, strongest recommendations, supporting deterministic signals, and the
   exact `implement-opencode-improvements` invocation to use if the user wants
   selected fixes.

## Data Sources

- Local OpenCode SQLite transcript evidence collected by
  `scripts/opencode_chat_improvement_review.py`.
- Aggregate OpenCode tool-turn telemetry from `audit_opencode_output_quality.py`.
- Git commit and path-churn history for workflow files.
- GitHub Actions and local test state surfaced through `scripts/tests.py` and
  `test-results/` when available.
- Deterministic nightly reports under `logs/nightly-reports/`.
- Current skills, hooks, agents, OpenCode config, and parity audits.

## Output

Report findings first. Include:

- Fresh report path and timestamp.
- High-priority recommendations with evidence and target files.
- Which recommendations appear already addressed or duplicated by current code.
- Which deterministic guard, hook, skill, agent/subagent definition, or audit is
  the smallest next mechanism for each open item.
- Exact verification commands from the report.
- A clear handoff, for example:
  `Use implement-opencode-improvements REC-1 REC-2 from logs/nightly-reports/opencode-improvements/latest.json`.
