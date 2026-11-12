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
  `Session(Admitted)`; call `bootSync` for the chat list. It returns a
  `LoginRecord`: after a legacy (v1) password login the core migrates the
  password to v2 before the hand-over and reports `passwordMigration`
  (`Completed`, `PendingConfirmation` — resumed by the core at the next
  password login, nothing stored in Swift — `Deferred…`, `Unsupported`,
  `Failed`); a migration never fails the login.
- `loginBackupCode(email:password:backupCode:stayLoggedIn:cancellation:)` is
  the same login with a backup code (`remainingBackupCodes` in the record; a
  refused code is `Authentication`). `loginRecoveryKey(email:recoveryKey:
  stayLoggedIn:cancellation:)` signs in with the recovery key (no second
  factor). Both end like `loginPassword`, including cancellation.
- Pair login of this device: `beginPairLogin()` (code and link to show),
  `pollPairLogin()` until `"approved"`, `submitPairPin(pin:)`, then
  `finishPairLogin(cancellation:)` until `true` (stored, relay acknowledged,
  started); `cancelPairLogin()` abandons it.
- `send(request:chatId:text:cancellation:)` sends a turn; the user message
  carries `sendState` (`Sending` … `Delivered`, `Failed`, `Cancelled`).
  `cancelSend()` cancels the running send without waiting for the actor.
- Passwords, codes and PINs are only call arguments; the binding zeroizes them
  after the core call and never stores or logs them.

## Passkey login on `ViewModelCore`

Swift runs only the system ceremony (`ASAuthorizationController` with the PRF
extension); the core keeps the continuation and does verification, key
derivation, unwrap, login and admission.

- `beginPasskeyLogin(email:cancellation:)` returns `PasskeyChallengeRecord`
  (`optionsJson`: the server's assertion options, `challenge` and
  `extensions.prf.eval.first` base64url). Without `email` any passkey of this
  device may answer; with `email` another account's passkey is refused.
- `finishPasskeyLogin(assertionJson:prfOutput:stayLoggedIn:cancellation:)`
  takes UTF-8 JSON `{"credential_id": base64url raw id, "client_data_json",
  "authenticator_data", "signature", "user_handle"?}` (standard base64 of the
  raw bytes) and the raw PRF `first` output (16..=64 bytes, zeroized, never
  stored or logged). It ends like `loginPassword` (`passwordMigration` is
  `NotNeeded`), including cancellation. The continuation is single use.
- `cancelPasskeyLogin()` forgets a begun login or device verification.
- Errors: `Invalid` with the core's fixed message for no begun request, an
  answer to another request, a missing PRF output ("This passkey does not
  support OpenMates encryption. …") or another account's passkey;
  `Authentication` when the server refused the passkey; `Crypto` when the
  master key does not unwrap.

## Profile and device verification on `ViewModelCore`

- `userProfileJson()` returns the admitted account's server user payload as
  JSON bytes; decode it with `UserProfile`. Every admission (login, restore,
  adoption, team switch) replaces it and emits `Session(Admitted)`, so re-read
  it on that event. `Authentication` while signed out or not admitted. It holds
  the server's wrapped-key fields: never log it.
- When the session check asks to verify this device or to sign in again, the
  call (`start`, `loginPassword`, `adoptSession`, …) fails with
  `VerificationRequired` and the listener gets
  `Session(VerificationRequired(verification:))`; `pendingVerification()`
  returns the same value. The session and the Keychain payload stay.
  `Device(method: .twoFactor, …)`: call `verifyDevice2fa(code:cancellation:)`
  (refused code: `Authentication`, still pending; success: `Session(Admitted)`).
  `Device(method: .passkey, …)`: call `beginPasskeyDeviceVerification(
  cancellation:)`, run the ceremony with its `optionsJson`, then
  `finishPasskeyDeviceVerification(assertionJson:cancellation:)` (same JSON
  shape, no PRF; refused: `Authentication`, still pending; success:
  `Session(Admitted)`). `ReAuth`: sign out and sign in again.
- `userProfile()` returns the admitted account's profile as a typed
  `UserProfileRecord` (same lifetime and errors as `userProfileJson()`).
- `uploadFile(request:cancellation:)` uploads one file described by an
  `UploadRequestRecord` through the core (size limit and transport in Rust) and
  returns the server reply as `HttpResponseRecord`.

## Memories on `ViewModelCore`

Memory documents live in the master-key encrypted account settings; the core
decrypts, parses, writes and re-encrypts them. Swift gets plaintext
`MemoryDocumentRecord`s only (`fields` is `nil` for a document that does not
parse; it can still be deleted). Refusals are `CoreError.Memory(code:)` with
the web codes (`rule_not_found`, `rule_exists`, `rule_changed`,
`rule_not_undoable`, `invalid_rule_document`, `rule_catalog_limit`,
`rule_settings_unavailable`, `rule_save_failed`). All calls take an optional
`CoreCancellation`; signed out is `Authentication`.

- `listMemoryDocuments`, `memoryDocument(id:)`: the stored Memories.
- `createMemoryDocument(fields:)`, `updateMemoryDocument(id:fields:)`: validate
  and stamp `created_at`/`updated_at`, then save; `deleteMemoryDocument(id:)`.
- `deleteExpiredMemoryDocuments()`: removes Memories past `valid_until` and
  returns the count (call when the Memories screen opens).
- `setAssistantMemoryWrites(enabled:)`: opt-in (off by default) for assistant
  memory-write jobs during this device's own sends. Turn it on only once the
  chat shows `context_entry` system messages: `contextEntryNotice(content:)`
  parses one into a `ContextEntryNoticeRecord`; its `undoJobId` goes to
  `undoAssistantMemoryWrite(chatId:jobId:)`. `assistantMemoryWrites(chatId:)`
  lists a chat's notices.

## Embed versions and Enhance on `ViewModelCore`

User-made embed versions and image Enhance (spec `feature.embed-user-edits`).
The core reads the server head fresh before each write, owns the embed keys,
encryption and the compare-and-swap; Swift passes plaintext and an
`EmbedScopeRecord` (where the user acted) and gets presentation records.
Refusals are `EmbedEditError` (`AccessDenied`, `Validation`, `Refused`,
`KeyUnavailable`, `Offline`, `SessionExpired`, `Cancelled`, `Transport`). All
calls take an optional `CoreCancellation`.

- `embedVersionHistory(embedId:scope:)`: every version with its origin
  (assistant or user) and action, oldest first, as `EmbedVersionHistoryRecord`.
- `commitEmbedEdit(embedId:scope:content:textPreview:operationId:)`: commits
  edited content as the next version (`EmbedRevisionOutcomeRecord`).
- `restoreEmbedVersion(embedId:scope:fromVersion:)`: adds version
  `fromVersion` again as the newest version; nothing is deleted.
- `reconcileEmbedUpdateNotices(chatId:)`: on chat open, settles pending
  `embed_updated` notices (`EmbedNoticeReconcileRecord`).
- `embedUpdateTimeline(rows:)` (free function): groups `embed_updated` rows of
  a chat timeline into `EmbedTimelineItemRecord`s.
- Image Enhance: `startImageEnhance(embedId:scope:operationId:)`,
  `imageEnhanceStatus(operationId:)`,
  `waitImageEnhance(operationId:deadlineMs:waker:)`,
  `saveImageEnhanceResult(embedId:scope:operationId:)` and the one-call
  `enhanceImage(embedId:scope:operationId:waker:)`. An `ImageEnhanceWaker`
  (`ImageEnhanceWaker()`, `notifyFrame(eventType:payloadJson:)`) lets Swift
  forward socket frames so a wait ends as soon as the job reports.

## Server region on `ViewModelCore`

The Settings > AI "Prefer EU servers" choice. Device-local, like the web's
profile-store field: the core does not persist it, so Swift keeps it in its
preferences and sets it after launch. The core sends it with each turn as
`model_routing_restrictions.server_region_preference` (only for `Global`; EU is
the server default).

- `serverRegionPreference()`, `setServerRegionPreference(preference:)`:
  `ServerRegionPreferenceRecord.eu` (default) or `.global` (each model's
  fastest server); applies from the next `send`.
- `serverRegionPreferenceFromStored(value:)`: reads a stored text value the way
  every shell does (`"global"` is `.global`, anything else `.eu`).

## Session ownership and un-migrated Swift code

- The core alone owns the session (cookies, `ws_token`, master key). A login
  that finishes in Swift (passkey, recovery key, backup code, passkey device
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

Draft reconciliation and un-migrated socket features: `draftVersions(chats:cancellation:)`
returns the server's `draft_v`/tombstone per chat on the core's monitor socket
(`Offline` without a live monitor). `forwardUnownedFrames()` opts in to
`unownedSocketFrame` events; `sendUnownedFrame(eventType:payloadJson:cancellation:)`
writes a raw frame of a type the core does not own (core-owned types are refused).
