# Prevent silent stalls in work chats

**Approved on November 24.** Ship the connector fix first, then progress, checked deadlines, two recovery attempts and alerts. Enable each change on dev after its stall simulation passes.

## What happened on November 24

A chat can say “working” because a turn or process is open, even when nothing is moving the job forward. A chat can also say “waiting” without any component responsible for delivering the result or handling a missed deadline. The lifecycle, connector, waiters and watchdog each have part of the picture. A wake request can look successful before a new step occurs.

| Incident | Evidence and cause |
| --- | --- |
| Production release waited on an installer | Marco reported roughly two hours with no step during an outage. A live Codex turn was enough to show “working.” There was no progress checkpoint for the installer and no release-specific deadline to trigger recovery. |
| Live collaboration had an unsent draft | Marco reported six hours without a step. The delivery log shows one message held by the draft and another unseen by the session. The connector protects drafts but has no save-and-deliver path or deadline for this conflict. The open turn hid the delivery failure. |
| Four handoff or dependency waits timed out | Lifecycle records showed expired waits, several of them owner decisions, and one chat also had a ready dependency. A timeout label alone advances nothing. An internal handoff needs a component responsible for completion and timeout handling. An owner decision needs an accurate “Needs Marco” state and must stay protected. |
| Two wake attempts failed to resolve a Task | The lifecycle reported “No unambiguous open Task for the stopped source.” Recovery tries to find an eligible Task when it wakes, after links or status may have changed. Without a recorded full Task UUID, multiple candidates can prevent a safe wake. |
| Work became ready while a chat needed Marco | The lifecycle correctly held the owner decision open when a dependency finished. A single wait label mixed the two states. The result needs to remain ready for delivery after Marco answers, with no automatic wake or new stall alert for that decision. |
| Two CI waits passed their deadlines | One CI runner was still active when the lifecycle recorded an overdue event. Marco reported the same pattern on another chat. The waiter deadline can expire before the runner finishes. A missed check-in needs to query the recorded job and preserve its eventual result. |
| Connector messages went undelivered | Marco reported the Slides delivery. Another delivery record says the process exited before the chat took the message. Queueing and typing are intermediate states. Delivery needs an observed receipt, recovery when a process exits and a deadline when a message stays unseen. |
| The recovery watchdog missed the incidents | The new watchdog runs on the half hour. Its existing notice path is tied to selected recovery failures. An active but quiet turn can be left for inspection, and a submitted wake can count as recovery before the chat takes a step. Half-hour polling also cannot meet a ten-minute release deadline. |

The evidence comes from chat lifecycle status, registered waiters, connector delivery records and the watchdog unit and journal. The Task activity records the private incident references. Where a duration or example came from Marco, the table attributes it to him.

## Smallest changes

| Change | Behavior and acceptance check |
| --- | --- |
| Make connector delivery recoverable | Preserve and verify a conflicting draft in protected local storage before touching the composer. Deliver in order, wait for evidence the chat received the message, and restore the unsent draft when safe or tell Marco where it was saved. After 10 minutes unseen, enter the same recovery path, even if the chat otherwise looks active. Keep draft and message content out of logs and pushes. |
| Record progress for both engines | Read the existing engine events and store the last meaningful step separately from process or terminal activity. A tool result, accepted message or confirmed dependency transition counts as progress. Check every minute for 30 minutes without progress on ordinary work, or 10 minutes on a tagged production release or rollout. A reported live dependency can defer escalation, with its next check visible. |
| Give waits an owner and an effective deadline | Store the wait type, responsible component, next check, deadline and full Task UUID, plus the job or successor reference when known. A deadline makes the coordinator check the source and record an outcome. Live CI renews its check-in. Terminal CI and completed handoffs deliver their result once. Carry the exact Task and worktree binding into recovery. Show ambiguity explicitly and preserve the work. |
| Put one coordinator in charge of recovery | Existing watchers report events to the coordinator. It records one incident per stall, attempts a normal wake and checks for a new step. If still quiet, it refreshes the Task, wait and last-step context and attempts a second wake. Use a fresh chat only when it can safely take over the worktree. For a production incident recheck after two minutes per attempt, and after five minutes for other work. If a wake is unsafe or both attempts fail or stay quiet, record the reason and send one push. Persist attempt and notification state across restarts. |
| Make unresolved work visible | A push names the chat, wait reason, last confirmed step and what recovery tried. Merge delivery and progress failures for the same incident. Close it only on relevant progress or a terminal outcome, so repeated scans do not repeat the push. Add a daily list of unresolved stalls, pending deliveries and “Needs Marco” decisions, with the next action and its owner. Owner-only waits receive no stall push. |
| Classify automatic notices | Apply the shared [alert contract and examples](alert-examples.md) to the watchdog, voice post-update check and related host helpers. Check fresh Task state before alerting, retry blocked checks, and distinguish setup failures, failed checks and confirmed breakage. |
| Verify and roll out | Exercise both engines with a fake clock and controlled chat, CI and delivery events. Capture the simulated stall output, including one push for a simulated stall and no push for protected or recovered cases. |


## Tests and rollout

1. Enable draft rescue and delivery tracking after a conflicting draft, a process exit and a ten-minute unseen delivery pass their simulations.
2. Enable progress tracking after its checks pass. Verify that an idle installer triggers the 10-minute release threshold, an ordinary silent turn reaches 30 minutes, and a genuinely live dependency stays visible with its next check. Check that an explicit owner wait stays protected when a result arrives.
3. Enable checked waits and recovery after testing both engines. Simulate an unfired handoff, an ambiguous Task, a still-running CI job, a late CI result and watcher restarts. Verify that deadlines cause an action or a visible block, competition produces one wake path, and work is preserved.
4. Enable the daily list and final notification after their checks pass. Simulate normal wake recovery, fresh-context recovery and two unsuccessful attempts. Verify the notice content and deduplication across scans and restarts. Test suppression for completed chats, a blocked signed-in voice check, a guest check failure in the same run, and an unchanged repeat.  Keep the coordinator's recovery and notification switches separate so either can be disabled while retaining status and evidence.

Keep any suppression of production DOWN alerts as a separate rollout decision. A planned restart flag would identify the rollout, expire automatically and leave monitoring active. An outage that outlasts the window would alert again.
