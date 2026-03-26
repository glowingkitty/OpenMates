---
phase: quick
plan: 260326-hxd
subsystem: infra
tags: [linear, webhooks, graphql, automation, claude-code, agent-pipeline]

requires:
  - phase: none
    provides: standalone research task
provides:
  - "Research document: Linear API capabilities, webhook integration design, two workflow proposals"
  - "Implementation sketches for both workflows (A: issue-report-enhanced, B: Linear-webhook-triggered)"
affects: [admin-sidecar, agent-trigger-watcher, settings-api]

tech-stack:
  added: []
  patterns: ["Linear GraphQL API via httpx (proposed)", "Webhook signature verification with HMAC-SHA256 (proposed)"]

key-files:
  created:
    - ".planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md"
  modified: []

key-decisions:
  - "Use Linear Personal API Key (not OAuth) stored in Vault for server-to-server integration"
  - "Use raw httpx + GraphQL queries instead of a Python SDK (no official Linear Python SDK exists)"
  - "Post investigation results as Linear comments (not description updates) for audit trail"
  - "Recommend implementing Workflow A first (enhance existing pipeline), then Workflow B (webhook-triggered)"

patterns-established:
  - "Linear integration pattern: thin GraphQL client in backend/shared/python_utils/"

requirements-completed: []

duration: 3min
completed: 2026-03-26
---

# Quick Task 260326-hxd: Linear Integration Research Summary

**Research document covering Linear API capabilities, existing agent pipeline architecture, and two proposed integration workflows (issue-report-enhanced and webhook-triggered) with implementation sketches**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-26T12:57:05Z
- **Completed:** 2026-03-26T13:00:25Z
- **Tasks:** 2
- **Files created:** 1

## Accomplishments

- Documented the complete existing issue-report-to-agent pipeline (4 stages: frontend form, API gateway, admin sidecar, host watcher)
- Researched Linear API capabilities: GraphQL API, webhooks, authentication, SDK/CLI options, custom fields/comments
- Designed two integration workflows with detailed implementation sketches and security considerations
- Provided phased recommendation: Workflow A first (1-2 sessions), then Workflow B (2-3 sessions)

## Task Commits

Each task was committed atomically:

1. **Task 1+2: Research Linear API + Write research document** - `963a4ce11` (docs)

**Plan metadata:** (pending)

## Files Created/Modified

- `.planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md` - 716-line research document with 5 sections covering current pipeline, Linear API, two workflow designs, implementation sketches, and recommendation

## Decisions Made

- **Personal API Key over OAuth:** Single-workspace internal integration does not need full OAuth complexity
- **httpx over SDK:** No official Python SDK exists; httpx is already a project dependency
- **Comments over description updates:** Preserves original issue description, creates audit trail for multiple investigations
- **Workflow A first:** Minimal infrastructure change (enhances existing pipeline), provides immediate tracking value

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - this is a research document only, no code changes.

## Next Steps

- Implement Workflow A (enhanced issue report -> Linear) in a future session
- Requires: Linear workspace setup, Vault secret for API key, ~50 lines of new Python code

---
*Quick task: 260326-hxd*
*Completed: 2026-03-26*
