---
paths:
  - "frontend/packages/openmates-cli/**"
  - "frontend/packages/openmates-tui-prototype/**"
  - "packages/openmates-*/**"
  - "**/*.rs"
  - "**/Cargo.toml"
  - "specifications/surfaces/cli/**"
  - "specifications/surfaces/sdk/**"
  - "docs/architecture/platforms/cli-package.md"
---
The approved architecture is recorded in `docs/architecture/platforms/cli-package.md`,
`specifications/surfaces/cli/` and `specifications/surfaces/sdk/`. Keep these existing
contracts authoritative rather than creating another architecture source. Shared
sync and persistence policy also follows `specifications/architecture/sync/` and
`specifications/architecture/storage-lifecycle/`.

- One native Rust application implements the entire CLI and TUI. Do not delegate
  application behavior to Node, TypeScript or Python, sidecars or hidden fallbacks.
  Existing backend services and separate test/benchmark harnesses are exempt.
- Shared Rust owns ALL reusable headless application operations, crypto, auth,
  storage policy, sync, reconnect and recovery across CLI/TUI, web and Apple.
  Platform IO adapters are explicit. Parsing, UI and interactive profile
  selection stay in adapters.
- Public SDKs (npm, Python, Rust `openmates::sdk`) are API-key only and separate
  from the CLI login (user decision): never read CLI state, session files,
  profiles or keychains; a missing key is a typed error, never a login or
  anonymous fallback. Password/imported-session login is CLI/TUI, web and Apple
  session authority in shared Rust, not a public SDK mode. Each API key carries
  its own wrapped master key, so API-key SDKs decrypt chats, messages and embeds
  locally (memory only, zeroized); provide session-mode capabilities through the
  API-key path rather than dropping them, and track remaining gaps as open work.
- Web Svelte/TypeScript retains UI/DOM and thin browser APIs such as media and
  WebRTC. Apple retains native SwiftUI and platform hooks. Neither duplicates the
  reusable Rust behavior. Keep thin IndexedDB/SwiftData persistence adapters
  initially and preserve existing data; do not force a SQLite/OPFS migration.
- Rust, npm and PyPI remain supported SDKs with matching public capabilities,
  including API-key auth (plus explicit anonymous mode), operations, crypto,
  streaming, recovery and errors.
  npm/Python are libraries, call library code directly and never launch the CLI.
  Preserve compatible interfaces where practical; document and version breaking changes.
- Update the maintained capability matrix, shared schemas/protocol fixtures/crypto
  vectors and executable cross-SDK conformance whenever a capability changes.
  Publication must fail for unsynchronized capabilities; a declared migration gap
  is unfinished work, not permission to ship a one-language capability silently.
- Preserve CLI flags, scripting, JSON/stdout/stderr, exit codes, cancellation,
  privacy/security and platform support. Keep command/platform gaps explicit.
- Prove essential auth, encrypted chat, streaming/cancel, persistence and
  sync/reconnect/recovery through the entirely Rust CLI/TUI first. Then begin
  browser/WASM integration immediately; exhaustive CLI command/app parity remains
  required as separate work and does not block web. Verify web before Apple through
  the coordinated Mac workflow. Retire old code/commands only after full parity,
  reliable security verification and explicit agent AND user retirement acceptance. Backend Rust
  migration waits until every client and accepted cleanup are complete and is
  outside current implementation scope.
- Before and after web migration, compare compressed JavaScript and WASM sizes
  separately and together, actual download/transfer, cold startup including WASM
  initialization, usable-chat time, essential core-flow responsiveness, CPU and RAM
  under matching full-application conditions. Do not assume minimal WASM overhead.
  Keep warm/renderer-only measurements separate.
- Web Rust performance gate (user decision):
  - Gate only user-facing flows: cold start to usable chat, open chat, send/stream,
    embed ready and search.
  - Budget: Rust may be slower than TS only by an amount users cannot notice
    (user decision 2026-11-06; it replaces the earlier +3% gate).
    - Measure with a paired, interleaved benchmark of at least 12 pairs.
    - Wall time per flow: the upper bound of the 95% CI must be
      ≤ max(+10%, +50 ms).
    - Slow end: p95 at most +100 ms slower than TS (+200 ms for cold start).
    - CPU: the upper bound of the 95% CI must be ≤ +15%.
    - Don't spend effort optimizing inside this budget; port code instead.
  - Isolated micro-ops, such as single page-to-worker calls, are reported but not gated.
  - After every web bench, append the result to `docs/migration/rust/performance-history.yml`
    with `scripts/record_perf_measurement.py` (append-only; never edit old entries).
    Refresh the status with `python3 scripts/rust_migration_yaml.py`.
  - Memory during the migration: at most one WASM instance, about +30 MB. More than
    one is a blocker. Memory that grows per page reload is always a bug. The final build with the TS paths removed must have RAM and
    download ≤ TS.
- Web architecture:
  - Run one shared worker and one WASM instance, with no main-thread WASM.
  - Run logic in the worker next to its data, and send only results to the page.
  - Put platform primitives (WebCrypto, IndexedDB, CryptoKit) behind thin adapters.
    Never duplicate Rust logic in TS for speed.
- Follow `architecture.sync` for bounded startup and on-demand sub-chat messages.
  The approved cold-start parent-content budget is 20; warm sync uses the cursor
  feed without transcript content, and one-shot CLI commands perform no account
  sync. Keep existing metadata,
  pagination, pinned-chat and draft behavior; a client cache count is not an
  authoritative account total. Real personal-dev benchmarks use ordinary bounded
  windows and representative existing chats, without forcing a full-account sync.
- Primary distribution is one crates.io crate `openmates`: `cargo install openmates`
  installs the CLI/TUI; the SDK is re-exported as `openmates::sdk` (`cargo add
  openmates --no-default-features` for SDK-only). The SDK core remains an internal
  member crate. Python uses native PyO3 wheels; the npm SDK loads the portable
  WASM build of the shared core. Use explicit versioned dev
  prereleases. GitHub prebuilt executable assets are outside this migration scope.
- Keep the installed npm CLI and command operational during transition. Expose
  verified Rust alongside it early through a separate command or installation path
  for daily testing; do not automatically replace the global command. Retire the
  old command/source only after full parity/security evidence and explicit agent
  AND user confirmation of completeness/reliability and retirement.
- GitHub CI must exercise self-host edition setup through the native CLI. Product
  integration checks use isolated CI; real AI remains isolated dev-only and retains
  automatic routing without model/provider overrides.
- Acceptance also requires the actual Linux dev installation and Mac testing
  through an explicit coordinated Mac-chat handoff or admitted typed `apple_remote`
  operation. Windows testing is explicitly
  waived; do not add a CPU-architecture matrix, infer Windows build/support proof,
  or waive existing GitHub product/self-host requirements.
- Preserve the original TypeScript performance baseline before retiring source.
  Report renderer measurements separately from full-application measurements.
