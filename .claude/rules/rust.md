---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
  - "packages/openmates-*/**"
  - "frontend/packages/openmates-tui-native/**"
---
# Rust code: documentation and structure (user decision)

Rust code must be understandable for humans and agents without reading the TS
original. These rules apply to every Rust file you create or change. Leave
`packages/third_party/` alone: those are vendored crates.

## Documentation
- **Every file starts with a `//!` module doc** of 2–6 lines. It covers what the
  module owns, its place in the architecture (shared core, CLI/TUI adapter,
  browser/session binding), the TS/npm source it mirrors when one exists, and
  the spec it implements (`specifications/...` id).
- **Every `pub` item gets a `///` doc:** fn, struct, enum, trait, type, const and
  re-export. `pub(crate)` items need one when they are not obvious. Say what
  it does and why, plus any non-obvious contract:
  - errors returned (`# Errors`);
  - panics (`# Panics`; there should be none);
  - cancellation and ordering;
  - zeroization and secret handling;
  - wire/format compatibility.
  Don't restate the signature.
- **Crypto, protocol, sync and storage code** documents the invariant it protects.
  Examples: AAD layout, key wrapper order, epoch rules, idempotency key, cursor
  semantics, and which TS function or vector proves byte compatibility.
- **Inline `//` comments explain why**, not what: workarounds, ordering
  constraints, security reasoning, deliberate deviations from npm. Each
  `#[allow(...)]` and each `unsafe` block carries a reason (`// SAFETY:` for
  `unsafe`).
- **Tests:** give each test module a one-line `//!` naming the behaviour or
  fixture it covers. Test names state the expected behaviour
  (`refuses_team_write_before_request`).

## Structure
- **One concern per module.** No new file over 800 lines. Extract a seam before
  growing any file over 2,500 lines. Never add to the giant files (`ui.rs`,
  `storage.rs`, `runtime.rs`, `command_runtime.rs`, `handlers.rs`, `server.rs`,
  `transport.rs`, `sync.rs`, `work/tasks.rs`); add a new submodule instead.
- **Keep tests out of production files.** Put them in a sibling `*_tests.rs`
  (`#[cfg(test)] mod x_tests;`) or in `tests/`, not in long inline blocks.
- **Layering:**
  - shared logic lives in `packages/openmates-rust`;
  - CLI/TUI handlers in `openmates-tui-native` stay thin: parse, call the core,
    render;
  - bindings (`*-bindings`) only marshal.
  Never duplicate core logic in an adapter.
- **Errors:** use typed error enums (`thiserror`-style) with stable codes that
  match the npm/web error codes. In production code, no `unwrap()` or
  `expect()` on fallible input. Allowed:
  - an invariant that truly cannot fail, documented by an `expect("why this
    cannot fail")`;
  - mutex poisoning, handled explicitly.
  No silent `unwrap_or_default()` that hides a protocol error.
- **Secrets** use zeroizing types, never `Debug`/`Display` them, and never log
  them.
- **Public API:** keep it small, prefer `pub(crate)`, and classify new public SDK
  APIs in `config/sdk-capabilities.json` (see `cli-sdk.md`).
- **Formatting:** follow `cargo fmt` and fix clippy warnings in touched code.
  Prefer explicit types at module boundaries.

## When touching existing code
The codebase predates these rules: about 3% doc comments, 43% of pub items
undocumented, 165 files without a module doc, and 76 files over 800 lines.
Ratchet, don't rewrite:
- add the module doc and the missing `///` docs for the items you change;
- move tests out when you touch a mixed file;
- split a file only along a clear seam that you are already working in.
Keep documentation-only changes separate from behaviour changes in review, and
never change behaviour while "just adding docs".
