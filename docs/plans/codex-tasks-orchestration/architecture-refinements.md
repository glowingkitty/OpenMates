# Architecture refinement rounds

The user requested five additional clarification questions after the initial architecture, one per round. Each round should include concrete existing CLI inputs and explicitly labeled proposed outputs/instruction examples, useful diagrams, and the specific old orchestration failures addressed. Do not present proposed commands or output as implemented behavior.

## Transport and scalability inspection — 9 September 2026

Recommendation: reuse the outbound websocket of each running remote-access CLI process/authenticated context and multiplex selected Projects over it. Remote file access already needs bidirectional traffic. A webhook is useful for reachable server-to-server endpoints but is a poor default for laptops/private hosts without an inbound receiver or relay. It would not remove the existing remote-access connection requirement.

Scalable protocol does not imply a proven scalable current deployment. Bound per-connection memory and outgoing queues; index authorized subscriptions rather than scanning users; horizontally distribute connections behind a stable service endpoint; durably record changes and replay on reconnect; coalesce acknowledgements and changes; preserve disconnect/slow-consumer limits and authorization boundaries. Measure capacity rather than committing a device count to a single server without hardware/workload data.

Current source findings:

- `remoteAccess.ts:335`: one 15-second heartbeat timer per remote-access process; one connection can register multiple Project/source bindings.
- `project_remote_access_service.py:24`: 45-second session timeout. `heartbeat_session:162` renews session state, updates team indexes where applicable, and loops over bindings to read/write their leases under a context lock. At 100,000 processes, a 15-second cadence implies roughly 6,667 heartbeat invocations/second; datastore operations exceed that. This is arithmetic, not a benchmark.
- `remoteAccess.ts:531`: reconnect backoff already includes random jitter. Preserve it; do not claim it is missing.
- Task context sync should not create a websocket, polling process or model turn per Task or Codex conversation.

Heartbeat interval, infrastructure idle limits and the existing 45-second liveness timeout must be considered together. Changing only the timer can falsely expire healthy sessions. Project sync needs separate capacity/fairness limits from the existing file-operation request budget.

Sources consulted: RFC 6455 (https://datatracker.ietf.org/doc/html/rfc6455), GitHub webhook setup (https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks), and Cloudflare websocket lifecycle guidance (https://developers.cloudflare.com/durable-objects/best-practices/websockets/). Cloudflare is evidence of scalable websocket patterns, not a hosting recommendation or required dependency.

Further clarification round 1 answered: keep scalability in mind, but do not spend significant time load-testing before work resumes. Large connection-count targets are future planning figures, not first-release gates. Prioritize a small real end-to-end campaign and essential failure/recovery checks.

## Further question 2: conversation ownership

User direction: one Task can be claimed/linked for execution by only one conversation at a time; only that conversation claims it for its own work. Other devices can see the link, but another conversation cannot take over the Task until the owner releases it. Ownership should follow the conversation rather than establishing a competing per-device Task owner.

Verified source: `cli.ts:848` tasks connect refuses a native-chat link, but does not refuse replacing a different existing external-chat link. It reads the requested Codex conversation and issues a normal versioned Task update. `user_task_service.py:151` and Directus methods provide optimistic version conflict protection, not exclusive conversation ownership. The new rule needs atomic ownership checks across every applicable update path. Existing account authentication alone does not authenticate the calling Codex conversation; actor-bound claim/release must be addressed by the integration, not trusted arbitrary --thread input.

Single-conversation ownership also needs one execution/wakeup path for that conversation; duplicated delivery to the same conversation is a separate issue from two conversations claiming one Task. Preserve the existing Codex execution host and reconcile ambiguous wake submission instead of launching replacement conversations.

“GitHub CI delivery” means routing a completed CI test result and its source-bound evidence to the existing owning conversation. It does not mean deploying code or automatically marking a Task done. Reuse the CI coordinator result cache; no per-agent GitHub polling.

Next clarification: explicit user recovery when the owning conversation cannot release a Task because it has been deleted or is otherwise unrecoverable.

## Further question 3 answered; creation and deletion requirements

User accepts explicit user recovery, and specifies automatic removal of all Task/Plan links when a Codex or native OpenMates conversation is deleted. Preserve Task/Plan records. Confirmed deletion is distinct from archiving, inactivity, missing visibility and an offline device. Native deletion should arrange durable backend cleanup; external Codex deletion requires an authoritative host/runtime signal and catch-up while the integration was offline. Prevent pending wakeups and stale updates from reattaching a deleted conversation. Ensure removing chat-specific wrappers does not remove remaining authorized access to retained encrypted records.

Task creation must include its linkage choice in the same creation write: default to current conversation, with an explicit unlinked option. No subsequent connect request should be necessary. This applies to native OpenMates and Codex agent creation; an ordinary terminal without conversation context must not guess a chat. Current creation API already accepts native/external context, and CLI accepts explicit --chat/--external-chat, but cli.ts:1062 does not derive current chat automatically. Current --as-assignee creation requires explicit Codex external context; support for explicitly unlinked agent creation needs reconciling with that path. An end-to-end command can still contain lookup reads today; one create mutation is verified, not a claim that the whole current command uses one HTTP request.

Rejected claims must identify the owning conversation title in quotes. Codex rejection includes its Codex chat ID. Native OpenMates rejection includes its chat ID and the real command `openmates chats show <chat-id>`.

The inspected native deletion handler queues persist_delete_chat. Its Directus delete method deletes the chat and cleans speech; no explicit Task/Plan unlinking was found in the inspected deletion path. Do not claim existing reliable cascade behavior without completing schema/path validation.

Next clarification (additional question 4): resulting status of an unfinished Task after its owning conversation is deleted. Proposed policy for discussion: in_progress becomes todo; done remains done; existing independent blockers remain blocked; no automatic worker creation.

## Additional question 4 answered; refined creation boundary

User approves deletion cleanup and its state transitions: confirmed chat deletion removes Task/Plan connections, returns in-progress Tasks to todo, preserves done and independent blocked states, and does not automatically create replacement workers.

User proposes a simpler creation boundary, adopted as the recommendation: ordinary OpenMates CLI creation stays unlinked by default; Codex explicitly supplies its current chat ID in the same create call using the existing --external-chat codex:<id> flag. This preserves one create mutation and avoids inferred shell context or a new --unlinked flag. Omit the external-chat flag for intentionally unlinked work. The previous proposed CLI default-to-current and --unlinked syntax are superseded.

Native OpenMates chats invoke skills/tools, never CLI instructions. Their task-creation tool defaults its native conversation link from authenticated tool context, with explicit no-link behavior. CLI advice for a Task owned by a native OpenMates chat is output for a Codex/CLI caller, not an instruction injected into the native conversation.

Next and final clarification (additional question 5): behavior during temporary OpenMates API/sync failure. Recommendation for discussion: continue already-owned approved work using explicitly stale context; queue status/activity writes durably; do not claim/reassign/start newly dependent work based on unconfirmed state. Synchronization bookkeeping must not create Stop-hook inference loops.

## Additional question 5 answered: transient outages and durable retry

User approves continuing already-owned work and requires a local queue that tolerates temporary OpenMates CLI/API unavailability, including server restarts. Report delivery failure only after repeated failures separated by time. Queue/retry is deterministic integration code, not agent polling. An unavailable executable needs the local queue writer to be independent of spawning that executable; actual transport delivery still uses the canonical CLI implementation/account context when available.

Recommended initial policy, configurable integration settings rather than Task fields: retry transient failures with jittered increasing delays, honor Retry-After and a shared account/API cooldown, and report persistent delivery trouble only after both at least five failed attempts and five minutes have elapsed. Then retain pending writes and reduce retry frequency; emit one actionable notice rather than repeated prompts. A recovered connection triggers catch-up and reconciliation. These thresholds are recommended defaults, not previously specified numeric user requirements.

An ownership rejection, invalid request or revoked credentials is not a transient server restart. Do not blindly retry permanent/semantic errors. In particular, re-read and re-evaluate version/ownership conflicts rather than overwriting someone else's changes.

Persist an operation identity and payload before attempting delivery. Reuse the same identity across retries, and reconcile uncertain server acknowledgements. Apply queued work in dependency order, preserve activity history, and do not coalesce away meaningful lifecycle transitions. Do not report queued status changes as server-confirmed. Claims require confirmation before work begins, even if the claim intent is queued. Cancel obsolete claim/wakeup intents after confirmed deletion or superseding user direction.

All five additional clarification rounds are now answered. Large-scale benchmarking remains deferred; verify outage/retry and duplicate-delivery handling in the small real campaign.
