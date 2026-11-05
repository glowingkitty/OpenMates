# Bounded native session recovery protocol proof

`fixtures/session-recovery.json` and capability `session.recovery-replay.v1`
exercise actual Rust `SessionBridge`, npm NAPI `SessionClient`, and Python PyO3
`SessionClient`. Every adapter uses one canonical protocol peer implemented in
`recovery_server.py`, bound exclusively to `127.0.0.1` on an ephemeral port.

The Rust/npm developer runners start that fixture service as a child process;
the Python runner hosts the same peer in process. This helper belongs exclusively
to the conformance harness. SDK and facade runtime code never imports or launches
it, and never starts the OpenMates CLI. No real credentials, saved account state,
product endpoint or inference request is used. The service's `cryptography`
dependency is already required by the Python SDK.

The eleven vectors establish these specific client behaviors:

- Native encrypted turn admission uses explicit session cookies, Origin and SDK
  identity, a same-socket privacy receipt, a distinct chat key, and default model
  routing. The peer decrypts the admitted ciphertext and checks its exact input.
- Recovery claims bind job, turn, chat and assistant identity. A zero lease
  generation and a different turn identity fail before any persist request.
- X25519/HKDF-SHA256/AES-GCM sealed recovery content becomes the authoritative
  result. Transient stream text is deliberately different. A tampered tag fails
  without persistence or a completion event.
- Before persistence, the client rereads authorized metadata and uses its fresh
  `messages_v=5`, rather than the admission version1. Changed chat key or
  regressed metadata version fails without persistence.
- Persistence carries the exact lease token/generation, fresh version and an
  encrypted assistant message whose plaintext equals the sealed answer.
  Completion follows a terminal acknowledgement. A server conflict fails with a
  sanitized error and no completion.
- A terminal claim reads and decrypts canonical message history, choosing its
  content over transient output and issuing no duplicate persist.
- Losing the acknowledgement after the peer commits produces an offline error,
  without reporting completion. A new client imports an explicit credential
  snapshot, reconnects, discovers an already acknowledged recovery output,
  rereads canonical embed ciphertext and validates its digest, then opens the
  committed canonical assistant message. Admission and persist counts remain1.
- A mismatching acknowledged-output digest fails against an actual canonical
  embed reread. Cancellation while awaiting the lease response closes the socket
  without persistence or completion.

The adapters assert exact admission/claim/persist/socket counts, every required
server-side observation, and absence of completion on all negative paths. The
peer refuses wrong lease tokens/generations, stale versions and content that does
not decrypt to the sealed answer. Separate tooling unit tests prove those peer
fences and verify identity/nonce/ciphertext authentication in its envelope builder.
The peer checks client behavior; this does not independently test backend lease
or transaction implementation.

Run from the repository workspace with real native bindings installed:

```sh
node tests/sdk-conformance/runners/session-recovery.mjs --fixture tests/sdk-conformance/fixtures/session-recovery.json --capability session.recovery-replay.v1
python3 tests/sdk-conformance/runners/session-recovery.py --fixture tests/sdk-conformance/fixtures/session-recovery.json --capability session.recovery-replay.v1
cargo run --example session-recovery-conformance --manifest-path packages/openmates-session-bindings/Cargo.toml --locked --quiet -- --fixture tests/sdk-conformance/fixtures/session-recovery.json --capability session.recovery-replay.v1
python3 tests/sdk-conformance/test_session_recovery.py
```

Set `OPENMATES_SDK_CONFORMANCE_PYTHON` to an absolute Python interpreter when the
harness uses a virtual environment or an empty PATH. This test-only variable is
consumed exclusively by the Rust/npm runners. Runners return the standard
language/capability/results object plus SHA256 of the exact shared fixture bytes.

Remaining gaps include lease renewal/expiry, new typed-output persistence,
artifact revision/checkpoint dependency replay, pagination and compression
boundaries, Team/direct recipient recovery, duplicate/out-of-order discovery,
longer outages and process restart durability. These vectors support a bounded
implemented conformance case; broad session recovery parity remains partial.
