# Changelog — `openmates` npm package (CLI and SDK)

Only SDK-relevant compatibility notes are recorded here. Release versions follow
the product line (`0.29.x` alpha prereleases from `dev`, stable from `main`).

## Unreleased

### Breaking

- Rust SDK: `Memories::create`, `update` and `types`, `MemoryInput`,
  `hash_item_key` and `memory_plaintext` are removed, matching npm and Python
  (removed 2026-11-07; the backend answers 410). `IdeaBucket::save_settings` now
  returns the same refusal as npm/Python. `sdk.memories` is implemented in all
  three SDKs.

### Changed

- `billing.downloadInvoice`, `billing.downloadCreditNote` and
  `billing.usageExport` now declare the exported `RawDownload` type
  (`contentType`, optional `filename`, `data: ArrayBuffer`); the runtime shape is
  unchanged. `filename` is now always the last path component of the
  `Content-Disposition` name, and is omitted for `.`/`..` names or a malformed
  `filename*` encoding (previously such a header threw a `URIError`). Rust and
  Python follow the same filename contract.

Cross-language SDK alignment (npm, Python and Rust now behave the same; each case
is a shared conformance vector):

- **Malformed document slugs are refused locally.** `docs.show()` and
  `docs.download()` throw the new `OpenMatesInvalidInputError`
  (code `OPENMATES_SDK_INVALID_INPUT`) before any request for an empty slug,
  `..`, a leading or trailing `/`, an empty or `.` segment, `\`, `:`, NUL or other
  control characters, or a slug over 4096 bytes. Previously these reached the
  server. Python raises the same error class, which is a `ValueError`.
- **An empty Wikipedia `language` means English.** `wikipedia.search()`,
  `summary()`, `learning()` and `article()` send `language=en` for `""`, the same
  as an omitted language. Previously npm sent `language=` and the backend
  rejected the request.
- **Draft preview fallback counts Unicode characters.** When a draft has no saved
  preview, `drafts.get()`/`list()` use the first 160 Unicode characters of the
  markdown instead of 160 UTF-16 code units, so the preview never ends in half an
  emoji. A saved but empty or undecryptable `encryptedDraftPreview` now gives
  `preview: null` instead of falling back to the markdown.

### Added (Python)

- `OpenMatesClient(api_key=...)` mirrors the npm root client: a missing or blank
  key raises `OpenMatesApiKeyRequiredError` (code `OPENMATES_SDK_API_KEY_REQUIRED`,
  a subclass of `OpenMatesConfigError`) at construction, it never reads
  `OPENMATES_API_KEY`, and it refuses the legacy `session`/`load_stored_session`
  options. `OpenMates()` is unchanged.
- Python `embeds.add_to_project()`/`remove_from_project()` resolve a Project
  slug, name or id prefix before routing, as npm does.

## 0.30.0

### Breaking

- **The SDK is API-key only and separate from the CLI login.** The root
  `OpenMatesClient` export no longer loads the stored CLI login (the 0.29.x
  `OPENMATES_SDK_CLI_SESSION` deprecation is complete). It is now the API-key
  client: `new OpenMatesClient({ apiKey })`. Constructing it (or calling
  `OpenMatesClient.load()`) without an `apiKey` throws
  `OpenMatesApiKeyRequiredError` (code `OPENMATES_SDK_API_KEY_REQUIRED`), and the
  `session` / `loadStoredSession` options are rejected. No SDK entrypoint reads
  CLI state files or the keychain, so an SDK script can use a different account
  from the logged-in CLI. `SDK_CLI_SESSION_DEPRECATION_CODE` is removed.

  **Migration:** create an API key in Settings → Developers and pass it
  explicitly (`new OpenMatesClient({ apiKey })` or `new OpenMates({ apiKey })`).
  The key decrypts your chats locally with its own wrapped account key; nothing
  else is needed. The `openmates` command line keeps its own login and is
  unaffected.

### Deprecated

- `SessionClient.loginPassword()` / `importSession()` in `openmates/sdk/v1`. Public
  SDKs are API-key only; these login modes are removed once every capability they
  offer is available through API-key authentication (open work tracked in
  `config/sdk-capabilities.json`).

## 0.29.x

### Deprecated

- **Implicit CLI login in the root `OpenMatesClient`.** Constructing
  `OpenMatesClient` (or calling `OpenMatesClient.load()`) from the root
  `openmates` export without a `session` still loads the stored CLI login, but now
  emits one `DeprecationWarning` per process with code `OPENMATES_SDK_CLI_SESSION`.
  SDK credentials must be explicit. Migrate by passing `session` explicitly,
  setting `loadStoredSession: false`, or using `SessionClient` from
  `openmates/sdk/v1` (`loginPassword()` / `importSession()`).
  A future minor release (planned 0.30.0) will require explicit credentials for
  the root export; the `openmates` command line is unaffected.

### Added

- `openmates/sdk` and `openmates/sdk/v1` entrypoints backed by the shared Rust
  core. Privacy helpers, task ordering and embed-version reconstruction use the
  portable WebAssembly build; `SessionClient` uses the Node-API build for now.
  A missing artifact raises `native_binding_unavailable` (no fallback).
