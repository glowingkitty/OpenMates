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

struct ComposerDocumentPIIRedactionResult: Equatable, Sendable {
    let document: ComposerDocumentV1
    let mappings: [PIIMapping]
}

struct ComposerPIIDecorations {
    private static let emailPattern = #"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"#

    static func visibleText(document: ComposerDocumentV1) -> String {
        document.nodes.map { node in
            switch node.kind {
            case "text":
                node.source ?? ""
            case "hardBreak":
                "\n"
            case "mention", "embed":
                "\u{FFFC}"
            default:
                ""
            }
        }.joined()
    }

    static func redactedDocument(
        document: ComposerDocumentV1,
        excludedIds: Set<String> = [],
        options: PIIDetectionOptions = PIIDetectionOptions()
    ) -> ComposerDocumentPIIRedactionResult {
        let effectiveOptions = PIIDetectionOptions(
            excludedIds: options.excludedIds.union(excludedIds),
            disabledCategories: options.disabledCategories,
            personalDataEntries: options.personalDataEntries
        )
        let matches = PIIDetector.detect(in: visibleText(document: document), options: effectiveOptions)
        var textRanges: [(nodeIndex: Int, range: NSRange)] = []
        var location = 0

        for (index, node) in document.nodes.enumerated() {
            switch node.kind {
            case "text":
                let length = node.source?.utf16.count ?? 0
                textRanges.append((index, NSRange(location: location, length: length)))
                location += length
            case "hardBreak", "mention", "embed":
                location += 1
            default:
                continue
            }
        }

        var nodes = document.nodes
        var mappings: [PIIMapping] = []
        for textRange in textRanges {
            let localMatches = matches.compactMap { match -> PIIMatch? in
                guard NSLocationInRange(match.range.location, textRange.range),
                      NSMaxRange(match.range) <= NSMaxRange(textRange.range) else {
                    return nil
                }
                return PIIMatch(
                    id: match.id,
                    type: match.type,
                    value: match.value,
                    range: NSRange(
                        location: match.range.location - textRange.range.location,
                        length: match.range.length
                    ),
                    placeholder: match.placeholder
                )
            }
            guard let source = nodes[textRange.nodeIndex].source, !localMatches.isEmpty else { continue }

            nodes[textRange.nodeIndex] = .text(
                id: nodes[textRange.nodeIndex].id,
                source: PIIDetector.redactedText(source, matches: localMatches, excludedIds: effectiveOptions.excludedIds)
            )
            mappings.append(contentsOf: PIIDetector.mappings(for: localMatches, excludedIds: effectiveOptions.excludedIds))
        }

        return ComposerDocumentPIIRedactionResult(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            mappings: mappings
        )
    }

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
