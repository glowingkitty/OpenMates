---
paths:
  - "**/tests/**"
  - "**/__tests__/**"
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "**/test_*.py"
  - "apple/**/*Tests*/**"
  - "scripts/ci_coordinator.py"
  - "scripts/ci_evidence.py"
  - ".github/workflows/**"
---
# Verification

## Coverage
- Every behavior fix/feature updates relevant E2E coverage: extend an existing
  case or add a focused one. Mechanical/docs changes need no invented case.
  Routine test maintenance within authorized work needs no extra permission.
- Keep unit checks for the underlying cause; a fixture-only component test does
  not prove an end-to-end failure is fixed. Use existing `contract-test`
  metadata and stable assertion IDs; classify tooling tests as such.
- Changed web UI: the focused component spec on the `/dev/preview` page
  (`tests/components/`, `/verify-component-preview`) runs and is green, with its
  screenshots viewed and sent to the user, before any route-level or full E2E
  spec is submitted.
- Never weaken assertions to force a pass. Do not claim a pass from a queued,
  cancelled, unrelated or stale run, or from mocks/replays.
- Honor execution waivers (`skip E2E`) and report what was not run; a waiver
  does not waive updating coverage unless the user says so.
- Project names: tests, fixtures, scripts and manual checks of Project features
  use clear natural-language names a person would choose ("Kitchen
  renovation", "Spanish lessons"), never timestamps, random ids or bare
  numbers. For uniqueness use `naturalProjectName(topic)` from
  `frontend/apps/web_app/tests/helpers/project-names.ts` (adds a word nickname,
  not digits). Digits only when the check is about digits, e.g. a reference
  number in a name for a privacy regression.

## Where checks run
- Locally in the worktree: lint, `tsc`, `cargo
  fmt/metadata/tree`, and pytest of `scripts/` tooling (light; still refused
  while the host is overloaded).
- Builds, unit tests and benchmarks (`cargo build/test/check/clippy/run/bench`,
  `rustc`, `wasm-pack`, vitest, `svelte-check` (several GB per run),
  `vite`/`svelte-kit`/`pnpm build`, local
  headless-browser benches) may run on the dev server only through
  `python3 scripts/heavy_slot.py run -- <command>`: it waits until
  `host_load_guard` reports a healthy host, allows at most 2 heavy commands
  host-wide at once, starts one only when its 6 GB fit in free memory, and runs
  each in a systemd scope capped at 4 CPUs and 6 GB RAM with low priority. One
  heavy command per chat at a time; parallel lanes queue, they never bypass it. `.claude/hooks/bash-guard.sh` blocks direct runs.
  The same wrapper runs `cargo test/check/clippy` (host target) and `vitest`
  without `-u` in an E2B sandbox (8 CPUs, 8 GB, no local slot): it uploads the
  worktree's differences from the template baseline and streams output and exit
  code back. Write such commands directly (`cargo test -p openmates-sdk`,
  `pnpm --dir frontend/packages/ui exec vitest run <file>`, or `bash -c "cd DIR &&
  CMD | tail -N"`); other shell syntax runs locally. If E2B is unavailable it
  says so and runs locally; `--local` forces a local run. Refresh the template
  with `heavy_slot.py remote-template` when it reports a stale baseline.
  Prefer isolated GitHub CI (`ci_coordinator.py submit --mode
  rust-check|rust-wasm|rust-native-dev|vitest|pytest`) for full suites.
- Product REST/WebSocket, CLI/SDK and browser E2E: isolated GitHub CI only (one
  browser spec per job, disposable backend, fresh accounts). Specs marked
  `reason=isolated_component_preview` use the Vite-only component profile.
  e2e and component jobs build the web app with the Rust client core ON (as
  dev/production serve it; job log shows `RUST-CORE-ON`); `--no-web-rust-core`
  opts out, `--web-rust-core` is an accepted no-op. Daily reports list `web_build`.
  Flow: `sessions.py ci-source` → `ci_coordinator.py submit` →
  `ci_coordinator.py wait <id>`. Never start a second scheduler, deploy before
  E2E, or use the shared dev stack for these tests.
- Real AI inference: only on the dev server, never in CI. Deploy the candidate
  via the session helper first, use disposable Projects and isolated
  CLI state, select `@Gemini-3.8-Flash` (unless the user names another model)
  and fail if the persisted assistant model differs. Record revision + results.
  Account: the personal dev test account only (`OPENMATES_PERSONAL_TEST_ACOUNT_*`,
  lease `playwright-account:personal-dev`); numbered `OPENMATES_TEST_ACCOUNT_<n>_*`
  slots are CI accounts and may not exist on dev. If its login fails, stop and
  report; never sign up or repair accounts. Details: `docs/contributing/guides/testing.md`.
- Choose checks for the changed behavior and affected clients; a web-only fix
  does not trigger Apple verification.
- Client-core capability work (`.claude/rules/client-core.md`): core contract tests
  plus `sdk-conformance`; web Playwright with the core flag on; Apple
  `apple-unit`/`apple-core`/`apple-ui` on GitHub `macos-26`. Parity vectors never gate.

## Debugging bounds
Existing browser observations, logs or failing checks suffice to start; do not
re-reproduce known bugs. After two failed attempts with the same approach,
reassess. Ask before unrelated infrastructure repair, uncertain expected
behavior or material scope growth; keep the patch and evidence.

## E2E recording delivery (web, component, CLI)
1. `ci_coordinator.py wait <id>` downloads artifacts on success; for failed or
   cancelled runs use `ci_coordinator.py result <id>`.
2. Run the receipt's `ci_evidence_command` (older receipts name it
   `codex_evidence_command`; normally `python3 scripts/ci_evidence.py <dir>
   --upload`). Its output is an internal inventory; never paste it wholesale.
3. In the final reply link, per requested flow, only the latest successful
   recording (or, if it never passed, the latest failed one), labelled with test
   and result. Include extra device/participant views only when required. No
   appendix of attempts.
3b. Videos must come from a run whose source is the deployed commit. Older-commit
   recordings are never proof for the current change. Download or open the
   screenshots, inspect them, and send them to the user with `SendUserFile`;
   without that tool, open them with the Read tool and post the full signed
   link (see "How to show an image" in `CLAUDE.md`).
4. Report missing capture, expiry or upload failure beside the test result.
   Retry uploads or renew signed links from S3; never rerun a test just for
   media. Do not pass `--ack` (Claude has no delivered-message ID).
5. Keep Playwright video on for all attempts. CLI E2E needs real terminal
   recordings (`cli-tui-proof-helpers.ts` / `cli_video_capture.py`). Dev-host
   real-inference recordings: `response_media.py <video> --output markdown`.
6. Edited/captioned proof videos only when requested (`/create-demo-video`,
   `sessions.py update --require-proof-video`). Never publish private
   production evidence or personal data.

## Mandatory result video (new feature, drastic update, new provider)
Applies without the user asking when the work adds a feature, drastically
changes one (new flow, redesigned UI, replaced pipeline, different output) or
adds a provider. Small fixes, refactors without visible change, docs and
tooling follow the normal delivery rules above.
1. Decide at the start which flow the video will show and make sure a spec
   records it: a web or Apple flow for visible work, a real terminal recording
   (`cli-tui-proof-helpers.ts` / `cli_video_capture.py`) when there is no UI.
2. The video shows the result, not just a green check: the feature used end to
   end with its real output on screen. New provider: a real request through
   the deployed stack answered with that provider's data (result rendered in
   the chat, embed or CLI output). Mocks, fixture replay and direct function
   calls do not count.
3. It comes from a run on the deployed commit and is shown in the final reply
   as the signed link or `<video>` HTML, next to 1-3 screenshots from it. One
   video per new flow or provider; raw recordings are enough, captions and
   edits only on request.
4. Watch enough of it (frames or screenshots) to confirm the result is really
   visible, and name any defect you see.
5. No video means not done: do not mark the Task Done or call the work
   verified. If capture is impossible, say why and what is unproven; only the
   user can waive the video.
