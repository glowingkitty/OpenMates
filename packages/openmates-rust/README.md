# OpenMates Rust SDK

A headless Rust library for OpenMates authentication, encrypted chat transport,
workspace operations, typed recovery replay and App skills. The native CLI/TUI
uses this crate; the crate has no terminal UI, command parser, keyring, profile
manager or runtime dependency on Node or Python.

The current migration is **not capability complete** and `publish = false`
prevents accidental publication. The shared SDK capability matrix and conformance
gate track remaining parity work.

## API keys only; separate from the CLI login

The public SDK (`openmates::sdk`) authenticates account access only with an API
key the caller supplies (create one in Settings → Developers); it never reads the
CLI login, `~/.openmates`, CLI profiles or a keyring, so it can use a different
account than the logged-in CLI. Each API key carries its own wrapped account key,
unwrapped locally in memory, so the key alone decrypts your chats and embeds.

Boundary: `openmates::sdk` currently still re-exports the whole core crate,
including the cookie-session `Client` below that the CLI/TUI, web and Apple apps
use for their own login. Its password/imported-session login is first-party
session authority, not a supported SDK authentication mode, and is deprecated
for SDK use. It leaves the public `openmates::sdk` surface (staying internal to
the app crates) once every capability it offers is available on the API-key
`OpenMates` client; the remaining gaps are tracked in `config/sdk-capabilities.json`.

## Explicit client state (first-party session authority)

Import `openmates_sdk::{Client, ClientOptions, Session, Error}`. Construct a client
with `Client::new(api_url, optional_session)` or `Client::with_options(...)`.
An API URL is always required. The SDK never reads environment variables,
`~/.openmates`, installed CLI credentials, privacy preferences or an OS keyring.
The caller owns persistence, consent presentation and cancellation.

`ClientOptions` accepts an explicit application origin for custom installations,
privacy options and an optional private-operation policy callback. Default
privacy uses deterministic native detection; requesting unavailable enhanced
semantic privacy fails before submission. Server-provided privacy preferences
remain part of authenticated send preparation.

Supported authentication currently includes password v2, the existing permitted
legacy password fallback, supplied TOTP codes, explicit existing sessions,
native pairing v2 receiver operations, refresh and current-session logout.
Signup, password/recovery changes, 2FA enrollment, passkeys/SSO, pairing approval,
session administration and automatic legacy-password upgrades remain gaps. No routing/model override is introduced.

## API-key and anonymous clients

`OpenMates::new(SdkOptions)` is separate from the cookie-session `Client`.
Supply `SdkCredentials::ApiKey(ApiKey::new(setup_credential)?)` or
`SdkCredentials::Anonymous { anonymous_id }`, an API URL, a stable device ID and
explicit `ClientOptions`. There is no environment credential fallback.

Reviewed generated methods such as `sdk.apps().web().search(input).await` perform
direct SDK requests. Generic dispatch is internal. Task and Code Run results use
bounded polling without repeating the original POST. Anonymous clients expose
`anonymous_status()` and `send_anonymous_chat(message, history)`. Exhausted free
allowances return `Error::SignupRequired`; API-key failures never switch modes.

`sdk_session()` and `master_key()` recover API-key-wrapped account key material.
Only the bearer portion enters HTTP headers. The setup credential's decryption
suffix remains local for PBKDF2/AES-GCM unwrapping. API-key account workspace
facades beyond the reviewed skill/session surface remain parity gaps.

The retired `workflows().create_or_modify` compatibility method returns
`Error::Unavailable { code: "skill_unavailable", reason:
"WORKFLOW_RUNTIME_UNSUPPORTED" }` locally and is absent from live metadata.

New encrypted values use canonical OM/FNV headers. Readers also support legacy
IV/ciphertext values and the exact historical Python OM/01000000 marker, always
requiring successful AES-GCM authentication.

## Credential persistence

After authentication or an operation, obtain `credential_snapshot()`. Persist
its `session` in application-owned encrypted storage, then call
`acknowledge_credentials(snapshot.revision)`. A stale revision is rejected.
An optional `set_credential_updates` channel reports updated snapshots and local
credential clearing, including header rotations when a response body fails.
Events contain secrets, have no `Debug`, and must never be logged.

Pairing has a deliberate durability boundary: `finish_pair()` prepares local
credentials; persist and acknowledge the current snapshot **before** calling
`acknowledge_pair()`. The SDK rejects a premature acknowledgement. Application
storage failures must cancel the pending pair rather than approve it.

`Session` supports serialization for caller-owned encrypted storage and zeroizes
credential strings and key material when dropped. Serialized sessions are
sensitive plaintext until encrypted by the application.

`reset`, logout and dropping the client cancel owned lifecycle operations.
Logout clears local keys before attempting bounded remote revocation and reports
remote failure. A caller can also use `forget_session()` for immediate local
clearing.

## Encrypted chat sends

`Client::send(chat_id, text, options, updates, cancel)` returns `SendOutcome`
with the persisted native Chat and observed response metadata. Explicit options
support a new-chat slug, response timeout, local PII detection, and current-request
memory/sub-chat consent. `Caller` consent requires an independent consent receiver;
`Reject` and `ApproveRequested` act only on a fresh bounded server request.
The SDK preserves pending Task jobs as pending and never treats receipt as proof
of encrypted persistence.

Task update jobs run by default. The client authenticates the Task scope and
lease, encrypts private updates locally, checks the canonical stored ciphertext
after persistence, then confirms the encrypted chat event and final job receipt.
Lost receipts recover without creating new Task ciphertext. Explicitly setting
`task_update_jobs: false` disables both the turn and socket capability. Current
server limitations prevent Team Task creation and context moves through jobs;
those operations fail before a Task write. Ordinary Team updates use the Team
key and canonical Team-scoped Task wrappers.

`incognito: true` uses an authenticated volatile WebSocket session. It bypasses
saved admission, recovery keys, Task jobs, saved memory and all persistence. The
socket closes on success, failure and cancellation. `Client::send_anonymous`
instead uses the public budget/status and HTTP streaming endpoints with an
explicit separate anonymous identifier; it never attaches stored account
credentials or falls back from failed authentication. Both modes prepare PII
locally and retain their returned transcript only in caller-owned memory.

Applications must use `is_ephemeral_chat` to exclude volatile IDs from their own
drafts and journals. The SDK also rejects saved drafts, mutations and history
retrieval for those IDs. Cookie refresh during incognito remains an ordinary
credential update. Volatile history continuations, Team scope, slugs, Project
binding and anonymous Learning Mode remain unsupported; explicit saved consent
approval options reject before submission. Explicit Project binding also remains
unsupported for saved sends. The compatibility `send_message` returns the native
Chat; automatic authorized Project focus routing remains part of saved sends.

## Workflow result delivery

`Workflows::wait_run(workflow_id, initial_run, options, cancel)` observes an
already accepted run without resubmitting it. Completion requires canonical
acknowledgement of every selected chat delivery. A Personal cookie client claims
the delivery, encrypts the authorized destination message and selected embeds,
waits for fenced persistence, then acknowledges it. Recovery under a fresh lease
does not re-encrypt an already persisted result. API-key clients wait for an
authorized owner device to perform that delivery.

General chat sync also drains Workflow deliveries discovered on its socket.
The current Workflow and Task job discovery protocols have no completion/empty sentinel, so a discovery
frame arriving after sync closes is deferred to another connection. Targeted
`wait_run` avoids that discovery race by reading delivery IDs from the canonical
run details. Team Workflow owner delivery remains unsupported.

## Checks

```sh
cargo test --locked --manifest-path packages/openmates-rust/Cargo.toml
```

These checks use synthetic fixtures and local fake transports. Authenticated
product protocol evidence runs in isolated CI, through the native app's SDK
reexports. No local product account or real inference is used by unit tests.

## Cargo packaging

The crate remains `openmates-sdk` version `0.1.0`, MIT licensed and unpublished.
Its explicit package inputs include generated metadata and local crypto fixtures;
consumer library builds do not need the repository, Node or Python. Optional
conformance examples are repository test tooling and can require the explicit
synthetic peer harness when executed.

The native application pins this version exactly while retaining its local
source path for development. The repository guard
`python3 scripts/check_rust_cli_package.py` inspects both crates without building
or publishing. A local archive or dependency override does not establish public
registry availability. Publication, including dev prereleases, remains blocked
by the shared cross-SDK gate; packaging does not waive those gaps.
