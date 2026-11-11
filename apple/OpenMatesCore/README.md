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
window). A fresh sign-in after logout begins in the core
(`ViewModelCore::begin_session`, Rust only until the Apple login moves into the core).

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
