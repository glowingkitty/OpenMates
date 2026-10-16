# ExecuTorch arm64 build bridge

The pinned ExecuTorch 1.5.0 archives contain iOS device arm64, iOS simulator arm64
and macOS arm64 slices. They lack x86_64 slices. The Mac application stays
universal; Intel and x86_64 simulator runtime use remains explicitly unsupported.

ExecuTorch is not linked through SwiftPM. Its prebuilt product and TokenizersRust
both flatten a `module.modulemap` into Xcode's shared `include` output, causing a
build collision. The main-app prebuild bridge instead stages the exact original
headers, Clang module map, Swift overlay and six static libraries in separate
`$(DERIVED_FILE_DIR)/LocalModelBridge/<PLATFORM_NAME>` directories. Nothing is
written to SourcePackages or its flattened include output. Tokenizers retains
its ordinary SwiftPM dependency.

`catalog.json` pins all six exact upstream SDK ZIP checksums, including the
transitive threadpool, frameworks and C++ runtime. The pinned SwiftPM distribution
commit contains no license; the bundled BSD license is pinned to the corresponding
source release v1.5.0 commit and is included in the app resources.

The prebuild script runs for supported arm64 platform builds. It reuses cached
ZIP bytes only when their whole-file SHA-256 matches the catalog, including any
ZIPs retained by SourcePackages. Extracted cache directories or receipts alone
are insufficient verification. When no verified ZIP is available, the authorized
build fetches the exact pinned SDK archive and verifies it before extraction.
No model weights, private input, inference requests or replacement runtime are
involved.

Each selected platform keeps its original slice identifier and static library
names. The core archive contains both `ExecuTorch` Objective-C module headers and
`ExecuTorch.swiftinterface`; the latter supplies generic Tensor, Module.forward
and Value.tensor APIs. Its exact bytes are preserved under a platform-specific
`Modules/ExecuTorch.swiftmodule` directory. The upstream SwiftPM dummy.swift is
empty; no additional source wrapper is required.

Only architecture-qualified arm64 SDK settings receive the header/Swift search
paths and six force-load linker flags, preserving registration. Intel and Watch
receive no model linker flags. Generated ZIPs, headers, modules and receipts
remain under DERIVED_FILE_DIR, outside release source inputs. The committed
`apple/LocalModelBridge` script, catalog, license and tests are included in source
provenance.

Run checks without SDK or model downloads:

```sh
python3 -B apple/LocalModelBridge/prepare.py --validate-catalog
python3 -B apple/LocalModelBridge/test_prepare.py
```

Fixtures verify checksum rejection, cache reuse without network, exact selected
slice extraction, original Swift overlay preservation, platform module-map
separation and architecture selection. These are packaging checks, not native
compile or inference evidence. Native verification must confirm the module-map
collision is gone, imports and registration symbols resolve on iOS device and
simulator, the Mac archive stays universal, and deployed models run offline.
