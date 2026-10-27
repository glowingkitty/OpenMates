---
status: active
doc_type: index
audience:
- contributors
- technical-users
last_verified: 2026-10-22
claims:
- id: arch-platforms-readme-behavior
  type: unit
  claim: Platform Architecture is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - docs/architecture/platforms/README.md
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-platforms-readme-behavior
  verified: '2026-06-11'
- id: arch-platforms-readme-index-scope
  type: manual
  reason: 'Index doc: verifies navigation scope through Markdown link validation rather than source-code anchors.'
---

# Platform Architecture

## Summary

- OpenMates currently has three implemented platform surfaces: the SvelteKit web app, the OpenMates CLI, and the Apple app.
- The web app is the primary product surface and source of truth for shared UI behavior.
- The CLI covers terminal workflows, server management, and API/WebSocket interaction.
- The Apple app is native Swift/SwiftUI and follows web parity through generated tokens and mapped source docs.

## Approved shared client architecture

Shared Rust owns all reusable headless application operations, crypto,
authentication, storage policy, sync, reconnect and recovery. The complete CLI/TUI
is one Rust application. The web app retains Svelte/TypeScript UI, DOM and thin
browser APIs such as media and WebRTC; Apple retains native SwiftUI and platform
hooks. Thin persistence adapters keep IndexedDB and SwiftData initially and
preserve existing data. This is the migration target, not a claim that the web or
Apple migration has already shipped.

First prove essential authentication, encrypted chat, streaming/cancellation,
persistence and synchronization/reconnect/recovery through the entirely Rust
CLI/TUI. Begin browser/WASM integration immediately after that essential proof;
full CLI command and app parity remains required in parallel and does not delay
browser admission. Compare before/after compressed JavaScript and WASM sizes,
cold load, usable-chat latency, CPU and RAM. Verify web before Apple through the
coordinated Mac workflow. Remove superseded
client code only after reliable verification and explicit agent plus user
acceptance. Backend Rust migration begins only after every client and accepted
cleanup are complete; backend implementation is outside this migration.

The primary CLI distribution is its crates.io application crate through
`cargo install`, with a separate Rust SDK library crate and explicit versioned
development prereleases. npm and Python remain direct library SDKs under shared
conformance gates. GitHub prebuilt executables are outside scope. Required
acceptance includes actual Linux dev use, an explicit coordinated Mac-chat handoff
or admitted typed `apple_remote` Mac operation, and existing isolated product/self-host CI. Windows testing is explicitly
waived, without a Windows build/support claim or another CPU-architecture matrix.

The existing [CLI package architecture](cli-package.md), SDK/CLI surface
Specifications and shared sync/storage-lifecycle Specifications own these rules;
do not create a competing client-core contract.

## Platform Docs

- [Web App](../frontend/web-app.md) -- SvelteKit app architecture and public docs processing.
- [CLI](cli.md) -- command-line platform architecture and capabilities.
- [Apple App](../frontend/native-apps.md) -- native app architecture and web-parity model.
