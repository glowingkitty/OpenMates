---
description: Shared Rust client core, native CLI/TUI and synchronized library SDKs
globs: frontend/packages/openmates-*/**,packages/openmates-*/**,frontend/apps/web_app/**,frontend/packages/ui/**,apple/**
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
  SDK credentials and platform IO adapters are explicit; never discover the CLI
  user's login. Parsing, UI and interactive profile selection stay in adapters.
- Web Svelte/TypeScript retains UI/DOM and thin browser APIs such as media and
  WebRTC. Apple retains native SwiftUI and platform hooks. Neither duplicates the
  reusable Rust behavior. Keep thin IndexedDB/SwiftData persistence adapters
  initially and preserve existing data; do not force a SQLite/OPFS migration.
- Rust, npm and PyPI remain supported SDKs with matching public capabilities,
  including relevant auth modes, operations, crypto, streaming, recovery and errors.
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
- Primary CLI distribution is `cargo install` of its crates.io application crate;
  publish the Rust SDK as a separate library crate. Use explicit versioned dev
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
