# Native session bindings

This MIT-licensed crate links `openmates-sdk` directly. Optional `napi-bindings`
and `python-bindings` features export the same session bridge as Node-API and
PyO3 extension modules. SDK operations never launch a CLI or another process.

The shared bridge owns a serialized Rust `Client`, bounded stream events, an
independent cancellation token and request-bound consent decisions. The caller
supplies the API endpoint, optional app origin, enhanced-privacy setting and
private-operation policy. Constructors never read a saved login, environment
credentials or CLI profile. Enhanced privacy currently fails closed. Foreign
constructors set fixed npm/pip transport identities without changing auth scope.

The bounded public facades support password sign-in, explicit session import and
secret export, validation, workspace listing, chat opening, Team scope, send and
stream, consent, cancellation, logout and close. Pairing and the full workspace
mutation surface are separate incomplete capability families. No full SDK parity
or positive deployed authentication/streaming evidence is claimed here.

`exportSession({includeSecrets:true})` / `export_session(include_secrets=True)`
returns cookies and master-key material with its revision. Persist it only in a
caller-owned secure store; no automatic credential persistence occurs. Export
again after operations that can rotate credentials. Foreign strings returned to
the caller remain subject to the host language's memory management.

Stream updates preserve Rust SDK `Started`, `Submitted`, `Admitted`, `Consent`,
`Content` and recovery/completion events. A `Submitted` update can represent an
ambiguous commit after network failure; callers must not automatically resend.
Consent decisions must match the exact pending request and offered item IDs.
Stopping a consumer cooperatively cancels and drains the Rust operation. Dropping
an await does not interrupt a credential transaction at its commit boundary.
`logout` clears local credentials and requests remote revocation; `close` cancels
work and releases local credentials. Applications should await close.

## Developer builds

The npm artifact is built explicitly, then bundled alongside the JS SDK:

```sh
python3 scripts/build_sdk_native.py --language npm --debug
npm --prefix frontend/packages/openmates-cli run build:sdk
```

Omit `--debug` for an optimized release artifact. The script invokes Cargo only
as a developer build tool. It is never imported or launched by the SDK runtime.
Unsupported/missing native artifacts produce a typed unavailable error.

The Python package uses a mixed maturin project and `openmates._native`:

```sh
python3 -m pip install -e packages/openmates-python
```

A Rust toolchain is required when building from source. Wheels contain the native
extension; importing the existing API-key SDK remains compatible. Public source
distributions include this crate and the sibling Rust SDK, with rewritten local
manifest paths. Release workflows own platform artifact verification; a local
Linux ARM64 build does not establish portability to other targets.

## Offline verification

```sh
cargo test --manifest-path packages/openmates-session-bindings/Cargo.toml --locked
cargo run --example sdk-conformance --manifest-path packages/openmates-session-bindings/Cargo.toml --locked -- --fixture tests/sdk-conformance/fixtures/core.json --capability session.native-boundary.v1
```

The shared case invokes the actual bridge and foreign libraries against synthetic
session data. It proves explicit export consent, endpoint isolation, preservation
of prior credentials after invalid input, fail-closed privacy/private-operation
policy and lifecycle boundaries. It performs no product requests. A separate
loopback unit server verifies the real Rust transport and fixed npm/pip identity.
Broader positive auth, WebSocket, recovery and platform cases remain explicit
release-gate requirements.

Implementation references: [NAPI async functions](https://napi.rs/docs/concepts/async-fn),
[PyO3 classes](https://pyo3.rs/v0.29.0/class.html),
[Python/Tokio future conversion](https://docs.rs/pyo3-async-runtimes/0.29.0/pyo3_async_runtimes/tokio/fn.future_into_py.html),
and [maturin mixed package configuration](https://www.maturin.rs/config.html).
