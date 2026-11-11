# A2 design: core shell runtime

Design for step A2 of `plan.yml` (2026-11-11, analysed at dev 9859544140). TUI
paths are under `frontend/packages/openmates-tui-native/src/`.

## Decisions

- New core modules, outside the busy `client/` files: `local_cache/` (byte
  store, file store, record codec, fence, sections, async façade),
  `shell_session/` (restore, persist, admission, logout), `view_model/`
  (records, events, actor, open, send).
- Native shells pass a directory; the core's `FileByteStore` does the file IO.
  Apple passes its OS-provided container path (symlinks allowed) plus the name
  `core-cache`; the core opens the container directly (a sandbox cannot walk
  its ancestors from `/`) and creates `core-cache` `0700` with `O_NOFOLLOW`
  (`FileByteStore::open_in`; complete-until-first-unlock protection). A Swift callback adapter would cost
  two FFI crossings per record (about 1200 for 600 chat sections) and could not
  keep the fsync ordering. Swift writes no cache bytes at all.
- `ByteStore` is a synchronous trait (`get`, `version`, `put` with
  `Durability::{Now, AfterBarrier}`, `delete`, `list(prefix)`, `barrier`, `sync`,
  `lock(scope)`); the async façade `CacheStore` runs it on the ordered blocking
  queue. No multi-key transaction: section records first, barrier, index last.
- On-disk format and file names are unchanged (`cache-<sha256(owner)>-<sha256(logical)>.json`,
  AAD from the session only), so existing TUI installs need no migration.
- The single-record write-skip memo (`CacheWriteMemo`) is dropped; it is a
  shortcut for `completion-pending-*` journals only and depends on inode tricks.
- `ChatRefreshDurableReceipt` is minted only inside the core's `persist_for`,
  after credential acknowledgement and index commit; shells stop vouching.
- Credentials: `trait CredentialPersistence { store(snapshot) -> Saved | Superseded(Session); clear() }`.
  TUI implements it over its keyring/vault; Apple implements it by emitting
  `credentials_changed(rev)` and awaiting `acknowledge_credentials(rev)` with a timeout.
- Apple uses per-operation file locks only (a lock held in an app-group
  container while suspended gets the app killed) and wraps persist in a
  background task. Only the main app opens the cache in A4; extensions call the
  core statelessly.
- Default retention on Apple until decided otherwise: full index plus content
  of the 200 most recent chats.

## What moves, what stays

| TUI file | Moves to core | Stays in TUI |
|---|---|---|
| `storage.rs` | cache record codec, read/write/publish, AAD, fence, file primitives (about 820 lines) | credential backends, keyring, vault, session envelope, device identity (about 1180 lines) |
| `storage_sections.rs` | all (629 lines) | |
| `runtime_store.rs` | generation guard, ordered queue, cache and section functions, content loader | session load/save/revoke, storage mode |
| `session_runtime.rs` | `restore_command_cache`, `load_cached_chat`, `FreshSessionAdmission`, `persist`, `logout` | CLI command cache policy, whoami output |
| `runtime.rs` | actor loop, views, stamps, boot, boot sync, live update, open, publication wrappers (about 1650 lines) | terminal loop, prompts, profile setup, pairing UI |
| `completion_recovery_adapter.rs` | all | |
| `home_items.rs` | `arrange` (chat list order) | |

## View model

Commands: `Start{credentials}`, `RefreshChats`, `OpenChat`, `LoadOlder`,
`CloseChat`, `MarkRead`, `SwitchTeam`, `Send` (A5), `Cancel`, `Logout`.

Events: `Session(SignedOut | Restored | Admitted | Expired | AccessDenied)`,
`SyncProgress{phase, received}`, `ChatList{rows, completeness}`,
`ChatWindow{request, window}`, `ChatUnavailable`, `ChatOpenFailed`,
`Stream{request, chat_id, event}`, `Status`, `Failed`, `Done`.

Typed records replace `serde_json::Value` at the boundary: `ChatListRow`,
`MessageRecord`, `EmbedRef` (`data_json` string until the embeds lane),
`ChatWindowRecord` (with `source` and `has_more_before`), `StreamEvent`.

The two speedups for Apple: `Start` restores the index only (one file) and
emits `ChatList` before any network; `cached_chat(id)` is a mutex-free read of
one section file for instant chat open.

## Lanes

| Lane | Content | Collision risk |
|---|---|---|
| L1 | `FileByteStore` and trait; TUI `Store` uses the core primitives | low |
| L2 | fence, record codec, single records; memo dropped | low |
| L3 | sections and `CacheStore`; `storage_sections.rs` deleted | low |
| L4 | `shell_session`; `session_runtime.rs` shrinks to CLI policy | medium (`command_runtime.rs`) |
| L5 | recovery pump as `client/completion_recovery_pump.rs`; adapter deleted | low to medium |
| L6a | view-model records and events (no TUI change; can start at once) | none |
| L6b | actor: start, list, sync, refresh, team, logout, live list | medium (`runtime.rs`) |
| L7 | open, paging, live window | medium |
| L8 | Apple binding: `CoreConfig.cache_container` + `cache_directory_name`, start/open/paging, listener | regenerated Swift file; serialize with A3 |
| L9 | send, stream, cancel (for A5) | low |

Every lane: TUI crate tests through `heavy_slot`, rust-check, sdk-conformance,
the CLI E2E specs of the touched flows; `rustfmt` on touched files only; new
public items classified in `config/sdk-capabilities.json`.

Apple A4 (chat list and chat open from the core) needs L1 to L8. Apple A3
(batched decrypt) needs none of them and can run in parallel.

## Risks

1. Lifetime file locks in the app-group container (see decisions).
2. The symlink-safe directory walk fails on `/var` to `/private/var`; Swift
   passes a resolved path, and L8 proves ownership and mode checks in the sandbox.
3. `revocation.json` moves to the core while it still guards the TUI session
   file; it stays byte-compatible and revocation stays durable before keyring cleanup.
4. Security-sensitive code moves unchanged, with its tests.
5. Keychain round trip on each credential rotation: timeout and typed error.
