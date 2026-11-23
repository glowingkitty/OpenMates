# ONNX Runtime 1.20.0 for Apple (vendored)

Upstream package: `microsoft/onnxruntime-swift-package-manager` at revision
`12ce7374c86944e1f68f3a866d10105d8357f074` (MIT, see `LICENSE`). Since November 2026
that repository returns "Repository not found", and the binary host
`download.onnxruntime.ai` presents an invalid certificate, so a clean Xcode
build could resolve neither.

- `objectivec/`: the upstream Objective-C bindings, unchanged (training and test
  files left out, as upstream's own manifest excludes them).
- `onnxruntime-c-1.20.0.zip`: the files of the official
  `pod-archive-onnxruntime-c-1.20.0.zip` (SHA-256
  `50891a8aadd17d4811acb05ed151ba6c394129bb3ab14e843b0fc83a48d450ff`), taken from a
  SwiftPM artifact cache whose `workspace-state.json` records that exact URL and
  checksum, and zipped again (symlinks kept). The re-zipped archive has its own
  checksum; the files inside are unchanged:

| File | SHA-256 |
|---|---|
| `LICENSE` | `2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c` |
| `onnxruntime.xcframework/Info.plist` | `04c9d613d6b867841346c7e09b6994c9b33a2db6b74aef40132d9fb76dff4a39` |
| `onnxruntime.xcframework/ios-arm64/onnxruntime.framework/onnxruntime` | `ef321de13c7dd0075d38b82fbafb9a1e001b81cd11e4fb18229dedf8d7c64231` |
| `onnxruntime.xcframework/ios-arm64_x86_64-simulator/onnxruntime.framework/onnxruntime` | `f80750352a1207f58f459f711996a79bb107b34c3fa39988b67dc9b7d56aa1cc` |
| `onnxruntime.xcframework/macos-arm64_x86_64/onnxruntime.framework/Versions/A/onnxruntime` | `bd65d939ef23429a4085a52cd4b9c56a7581528ee45f2db69b95a85e655fe4fd` |
