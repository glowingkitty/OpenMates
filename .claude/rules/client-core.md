---
paths:
  - "packages/openmates-rust/**"
  - "packages/openmates-session-bindings/**"
  - "packages/openmates-browser-bindings/**"
  - "packages/openmates-apple-bindings/**"
  - "apple/OpenMates/Sources/Core/**"
  - "apple/OpenMatesShared/**"
  - "apple/OpenMatesCore/**"
  - "frontend/packages/ui/src/services/**"
  - "frontend/apps/web_app/src/lib/rustCore/**"
---
# Client core: one Rust core, three thin shells

Contract: `specifications/architecture/client-core/` (draft). Work breakdown,
capability inventory and status: `docs/plans/client-core-one-core-three-shells/plan.yml`.

## Where logic goes
- The crate `openmates-sdk` (`packages/openmates-rust`, mainly `src/client/`) is
  THE client: transport/reconnect, phased sync and cursor feed, keys and crypto,
  encrypted local cache, drafts, send/outbox, streaming, completion and metadata
  recovery, search, settings/project/task policy, logout and deletion fences.
- Shells only do: UI, navigation and view state; platform APIs (media, WebRTC,
  notifications/APNs, widgets, Live Activities, Spotlight, pickers, passkeys,
  OS lifecycle); credential storage (Keychain, OS keyring, browser store); an
  opaque byte persistence adapter; thin primitive adapters the core calls
  (WebCrypto, CryptoKit); binding glue.
  - Web shell: Svelte + the shared Worker (`frontend/apps/web_app/src/lib/rustCore/shared/`,
    units in `sharedWorkerUnits.ts`, installers in `frontend/packages/ui/src/services/rustCore/`).
  - Apple shell: SwiftUI + UniFFI framework (`packages/openmates-apple-bindings`,
    Swift package `apple/OpenMatesCore`, generalising `apple/PairOpaqueBridge`).
  - TUI/CLI shell: `frontend/packages/openmates-tui-native` (done; reference shell).
- Core first, shells bind: a fix or feature in reusable behavior lands in Rust and
  reaches every shell through its binding. If the core lacks it, add it to the core.
- Credentials: the core emits credential snapshots with a revision; the shell
  stores them and acknowledges (pattern: `openmates-tui-native/src/session_runtime.rs`).
  The core never touches a credential store; snapshots never enter view-model
  values or logs.
- Cache: the core owns schema, migrations, partitioning, encryption, retention
  and fences; shells store opaque ciphertext bytes only.

## Forbidden
- New or changed protocol, sync, crypto, cache, retry/conflict/deletion policy
  logic in TypeScript or Swift, including "temporary" duplicates for speed.
  Exception: a defect fix in not-yet-migrated shell code, marked
  `shell-only: bugfix-in-frozen-code <capability>` in the deploy message.
  Exception (live collaboration, `feature.live-collaboration`
  `live-collab.core.one-shared-model`): the web shell may keep a third-party Yjs
  mirror on the main thread for rich-text typing only (document editor, slide
  text boxes); it exchanges update bytes with the core and holds no OpenMates
  logic. Sheets and slides editors send typed operations to the core.
- Parity vectors (old vs new output) as a completion gate. They are debugging aids.
- Partial twins: a lane that adds a Rust path but leaves the old path in place
  has not finished. `rust-twin`/`rust-default` are unfinished states.
- Reading CLI state, keychains or profiles from the core (see `cli-sdk.md` for SDKs).

## Lane shape
- One capability (one inventory row) on one shell per lane. Read the row's `old:`
  paths, the matching `src/client/*` modules and the shell's existing tests first.
- Bind the shell to the core view model (chat list, chat window, stream updates,
  commands; drafted by `packages/openmates-rust/src/model.rs` and the TUI's use of
  `Client`). Do not add a shell-side adapter that re-derives state.
- Delete the old implementation and its parity tests in the same deploy; keep the
  shell's existing suite green; update the capability status (plan inventory, or
  `docs/migration/rust/capabilities.yml` once it exists) with the commit.
- Status enum per shell: `ts-only | swift-only | rust-twin | rust-default |
  rust-only | stays-shell`. Done = `rust-only` (old code deleted, suite green on
  the exact deployed commit). Progress = cells at `rust-only` or `stays-shell`.

## Testing per shell
- Core: unit/contract tests in the crate; `ci_coordinator.py submit --mode rust-check`
  and `--mode sdk-conformance` (via `sessions.py ci-source`). Builds/tests on the
  dev host only through `scripts/heavy_slot.py run -- <cmd>`.
- Web: the capability's existing Playwright specs with `VITE_OPENMATES_RUST_CORE=1`
  in isolated CI (`--mode e2e`). Today only `web-rust-core-*` specs build flag-on;
  plan TASK-3 opens the flag-on lane for the existing suite.
- Apple: XCTest on GitHub `macos-26` (`--mode apple-unit`, `--mode apple-core`);
  XCUITest there too (`--mode apple-ui --spec OpenMatesUITests/<Class>[/<test>]`,
  no secrets, so real-account tests skip). The coordinated Mac
  (`scripts/apple_remote.py`) is only for TestFlight, physical device/APNs and real-account tests. Apple web-parity tests are
  deleted when their subject moves into the core.
- TUI/CLI: crate tests plus the existing CLI E2E specs.

## Web flag rule
- Each capability is behind `VITE_OPENMATES_RUST_CORE`, on by default in dev.
  Until a capability flips, its flag-off path stays byte-identical to the old
  TypeScript behavior. The flip deploy deletes that capability's TypeScript and
  flag branch; after that the byte-identical rule no longer applies to it.
- One shared Worker, one wasm instance, no main-thread wasm (see `cli-sdk.md`
  for the performance gate).

## Binding conventions
- wasm (web): `packages/openmates-browser-bindings`; Worker namespace per unit;
  results are presentation values, never keys.
- UniFFI (Apple): the core owns its async runtime; expose async functions and an
  update listener; Swift hops to `@MainActor` once at the view-model boundary;
  support cancellation; no blocking calls on the main thread. watchOS arm64_32
  is tier-3: reuse the build-std recipe in `apple/PairOpaqueBridge/build-apple.sh`.
- Node/Python (`packages/openmates-session-bindings`) follow `cli-sdk.md`.
- Errors cross bindings as typed errors; no silent fallback.

## Transition caveat
- `scripts/rust_migration_yaml.py --check` still enforces the deprecated
  `web-port-ledger.yml` (an unledgered TS routing function fails deploy). Until
  plan TASK-2 removes it, add the ledger slice the check asks for; it is not a
  progress metric.
