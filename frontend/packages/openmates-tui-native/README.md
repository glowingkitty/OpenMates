# OpenMates native Rust CLI and TUI

A standalone Rust terminal application built with Ratatui, Crossterm and Tokio.
The executable uses the shared headless `openmates-sdk` Rust library for
authentication, encryption and HTTP/WebSocket protocols. It owns command parsing,
presentation, input and interactive profile storage. It does not load Node,
TypeScript, a client sidecar or
a rendering bridge. Browser pairing and explicitly opened links use the system
browser, as in the existing CLI.

The existing TypeScript CLI remains installed separately. This package is an
opt-in implementation while protocol and feature parity are verified. See the
[implementation and benchmark report](../../../docs/plans/rust-tui/report.md)
and [security inventory](../../../docs/plans/rust-tui/security.md) for measured
results, evidence and remaining limitations.

## Build and run

The verified development toolchain is Rust 1.98.1. Linux is the currently verified
target; actual macOS packaging and runtime validation remains pending isolated CI.
Filesystem hardening requires Unix.

```sh
cargo build --release --locked --manifest-path frontend/packages/openmates-tui-native/Cargo.toml --bin openmates
frontend/packages/openmates-tui-native/target/release/openmates
```

Use `--api-url https://api.dev.openmates.org` for a development account. The
default API is `https://api.openmates.org`. Custom origins require HTTPS except
literal loopback addresses, and credentials cannot be restored to a different
origin. Supply secrets through the masked interactive forms, not command flags.

```sh
# Synthetic local presentation, with no credentials, files or network access.
frontend/packages/openmates-tui-native/target/release/openmates --demo

# Choose an independent state directory and explicit encrypted vault.
frontend/packages/openmates-tui-native/target/release/openmates --encrypted-vault --state-dir /path/to/private-profile
```

An existing profile directory must be owned by the user with mode `0700`.
The native default is `~/.openmates-rust`; the
application does not import or rewrite the TypeScript CLI's credentials. An OS
keyring is preferred. If unavailable on first sign-in, the explicitly supplied
password protects a local Argon2id/AES-GCM vault. Pairing can request a separate
local vault passphrase. An existing keyring-backed profile never silently
downgrades. When first-time browser pairing supplies no vault password and the
keyring is unavailable, an owner-only local wrapping key preserves login without
an additional password. This mode is reported explicitly and provides filesystem
protection rather than OS-keyring protection. `--encrypted-vault` always requires
a vault password.

## Controls

| Action | Control |
|---|---|
| Workspace | `Ctrl+1` through `Ctrl+6`, or click its name |
| Actions and help | `Ctrl+K`, `F1` |
| Chat sidebar | `Ctrl+B` |
| New chat | `Ctrl+N` |
| Settings | `Ctrl+S` |
| Refresh | `Ctrl+R` |
| Send / insert newline | `Enter` / `Alt+Enter` or `Shift+Enter` |
| Submit form | `Ctrl+Enter`, or its Submit button |
| Text selection / pointer capture | `Ctrl+Y` |
| Cancel / back | `Escape` |
| Quit | `Ctrl+Q` |

The editor supports grapheme-aware navigation and deletion, multiline bracketed
paste and per-chat drafts. Memory sharing requires an explicit consent decision.
Downloads require a destination and separate overwrite consent. Share keys remain
in the URL fragment and are revealed or copied only through explicit actions.

## Verification

```sh
cargo test --locked --manifest-path frontend/packages/openmates-tui-native/Cargo.toml --all-targets
cargo clippy --locked --manifest-path frontend/packages/openmates-tui-native/Cargo.toml --all-targets -- -D warnings
python3 frontend/packages/openmates-tui-native/scripts/benchmark.py --output /tmp/native-tui-benchmark.json
```

The ignored authenticated protocol test, actual terminal recording, no-Node PTY
probe and signal restoration tests run through the repository's isolated GitHub
CI coordinator. They must use disposable accounts and isolated state. Unit
fixtures do not establish full operating-system keyring or live AI interoperability.
The TypeScript benchmark adapter runs the existing implementation as a separate
baseline; it is not part of the Rust application's runtime.

## Cargo package boundary

Cargo/crates.io is the intended primary distribution channel. This crate remains
`openmates-tui-native` version `0.1.0`, with the single installable binary
`openmates`. The renderer benchmark is an explicit Cargo example, built with
`cargo build --release --locked --example tui-benchmark`; it is not an additional
installed application. Python/Node proof scripts are excluded from the package.

Publication remains disabled. The exact `openmates-sdk = "=0.1.0"` dependency has a
local development path, but a public CLI package requires that exact SDK version
in the registry. The cross-SDK capability gate still blocks SDK releases,
including dev prereleases. An offline missing-registry dependency is therefore
an expected packaging blocker, not proof that a consumer install succeeds.

Maintainers check canonical inputs from the repository before packaging:

```sh
python3 scripts/sync_rust_cli_assets.py --check
python3 scripts/check_rust_cli_package.py
```

After reviewing canonical template/catalog/fixture changes, run the sync helper
without `--check` and review the copied bytes and manifest. The package guard
checks actual Cargo package lists, compile-time input closure, license copies,
source-snapshot hashes, dependency versions and the application-only binary
declaration. It does not publish, compile, install or claim registry availability.
The in-checkout Rust catalog test retains its repository audit; standalone crate
tests use the included catalog and fixtures without the legacy source tree.
A local SDK override is staging proof only, not public registry resolution.

The `openmates` crate (CLI/TUI plus the SDK re-exported as `openmates::sdk`) is
MIT licensed like the npm and PyPI packages; see `LICENSE` and `NOTICE`. The
OpenMates server and web app remain AGPL-3.0-only.
