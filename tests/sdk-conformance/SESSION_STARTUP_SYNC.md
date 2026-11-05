# Explicit initial startup synchronization

The authored `session.initial-startup-sync.v1` vectors use direct Rust
`SessionBridge`, npm NAPI and Python PyO3 libraries against the same independent
synthetic HTTP/WebSocket peer. They require actual paired native artifacts and
isolated three-language execution. Fixture registration and pure fixture checks
are not a runtime pass.

Rust Core retains the genuine original monitor, socket, owner, lifecycle and
operation scope. Only that actor's successful first `phased_sync_request` dispatch
can issue initial startup intent. Expanded metadata follows the actual startup
terminal and only an authenticated Phase 2 count above 100 selects that work.
Caller counts, booleans, row JSON and alternate handles grant no authority.

The direct bridge offers `prepare_initial_sync(monitor_id)`. Its one-use operation
has `control().cancel()` and `run()`. npm exposes
`await monitor.beginInitialSync()` and Python exposes synchronous
`monitor.begin_initial_sync()`; both capture native admission before a later
`operation.run()` future. Run returns an opaque metadata object. Its
`receivedMetadataCount()` / `received_metadata_count()` is an observed row count,
not an account total, cache coverage, deletion proof, store receipt or ACK. Both
operation and result can be cancelled. Closing the original monitor or changing
the session invalidates subsequent access. The wrappers keep the same original
operation alive while the result is retained.

Credentials remain explicit. This path preserves Core's existing
Master-capable `OwnedOperationScope`; it does not turn a caller-supplied key or
session DTO into a metadata-only authenticated resource. The separate genuine
`NativeMetadataContext` / no-usable-Master SDK path remains open. There is no
login enrollment, CLI profile discovery, child CLI, automatic application startup
activation, physical metadata storage, row release, decryption or full-hint ACK.

Ten authored vectors cover expansion after the original terminal, small/missing
count, cancellation before and during IO, replaced original credentials, foreign Bridge
monitor, one-use replay, foreign-context response rejection and actual expanded
server error. Existing monitor and recovery vectors are unchanged. The server
accepts only lifecycle, phased startup and expanded metadata frames; claims,
persist/ACK frames and extra content fetches fail its protocol.

Publication still requires composed Core startup prerequisites, registry/source
authority registration, actual semantic compilation and all three adapters in
isolated CI. Physical per-row store/readback, metadata-only auth, app activation,
older-page integration and whole/later-hint completion remain separate gaps.
