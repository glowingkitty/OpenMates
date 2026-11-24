# Automatic alert wording and suppression

## What the three alerts meant

| Alert | Evidence | Impact and action |
| --- | --- | --- |
| Dev voice check | The signed-in check stopped during test-account setup. Its receipt says the dev API container was stopped, although the alert reduced the error to “lease unavailable.” The same run's guest check separately timed out waiting for the user's message to appear. The prior dev revision passed both checks. | The signed-in call wasn't exercised on this revision. The guest check did fail, and the evidence does not establish whether the failed check reflects a voice regression. Retry the signed-in check when the API is up and retry the guest check with its own evidence. No action for Marco while those retries can run. |
| Prod monitoring alerts and recovery | The chat reported completion and stopped normally. The 13:00 UTC watchdog run classified it as stopped with an open Task. Its attempt to reopen the chat was refused. The exact linked Task is Done, the worktree is merged, and the Task's short number is ambiguous across the Task list. | The notice is about reopening a completed work chat. It is no evidence of a production monitoring outage. Suppress it after checking the full Task link and completion state. |
| Pinch zoom fix for all images + dropdown colours | The continuation had reported the workspace picker fix on dev and stopped normally. The same watchdog run tried to reopen the chat. The exact linked Task is Done and its worktree is merged. | The notice is about reopening completed work. It is no evidence of an image zoom or picker failure. Suppress it after checking the full Task link and completion state. |

The watchdog can use a Task snapshot up to two hours old to nominate candidates. Its restart guard collapses a closed Task, a lookup error and a conflicting chat link into one sentence. We know both linked Tasks are now Done. The generic failure result does not distinguish which condition each restart hit at the time. Voice reporting similarly flattened setup and flow failures, then showed only the first failed leg.

## Before and after

The first line is the phone preview. The following details are for the expanded push or linked proof. The two completed-chat examples belong in the daily list during rollout verification and are suppressed from Discord.

| Original first line | Proposed first line | Expanded detail and next action |
| --- | --- | --- |
| Dev voice check failed after deploy: signed-in call, lease unavailable. | **The dev voice check is incomplete after the update.** | The check could not set up a signed-in call while the dev API was stopped. The guest call check ran but timed out waiting for the message. A voice outage is unconfirmed. The checker retries both when the API is ready. Nothing for Marco to do yet. Combine both outcomes in one notice only if a retry cannot resolve the check or confirms a problem. |
| Chat recovery: the linked Task is closed, unavailable or owned by another OpenMates chat. | **Prod monitoring alerts and recovery finished normally.** | The watchdog tried to reopen the chat after it finished monitoring work. The Task is Done and the changes are on dev. No monitoring outage was established by this incident. No action needed. Suppress the push. |
| Chat recovery: the linked Task is closed, unavailable or owned by another OpenMates chat. | **Pinch zoom fix for all images + dropdown colours finished normally.** | The watchdog tried to reopen the continuation after it finished the workspace picker fix. The Task is Done and the changes are on dev. No action needed. Suppress the push. |

If retries confirm a guest regression on dev, a first line can read “The dev guest voice check still fails after a retry.” The expanded message gives the check and environment, the last successful step, the retry result and any decision the system cannot make, such as “Hold the next production rollout until the dev voice check passes.”

## Implementation and tests after approval

- Inventory outbound Discord calls in the watchdog, handoff and delivery helpers, the voice checker and its post-update siblings. Use the same format and deduplication rules for every automatic operational notice from those helpers. Keep existing urgent outage escalation paths available.
- Before recovering a stopped chat, use its full Task link and fresh completion evidence. A closed or superseded Task with no unfinished work closes the incident. A failed Task lookup calls for a retry. Keep an unresolved handoff visible when the chat still has work to do.
- For post-update voice checks, record a blocked setup separately from a test that ran and failed. Use typed outcomes from the two legs. Retry only unresolved legs against the same served revision when prerequisites are ready. Apply a bounded deadline, honor capacity limits and supersede stale checks when another revision is served.
- Use a short first sentence in ordinary words. Name the chat by its display title when a chat is involved. Use the check name and environment for automated tests with no chat. Expanded details give the job, last step, recovery attempt, verified impact and who should act. Keep IDs, internal errors, and private inputs in the evidence.
- Send a push on a new actionable result or material change. Combine failures from the same run or chat episode and suppress unchanged repeats. A completed chat, a retry that is still underway and a duplicate notice stay in the status list. If later evidence resolves a previously reported problem, send a recovery notice only when that changes what Marco should do.
- Use fixtures for these three incidents, a confirmed voice failure, a later successful retry, a temporary Task API outage and a genuinely unfinished chat. Check that the first line excludes internal terms and IDs, the same event sends once, and closed Tasks and automatic retries stay quiet.
