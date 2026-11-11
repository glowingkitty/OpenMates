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

After changing the binding crate's exported API or docs, regenerate:

```bash
packages/openmates-apple-bindings/build-xcframework.sh --update-bindings
```

CI (`--mode apple-core`) runs `--check-bindings` and fails when these files
differ from what the crate generates. Plan: `docs/plans/apple-client-core-migration/` (D-3).
