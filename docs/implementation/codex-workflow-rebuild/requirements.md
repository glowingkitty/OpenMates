# OpenMates CLI + Codex workflow rebuild

Decision record and implementation checklist · 10 September 2026

This is the current planning record. It supersedes earlier scope/readiness summaries where they conflict. Checked decisions mean agreed, not implemented. Implementation steps stay unchecked until verified. We are clarifying requirements; the existing Landing workers remain paused.

## Work order and scope

1. Record decisions and build the real Specification fullscreen component preview from the user's Figma draft.
2. Clarify Specification structure/templates through that preview.
3. Clarify Plan structure.
4. Clarify Checks execution, GitHub authorization, capacity and artifact retention.
5. Finalize this plan, implement the agreed CLI/backend/Codex changes and test a two-worker pilot before resuming broader Landing work.

The main rollout concerns CLI, required backend/remote-access capabilities, Codex and PDF generation. The user explicitly added a scoped web exception: implement/iterate the actual Spec fullscreen component through `/dev/preview`. Full web editors and broad Plans/Checks UI remain outside the current scope unless subsequently authorized.

## Agreed requirements

### Tasks, cache and orchestration

- [x] OpenMates Tasks are authoritative. Use existing status, blocker and dependency fields; do not introduce a Task “next action” field.
- [x] Workers mutate Tasks through the globally installed OpenMates CLI, using the personal dev-testing account and OpenMates Project. Native OpenMates chats use tools/skills, never CLI instructions.
- [x] CLI Task creation is unlinked by default; an explicit current-chat ID creates and links in one operation. Native Task creation links its current chat unless explicitly disabled.
- [x] One conversation owner per Task. A competing claim identifies the quoted chat title and Codex ID, or the native chat's view command. Never replace ownership silently.
- [x] Linking reserves ownership. Explicitly starting work may link and set In progress atomically. Preserve independent approval/dependency blockers.
- [x] Short-ID lookup must not enumerate hundreds of Tasks. Use an account-scoped local index plus targeted server lookup/validation. Server ownership and version checks remain authoritative.
- [x] Persist mutation intent before vulnerable lookup/transport stages. Cover create/edit/link/release/activity/block/unblock/completion. Reconcile uncertain acceptance, retain identity, use delayed shared retries, distinguish pending from acknowledged.
- [x] `remote-access` owns continuous encrypted Project Task sync, durable disk cache and recovery while running in the foreground, for example under Zellij. Do not copy full repositories into OpenMates simply to attach them.
- [x] Inject all linked Tasks, full titles, state, blockers and dependencies; shorten descriptions and latest activity. Include the orchestrator's registered workers and their Tasks. Read disk; inject changed content at supported context boundaries, not complete inventories per tool call.
- [x] Ordinary CLI output is concise text. Include Task title and chat title. Use JSON only when a program needs to parse it. Offer explicit detail/log commands.
- [x] Workers continue directly necessary in-scope repairs. A substantial discovery becomes a separate Task and coordinator scope decision. Product changes, added spending and material expansion come to the user.
- [x] Important decisions are recorded as Blocked with a concrete reason. The coordinator is the normal user interaction point and routes scoped decisions back to workers.
- [x] Cheap deterministic checks detect events. Notify promptly for needed user decisions; combine nearby requests. Summarize meaningful progress at most every 15 minutes, staying silent if unchanged.
- [x] Dependency/CI readiness goes directly to an eligible worker. Preserve manual pauses, deduplicate events, never blindly “continue” an idle worker.
- [x] After rebuilding, limit the pilot to **two workers**. Increase only after user approval. This is separate from CI job capacity.
- [x] Simplify conflicting/long instructions in place, with one authority per policy. Prefer deterministic setup, validation, status, retries and artifact processing over model work.
- [x] Chat creation must be checked for usable metadata, persisted results and sync. Missing titles/request errors must not cause unlimited replacement chats or repeated expensive generation.

### Due-date notifications

- [x] Implement Task due-date email notifications; do not confuse them with scheduling native AI Tasks.
- [x] Investigate why the dev-testing account reports notifications disabled despite prior activation. User authorized enabling notification email for the global CLI account and testing real inbox delivery.
- [x] Keep isolated GitHub signup tests independent of Brevo. Real deployed email checks run only on the dev server with isolated test state; never replace the global Tasks-account login.
- [x] Keep the broader debugging/testing discussion separate. Created `TASK-2642`, “Discuss debugging and testing workflow improvements”, due 11 September 2026 at 16:00 Europe/Berlin.

### Specifications

- [x] Dedicated encrypted Spec identity/revision records for native content; source-backed Specs live as `{name}.spec.yml` files on the attached source. Reuse the existing Project plus optional source model.
- [x] Support targeted edits of requirements/sections without making the agent supply the entire document. Deterministic client/daemon code owns validation, encryption and conflict-safe persistence.
- [x] Readable requirement addresses include Project and Spec, e.g. `openmates.tasks.status.save-failure`. Preserve stable internal identity across display-name changes.
- [x] Revision checks happen automatically in normal CLI use. Explain conflicts in plain language; never silently overwrite intervening edits.
- [x] Include three initial templates: General, Software Architecture, Design. They share one core model; detailed starting sections are still being clarified.
- [x] The core document has an **Outcome**, **Scope & boundaries**, then one or more custom sections containing suitable Requirements, User flows, Edge cases and Relevant models.
- [x] User flows and edge cases remain children of their Spec, not separate embed records or independent data models. Reuse the shared embed preview UI; clicking opens the shared fullscreen UI with that child’s content. Closing returns to the Spec. Presentation must not trigger embed lookups, sync or persistence.
- [x] Models are referenced once canonically. Web reading links to model/code embeds; PDFs include the relevant model definitions.
- [x] Requirement examples are concise prose or actual commands/code with expected outcomes. No flattened dictionary tables as examples.
- [x] Checks link evidence to specific requirements. PDF checkboxes derive from exact revision-matched results; include Check/test links and evidence-as-of time. Unverified, stale, failed and waived evidence must not be presented as proven.
- [x] For Design Specs, describe components, requirements, states, interactions, accessibility and responsive behavior. Show wireframes initially and verified isolated screenshots later; preserve earlier references in history. PDFs embed component screenshots and link interactive video proof.
- [x] Iterate the real fullscreen component via `/dev/preview` instead of further Markdown layout mockups. Use the supplied Teams Figma draft as the current visual reference.

### Plans

- [x] Plans describe how to reach the intended Spec state and link exact requirements rather than copying all Spec content.
- [x] Tasks remain executable work units; Plans do not maintain duplicate Task status.
- [x] Exact revision approval and material-scope boundaries remain required. Plan structure and review experience are the next clarification topic after Specs.
- [x] Redesign exported Plan PDFs using the clarified structure and the user's design input.

### Checks, execution and proof

- [x] Checks belong to a Project and can link to Specs and Plans. A Check covers a meaningful area with one or more test files/suites, not one record per unit test.
- [x] Provide filtered lists by Project, Spec and Plan. Catalog/index tests by source revision without materializing thousands of Check records.
- [x] One CLI command starts a Check. Background infrastructure handles admission, execution, results, video processing/upload and completion delivery.
- [x] Passing list entry: title + Passed. Failure: failed linked-source count when multiple are linked, failed filenames, concise reasons and run-specific detailed-log command. Distinguish files/sources from individual test cases.
- [x] Keep at most the last three video clips per test; exact handling of device profiles remains unresolved. Preserve Run/provenance history and visibly expired media.
- [x] Use a GitHub account connection/GitHub App installation authorized by the user, once per relevant account/organization. No implicit use of the operator's personal GitHub account for other users.
- [x] Queue rapid submissions and respect provider rate limits while making efficient use of runner capacity. Detailed repository binding, capacity accounting/headroom and billing explanation are deferred until the Checks discussion.
- [x] Preserve the current isolated GitHub testing setup as the execution foundation. Do not conflate two Codex workers with GitHub concurrency.

### Component-first UI workflow

- [x] Projects provide an isolated component preview/test harness. Reuse OpenMates `/dev/preview`; support an equivalent native host for Apple components.
- [x] Test meaningful interactive components in focused web `.spec.ts` or native UI tests, record interactions/hover/focus states and present evidence for user review through the coordinator.
- [x] Truly static components may use a loaded browser/simulator screenshot without video.
- [x] Test full integration flows after component verification/review, avoiding mechanical repetition while retaining essential cross-component/navigation/data/persistence assertions.
- [x] Verify web/Apple design parity when required by the Project, with explicit approved platform differences.

## Implementation sequence and acceptance tests

### A. Specification preview — current authorized work

- [ ] Build a shared-model fullscreen component using the existing embed shell and preview system.
- [ ] Use real Teams Spec content and clearly labelled sample proof states; do not imply real coverage was verified.
- [ ] Show outcome, boundaries and custom sections, readable requirements/applicability, flows/edge cases and model references.
- [ ] Use shared preview cards for flows and edge cases with a local fullscreen transition; retain requirement/model details for discussion without backend records or account data.
- [ ] For this discussion draft, verify loading and flow open/close on the live preview, then share the URL. Full responsive testing and proof-video production are deferred until the structure is agreed.
- [ ] Ask the next clarification about document structure after presenting the result.

### B. Reliable Task operations and concise instructions

- [ ] Replace bulk short-ID resolution in CLI and backend lookup paths; test account isolation, misses, stale cache and ambiguity.
- [ ] Add atomic link-and-start; test conflicts, same-owner idempotency and blocker preservation.
- [ ] Extend durable retries to preflight failures and all required mutations; reproduce HTTP 429 before enqueue, lost replies, restart recovery and block/unblock failures.
- [ ] Implement compact default receipts/list views and explicit detail commands; verify bounded output and zero unnecessary inventory requests.
- [ ] Remove conflicting instructions and repeated bootstrap reads; verify one clear coordinator/worker policy.

### C. Event and approval loop

- [ ] Complete coordinator decision routing, deduplication, acknowledgement and scoped unblocking.
- [ ] Add change-based digests, immediate actionable blocker events and deterministic waiting/reconciliation.
- [ ] Unify dispatch permissions and event delivery; verify manual pause preservation, no duplicate wakes, outages and new-chat startup readiness.
- [ ] Test chat title/result persistence and cross-client sync using controlled data before broader generation.
- [ ] Run only the approved two-worker pilot, inspect Task state and token/context growth, and stop expansion when correctness is uncertain.

### D. Spec/Plan storage and CLI

- [ ] Finalize schema/template decisions, update governing specifications and supply reviewable PDFs where required.
- [ ] Implement encrypted Spec records/revisions, source mappings, import/export and targeted CLI edits.
- [ ] Add safe remote source writes with revision checks, scoped authorization, atomic replacement, explicit offline/pending state and replay tests.
- [ ] Reconcile existing Plans code with the agreed model; avoid duplicating Tasks or Check definitions.
- [ ] Build the revised PDF presentation with deterministic requirement/evidence/model rendering.

### E. Checks and GitHub

- [ ] Finalize GitHub connection/binding, owner capacity, retry, result and retention decisions.
- [ ] Implement reusable Checks/source links and revision-bound Runs using existing CI execution infrastructure.
- [ ] Add account-scoped admission and completion delivery; test rate-limit cooldowns, matrix job accounting, concurrent devices and uncertain dispatches without a large load-testing campaign.
- [ ] Automate artifact processing/publication and retention; test failed upload retry without rerunning the test, correct account scope and expired links.
- [ ] Verify test failure versus infrastructure failure and exact requirement coverage before rendering green proof boxes.

### F. Due-date emails

- [ ] Reproduce/read-write-read/relogin-test notification preferences before overwriting evidence of the suspected bug.
- [ ] Implement due notification scheduling, deduplication, timezone handling and changed/completed/deleted Task behavior.
- [ ] Enable notifications for the authorized dev-testing account and verify a real controlled inbox receipt. Do not count queue acceptance as delivery.

## Open decisions — continue one at a time

Q1–Q6 are answered, with GitHub details explicitly deferred. The next discussions should follow the user's requested order: Specs → Plans → Checks/GitHub.

- Spec custom sections: which elements are optional versus required for approval; template starting structure; model placement and reference behavior.
- Plan sections and review/approval workflow within the CLI/PDF rollout.
- Check retention key across phone/laptop/Apple recordings; evidence expiration and completion eligibility.
- GitHub repository/account boundary, available parallelism, configured budget/headroom and installation onboarding details.
- Due-email timing/content and exact notification preferences, without exposing private Spec/Task content to the server.

## Current limitations, not completed claims

The audit found pre-queue 429 failures, bulk Task lookup, unqueued blocker changes, worker polling, incomplete coordinator approval routing and conflicting instructions. Existing architecture foundations are deployed, but these issues remain until their checks above pass. Spec/Plan/Check product readiness is partial. Notification emails were disabled in the inspected account and no Task due-email handler was found. No new worker was resumed for this planning/UI iteration.
