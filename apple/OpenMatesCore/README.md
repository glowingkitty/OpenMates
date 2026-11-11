# OpenMatesCore (generated UniFFI bindings)

Swift and C bindings of the shared Rust client core
(`packages/openmates-apple-bindings`, UniFFI 0.32.2). Do not edit these files by
hand; they are generated and committed so Xcode builds without a bindgen step.

- `Sources/OpenMatesCore/OpenMatesCore.swift` — Swift API, compiled into the
  OpenMates (iOS/macOS) and OpenMatesWatch targets.
- `include/OpenMatesCoreFFI/OpenMatesCoreFFI.h`, `module.modulemap` — the C
  module `OpenMatesCoreFFI`, found through `SWIFT_INCLUDE_PATHS`.

The static library `libopenmates_apple_bindings.a` is built per Xcode build by
the "Build OpenMatesCore" script phase
(`packages/openmates-apple-bindings/build-xcframework.sh --xcode-phase`) into
`$(DERIVED_FILE_DIR)/OpenMatesCore` and linked with `-lopenmates_apple_bindings`.

## Cache directory of `ViewModelCore`

Swift passes `CoreConfig.cacheContainer` (an existing OS-provided directory,
used as is, symlinks allowed) and `cacheDirectoryName` (one plain name such as
`core-cache`); the core creates that directory `0700` inside the container and
does all cache file IO there. It never walks the container's ancestors, which a
sandboxed app cannot read.

## Chat window and sign-in on `ViewModelCore`

`openChat(request:chatId:)`, `loadOlder`, `closeChat` and `markRead` run the
core chat window; `ViewListener` receives `ChatWindow` events tagged with the
Swift-chosen request id (cached window first, then first page or the strict
window). A fresh sign-in after logout begins in the core (see below).

## Login and send from Swift on `ViewModelCore`

- `loginPassword(email:password:tfaCode:stayLoggedIn:cancellation:)` runs the
  password login in the core, stores the session through `CredentialStore`
  (Swift acknowledges as usual) and then runs `start`. Outcomes are the core's
  own `CoreError` cases: `TwoFactorRequired` (call again with `tfaCode`),
  `Authentication`, `Locked` (Keychain store not acknowledged; the new server
  session is logged out), `Invalid` while signed in. A fresh profile emits only
  `Session(Admitted)`; call `bootSync` for the chat list.
- Pair login of this device: `beginPairLogin()` (code and link to show),
  `pollPairLogin()` until `"approved"`, `submitPairPin(pin:)`, then
  `finishPairLogin(cancellation:)` until `true` (stored, relay acknowledged,
  started); `cancelPairLogin()` abandons it.
- `send(request:chatId:text:cancellation:)` sends a turn; the user message
  carries `sendState` (`Sending` … `Delivered`, `Failed`, `Cancelled`).
  `cancelSend()` cancels the running send without waiting for the actor.
- Passwords, codes and PINs are only call arguments; the binding zeroizes them
  after the core call and never stores or logs them. Passkey, recovery-key and
  backup-code login, and importing a Swift-held session, are not in the core
  API yet; the app still signs in through `AuthManager` until plan step A4.

## Session ownership and un-migrated Swift code

- The core alone owns the session (cookies, `ws_token`, master key). A login
  that finishes in Swift (passkey, recovery key, backup code, device
  verification) is handed over once with `adoptSession(session:cancellation:)`
  (validated, stored and acknowledged, then `start`); Swift then deletes its
  copies. `Invalid` while signed in or for a malformed field.
- Swift REST calls go through `httpRequest(request:cancellation:)`: a `/v1/`
  path with no query string inside it, query pairs, allow-listed headers and
  an optional body. The core adds the cookie, stores rotated cookies and
  returns status, allow-listed headers and body. Core-owned auth routes,
  absolute URLs and other headers are `Forbidden` or `Invalid`. Uploads to the
  upload host and streaming are not covered.
- `sessionInfo()` gives the user id, email hash, team, pair deadline and
  whether the session was admitted (`nil` while signed out). A rejected session
  (401) wipes the profile and emits `Session(Expired)`; drop all state then.
- Frozen remainders, refused while signed out: `legacySocketGrant()` (session
  id and `ws_token` for `WebSocketManager`; plan step A4a removes it; valid only
  while the core opens no socket, the server keeps one socket per device) and
  `legacyMasterKey()` (memory only, for the remaining `CryptoManager` callers;
  step A3b removes it). Nothing new may use them.

## Watch arm64_32: no TLS in the core

The 32-bit Apple Watch slice (`arm64_32-apple-watchos`, built with nightly and
`-Zbuild-std`) links the same API, but the core is built there without any TLS
stack: `ring`, under the core's rustls TLS, does not support ILP32 arm64. On
that slice a core HTTPS request fails with the offline/transport error and a WSS
connection with a TLS-not-enabled error; nothing falls back to plain HTTP/WS.
The Watch uses only the pairing crypto from the core today and does its
networking in Swift. All other slices (iOS, simulators, macOS, 64-bit Watch)
keep full TLS. Plan `apple-client-core-migration` finding F-8; the Watch TLS path
is decided in step A7.

After changing the binding crate's exported API or docs, regenerate:

```bash
packages/openmates-apple-bindings/build-xcframework.sh --update-bindings
```

CI (`--mode apple-core`) runs `--check-bindings` and fails when these files
differ from what the crate generates. Plan: `docs/plans/apple-client-core-migration/` (D-3).
