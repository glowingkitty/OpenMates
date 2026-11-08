# Changelog — `openmates` npm package (CLI and SDK)

Only SDK-relevant compatibility notes are recorded here. Release versions follow
the product line (`0.29.x` alpha prereleases from `dev`, stable from `main`).

## Unreleased

### Changed

- `billing.downloadInvoice`, `billing.downloadCreditNote` and
  `billing.usageExport` now declare the exported `RawDownload` type
  (`contentType`, optional `filename`, `data: ArrayBuffer`); the runtime shape is
  unchanged. `filename` is now always the last path component of the
  `Content-Disposition` name, and is omitted for `.`/`..` names or a malformed
  `filename*` encoding (previously such a header threw a `URIError`). Rust and
  Python follow the same filename contract.

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
