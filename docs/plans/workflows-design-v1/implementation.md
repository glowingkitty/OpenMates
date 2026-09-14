# Workflow v1 implementation plan — approved and in implementation

Implement the updated Figma workflow experience in the web app, OpenMates CLI, npm SDK and Python SDK, including the necessary backend/API changes. Approved by the user on 2026-09-14; implementation is underway.

## Required real workflows

| Workflow | Required outcome |
| --- | --- |
| Daily, 09:00 | Weather for today, rain timing when applicable, and latest news in one new deterministic chat. |
| Every Sunday | AI events for the upcoming Monday–Sunday in the workflow timezone, delivered in a new chat. |
| Every hour | Apartment search, delivering only previously undelivered listings in a new chat. |

All three support manual execution for demonstration. Prepare clean disabled examples; preserve existing account workflows. Empty eligible content finishes successfully without an empty chat. A daily weather block can still be delivered when no new news remains. Concrete locations, search criteria and counts remain editable workflow inputs.

## Implementation sequence

1. **Align shared contracts.** Update the existing specifications and examples with the approved Figma design, per-node Save, optional testing of unsaved skill inputs, deterministic message templates and per-list Only new results. Keep one final Send message for the daily digest, with an optional Weather block bound to the Check's boolean result. No arbitrary template code.
2. **Build the web experience.** Fix start-screen copy/alignment, clipped previews and workflow icons; remove the extra top-right creation button. Implement compact expandable nodes, progressive trigger/app/skill/Check/chat selection, typed inputs and outputs, test feedback and contextual actions. Reuse shared cards, icons and theme tokens; verify desktop and responsive web layouts. Each explicit node Save persists a new workflow version; activation enables scheduling.
3. **Connect execution and skills.** Support once/hourly/daily/weekly schedules, timezone handling and run-relative dates. Normalize real Weather/News/Events/Home result schemas, counts and identities. Expose hourly rain information for deterministic messages. Ensure apartment searches actually select apartments and can discover new listings instead of repeatedly truncating to the cheapest results. Preserve error/partial/empty distinctions. Fix next-run timestamp drift and the observed run-history 429. Keep costs visible and ordinary skill charging consistent.
4. **Implement remembered deliveries.** Add run-owned, indexed keyed fingerprints with atomic pending reservations and acknowledgement-driven completion. For new chats, scope memory to the stable workflow and Send message step; existing-chat destinations remain distinct. Retry with stable chat/message/embed identities. Only selected delivered results become permanent embeds. Add run deletion with pending-write fencing and forgetting; existing chat messages remain. Payload expiry alone does not forget a still-visible run. Do not seed history from old fetched outputs.
5. **Deliver CLI/SDK parity.** Expose the same nodes, input/output types, save/test/run behavior, Only new results, delivery states and run deletion through REST, CLI, npm and Python. App-skill Test does not commit graph edits or alter sent-result memory. Message preview does not send; a full manual run exercises real delivery. Preserve immutable old versions and show unsupported legacy graphs clearly.
6. **Verify and deploy.** Run focused checks below, deploy the scoped changes to dev through the repository's session workflow, and provide the three demo workflows plus a short manual review checklist. Ask the user to test unresolved visual/provider behavior rather than expanding investigation indefinitely.

## Essential verification

- Focused unit/contract checks for node save and unsaved tests, date/hourly scheduling, typed output mapping, conditional messages and delivered-result lifecycle.
- One isolated end-to-end scenario per required workflow, including real chat output, plus concise CLI/npm/Python parity smoke checks.
- Duplicate lifecycle: first delivery sends A, repeat sends nothing, adding B sends only B; retries create no duplicate chat, undelivered failures do not suppress results, and deleting the sole remembering run makes its items eligible again while fencing late writes.
- Browser visual comparison with Figma on desktop and one narrow viewport, including long titles, expanded nodes and processing states. Use existing CI artifacts; no separate polished video production.
- Use isolated GitHub CI for product tests and local focused lint/type/build checks. No unrelated full-suite matrix. Final real provider behavior may be checked by the user when environment-specific access makes that more efficient.

## Delivery boundaries

General Filter nodes, Apple app, AI processing/authoring, App use/Webhook triggers, waits/loops, cross-provider apartment matching and general previous-value comparisons remain out of scope. Today's recurrence acceptance is once/hourly/daily/weekly; advanced monthly/ordinal recurrence and new budget-forecasting UI remain later work. Do not claim complete compliance with every older v3 requirement or assume unverified workflow budget caps exist; show current costs before activation.

Reliable sent-result memory begins with the new delivery implementation. Older example outputs cannot establish that a result was delivered and may therefore appear again once.

Only focused essential tests are required.
