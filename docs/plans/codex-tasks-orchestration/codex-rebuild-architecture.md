# Proposed OpenMates–Codex architecture

9 September 2026. Updated after the original five clarification rounds and five additional refinement rounds. This is the proposed architecture, not an implementation or deployment. It follows the user's choice to run `openmates remote-access` in Zellij and retain repository Plans/Specifications and PDF approval initially. Detailed decisions and source findings are recorded in `architecture-refinements.md` alongside this report.

## Outcome

OpenMates Tasks owns work state. The running OpenMates CLI continuously maintains local task context for the selected Project. A small Codex adapter supplies that context and resumes the worker that can act. The orchestration model handles planning, coordination decisions and final review; ordinary synchronization, waiting, retries and dependency routing run in code.

No new Task fields are proposed. Task titles, descriptions, status, activity, external-chat associations, Project links, blockers and dependency relationships use the existing model. Conversation ownership, delivery cursors, cached timestamps and CI associations are integration metadata, not extra Task fields or another authoritative task ledger.

## What the remote-access inspection established

Inspected canonical source at commit `e78dcedba7e5deda6bb4ae3deec92c63211fb55a`:

- `cli.ts:4287`: foreground startup, Personal/Team context, repository discovery or explicit paths, Project bindings, and a bridge loop. Its console text already recommends Zellij, tmux or screen.
- `cli.ts:4420`: reuse saved folder–Project associations; offer to create Projects for unresolved folders. There is no existing-Project picker for those folders in this function.
- `remoteAccess.ts:301`: register read/search/import capabilities, receive encrypted file requests, send a 15-second heartbeat, and reconnect after transport loss. No Task-sync subscription or task-context writer exists in this loop.
- `client.ts:9372`: remote access opens the websocket with `taskUpdateJobs: false`.
- `ws.ts:1172` and `websockets.py:831`: existing task events are filtered to an active native chat and clients supporting task-update jobs. `task_tool_executor.py` publishes them on native chat streams. This is not the required Project-wide feed of all committed Task mutations.

These findings are source verification, not a live remote-access end-to-end test. Inspection did not start a source host, create Projects, modify Tasks or dispatch CI.

## 1. Startup and process lifetime

Keep the public entry point: `openmates remote-access`, launched in Zellij. Preserve its existing file-access functionality.

Extend interactive startup to show detected folders and current Project bindings, allow an unbound folder to select an existing Project or create a new one, and select which Project should have Tasks synchronized and where its cache should live. Persist the selection in local CLI configuration. Do not silently create a second OpenMates Project because the folder lacks a saved binding.

For this setup, the selected Project is OpenMates and the cache should live outside all repository worktrees, under a user-selected directory. Scope cache storage by authenticated account/context and Project identity. Reuse approved selections on later starts while displaying a concise startup summary.

Task sync and an enabled Codex adapter run for the lifetime of this command. The adapter is a separate module, not a separately managed service the user must start. Closing the process stops synchronization and automatic wakeups; Zellij keeps it alive after a terminal disconnect. It does not survive a server reboot without being started again. Temporary network loss triggers reconnect and catch-up. Terminal authentication failures remain visible rather than causing silent infinite retries.

## 2. Project-wide committed changes

Add an explicitly scoped Task-sync subscription to the existing connection. Do not enable native task-update jobs as a substitute.

Send one initial consistent snapshot, then versioned changes. Cover Task creation, update, lifecycle transitions, deletion, restoration, Project membership, dependency edits, activity creation/deletion and changes needed to decrypt authorized records. This must cover web, CLI and other supported mutation paths, including server-generated lifecycle activity.

Record changes durably with the successful mutation, through a transactional outbox or equivalent durable change capture. Publishing only from a few HTTP handlers or relying on transient pub/sub can lose changes. Private content stays encrypted in transit and is decrypted by the authenticated CLI using the existing key model; a Project key alone is not assumed to unwrap every Task.

Use a replay cursor and explicit snapshot boundary so updates during initial loading cannot fall through a gap. Handle duplicate/out-of-order events and deletion tombstones. After reconnect, replay missed changes; if history has expired, rebuild the snapshot. Observe authorized external dependencies of selected Tasks without exporting unrelated Project content.

Prefer enough encrypted data in the change batch to update the cache directly. If a follow-up fetch is required, coalesce affected identifiers into bounded batch reads. Avoid one spawned CLI process and multiple HTTP requests per event. A batched bootstrap/change API is an integration extension, not a change to Task fields.

Keep low-frequency reconciliation for missed-event recovery. Push delivery is the normal freshness path. Measure save-to-cache latency under representative load; do not promise a fixed millisecond bound before measurement.

## 3. Local cache and generated text

The CLI maintains private synchronization metadata and generates one compact text file per registered Codex conversation. A Project inventory supports discovery. Use atomic replacement and a single writer so readers see complete snapshots. These are disposable views that can be rebuilt from OpenMates and the durable conversation registry.

Every linked Task appears, including completed Tasks. Keep full titles and actual states. Shorten descriptions and the latest activity entry with deterministic truncation; include only that latest entry. Preserve current blockers and dependencies separately. Do not use an LLM to summarize cache content or select an activity entry. Do not silently cap the list at eight Tasks as the old helper does.

Worker files include their own Tasks. Orchestrator files include their own Tasks, every managed worker and each worker's Tasks. Keep Codex execution state separately labeled from OpenMates Task status. Include last successful refresh and connection freshness as cache metadata. Failed refreshes must not appear successful by advancing that timestamp.

Full task details and older activity stay available through existing CLI commands. Exact Codex status/history tool examples appear only when the runtime exposes them. Task content is clearly marked as data, not new instructions or approvals.

## 4. Codex context injection

Keep permanent instructions short: create meaningful Tasks for complex work; maintain truthful states and dependencies; record meaningful activity; use the injected overview; retrieve more only when needed; follow existing approval and GitHub CI rules.

Use Codex's documented extra developer context through `SessionStart` and `UserPromptSubmit` for automatic snapshots. Deduplicate overlapping lifecycle events. After compaction, reconstruct a complete fresh snapshot. A text file is not itself a live system-prompt subscription.

For active turns, use a lightweight local pending-change check at a supported tool boundary and emit only changed rows, once. This is a local check with no network request and no context output when unchanged. It must not repeat the full overview before every tool call. A deletion is an explicit removal, not simply an absent row. Latest delivered versions supersede older snapshots.

For an idle worker that should resume, attach fresh context to one continuation. Close the race in which a turn ends just as an update arrives by retaining pending delivery and reconciling execution state. Do not force an extra model turn merely to acknowledge routine activity.

Official references: https://learn.chatgpt.com/docs/hooks and https://learn.chatgpt.com/docs/app-server. A bounded pilot must verify lifecycle coverage on the actual desktop/remote runtime, including automatic continuations and compaction. Additional developer context is supported; in-place replacement of a live system message is not assumed. Hook output limits must be accounted for explicitly so a large campaign is not silently truncated.

## 5. Conversation ownership and direct dependency routing

Maintain a durable registry of coordinator, managed workers, host identities, worktrees and associated Task IDs. Use full identities internally and readable titles in human-facing output. This registry expresses conversation ownership; it does not introduce recursive Tasks or a parent-task field.

Create/register persistent visible workers through the supported Codex task mechanism when the user authorizes those workers. Track queued creation until the final task identity exists. Do not substitute hidden subagents for requested sidebar tasks. A worker may own several flat Tasks, such as a shared repair, an audio pilot and a bulk follow-up linked by dependencies.

Task execution ownership belongs to one linked conversation at a time, across devices. A conversation may claim unlinked work for itself; another conversation cannot replace that link until it is released. Repeating the same claim is idempotent. Enforce ownership checks atomically across update paths, using a verified caller context rather than arbitrary --thread input. Current version-conflict checks alone do not implement this rule. A single execution/delivery path for the same conversation remains necessary, independently of exclusive Task ownership.

Ordinary CLI Task creation remains unlinked by default. Codex supplies `--external-chat codex:<current-chat-id>` in its create call for work it owns, so create-and-link is one mutation. Intentionally unlinked work omits that flag. Native OpenMates task-creation skills/tools default to their current authenticated native conversation, with explicit no-link behavior; never inject CLI instructions into native OpenMates conversations. Include the actual Codex ID in its static instruction context to avoid discovery calls. Current CLI supporting reads should be reduced using cached/runtime context without claiming they already disappear.

Rejected claims identify the owning title in quotes. Codex-owned Tasks show the Codex chat ID. For native OpenMates ownership, show the native chat ID and `openmates chats show <chat-id>` to the CLI/Codex caller.

Confirmed conversation deletion clears its Task/Plan connections, cancels its pending wakeups and stale ownership intents, and preserves the records, history and authorized decryption access. An in-progress Task returns to todo; completed states and independent blockers are preserved. Do not automatically create replacement workers. Active Plans losing an execution chat need coherent lifecycle cleanup. Archiving, disconnection and absence from a list are not deletion. Native deletion should arrange durable backend cleanup; Codex deletion requires a confirmed runtime signal and catch-up while the adapter was offline. Preserve explicit user release as a recovery action.

When a dependency completes, reevaluate all dependency edges and existing blockers. Do not infer removal of an approval or credential blocker from one completed dependency. Only apply the existing unblock transition when justified; confirm its behavior for external Codex assignments so it cannot accidentally dispatch native OpenMates AI work.

Then route to the affected worker: deliver a changed row to an active turn, or resume an idle worker parked for that dependency. A manually paused worker remains paused. The orchestrator's file is refreshed but its model is not needed for ordinary dependency routing.

Persist delivery intent and reconcile uncertain submissions against Codex state before retrying. Duplicate change events must not cause duplicate continuations. This is an idempotent delivery design, not a claim of universal exactly-once delivery across crashes. Record system-triggered continuations honestly; they do not represent new user approval.

Observe Codex execution through supported events where available and compact status reads for recovery. Avoid scraping transcripts as the primary status transport and avoid creating separate observer scripts for each campaign.

## 6. What wakes the orchestrator

Routine Task changes and progress only refresh its view. Direct dependencies and CI ownership route to workers. Wake the orchestrator for a coordination decision it actually owns, an unassigned/unresolvable problem requiring coordination, or when the campaign reaches final review. Coalesce independent completions into one continuation when their results require parent action. User intervention remains available at any time.

The user's direction establishes direct worker routing. Exact escalation categories can be refined in implementation acceptance examples without inventing Task fields. Human messages should explain the outcome and decision, not repeat campaign tables, internal leases and exact-match boilerplate.

## 7. GitHub CI remains the test scheduler

Reuse `sessions.py ci-source`, the existing CI coordinator and its submit/status/result paths, and the established test runner. Publish immutable candidate source and preserve source, harness and profile associations. Do not introduce a second CI queue, poller or host-container test path.

The Codex adapter records which Task/worker owns a CI job in integration metadata. The existing coordinator emits or exposes a durable completion result. Its owner receives one actionable result and verified receipt; unrelated workers and the parent remain quiet. A passed test does not automatically mean the Task is done: the worker evaluates the required evidence and remaining approved work.

Retain local focused unit tests where allowed. Isolated browser/integration tests run through GitHub. Real-provider tests preserve the existing explicit execution/spending rules; replay results are not represented as live provider proof.

Update repository Plan/skill guidance to accept isolated CI evidence without a shared dev/Vercel deployment prerequisite. Repair the Plan evidence helper that accepts any ancestor as covering later implementation. Require the tested subject or an explicitly justified equivalence check. Keep artifact/visual review where the approved change requires it.

## 8. Durable local delivery queue

Persist status/activity/create/claim intents locally before transport attempts, scoped to the correct authenticated account, API and Project. Reuse the existing activity outbox machinery where applicable and extend the shared delivery layer instead of adding another independent retry loop per worker. If the CLI executable itself is temporarily unavailable, a small integration-owned writer must still be able to persist an intent without invoking it; resume canonical CLI delivery when available.

Server restarts, temporary network/transport failures and rate limits leave writes pending. Already-owned, approved work can continue with explicit cache freshness. A queued claim is not ownership: confirm claims and dependency-based starts before proceeding. Do not mark Tasks blocked/failed simply because synchronization is unavailable, or describe local pending writes as server-confirmed.

Recommended initial defaults: increasing retry delays with jitter, Retry-After support and shared cooldown; report persistent trouble only after at least five unsuccessful attempts over at least five minutes. Retain the queue and retry less frequently afterward, with one actionable notice per incident. Recover and reconcile automatically when connectivity returns. Numeric thresholds are configurable integration policy, not new Task fields or measured service guarantees.

Do not retry invalid requests, ownership denials or revoked credentials as though they were server restarts. Reevaluate version conflicts against authoritative state. Use stable operation identities, server idempotency or acknowledgment reconciliation, and ordered dependent writes so a lost acknowledgment does not duplicate a Task or activity. Preserve meaningful lifecycle history. Cancel intents made obsolete by deletion, release or explicit new user direction.

The running remote-access process owns delivery retries for this setup. Stopping it retains the disk queue for next startup. No sleeping model turns, exact-wording Stop checks, or per-worker polling loops are part of queue maintenance.

## 9. Request and inference budget

| Operation | Expected behavior |
|---|---|
| No Task changes | No task-context API reads per agent/tool; connection heartbeats and infrequent recovery checks run in code |
| One committed change | One shared update path; batch related changes, no per-worker HTTP fan-out |
| Task activity | Update affected files, no model turn |
| Turn begins | Read local generated context in the hook, no agent discovery call |
| Relevant mid-turn change | Deliver compact changed rows once, not another full overview |
| Dependency unblocks work | One direct owner continuation when idle and eligible |
| CI completes | Existing CI result handling; one owner notification, no independent worker GitHub polling |
| Reconnect | Cursor catch-up or bounded rebuild, no agent needed |

Dynamic context still consumes input tokens, and an append-only hook does not erase older context. Keep static instructions stable, use deterministic compact rows/deltas, and measure injected bytes/tokens and model wake counts in the pilot. Do not claim cache injection is free or guarantee savings before measurement.

## 10. Migration and acceptance

First build the generic remote-access Project binding and task sync, then the Codex context/delivery module. Keep the installed global CLI as the operational entry point; publish the matching version before rollout. Source builds belong to development and CI, not routine orchestration. Keep connection memory, fan-out and heartbeat overhead bounded, but do not gate first release on large connection-count benchmarks or a new hosting platform. The priority is resuming real work quickly.

Pilot one coordinator and two visible workers, each with multiple Tasks. Keep old bookkeeping hooks disabled for the pilot only once the replacement is ready; do not run two writers or two wakeup owners for the same workers. Preserve relevant code/security checks independently of removing orchestration bureaucracy.

Acceptance examples:

1. A web edit updates the correct Project cache and worker context, without a model discovery call or unrelated worker wakeup.
2. Every linked Task is visible, even beyond the old eight-task limit; only descriptions and latest activity are shortened.
3. The last dependency finishing resumes its waiting worker once. Another approval blocker prevents resumption. Duplicate events and completion-at-turn-end races do not duplicate work.
4. Disconnect, missed events and reconnect recover creations, deletes, activity and dependency changes correctly; stale data is visibly stale.
5. A GitHub pass/failure reaches its actual worker with matching subject evidence; the coordinator sleeps through routine delivery.
6. Zellij detachment leaves remote access running; stopping the command stops sync cleanly; restarting catches up. Paused workers stay paused.
7. Selecting an existing OpenMates Project at startup does not create a duplicate. Account/Project boundaries and authorized key access are preserved.
8. Clarification-only turns end normally. There are no exact-final-wording checks, obligatory retrospective records or model turns to repair routine task bookkeeping.
9. A server restart leaves updates pending while owned work continues. Delivery recovers without duplicate Task creation or activity, including when the server committed a write but its acknowledgment was lost. A genuine ownership denial does not enter the transient retry loop.
10. Two conversations cannot claim the same Task. Create-and-link uses one mutation; confirmed deletion removes dead links and applies the agreed lifecycle cleanup without creating a replacement worker.

Test protocol/state invariants with focused unit tests; run the supported browser/integration scenarios through GitHub CI. Add a runtime compatibility pilot for Codex hook delivery. Compare requests, wakeups, delay and context volume with the inspected Landing baseline before expanding to the full campaign.

Native OpenMates Plans, Specifications and reusable Checks remain later integrations. The current repository/PDF process remains the approval source during this rebuild.
