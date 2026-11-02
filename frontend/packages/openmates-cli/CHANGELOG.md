# Changelog — `openmates` npm package (CLI and SDK)

Only SDK-relevant compatibility notes are recorded here. Release versions follow
the product line (`0.29.x` alpha prereleases from `dev`, stable from `main`).

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
