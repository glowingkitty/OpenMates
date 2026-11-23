// swift-tools-version: 5.6
//
// Vendored copy of the ONNX Runtime Swift package (MIT, see LICENSE), taken
// unchanged from upstream revision 12ce7374c86944e1f68f3a866d10105d8357f074
// (ONNX Runtime 1.20.0). The upstream package repository is no longer
// reachable, so a clean Xcode build could not resolve it; this local package
// keeps the exact same Objective-C bindings and binary.
//
// Changes from upstream: the unused onnxruntime_extensions product and binary,
// the test targets and the training sources were removed, and the binary is a
// local archive of the official release files (PROVENANCE.md) because its
// download host no longer serves it.
// Used by: apple/OpenMates/Sources/Core/LocalModels/LocalNeuralTTSRuntime.swift

import PackageDescription

let package = Package(
    name: "onnxruntime",
    platforms: [.iOS(.v13),
                .macOS(.v11)],
    products: [
        .library(name: "onnxruntime",
                 type: .static,
                 targets: ["OnnxRuntimeBindings"]),
    ],
    dependencies: [],
    targets: [
        .target(name: "OnnxRuntimeBindings",
                dependencies: ["onnxruntime"],
                path: "objectivec",
                cxxSettings: [
                    .define("SPM_BUILD"),
                ]),
        // Local archive: the official 1.20.0 binary is no longer downloadable. See PROVENANCE.md.
        .binaryTarget(name: "onnxruntime", path: "onnxruntime-c-1.20.0.zip"),
    ],
    cxxLanguageStandard: .cxx17
)
