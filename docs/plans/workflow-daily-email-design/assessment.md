# Daily Workflow email audit

Reviewed 2026-10-28 in session f4fe. Task: TASK-3248. This is source investigation
and a proposed plan; no mail behavior or preferences were changed and no test
email was sent during this audit.

## Reminder work already completed

The implemented reminder context supports chats, events, appointments, travel
connections, travel stays, home listings and generic saved embeds. New-chat task
reminders and legacy saved prompts retain their supported fallback. The same
sender handles scheduled occurrences, including repeated reminders. Chat and
event test emails have provider-confirmed delivery; the other item kinds use the
shared tested context/renderer path, rather than separate live-mailbox proofs.

The approved shell, bell, identifying subject, title alt text, readable
description/facts/note, linked preview and separate action are implemented.
Explicit hide-content choices remain effective, and missing legacy metadata is
not fabricated. Dev gateway persistence is directly verified; the user's
production file output confirms the saved reminder route. This is separate from
verifying every production sender or inbox.

## Existing Workflow implementation

| Area | Observed behavior | Source |
| --- | --- | --- |
| Cadence | Daily 09:00 UTC dispatcher; current dev scheduler contains this registration | backend/core/api/app/tasks/celery_config.py:1611 |
| Window | Fixed previous 24 hours, selected by accepted_at | backend/core/api/app/services/workflow_digest_service.py:28 |
| Scope | All scheduled Workflows for one user; manual/test/event runs excluded; empty windows send nothing | workflow_digest_service.py:68; workflow_digest_email_task.py:47 |
| Status | Successful, failed, cancelled, waiting, queued and running states; chat delivery outcomes remain separate | workflow_digest_service.py:113 |
| Bounds | Complete selected-run totals, but only the oldest 50 runs appear individually | workflow_digest_service.py:119 |
| Privacy | Verified account address and fresh preferences; Workflow names and intended message excerpts require explicit includeContent consent | workflow_digest_email_task.py:51; workflow_digest_service.py:175 |
| Dedupe | Durable user/date digest identity, fixed-cutoff bounded retries and transport guard | workflow_digest_email_task.py:130 |
| Extra email | Every successful scheduled run queues completion dispatch, which sends per-run email when eligible using run_id identity | backend/core/api/app/tasks/workflow_tasks.py:247; workflow_completion_notification_service.py:372 |
| Design | Shared brand header/footer and gray shell, but a text-heavy per-run list without the reminder bell or compact Workflow cards | backend/core/api/templates/email/workflow-run-digest.mjml:10 |
| Disclosure | Current settings explicitly promise completion emails plus a daily summary | frontend/packages/ui/src/i18n/sources/settings/chat.yml:856 |
| Contract | Current completed-delivery assertion expressly requires immediate email independently of the digest | specifications/features/notifications/specification.yml:200 |

At 09:00 UTC, Berlin local time is 10:00 in winter and 11:00 in summer. The
existing schedule is not a per-user local-time setting.

## Confirmed gaps and follow-up risks

1. A user can receive N automatic completion emails plus the daily digest. The
   two paths have separate passing tests, but no combined one-total-email test.
2. A run accepted before the window but finishing inside it is omitted. A run
   reported as waiting today is not included tomorrow merely because it finished.
3. Frequent runs are listed individually, making the email long and potentially
   consuming its 50 displayed rows before other useful activity is shown.
4. The digest shares the older shell but lacks the approved reminder treatment.
   The standalone completion email is also an older, separate template.
5. Title consent is coupled to detailed content. A useful identifying-title
   policy must be decided explicitly rather than silently widening consent.
6. Current bounded retries do not provide historical-window catch-up or durable
   sweep-wide recovery. Current-window recovery should avoid a backlog email burst.
7. Pagination robustness under lower effective page caps is a risk to test, not
   a demonstrated production loss. Existing coverage lacks more-than-200 run and
   delivery cases and the full combined no-flooding scenario.

The explicit Send email Workflow action currently fails closed. It is a separate
capability gap and does not currently add another working flood path.

## Recommended implementation sequence

1. Revise the existing notification cadence contract and examples; retain push
   and history semantics. Settle basic-title consent and activity-window meaning.
2. Suppress automatic per-run mail and terminate/reclassify old pending email
   outboxes so reconciliation cannot emit the old behavior after deployment.
   Cover already-queued completion jobs and old workers that already loaded their
   send state with coordinated worker drain/rollout or a compatible final send
   gate. Preserve historical sent state and pending event/push reconciliation;
   changing database outboxes alone cannot stop an old sender already in flight.
3. Improve the existing digest collection: activity overlap, grouping, complete
   counts, bounded cards, stable pagination and recovery of the current window.
4. Reuse the reminder/newsletter shell, bell and orange actions. Adapt the actual
   Workflow preview's icon/title/status hierarchy to email-safe HTML cards with
   readable text. Include a daily summary and direct authorized detail links.
5. Update settings copy/translations and the combined regression, then run scoped
   unit/render checks and isolated SMTP/navigation/desktop/phone coverage. After
   implementation approval, verify one real dev test digest and record its result.

Previous verification records show the daily digest passed isolated SMTP runs
36923312588 and 37779193320. Completion integration run 37818253956 explicitly
accepted separate emails for two scheduled runs. These are historical recorded
results, not newly executed tests or proof of current production inbox delivery.

The [draft plan](plan.yml) records the proposed scope and required checks.
