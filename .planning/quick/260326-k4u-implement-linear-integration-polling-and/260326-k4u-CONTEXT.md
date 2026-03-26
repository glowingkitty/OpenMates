# Quick Task 260326-k4u: Linear Integration Polling & Post-Investigation Updates - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Task Boundary

Implement a Linear-to-Claude-Code investigation pipeline:
- Poller checks Linear for issues with `claude-investigate` label every 30s
- Writes trigger files to existing `scripts/.agent-triggers/` mechanism
- After Claude investigation, posts resume command + GSD recommendation as Linear comment
- Auto-archives closed issues at 230 count to preserve 250 free-plan limit
- GSD-aware investigation prompt template

</domain>

<decisions>
## Implementation Decisions

### Polling Architecture
- Python script in repo (`scripts/linear-poller.py`)
- Runs via `docker exec api` — gets Vault secrets automatically
- Triggered by host cron job every 30s — only installed on dev server, NOT production
- Writes trigger JSON files to `scripts/.agent-triggers/` (bind-mounted volume)
- Host-side `agent-trigger-watcher.sh` picks up triggers as usual

### Linear API Authentication
- LINEAR_API_KEY stored in `.env` file (auto-imported to Vault on server start)
- Poller accesses it via the `api` container's environment (Vault-injected)
- No separate auth mechanism needed — reuses existing secret pipeline

### Investigation Prompt Scope
- Include: title, description, priority, labels
- Exclude: comments, assignee, linked issues (keep it focused)
- Prompt template recommends a GSD command but does NOT execute it

### Issue Archival
- At 230 issues, export oldest closed/investigated issues to `.planning/linear-archive.md`
- Close + delete archived issues from Linear
- Daily sweep (not every 30s — unnecessary frequency)

### Claude's Discretion
- Exact GSD command recommendation logic (which command for which situation)
- Archive file format details
- Error handling / retry logic for Linear API failures

</decisions>

<specifics>
## Specific Ideas

- Poller script: `scripts/linear-poller.py`
- Post-investigation script: `scripts/linear-update-issue.py`
- Archive script: `scripts/linear-archive-issues.py`
- Investigation prompt: `scripts/prompts/linear-issue-investigation.md`
- Cron setup: `scripts/linear-cron-setup.sh` (installer for dev server only)
- Trigger JSON includes `linear_issue_id` field so watcher can pass it to update script
- `agent-trigger-watcher.sh` needs minor modification to call update script after Claude finishes

</specifics>

<canonical_refs>
## Canonical References

- Existing research: `.planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md`
- Current trigger watcher: `scripts/agent-trigger-watcher.sh`
- Admin sidecar investigate endpoint: `backend/admin_sidecar/main.py` (lines 884-1047)
- Settings issue submission: `backend/core/api/app/routes/settings.py` (lines 2385-2955)
- Investigation prompt template: `scripts/prompts/admin-issue-investigation.md`

</canonical_refs>
