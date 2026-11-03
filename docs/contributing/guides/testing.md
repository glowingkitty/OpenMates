# Testing

Maintain relevant E2E coverage for behavior fixes/features, adding a focused case
when missing. Preserve contract/assertion markers. A waiver of test execution
does not waive coverage updates unless explicitly stated by the user.

Run relevant unit, lint and build checks locally. Full product browser, REST,
WebSocket and CLI/SDK E2E use one GitHub-hosted job per browser spec, with a
disposable Docker backend and runner-private localhost web process. Use
`sessions.py ci-source` to prepare the source, then `ci_coordinator.py submit`
with the matching supported mode/spec; multi-spec E2E submissions are split into
independent jobs. `ci_coordinator.py wait <id>` waits on the coordinator cache;
`result <id>` retrieves evidence. Use `--json` only for parsers. Retain source/run
identity when reporting a pass. Unsupported coverage or a queue timeout is not a
passing result. Deployment and Vercel readiness are not E2E prerequisites.

Keep investigation tied to the original acceptance criteria. Inspect the first
useful failure, rerun only after a relevant change or new evidence, and reassess
after two unsuccessful attempts with the same approach. Ask before debugging
unrelated infrastructure, uncertain expected behavior, or a materially expanded
scope. Preserve the patch and evidence while that decision is pending.

Review visible UI changes in the relevant viewports. Reuse screenshots, traces,
logs and useful videos from the existing run. A separate proof-video production
workflow is needed only when requested or part of the accepted scope. Use
`response_media.py` to publish reviewed private expiring evidence if needed.

## Rust and unit checks in isolated CI

Rust builds and tests never run on the dev server. Submit the candidate source
(`sessions.py ci-source`) with `ci_coordinator.py submit --mode rust-check`:

```bash
python3 scripts/ci_coordinator.py submit --session <id> --source <sha> --mode rust-check --spec all
python3 scripts/ci_coordinator.py submit ... --mode rust-check --spec openmates-sdk
python3 scripts/ci_coordinator.py submit ... --mode rust-check --spec 'openmates-sdk::chat::tests'
python3 scripts/ci_coordinator.py wait <id>      # then: result <id> for failures
```

- `--spec all` runs `cargo test --workspace --locked --lib --bins --tests`
  (examples excluded, as in `rust.yml`), the SDK-only `openmates` build without
  default features, and a wasm32 `cargo check` of `openmates-browser-bindings`.
- `--spec <crate>` runs `cargo test -p <crate> --locked --lib --bins --tests`;
  `--spec <crate>::<filter>` passes `<filter>` as the cargo test-name filter.
  Exactly one target per job; doc tests are not run.
- Runs on `ubuntu-24.04-arm` with a `Swatinem/rust-cache` dependency cache
  (saved only by runs without a candidate patch; patch runs restore only). A
  cold build takes tens of minutes. It counts as a lightweight hosted job.
- `result`/`wait` print each step's verdict plus its first failure lines (failing
  tests, panics, compiler errors). Full bounded logs are in the result
  artifact under `test-results/rust-check/`.
- Vitest: `--mode vitest --spec <path>` takes exact test files (repeatable, up
  to 30) under `frontend/packages/ui/src`, `frontend/apps/web_app/src` or
  `frontend/packages/openmates-cli/tests`; without `--spec` it runs all suites.

## Real-inference checks on the dev server

Real AI, speech and provider checks run only against dev, after the candidate is
deployed and the affected services restarted with `sessions.py docker restart`.

- **Account:** use only the personal dev test account. Its credentials are the
  three `OPENMATES_PERSONAL_TEST_ACOUNT_{EMAIL,PASSWORD,OTP_KEY}` keys in the
  canonical root `.env` (the `ACOUNT` spelling is intentional). Map only those
  keys in process; never print or source the whole `.env`. Hold the
  `playwright-account:personal-dev` lease (exclusive) and the `dev-stack` lease
  (shared) for the whole run; `scripts/code_run_real_test.py` shows the pattern.
- **Not these accounts:** numbered `OPENMATES_TEST_ACCOUNT_<n>_*` slots belong to
  isolated CI backends and are not guaranteed to exist on dev (a failed OTP login
  or "user not found" is expected there). Do not sign up, provision or repair
  accounts to work around a missing login; stop and report instead.
- **CLI state:** log in through `scripts/openmates_cli_test_account.mjs login
  --slot PERSONAL` with a temporary `HOME` and `OPENMATES_STATE_DIR`, so the
  global engineering CLI login is never replaced
  (see `openmates-tasks-dev-login.md`).
- **Projects:** create a disposable Project in that isolated state
  (`openmates projects create <name> --write-policy always_ask --json`, id in
  `project.project_id`) and delete it with `projects delete <id> --confirm <id>`
  when the run ends, including on failure. Never reuse the engineering Project.
- **Browser on the dev host:** the repo's Playwright version may not match the
  Chromium build in `~/.cache/ms-playwright`. Do not download browsers; launch
  with `executablePath` pointing at the installed `chromium-*/chrome-linux/chrome`.
  Scripts that refuse in-repo output need an output directory outside the
  repository.

### Voice calls

- `backend/scripts/test_voice_call_real_speech.py` (run in the `api` container)
  streams Mistral TTS speech through the real `/v1/voice-call` handler, real
  Voxtral STT and the real completion decision. No account is needed. Use it
  for turn-taking, pause and latency changes.
- `scripts/verify_voice_call_live_smoke.cjs` drives the real web call in
  Chromium with fake-microphone input, real assistant inference and spoken
  playback. Feed it two short TTS-generated MP3/WAV utterances and the personal
  account, in a disposable Project as above.

Platform-specific checks belong to their relevant skills (for example `ios`).
Shared policy and exception handling: `.claude/rules/testing.md` and `AGENTS.md`.
