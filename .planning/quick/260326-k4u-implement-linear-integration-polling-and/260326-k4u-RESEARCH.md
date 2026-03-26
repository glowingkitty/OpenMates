# Quick Task 260326-k4u: Linear Integration - Research

**Researched:** 2026-03-26
**Domain:** Linear GraphQL API, Docker exec patterns, sub-minute scheduling
**Confidence:** HIGH

## Summary

This task implements a polling-based Linear integration that detects issues with a `claude-investigate` label, writes trigger files to the existing agent pipeline, and posts investigation results back to Linear. Prior research (260326-hxd) already mapped the full architecture and API surface. This research fills the remaining implementation gaps: exact GraphQL queries, 30s scheduling approach, trigger watcher modifications, and Docker exec patterns.

**Primary recommendation:** Use the existing `agent-trigger-watcher.sh` sleep loop as the model -- add Linear polling directly into it (or as a companion loop), avoiding cron entirely. Run the poller script via `docker exec api` to get Vault secrets, writing trigger files to the bind-mounted volume.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Python script in repo (`scripts/linear-poller.py`)
- Runs via `docker exec api` -- gets Vault secrets automatically
- Triggered by host cron job every 30s -- only installed on dev server, NOT production
- Writes trigger JSON files to `scripts/.agent-triggers/` (bind-mounted volume)
- Host-side `agent-trigger-watcher.sh` picks up triggers as usual
- LINEAR_API_KEY stored in `.env` file (auto-imported to Vault on server start)
- Investigation prompt: include title, description, priority, labels; exclude comments, assignee, linked issues
- Archive at 230 issues, export to `.planning/linear-archive.md`, daily sweep

### Claude's Discretion
- Exact GSD command recommendation logic
- Archive file format details
- Error handling / retry logic for Linear API failures

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Linear GraphQL API -- Exact Queries Needed

**Confidence:** HIGH (verified against Linear developer docs, Apollo Studio schema, and SDK source)

### 1. Fetch Issues with `claude-investigate` Label

```graphql
query GetInvestigateIssues {
  issues(filter: {
    labels: { name: { eq: "claude-investigate" } }
  }) {
    nodes {
      id
      identifier
      title
      description
      priority
      url
      labels {
        nodes {
          id
          name
        }
      }
    }
  }
}
```

**Note:** The `labels` filter uses nested comparators. The `name: { eq: "..." }` form matches issues that have at least one label with that exact name. No pagination needed -- this should return a small set (typically 0-3 issues at a time).

### 2. Add a Comment to an Issue

```graphql
mutation AddComment($issueId: String!, $body: String!) {
  commentCreate(input: {
    issueId: $issueId
    body: $body
  }) {
    success
    comment {
      id
    }
  }
}
```

### 3. Update Issue Labels (Remove `claude-investigate`, Add `claude-investigated`)

Linear does NOT have `addLabel`/`removeLabel` mutations. You must pass the full set of desired `labelIds` to `issueUpdate`. The workflow:

1. Query the issue to get current `labels.nodes[].id`
2. Filter out the `claude-investigate` label ID
3. Add the `claude-investigated` label ID
4. Call `issueUpdate` with the new full list

```graphql
mutation UpdateIssueLabels($id: String!, $labelIds: [String!]!) {
  issueUpdate(id: $id, input: {
    labelIds: $labelIds
  }) {
    success
    issue {
      id
      labels { nodes { id name } }
    }
  }
}
```

**Pitfall:** If you set `labelIds` without including existing labels, they get removed. Always read-then-write.

### 4. Count Total Issues (for Archive Threshold)

```graphql
query IssueCount {
  issues(filter: {
    state: { type: { in: ["completed", "canceled"] } }
  }, first: 0) {
    pageInfo {
      endCursor
    }
  }
}
```

**Better approach:** Linear connections don't expose a `totalCount` field directly. Instead, use pagination to count. However, for a simpler approach, query with a high `first` value or use the `issueCount` query if available. Alternatively, the pragmatic approach is:

```graphql
query ClosedIssueCount {
  issues(filter: {
    state: { type: { in: ["completed", "canceled"] } }
  }, first: 250) {
    nodes {
      id
      identifier
      title
      createdAt
      completedAt
    }
  }
}
```

Since the free plan limit is 250 and we trigger at 230, fetching up to 250 nodes is always within bounds. Sort by `createdAt` to find oldest for archival.

### 5. Archive (Delete) Issues

```graphql
mutation ArchiveIssue($id: String!) {
  issueArchive(id: $id) {
    success
  }
}
```

For permanent deletion (if archive is not sufficient):

```graphql
mutation DeleteIssue($id: String!) {
  issueDelete(id: $id) {
    success
  }
}
```

**Recommendation:** Use `issueArchive` first (reversible). Only `issueDelete` if archived issues count toward the 250 limit.

### 6. Look Up Label IDs (One-Time Setup Query)

```graphql
query GetLabels {
  issueLabels(filter: {
    name: { in: ["claude-investigate", "claude-investigated"] }
  }) {
    nodes {
      id
      name
    }
  }
}
```

Cache these IDs in the poller script as constants (labels rarely change).

### Python Pattern with httpx

```python
import httpx

LINEAR_API_URL = "https://api.linear.app/graphql"

def linear_query(api_key: str, query: str, variables: dict = None) -> dict:
    """Execute a Linear GraphQL query/mutation."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = httpx.post(LINEAR_API_URL, headers=headers, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"Linear API error: {data['errors']}")

    return data["data"]
```

### Rate Limits

- 1,500 requests per hour per API key
- At 30s polling interval = 120 requests/hour (well within limits)
- Headers: `X-RateLimit-Requests-Remaining`, `X-RateLimit-Requests-Reset`

## 30-Second Polling -- Approach

**Confidence:** HIGH

Cron only supports 1-minute minimum. Three options:

| Approach | Pros | Cons |
|----------|------|------|
| Two cron entries (`:00` and `:30`) | Simple, no daemon | Fragile, two entries to maintain |
| Systemd timer with `OnUnitActiveSec=30s` | Clean, restartable, journald logs | More files to manage |
| **Sleep loop in a long-running script** | Matches existing watcher pattern | Need systemd service for restart |

**Recommendation:** Use a **systemd user service** running a sleep loop, identical to how `agent-trigger-watcher.sh` works. This is the established pattern in this project. The poller script runs as:

```bash
# linear-poller.service (systemd user service)
while true; do
    docker exec api python3 /app/scripts/linear-poller.py 2>&1 || true
    sleep 30
done
```

Or even simpler: add the Linear polling to the EXISTING `agent-trigger-watcher.sh` loop. The watcher already polls every 5 seconds. Adding a Linear check every 6th iteration (30s) keeps everything in one service.

**Recommended approach:** Standalone systemd service. Keeps concerns separated, and the poller can fail independently without affecting the trigger watcher.

## Docker Exec Pattern

**Confidence:** HIGH (verified `docker exec api python3 -c "import httpx"` works)

### How It Works

```bash
docker exec api python3 /app/scripts/linear-poller.py
```

The script at `scripts/linear-poller.py` is bind-mounted into the container at `/app/scripts/` (via docker-compose volume mount). It runs inside the `api` container where:
- `httpx` is available (verified)
- Vault secrets are in environment variables
- The `scripts/.agent-triggers/` directory is bind-mounted and writable

### Pitfalls

| Pitfall | Prevention |
|---------|------------|
| Container not running | Wrap in `docker exec ... 2>/dev/null \|\| true`; log warning |
| Container restarting (exit code 137) | Same -- the next 30s cycle will retry |
| Script takes >30s (overlapping runs) | Use a lockfile (`/tmp/linear-poller.lock`) or `flock` |
| `.env` not loaded in host script | The docker exec runs INSIDE the container where env is already set |
| Trigger file write race with watcher | Atomic write: write to `.tmp` then `mv` (rename is atomic on same filesystem) |

### Lockfile Pattern

```bash
# In the wrapper script or systemd service
exec flock -n /tmp/linear-poller.lock docker exec api python3 /app/scripts/linear-poller.py
```

## Agent Trigger Watcher Modifications

**Confidence:** HIGH (read the full script)

The watcher at `scripts/agent-trigger-watcher.sh` needs two changes:

### Change 1: Extract `linear_issue_id` from Trigger JSON

After extracting `issue_id`, `session_title`, and `prompt`, also extract:

```bash
linear_issue_id="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('linear_issue_id',''))" "$trigger_file" 2>/dev/null)" || true
```

### Change 2: Post-Investigation Linear Update

After the Claude session completes (after line 111 `mv "$trigger_file" ...`), add:

```bash
if [[ -n "$linear_issue_id" && -n "$session_id" ]]; then
    log "[agent-watcher] Updating Linear issue $linear_issue_id with session $session_id"
    docker exec api python3 /app/scripts/linear-update-issue.py \
        --issue-id "$linear_issue_id" \
        --session-id "$session_id" \
        2>&1 | while read -r line; do log "[linear-update] $line"; done || {
        log "[agent-watcher] WARNING: Failed to update Linear issue"
    }
fi
```

**Key detail:** The update script runs via `docker exec api` too, so it gets the LINEAR_API_KEY from Vault. No need to pass secrets through the host.

### Trigger File Format (Linear-Sourced)

```json
{
  "issue_id": "linear-ENG-42",
  "linear_issue_id": "uuid-of-linear-issue",
  "linear_identifier": "ENG-42",
  "session_title": "Linear ENG-42: Decryption fails on iOS",
  "prompt": "... rendered investigation prompt ...",
  "source": "linear-poller"
}
```

The `issue_id` field uses a `linear-` prefix to avoid collisions with Directus UUIDs.

## Investigation Prompt Template

The new prompt (`scripts/prompts/linear-issue-investigation.md`) should:

1. Be based on the existing `admin-issue-investigation.md` but simplified (Linear issues have less context than web-reported issues -- no console logs, screenshots, or action history)
2. Include GSD command recommendation at the end
3. Use these placeholders: `{{LINEAR_IDENTIFIER}}`, `{{TITLE}}`, `{{DESCRIPTION}}`, `{{PRIORITY}}`, `{{LABELS}}`, `{{URL}}`, `{{DATE}}`

### GSD Command Recommendation Logic

```
IF description mentions "bug" or "error" or "broken" or "fails" or "crash":
    Recommend: /gsd:debug
ELIF description mentions "add" or "implement" or "create" or "new feature":
    Recommend: /gsd:quick (for small) or /gsd:execute-phase (if part of roadmap)
ELIF description mentions "refactor" or "clean up" or "improve":
    Recommend: /gsd:quick
ELSE:
    Recommend: /gsd:debug (default -- most Linear issues will be bugs)
```

This logic should be embedded in the prompt text itself (instruct Claude to recommend the right command), not hardcoded in the poller.

## Common Pitfalls

### Pitfall 1: Polling the Same Issue Repeatedly
**What goes wrong:** Poller finds an issue with `claude-investigate`, writes trigger, but label removal happens after Claude finishes (not immediately). Next poll picks up the same issue.
**Prevention:** The poller must remove the `claude-investigate` label immediately after writing the trigger file, BEFORE the investigation starts. This is a two-step operation: (1) write trigger, (2) update label to prevent re-pick.

### Pitfall 2: Linear API Key Not Available
**What goes wrong:** `docker exec api` runs the script but LINEAR_API_KEY isn't in the container env.
**Prevention:** Add `LINEAR_API_KEY` to `.env` file and ensure it's in the docker-compose `env_file` list. Poller should fail loudly (exit 1) if key is missing.

### Pitfall 3: Free Plan Issue Limit
**What goes wrong:** Hitting 250 issues silently, new issues fail to create.
**Prevention:** Archive script runs daily. Log a warning at 200+ issues. The 230 threshold gives 20 issues of buffer.

### Pitfall 4: Atomic Trigger File Writes
**What goes wrong:** Watcher reads a partially-written trigger JSON.
**Prevention:** Write to a `.tmp` file, then `os.rename()` to `.json`. The watcher only globs `*.json`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| GraphQL client | Full typed client | Raw `httpx.post` + query strings (matches project patterns) |
| Scheduling daemon | Custom scheduler | Systemd user service with sleep loop |
| Secret management | Custom config | Existing Vault / `.env` pipeline via `docker exec api` |

## Sources

### Primary (HIGH confidence)
- Linear developer docs: https://linear.app/developers -- API overview, auth, rate limits
- Linear GraphQL schema: https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql -- mutation signatures
- Apollo Studio: https://studio.apollographql.com/public/Linear-API/variant/current -- interactive schema explorer
- Existing codebase: `scripts/agent-trigger-watcher.sh` -- established trigger file pattern

### Secondary (MEDIUM confidence)
- Endgrate Python guide: https://endgrate.com/blog/how-to-create-or-update-issues-with-the-linear-api-in-python -- Python httpx pattern
- Prior research: `.planning/quick/260326-hxd-*/LINEAR-INTEGRATION-RESEARCH.md` -- full architecture mapping

## Metadata

**Confidence breakdown:**
- Linear GraphQL queries: HIGH -- verified against schema and multiple sources
- Docker exec pattern: HIGH -- verified on this server
- 30s scheduling: HIGH -- established pattern in this project
- Watcher modifications: HIGH -- read full source, changes are minimal
- Label update pitfall (read-then-write): MEDIUM -- consistent across sources but not tested

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (Linear API is stable, infrequent breaking changes)
