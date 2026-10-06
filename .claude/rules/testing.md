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
REST/WebSocket, CLI/SDK and browser E2E run in the existing isolated GitHub CI
infrastructure, with one browser spec per job. Application E2E uses a disposable
Docker backend, runner-private localhost web process and fresh accounts. Specs
marked `reason=isolated_component_preview` use the GitHub Vite-only component
profile and start no backend, CLI build or production web build. Do not
launch a second CI scheduler, deploy before E2E, or use the shared dev stack for
these tests. Publish immutable source with `sessions.py ci-source`, submit with
`ci_coordinator.py submit`, then use `ci_coordinator.py wait <id>` or existing
result events. Inspect the scoped receipt on completion. Source and harness
identity must match the check; mocks and old runs are not new integration proof.

Exception: tests that strictly need real AI inference always run directly on the
dev server for now, never in CI. Use disposable accounts/Projects, temporary source
folders outside the repository, and isolated CLI state. Keep relevant non-inference
checks in CI. Deploy the scoped candidate through the session helper before its
live-inference verification; shared runtime changes require an explicit target
and coordinator lease. Record the deployed revision and actual live results.
Do not add a paid-provider CI profile or substitute replay for real-inference proof.

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

## Required E2E recording delivery

For every web/browser, component and OpenMates CLI E2E run used in this chat,
always download its existing recordings, upload them and include clickable video
links in the final response. This applies to successful and failed runs, retries
and every recorded profile. Include available failure recordings when reporting
a blocker. A passing test, GitHub run link, artifact archive or local file path
alone does not fulfill video delivery. This is required by default; it does not
depend on a Plan, a separate request or `--require-proof-video`. Honor an explicit
user waiver of recording delivery.

1. Wait with `python3 scripts/ci_coordinator.py wait <request-id>`. A successful
   wait downloads and validates the artifact under `test-results/ci-runs/<id>`.
   For failed/cancelled runs with a GitHub run ID, run
   `python3 scripts/ci_coordinator.py result <request-id>` to retrieve available
   artifacts; `wait` does not download those automatically. Reuse cached receipts
   instead of downloading them through a second path.
2. Run the receipt's `codex_evidence_command`, normally
   `python3 scripts/codex_evidence.py <directory> --upload`. It enumerates browser
   attachments and real CLI terminal recordings, including attempts/profiles,
   and uses the existing private, expiring response-media transport. Paste all
   returned video links in the final chat response, with the test/profile and
   result. Keep source/run identity attached to the evidence. Unit/lint/tooling
   checks do not need invented recordings.
3. If capture never started, a recording is missing, an artifact expired, or an
   upload fails, report the affected test and concrete reason beside its test
   result. Link available recordings and retain local artifacts for upload retry.
   Report verification and delivery separately; never claim video was delivered
   from a download/upload alone. Use `--ack` only with an actual delivered chat
   message ID; leave delivery pending when the client does not expose one.
4. Keep Playwright video capture enabled for E2E, including passing attempts.
   CLI E2E must retain actual terminal-screen recordings using the existing
   `cli-tui-proof-helpers.ts` / `cli_video_capture.py` helpers. A blank browser
   video from a headless CLI test or replayed stdout is not CLI video proof.
   For authorized dev-host real-inference runs, deliver their retained recordings
   with `response_media.py <video-path> --output markdown`; the CI requirement
   does not move these tests into CI.

Extra proof-video editing, captions, additional device profiles, frame review and
visual-smoke production follow the accepted task/Plan or explicit request through
`create-demo-video`. They do not make delivery of existing E2E recordings optional.
Do not rerun a test solely to repair an upload or refresh an expired media link;
retry/re-upload the retained artifact. Never publish private production evidence
or unredacted personal data; report withheld evidence with its reason.

The explicitly authorized real signup-email smoke remains a dev-host check with
isolated CLI state. It is separate from CI signup and must not replace the global
engineering Tasks login. Runtime restarts for deployment use the scoped session
helper and preserve shared-resource leases.

Record an explicitly requested edited/captioned proof-video deliverable with
`sessions.py update --require-proof-video` (or the same flag on `start`). Ordinary
E2E recording delivery remains mandatory without this additional workflow gate.
