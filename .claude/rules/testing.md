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
- Never weaken assertions to force a pass. Do not claim a pass from a queued,
  cancelled, unrelated or stale run, or from mocks/replays.
- Honor execution waivers (`skip E2E`) and report what was not run; a waiver
  does not waive updating coverage unless the user says so.

## Where checks run
- Locally in the worktree: lint, typecheck (`tsc`, `svelte-check`), `cargo
  fmt/metadata/tree`, and pytest of `scripts/` tooling (light; still refused
  while the host is overloaded).
- Builds, unit tests and benchmarks (`cargo build/test/check/clippy/run/bench`,
  `rustc`, `wasm-pack`, vitest, Playwright, `vite`/`svelte-kit`/`pnpm build`,
  local headless-browser benches): isolated GitHub CI only, e.g.
  `ci_coordinator.py submit --mode rust-check|rust-wasm|rust-native-dev|vitest|pytest`.
  `.claude/hooks/bash-guard.sh` enforces this; the only override is the logged
  `OPENMATES_ALLOW_LOCAL_HEAVY=real-inference` prefix for real-inference runs.
- Product REST/WebSocket, CLI/SDK and browser E2E: isolated GitHub CI only (one
  browser spec per job, disposable backend, fresh accounts). Specs marked
  `reason=isolated_component_preview` use the Vite-only component profile.
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
4. Report missing capture, expiry or upload failure beside the test result.
   Retry uploads or renew signed links from S3; never rerun a test just for
   media. Do not pass `--ack` (Claude has no delivered-message ID).
5. Keep Playwright video on for all attempts. CLI E2E needs real terminal
   recordings (`cli-tui-proof-helpers.ts` / `cli_video_capture.py`). Dev-host
   real-inference recordings: `response_media.py <video> --output markdown`.
6. Edited/captioned proof videos only when requested (`/create-demo-video`,
   `sessions.py update --require-proof-video`). Never publish private
   production evidence or personal data.
