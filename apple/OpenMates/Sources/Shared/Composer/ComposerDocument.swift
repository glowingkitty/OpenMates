// Product-owned native composer document contract.
// Canonical markdown remains durable; TextKit and Tiptap are transient adapters.
// This initial implementation is intentionally a red-phase compile skeleton.
// Parsing and serialization are added only after shared contract tests fail.
// Encryption material and platform editor objects must never enter this model.

import Foundation

struct ComposerDocumentV1: Equatable {
    let version: Int
    let nodes: [ComposerNodeV1]
}

struct ComposerNodeV1: Equatable {
    let kind: String
    let id: String
}

enum ComposerDocumentError: Error {
    case notImplemented
}

enum ComposerMarkdownAdapter {
    static func parse(_ markdown: String) throws -> ComposerDocumentV1 {
        throw ComposerDocumentError.notImplemented
    }

    static func serialize(_ document: ComposerDocumentV1) throws -> String {
        throw ComposerDocumentError.notImplemented
    }
}

enum ComposerPositionMap {
    static func utf16Length(_ value: String) -> Int {
        value.utf16.count
    }
}
