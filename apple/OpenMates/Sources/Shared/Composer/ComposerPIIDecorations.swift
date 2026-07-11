// Text-node-only PII detection and redacted composer snapshots.
// Mention and embed atoms are opaque and their machine metadata is never scanned.
// Decorations identify visible UTF-16 ranges without mutating the live document.
// Redacted snapshots preserve node order, IDs, and canonical machine references.
// Detection output contains placeholders and categories, never diagnostics payloads.

import Foundation

struct ComposerPIIMapping: Equatable, Sendable {
    // Request-scoped reversible plaintext. Never persist or include in diagnostics.
    let placeholder: String
    let original: String
    let category: String
}

struct ComposerPIIRedactionSnapshot: Equatable, Sendable {
    let document: ComposerDocumentV1
    let mappings: [ComposerPIIMapping]
}

struct ComposerPIIDecorations {
    private static let emailPattern = #"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"#

    func redactedSnapshot(document: ComposerDocumentV1) -> ComposerPIIRedactionSnapshot {
        var mappings: [ComposerPIIMapping] = []
        let nodes = document.nodes.map { node -> ComposerNodeV1 in
            guard node.kind == "text", let source = node.source else { return node }
            let matches = emailMatches(in: source)
            guard !matches.isEmpty else { return node }
            let mutable = NSMutableString(string: source)
            for match in matches.reversed() {
                let original = (source as NSString).substring(with: match)
                let placeholder = "{{EMAIL_\(mappings.count + 1)}}"
                mappings.append(.init(
                    placeholder: placeholder,
                    original: original,
                    category: "email"
                ))
                mutable.replaceCharacters(in: match, with: placeholder)
            }
            return .text(id: node.id, source: mutable as String)
        }
        return ComposerPIIRedactionSnapshot(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            mappings: mappings
        )
    }

    static func nativeDecorations(matches: [PIIMatch], visibleText: String) -> [NativeComposerPIIDecoration] {
        let source = visibleText as NSString
        var searchLocation = 0
        return matches.compactMap { match in
            guard searchLocation <= source.length else { return nil }
            let range = source.range(
                of: match.value,
                options: [],
                range: NSRange(location: searchLocation, length: source.length - searchLocation)
            )
            guard range.location != NSNotFound else { return nil }
            searchLocation = NSMaxRange(range)
            return NativeComposerPIIDecoration(id: match.id, range: range)
        }
    }

    private func emailMatches(in source: String) -> [NSRange] {
        guard let regex = try? NSRegularExpression(
            pattern: Self.emailPattern,
            options: [.caseInsensitive]
        ) else {
            return []
        }
        return regex.matches(
            in: source,
            range: NSRange(location: 0, length: source.utf16.count)
        ).map(\.range)
    }
}
