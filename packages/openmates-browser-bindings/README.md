# Browser Worker foundation

This unpublished crate delegates browser session admission to the shared Rust
SDK. It is not connected to the existing web application. No active auth, chat,
sync, streaming or storage reducer is replaced by these files.

`PreparedBrowserProfile.from_bytes` is Worker-only and one-use. It authenticates
the captured encrypted-email envelope with the captured master key, then derives
SHA256/base64 from exact UTF-8 inside Rust. Plaintext and the derived hash use
`Zeroizing`; neither is returned through RPC. Its transferred WASM byte vector
and retained master key also use `Zeroizing`; the thin Worker must wipe the
JavaScript export immediately. `BrowserCoreClient.restore` consumes
that prepared profile, calls the SDK's credentialed fresh session check, and
exposes only a random opaque handle plus principal, generation and persistence.
Every subsequent status access checks both handle and exact generation. Native
session JSON, cookies, refresh credentials and WebSocket tokens are not exports.

The inactive `rustCore` frontend modules provide a bounded structured-clone RPC,
page-owned Worker termination, Web Lock coordination, and transaction-completion
adapters for the existing CryptoKey-only `openmates_crypto/keys/master_key`
record. `PriorProfileReader` snapshots `userDB.getUserProfile().user_id`,
`getMasterKey()`, existing encrypted email/salt (session storage before local
storage), persistence flags and a lifecycle generation before the fresh check.
It rereads the sources before and after admission and invalidates the Worker on
coordinated mutation. Missing evidence or changed sources fail closed without a
retry. The caller must retain the returned lifecycle disposal hook for the entire
Worker session. Evidence is not authority:
only the Rust SDK's comparison against authenticated server `user.id` admits it.

No generated WASM package, lockfile, build or runtime admission proof is included.
The SDK browser implementation is being developed separately. The reader is not
wired into existing auth: before activation, all legacy auth/profile mutations
and cross-tab changes must use the lifecycle gate, before checkAuth/initialize
can replace prior identity. Independent databases and web storage are not atomic;
the reader cannot establish coherence against uncoordinated writes or ABA changes.
Its key reread uses the legacy getMasterKey cache, so out-of-band IDB key mutation
also requires lifecycle invalidation. WebAuthn/challenge,
logout storage policy, actual persistence wiring and application activation await
that SDK contract and coordinated before/after measurements. Optional email-key
material is not part of RPC or the SDK browser-profile constructor. The SDK
browser session leaves that optional native-session field empty.
Inert Node fixtures
test host behavior only; they are not browser, network, Rust or WASM evidence.


## Private next-stage proposal: selected encrypted history

The proposed Worker-only `open_chat(handle,generation,chatId)` is an adapter to the
existing Rust `Client::open_chat`, with the Rust admission checked before and after
the await. It exposes a bounded text projection only: selected ID/title and complete
message ID/role/content for 1–128 messages, up to 64KiB per content and 256KiB total
UTF-8 text including a reserved envelope. Oversize/unsupported output is refused
whole, never truncated. Sender/thinking/embeds, streaming, persistence, writes,
background sync, general history paging and production renderer activation are
not accepted by this first slice. No SDK method, Cargo dependency or lock changes
are proposed; existing Rust owns all metadata access, key unwrap, decryption and
message-window policy. Cookies remain browser-owned and credentialed SDK transport
is unchanged. There is no API-key/developer endpoint or plaintext logging surface.

The thin existing-IDB adapter reads only one encrypted legacy `chats_db/chats`
record after its readonly transaction completes. It refuses absence, blocked opens,
upgrade races, malformed rows, cancellation and missing enumeration support. It
never creates a persistent empty database, upgrades, repairs, deletes or writes
rows. Its ciphertext witness is page-local selection/preservation evidence, not
owner/key/cache authority and is never sent to Rust or public proof output. Rust
freshly obtains its own encrypted metadata/history from existing first-party APIs.

The inactive preview privately compares Rust's plaintext against a genuinely
seeded encrypted synthetic fixture and emits boolean proof flags only. The isolated
CI proposal preserves the existing 4 session/owner/stale/cancellation cases and adds
one true selected-history readback with real verified WASM assets and unmocked API
responses. Fixture setup uses independent explicit CI SDK credentials, not imported
browser cookies or master-key bytes; exact owner/ciphertext cleanup is reused.
Raw credentials, keys and plaintext never enter proof attachments. Actual chat
plaintext is intentionally available to the authorized page through bounded RPC;
JavaScript strings are garbage-collected, not claimed zeroized.

This proposal is uncompiled and unrun as Rust/WASM/browser product behavior.
Only inert host/adapter checks may be reported locally. Exact-source managed WASM
compilation, isolated Chromium preview/API+encrypted-readback/security proof,
rendered preview evidence and the accepted full-application performance floor
remain required. Legacy app data, lifecycle coordination and production auth/chat
routing remain untouched. Uncoordinated cross-tab/ABA writes retain the foundation's
existing limitations; activation still requires all legacy mutations to participate
in the prior-profile lifecycle gate. No native/Mac/publication acceptance is inferred.
