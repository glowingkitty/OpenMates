---
description: Maintain relevant E2E coverage and verify within task scope
globs:
---

# Verification

Every behavior fix or new feature updates the relevant E2E coverage. Extend an
existing case when appropriate; add a focused case when none covers the intended
behavior. Do not request separate permission for routine test maintenance within
an authorized implementation. A purely mechanical/docs change needs no invented
E2E case. Explicit user instructions override this default.

Confirmed browser observations, logs or existing failing checks are sufficient
to begin a fix. Investigate only remaining uncertainty; do not require a fresh
failing baseline or approval to reconfirm a known bug. Preserve useful before
measurements and verify the affected path after the fix.
Keep unit checks for the underlying cause; a fixture-only banner/component test
does not establish that the reported end-to-end failure is fixed. Use existing
contract-test metadata and stable assertion IDs for product tests; classify
engineering/tooling tests as such. Never weaken assertions to force a pass.

Focused unit, lint and build checks run in the isolated checkout. Product
REST/WebSocket, CLI/SDK and browser E2E run with the full Docker/web application
stack in the existing isolated GitHub CI infrastructure, with disposable test
accounts. Do not launch a second CI scheduler or use the shared dev stack for
these tests. Publish immutable source with `sessions.py ci-source`, submit with
`ci_coordinator.py submit`, then use `ci_coordinator.py wait <id>` or existing
result events. Inspect the scoped receipt on completion. Source and harness
identity must match the check; mocks and old runs are not new integration proof.

Choose checks for the actual changed behavior and affected clients. Shared API
changes need relevant API/client coverage; a web-only fix does not create an
automatic Apple-verification ladder. Use existing test helpers, fixtures and
data-testid selectors for reliable UI interaction. Reuse regression coverage.

Keep debugging bounded by the original acceptance criteria. After two failed
attempts with the same approach, reassess before another attempt. When the cause
is unrelated infrastructure, expected behavior is uncertain, or repair would
materially expand the task, explain the finding and ask the user before resuming
that expanded work. Keep the implementation and test evidence available. Do not
turn one product fix into a test-infrastructure repair campaign without approval.

Honor execution waivers (`skip E2E`, for example) and report what was not run.
An execution waiver does not waive updating the relevant E2E coverage unless the
user says so. Ask if the user instruction itself leaves that distinction unclear.
Do not claim a pass from a queued, cancelled, unrelated or stale run.

Return useful existing CI artifacts and failure evidence using the current
client's supported links. Proof-video captions, extra profiles and visual-smoke
production are required only by the accepted task/Plan or an explicit request.
Do not rerun a passing test solely to repair an upload; retry the upload itself.
Never publish private production evidence or unredacted personal data.

The explicitly authorized real signup-email smoke remains a dev-host check with
isolated CLI state. It is separate from CI signup and must not replace the global
engineering Tasks login. Runtime restarts for deployment use the scoped session
helper and preserve shared-resource leases.

Record an explicitly requested video deliverable with `sessions.py update
--require-proof-video` (or the same flag on `start`).
