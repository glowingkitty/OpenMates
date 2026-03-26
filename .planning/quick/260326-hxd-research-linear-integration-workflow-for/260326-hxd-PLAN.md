---
phase: quick
plan: 260326-hxd
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "Research document covers existing issue-report-to-agent pipeline"
    - "Research document covers Linear API capabilities (webhooks, GraphQL, automations)"
    - "Research document proposes a concrete Linear-to-Claude-Code forwarding workflow"
  artifacts:
    - path: ".planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md"
      provides: "Complete research document with integration design"
      min_lines: 100
  key_links: []
---

<objective>
Research and design a Linear integration workflow for forwarding issues to Claude Code.

Purpose: Understand how the existing report-issue pipeline works, explore Linear API capabilities, and design a workflow where Linear entries trigger Claude Code investigation sessions — with the Linear task updated to contain the command to continue the chat.

Output: A research document (LINEAR-INTEGRATION-RESEARCH.md) with findings and proposed architecture.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

Existing issue-report-to-agent pipeline (already explored, key files below):

**Frontend submission:**
- `frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte` — form with "Submit to agent" toggle (admin-only)
- `frontend/packages/ui/src/stores/reportIssueStore.ts` — store with issue template/draft types
- Submits to `POST /v1/settings/issues` on the API gateway

**Backend processing:**
- `backend/core/api/app/routes/settings.py` — receives issue, stores in Directus, optionally calls admin sidecar
- `backend/admin_sidecar/main.py` — `POST /admin/claude-investigate` endpoint writes JSON trigger files to `scripts/.agent-triggers/`
- `scripts/prompts/admin-issue-investigation.md` — prompt template with placeholders (ISSUE_ID, ISSUE_TITLE, etc.)

**Host-side execution:**
- `scripts/agent-trigger-watcher.sh` — systemd service polling `scripts/.agent-triggers/` every 5s
- Reads JSON trigger, writes prompt to temp file, runs `claude -p` in plan mode with 15-min timeout
- Moves processed triggers to `done/` subdirectory

**Key insight:** There is NO existing Linear integration anywhere in the codebase. The current pipeline goes: Frontend form -> API -> Admin Sidecar -> JSON trigger file -> host watcher -> Claude CLI.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Research Linear API capabilities for webhook/automation integration</name>
  <files>none (web research only)</files>
  <action>
Research the following about Linear's API and automation capabilities:

1. **Linear GraphQL API** — How to create, update, and query issues programmatically. Authentication (API keys vs OAuth). Rate limits.

2. **Linear Webhooks** — What events are available (issue.created, issue.updated, label changes, status changes). Webhook payload structure. How to configure webhooks (UI vs API). Signature verification.

3. **Linear Automations** — Built-in automation rules (e.g., "when issue gets label X, trigger webhook"). Whether automations can call external URLs.

4. **Linear CLI / SDK** — Does Linear have a CLI? Node.js SDK? Python SDK? What's the easiest way to update an issue programmatically from a script.

5. **Linear issue metadata** — Can custom fields or comments be added? Can we store a "claude resume command" in the issue description or a comment?

Use WebFetch to check:
- https://developers.linear.app/docs (main API docs)
- https://developers.linear.app/docs/graphql/webhooks (webhook docs)

Document findings with specific API endpoints, payload examples, and authentication requirements.
  </action>
  <verify>Research notes captured with concrete API details (endpoints, auth, payload structure)</verify>
  <done>Linear API capabilities documented: GraphQL API, webhooks, automations, SDK options, and custom field/comment support</done>
</task>

<task type="auto">
  <name>Task 2: Write research document with integration design</name>
  <files>.planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md</files>
  <action>
Write a comprehensive research document covering:

**Section 1: Current Issue-Report-to-Agent Pipeline**
Document the existing flow discovered in codebase exploration:
- Frontend SettingsReportIssue.svelte -> POST /v1/settings/issues -> Admin Sidecar -> JSON trigger -> agent-trigger-watcher.sh -> Claude CLI
- Key files and their roles
- What data flows through the pipeline (issue_id, title, description, console logs, screenshots, etc.)
- The "Submit to agent" admin toggle mechanism

**Section 2: Linear API Capabilities**
Summarize findings from Task 1:
- GraphQL API (create/update issues, comments)
- Webhooks (events, payloads, configuration)
- Authentication options
- SDK/CLI availability

**Section 3: Proposed Integration Design**
Design TWO workflows:

**Workflow A: Issue Report -> Linear + Claude Code (enhanced current flow)**
1. When admin submits issue with "Submit to agent" toggle:
   - Current: writes JSON trigger -> Claude investigates
   - New: ALSO creates a Linear issue via API with issue details
   - After Claude session completes, update Linear issue with:
     - Session ID and resume command (`claude --resume SESSION_ID`)
     - Investigation summary/findings
     - Status update (e.g., move to "In Progress" or "Investigated")

**Workflow B: Linear -> Claude Code (new flow for planning phase)**
1. Create a specific Linear label or status (e.g., "claude-investigate")
2. Linear webhook fires when issue gets this label
3. Webhook hits an endpoint on admin sidecar (new route)
4. Sidecar writes trigger file (reusing existing mechanism)
5. agent-trigger-watcher picks it up and runs Claude
6. After completion, script updates Linear issue via API with resume command

**Section 4: Implementation Sketch**
For each workflow, outline:
- New code needed (endpoints, scripts, config)
- Linear workspace setup required (labels, webhooks, API key)
- Where the "resume command" gets written back to Linear
- How this fits the existing agent-trigger-watcher architecture
- Security considerations (webhook signature verification, API key storage in Vault)

**Section 5: Recommendation**
Which workflow to implement first, estimated effort, and phasing suggestion.
Recommend whether this should only trigger during planning phases or be available more broadly.

Format as a clean Markdown document suitable for architecture discussion.
  </action>
  <verify>
    <automated>test -f .planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md && wc -l .planning/quick/260326-hxd-research-linear-integration-workflow-for/LINEAR-INTEGRATION-RESEARCH.md | awk '{if ($1 >= 100) print "OK: "$1" lines"; else print "FAIL: only "$1" lines"}'</automated>
  </verify>
  <done>Research document exists with all 5 sections, covers both workflow designs, includes implementation sketches and recommendation</done>
</task>

</tasks>

<verification>
- LINEAR-INTEGRATION-RESEARCH.md exists and has 100+ lines
- Document covers existing pipeline, Linear API, and proposed integration design
- Both workflow directions are designed (issue-report->Linear and Linear->Claude)
</verification>

<success_criteria>
A research document that another developer (or Claude) could read and use to implement the Linear integration without further research. Covers API details, existing codebase architecture, and a concrete proposed design.
</success_criteria>

<output>
After completion, create `.planning/quick/260326-hxd-research-linear-integration-workflow-for/260326-hxd-SUMMARY.md`
</output>
