# Linear Integration Research: Issue-to-Claude-Code Workflow

> Research document for integrating Linear issue tracking with the existing
> Claude Code agent investigation pipeline. Covers the current architecture,
> Linear API capabilities, and two proposed integration workflows.

**Date:** 2026-03-26
**Author:** GSD executor (research task 260326-hxd)
**Status:** Proposal / ready for architecture discussion

---

## Table of Contents

1. [Current Issue-Report-to-Agent Pipeline](#1-current-issue-report-to-agent-pipeline)
2. [Linear API Capabilities](#2-linear-api-capabilities)
3. [Proposed Integration Design](#3-proposed-integration-design)
4. [Implementation Sketch](#4-implementation-sketch)
5. [Recommendation](#5-recommendation)

---

## 1. Current Issue-Report-to-Agent Pipeline

### Overview

OpenMates has an existing pipeline that lets the admin submit an issue report
from the web app and have it automatically investigated by a Claude Code session
running on the host. The pipeline has four stages:

```
Frontend Form -> API Gateway -> Admin Sidecar -> Host Watcher -> Claude CLI
```

### Stage 1: Frontend Submission

**File:** `frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte`

The settings panel includes a "Report Issue" form with:

- **Short description** (required, multi-line)
- **Structured fields** (optional): "What were you doing?", "Expected behaviour", "Actual behaviour"
- **Share chat toggle** -- attaches the active chat/embed URL
- **Submit to agent toggle** (admin-only) -- defaults to ON, triggers Claude investigation
- **Screenshot** -- captured via DOM element picker, uploaded to S3
- **Console logs** -- last ~100 lines from the `logCollector` service
- **UI action history** -- last 20 interactions from `userActionTracker`

The form POSTs to `POST /v1/settings/issues` on the API gateway.

**Store:** `frontend/packages/ui/src/stores/reportIssueStore.ts` -- holds template/draft state so the form survives settings panel unmount/remount cycles.

### Stage 2: API Gateway Processing

**File:** `backend/core/api/app/routes/settings.py` (lines ~2385-2950)

The endpoint:
1. Validates the issue payload (Pydantic model with `submit_to_agent: bool` field)
2. Creates an issue record in Directus CMS
3. If admin AND `submit_to_agent` is true, calls `_trigger_agent_issue_investigation()`
4. That function POSTs to the admin sidecar at `{CORE_SIDECAR_URL}/admin/claude-investigate`

**Data sent to sidecar:**
- `issue_id` (UUID from Directus)
- `issue_title` (sanitised short description)
- `issue_description` (structured description)
- `chat_or_embed_url` (optional share link)
- `console_logs` (optional)
- `action_history` (optional)
- `screenshot_url` (optional pre-signed S3 URL)
- `environment` ("production" or "development")
- `domain` (instance URL)

### Stage 3: Admin Sidecar

**File:** `backend/admin_sidecar/main.py` (lines ~947-1043)

Endpoint: `POST /admin/claude-investigate`

The sidecar does NOT run Claude itself (it runs in Docker without the Claude binary). Instead it:
1. Reads the prompt template from `scripts/prompts/admin-issue-investigation.md`
2. Replaces `{{PLACEHOLDER}}` tokens with issue data
3. Writes a JSON trigger file to `<GIT_WORK_DIR>/scripts/.agent-triggers/<issue_id>.json`
4. Returns 202 Accepted immediately

The trigger JSON contains: `issue_id`, `session_title`, `prompt` (the fully rendered investigation prompt).

**Prompt template:** `scripts/prompts/admin-issue-investigation.md` -- instructs Claude to understand the problem, locate code, diagnose root cause, propose and optionally implement a fix.

### Stage 4: Host-Side Agent Trigger Watcher

**File:** `scripts/agent-trigger-watcher.sh`

A systemd user service that:
1. Polls `scripts/.agent-triggers/` every 5 seconds for `*.json` files
2. Parses each trigger file (extracts `issue_id`, `session_title`, `prompt`)
3. Writes the prompt to a temp file (avoids MAX_ARG_STRLEN limit)
4. Runs `claude -p` in plan mode with `--model claude-sonnet-4-6`, `--permission-mode plan`, 15-min timeout
5. Extracts the `session_id` from the JSON output
6. Moves the trigger file to `done/` subdirectory
7. Logs everything to `logs/agent-investigations.log`

### Key Observations

- **No Linear integration exists** anywhere in the codebase currently.
- The pipeline is **one-directional**: issue goes in, Claude investigates, but results are only in Claude's session log. There is no automatic feedback loop back to the issue record.
- The `session_id` is logged but not written back to Directus or anywhere the admin can easily find it.
- The architecture is **extensible**: the trigger file mechanism is a clean seam for adding new trigger sources (like Linear webhooks).

---

## 2. Linear API Capabilities

### 2.1 GraphQL API

Linear exposes a single GraphQL endpoint at:

```
POST https://api.linear.app/graphql
```

**Key operations for this integration:**

```graphql
# Create an issue
mutation {
  issueCreate(input: {
    title: "Bug: decryption fails on cross-device sync"
    description: "Structured description here..."
    teamId: "TEAM_UUID"
    labelIds: ["LABEL_UUID"]
    priority: 1  # 0=none, 1=urgent, 2=high, 3=medium, 4=low
  }) {
    success
    issue { id identifier url }
  }
}

# Update an issue (e.g., add investigation results)
mutation {
  issueUpdate(id: "ISSUE_UUID", input: {
    description: "Updated description with Claude findings..."
    stateId: "STATE_UUID"  # move to "In Progress" or "Investigated"
  }) {
    success
    issue { id identifier }
  }
}

# Add a comment to an issue
mutation {
  commentCreate(input: {
    issueId: "ISSUE_UUID"
    body: "## Claude Investigation Results\n\nSession ID: `abc123`\nResume: `claude --resume abc123`\n\n..."
  }) {
    success
    comment { id }
  }
}

# Query issues by label
query {
  issues(filter: {
    labels: { name: { eq: "claude-investigate" } }
    state: { name: { eq: "Triage" } }
  }) {
    nodes { id identifier title description url }
  }
}
```

**Rate limits:**
- 1,500 requests per hour per API key (per workspace)
- Complexity-based limiting for large queries (max 10,000 complexity points)
- Rate limit headers: `X-RateLimit-Requests-Remaining`, `X-RateLimit-Requests-Reset`

### 2.2 Authentication

**Option A: Personal API Key (recommended for this use case)**
- Generated at: Settings > Account > API > Personal API keys
- Passed as: `Authorization: Bearer lin_api_XXXXXXXX`
- Scoped to the user's permissions in the workspace
- Best for: server-to-server integrations where a single admin controls the pipeline

**Option B: OAuth 2.0 Application**
- Full OAuth flow with client_id/client_secret
- Scoped access tokens with granular permissions
- Best for: multi-tenant apps or public integrations
- Overkill for a single-workspace internal integration

**Recommendation:** Use a Personal API Key stored in HashiCorp Vault (consistent with existing secret management).

### 2.3 Webhooks

Linear webhooks fire HTTP POST requests when resources change.

**Configuration:** Settings > API > Webhooks (or via GraphQL API)

```graphql
mutation {
  webhookCreate(input: {
    url: "https://<PLACEHOLDER>/admin/linear-webhook"
    teamId: "TEAM_UUID"       # optional: scope to one team
    resourceTypes: ["Issue"]   # Issue, Comment, Project, Cycle, etc.
    label: "Claude Code Trigger"
    enabled: true
  }) {
    success
    webhook { id enabled }
  }
}
```

**Webhook payload structure (issue updated):**

```json
{
  "action": "update",
  "type": "Issue",
  "createdAt": "2026-03-26T12:00:00.000Z",
  "data": {
    "id": "issue-uuid",
    "identifier": "ENG-123",
    "title": "Bug: decryption fails",
    "description": "...",
    "priority": 1,
    "url": "https://linear.app/workspace/issue/ENG-123",
    "state": { "id": "...", "name": "Triage", "type": "triage" },
    "labels": [
      { "id": "...", "name": "claude-investigate" }
    ],
    "team": { "id": "...", "key": "ENG" },
    "assignee": null
  },
  "updatedFrom": {
    "labelIds": ["previous-label-id"],
    "updatedAt": "2026-03-26T11:59:00.000Z"
  },
  "url": "https://linear.app/workspace/issue/ENG-123",
  "organizationId": "org-uuid"
}
```

**Key webhook events for this integration:**
- `Issue` with `action: "create"` -- new issue created
- `Issue` with `action: "update"` -- issue updated (label added, status changed)
- The `updatedFrom` field shows what changed, useful for detecting label additions

**Signature verification:**
- Linear signs webhooks with a shared secret
- Header: `Linear-Signature` (HMAC-SHA256 of the raw request body)
- The signing secret is shown once when creating the webhook
- Verification: `hmac_sha256(signing_secret, raw_body) == signature_header`

### 2.4 Built-in Automations

Linear has built-in workflow automations (Settings > Teams > Workflows):

- **Auto-assign** on status change
- **Auto-close** after merge
- **Auto-archive** completed issues
- **Auto-add label** based on conditions
- **SLA alerts** based on priority

These automations **cannot call external URLs** directly. They only trigger internal Linear state changes. For external triggers, webhooks are the correct mechanism.

However, automations can be combined with webhooks:
1. Create an automation: "When issue status changes to X, add label `claude-investigate`"
2. Webhook fires on the label addition
3. This gives us a two-step trigger: manual status change -> automatic label -> webhook

### 2.5 SDK and CLI Options

**Node.js SDK (`@linear/sdk`):**
```bash
npm install @linear/sdk
```
```typescript
import { LinearClient } from "@linear/sdk";
const client = new LinearClient({ apiKey: "lin_api_XXXXXXXX" });

// Create issue
const issue = await client.createIssue({
  teamId: "...", title: "...", description: "..."
});

// Update issue
await client.updateIssue("issue-id", { description: "Updated..." });

// Create comment
await client.createComment({ issueId: "...", body: "..." });
```

**Python (no official SDK):**
- No official Linear Python SDK exists
- Use `httpx` (already a project dependency) with raw GraphQL queries
- Alternatively, `sgqlc` or `gql` libraries for typed GraphQL
- **Recommendation:** Use raw `httpx` + GraphQL strings -- keeps dependencies minimal and aligns with existing codebase patterns

**Linear CLI:**
- Linear does not provide an official CLI tool
- Community tools exist but are not maintained
- For scripting: use the GraphQL API directly via `curl` or `httpx`

### 2.6 Issue Metadata and Custom Fields

**Comments:** Full Markdown support. Can be created/updated/deleted via API. Ideal for posting investigation results.

**Custom fields:** Linear supports custom properties (text, number, select, date) on issues. Could be used for:
- `claude_session_id` (text) -- store the session ID
- `investigation_status` (select) -- "pending", "in-progress", "complete"

**Labels:** Simple string labels, can be created/queried via API. Ideal for triggering workflows (e.g., `claude-investigate`).

**Description:** Markdown-formatted, no length limit. Can be appended to programmatically. Could store the resume command here.

**Recommendation:** Use **comments** for investigation results (keeps original issue description clean) and **labels** for triggering workflows.

---

## 3. Proposed Integration Design

### Workflow A: Issue Report -> Linear + Claude Code (Enhanced Current Flow)

**Scenario:** Admin submits an issue from the OpenMates web app. The existing Claude investigation runs AND a Linear issue is created for tracking.

```
                                    +---> Linear API: Create Issue
                                    |     (with labels, priority)
Admin submits       API Gateway     |
issue report   -->  settings.py  ---+
                                    |
                                    +---> Admin Sidecar: Write trigger
                                          (existing flow, unchanged)
                                          |
                                          v
                                    Host Watcher: Run Claude
                                          |
                                          v
                                    On completion:
                                      1. Update Linear issue comment
                                         (session_id, resume cmd, findings)
                                      2. Update Linear issue status
                                         ("Investigated" or "In Progress")
```

**Data flow:**

1. Admin toggles "Submit to agent" ON and submits issue report
2. `settings.py` does everything it does today PLUS:
   - Calls Linear GraphQL API to create an issue in the configured team
   - Stores the Linear `issue_id` and `identifier` (e.g., "ENG-123") in the Directus issue record
3. Sidecar writes trigger file as before, but includes `linear_issue_id` in the JSON
4. `agent-trigger-watcher.sh` runs Claude as before
5. **NEW:** After Claude session completes, the watcher script:
   - Calls Linear API to add a comment with investigation results
   - Updates the issue status to "Investigated"
   - Includes the `claude --resume SESSION_ID` command in the comment

**Linear issue created with:**
- Title: issue short description
- Description: structured description + console logs + screenshot link
- Labels: `bug-report`, `claude-investigated` (after completion)
- Priority: mapped from issue severity (if available)

### Workflow B: Linear -> Claude Code (New Reverse Flow)

**Scenario:** An issue is created or triaged in Linear (manually or by another tool). Adding a specific label triggers Claude Code investigation.

```
Linear Issue        Linear Webhook       Admin Sidecar       Host Watcher
(label added:  -->  POST to sidecar  --> Write trigger   --> Run Claude
 "claude-           /admin/linear-       .json file           |
  investigate")     webhook                                   v
                                                         On completion:
                                                           Linear API:
                                                           - Add comment
                                                           - Update status
                                                           - Remove trigger label
```

**Trigger mechanism:**

1. Admin (or automation) adds label `claude-investigate` to a Linear issue
2. Linear webhook fires to `POST /admin/linear-webhook` on the admin sidecar
3. Sidecar endpoint:
   - Verifies webhook signature (HMAC-SHA256)
   - Checks that the `claude-investigate` label was just added (compare `data.labels` with `updatedFrom.labelIds`)
   - Extracts issue title, description, URL, and any attachments
   - Renders the investigation prompt (reuses existing template with minor adaptations)
   - Writes a JSON trigger file to `scripts/.agent-triggers/`
   - Returns 200 OK
4. `agent-trigger-watcher.sh` picks up the trigger and runs Claude
5. After completion, the watcher script:
   - Adds a comment to the Linear issue with findings and resume command
   - Changes issue status from "Triage" to "In Progress" or a custom "Investigated" state
   - Removes the `claude-investigate` label (prevents re-triggering)

**Webhook filtering logic (sidecar):**

```python
def should_trigger_investigation(payload: dict) -> bool:
    """Determine if this webhook should trigger a Claude investigation."""
    if payload.get("action") != "update":
        return False

    labels = payload.get("data", {}).get("labels", [])
    label_names = {l["name"] for l in labels}

    if "claude-investigate" not in label_names:
        return False

    # Check that the label was JUST added (not already present)
    previous_label_ids = set(
        payload.get("updatedFrom", {}).get("labelIds", [])
    )
    current_label_ids = {l["id"] for l in labels}
    new_labels = current_label_ids - previous_label_ids

    # At least one new label was added and it includes our trigger
    return len(new_labels) > 0
```

---

## 4. Implementation Sketch

### 4.1 Workflow A Implementation

**New code needed:**

| Component | File | Changes |
|-----------|------|---------|
| Linear API client | `backend/shared/python_utils/linear_client.py` | New file: thin GraphQL wrapper using `httpx` |
| Issue creation | `backend/core/api/app/routes/settings.py` | Add `_create_linear_issue()` call after Directus insert |
| Trigger file enhancement | `backend/admin_sidecar/main.py` | Pass `linear_issue_id` into trigger JSON |
| Post-investigation update | `scripts/agent-trigger-watcher.sh` | After Claude completes, call Linear API via `curl` or a small Python script |
| Vault secret | Vault config | Store `LINEAR_API_KEY` in Vault |

**Linear workspace setup:**
- Create a team (or use existing) for bug tracking
- Create labels: `bug-report`, `from-openmates`, `claude-investigated`
- Create a custom workflow state: "Investigated" (between Triage and In Progress)
- Generate a Personal API Key for the admin
- Store key in Vault at `secret/linear/api_key`

**Post-investigation script (`scripts/linear-update-issue.py`):**

```python
#!/usr/bin/env python3
"""
Update a Linear issue with Claude Code investigation results.

Called by agent-trigger-watcher.sh after a Claude session completes.

Usage:
    python3 scripts/linear-update-issue.py \
        --issue-id LINEAR_ISSUE_ID \
        --session-id CLAUDE_SESSION_ID \
        --status investigated
"""
import argparse
import json
import os
import httpx

LINEAR_API_URL = "https://api.linear.app/graphql"

def update_issue(api_key: str, issue_id: str, session_id: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    comment_body = (
        f"## Claude Code Investigation Complete\n\n"
        f"**Session ID:** `{session_id}`\n\n"
        f"**Resume command:**\n```\nclaude --resume {session_id}\n```\n\n"
        f"Review the session for detailed findings and any proposed fixes."
    )

    mutation = """
    mutation($issueId: String!, $body: String!) {
      commentCreate(input: { issueId: $issueId, body: $body }) {
        success
      }
    }
    """

    resp = httpx.post(LINEAR_API_URL, headers=headers, json={
        "query": mutation,
        "variables": {"issueId": issue_id, "body": comment_body}
    })
    resp.raise_for_status()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-id", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        print("ERROR: LINEAR_API_KEY not set")
        exit(1)

    update_issue(api_key, args.issue_id, args.session_id)
```

**Changes to `agent-trigger-watcher.sh`:**

```bash
# After Claude session completes, update Linear if issue has a linear_issue_id
linear_issue_id="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('linear_issue_id',''))" "$trigger_file" 2>/dev/null)" || true

if [[ -n "$linear_issue_id" && -n "$session_id" ]]; then
    log "[agent-watcher] Updating Linear issue $linear_issue_id with session $session_id"
    python3 "$PROJECT_ROOT/scripts/linear-update-issue.py" \
        --issue-id "$linear_issue_id" \
        --session-id "$session_id" || {
        log "[agent-watcher] WARNING: Failed to update Linear issue"
    }
fi
```

### 4.2 Workflow B Implementation

**New code needed:**

| Component | File | Changes |
|-----------|------|---------|
| Webhook endpoint | `backend/admin_sidecar/main.py` | New `POST /admin/linear-webhook` route |
| Webhook verification | `backend/admin_sidecar/main.py` | HMAC-SHA256 signature check |
| Prompt adaptation | `scripts/prompts/linear-issue-investigation.md` | New template for Linear-sourced issues |
| Trigger file writer | `backend/admin_sidecar/main.py` | Reuse existing `_write_trigger_file()` logic |
| Post-investigation update | `scripts/agent-trigger-watcher.sh` | Same as Workflow A |

**New admin sidecar endpoint:**

```python
class LinearWebhookPayload(BaseModel):
    action: str
    type: str
    data: dict
    updatedFrom: Optional[dict] = None
    url: Optional[str] = None
    organizationId: Optional[str] = None

@app.post("/admin/linear-webhook")
async def handle_linear_webhook(
    request: Request,
    linear_signature: str = Header(None, alias="Linear-Signature"),
):
    """
    Receive Linear webhook events and trigger Claude investigation
    when the 'claude-investigate' label is added to an issue.
    """
    raw_body = await request.body()

    # Verify signature
    signing_secret = os.environ.get("LINEAR_WEBHOOK_SECRET", "")
    if not signing_secret:
        raise HTTPException(500, "LINEAR_WEBHOOK_SECRET not configured")

    expected = hmac.new(
        signing_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, linear_signature or ""):
        raise HTTPException(401, "Invalid webhook signature")

    payload = LinearWebhookPayload(**await request.json())

    if not should_trigger_investigation(payload.model_dump()):
        return {"status": "ignored", "reason": "not a trigger event"}

    # Extract issue data
    issue_data = payload.data
    issue_id = issue_data["id"]
    issue_title = issue_data.get("title", "Untitled")
    issue_description = issue_data.get("description", "")
    issue_url = issue_data.get("url", payload.url or "")
    linear_identifier = issue_data.get("identifier", "")

    # Render prompt from template
    prompt = _render_linear_prompt(
        issue_id=issue_id,
        identifier=linear_identifier,
        title=issue_title,
        description=issue_description,
        url=issue_url,
    )

    # Write trigger file (reuses existing mechanism)
    trigger_dir = Path(_GIT_WORK_DIR) / "scripts" / ".agent-triggers"
    trigger_dir.mkdir(parents=True, exist_ok=True)

    trigger_file = trigger_dir / f"linear-{linear_identifier}.json"
    trigger_data = {
        "issue_id": issue_id,
        "linear_issue_id": issue_id,
        "linear_identifier": linear_identifier,
        "session_title": f"Linear {linear_identifier}: {issue_title[:60]}",
        "prompt": prompt,
        "source": "linear-webhook",
    }
    trigger_file.write_text(json.dumps(trigger_data, indent=2))

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "trigger_file": trigger_file.name}
    )
```

**Linear workspace setup (in addition to Workflow A):**
- Create webhook: URL = `https://<CORE_SIDECAR_DOMAIN>/admin/linear-webhook`, resource types = `Issue`
- Save the signing secret in Vault at `secret/linear/webhook_secret`
- Create label: `claude-investigate` (the trigger label)
- Optionally create automation: "When issue moves to Triage, if priority is Urgent, add label `claude-investigate`"

**Environment variables (admin sidecar):**
- `LINEAR_API_KEY` -- for post-investigation updates (stored in Vault, injected via env)
- `LINEAR_WEBHOOK_SECRET` -- for signature verification (stored in Vault, injected via env)

**Security considerations:**
- Webhook signature verification is mandatory (prevents unauthorized triggers)
- The sidecar is not publicly routable (only accessible via internal Docker network + Caddy reverse proxy)
- Linear API key should be a dedicated "bot" user with minimal permissions (issue read/write only)
- Rate-limit the webhook endpoint (1 trigger per issue per hour) to prevent webhook replay or loop attacks
- The `claude-investigate` label is removed after investigation to prevent re-triggering

### 4.3 Resume Command Location

In both workflows, the "resume command" is written to Linear as a **comment** on the issue:

```markdown
## Claude Code Investigation Complete

**Session ID:** `session_abc123def`

**Resume command:**
```
claude --resume session_abc123def
```

**Summary:** [brief findings from Claude's session output]

**Files investigated:**
- `frontend/packages/ui/src/services/chatSyncService.ts`
- `backend/core/api/app/routes/settings.py`

**Status:** Awaiting developer review
```

This approach:
- Preserves the original issue description untouched
- Creates a clear audit trail (multiple investigations = multiple comments)
- Is easily visible in Linear's issue detail view
- Can be expanded later with richer formatting or attachments

---

## 5. Recommendation

### Phase 1: Implement Workflow A First

**Why:** Workflow A enhances the existing pipeline with minimal new infrastructure. It adds Linear as a tracking layer without changing the trigger mechanism. This gives immediate value:
- Issues get tracked in Linear (not just Directus)
- Investigation results are posted back to Linear automatically
- The resume command is discoverable in Linear's UI

**Estimated effort:** 1-2 sessions (small)
- `linear_client.py` utility: ~50 lines
- `settings.py` changes: ~30 lines
- `agent-trigger-watcher.sh` changes: ~15 lines
- `linear-update-issue.py` script: ~40 lines
- Vault/env setup: ~15 minutes

### Phase 2: Implement Workflow B After Stabilization

**Why:** Workflow B requires webhook infrastructure (public endpoint, signature verification, new sidecar route). It is more complex and benefits from having Workflow A already working (the post-investigation Linear update code is shared).

**Estimated effort:** 2-3 sessions (medium)
- New sidecar endpoint: ~100 lines
- New prompt template: ~50 lines
- Webhook setup in Linear: ~10 minutes
- Network/Caddy config for webhook routing: ~30 minutes

### Broader Availability

The Linear integration should be available beyond just planning phases:
- **Workflow A** (issue report -> Linear) should run for ALL admin-submitted issues, always
- **Workflow B** (Linear -> Claude) should be gated by the `claude-investigate` label, which is a deliberate action. This makes it safe for general use -- only labeled issues trigger investigation

### Alternative: Direct API Polling (No Webhooks)

If exposing a webhook endpoint to Linear is undesirable (security concern), Workflow B can be implemented as a **polling cron job** instead:

```bash
# Run every 5 minutes via systemd timer
# Query Linear for issues with "claude-investigate" label
# For each found: write trigger file, remove label
```

This avoids any inbound HTTP from Linear but adds 0-5 minutes of latency. Given the non-urgent nature of issue investigation, this is acceptable and may be the simpler starting point.

---

## Appendix: Key File References

| File | Role |
|------|------|
| `frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte` | Issue report form (frontend) |
| `frontend/packages/ui/src/stores/reportIssueStore.ts` | Form state persistence |
| `backend/core/api/app/routes/settings.py` | Issue submission endpoint |
| `backend/admin_sidecar/main.py` | Sidecar: trigger file writer + proposed webhook receiver |
| `scripts/agent-trigger-watcher.sh` | Host-side Claude session launcher |
| `scripts/prompts/admin-issue-investigation.md` | Claude investigation prompt template |
| `backend/core/api/app/utils/secrets_manager.py` | Vault integration for API key storage |
