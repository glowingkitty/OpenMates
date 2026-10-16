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

struct ComposerDocumentPIIRewriteResult: Equatable, Sendable {
    let document: ComposerDocumentV1
    let appliedMappings: [PIIMapping]
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
        options: PIIDetectionOptions = PIIDetectionOptions(),
        detectedMatches: [PIIMatch]? = nil
    ) -> ComposerDocumentPIIRedactionResult {
        let effectiveOptions = PIIDetectionOptions(
            excludedIds: options.excludedIds.union(excludedIds),
            disabledCategories: options.disabledCategories,
            personalDataEntries: options.personalDataEntries
        )
        let visible = visibleText(document: document)
        let source = visible as NSString
        let matches = (detectedMatches ?? PIIDetector.detect(in: visible, options: effectiveOptions)).filter {
            $0.range.location >= 0 && $0.range.length > 0 && NSMaxRange($0.range) <= source.length
                && !effectiveOptions.excludedIds.contains($0.id)
                && source.substring(with: $0.range) == $0.value && !$0.value.contains("\u{FFFC}")
        }
        var textRanges: [(nodeIndex: Int, range: NSRange)] = []
        var location = 0
        for (index, node) in document.nodes.enumerated() {
            switch node.kind {
            case "text":
                let length = node.source?.utf16.count ?? 0
                textRanges.append((index, NSRange(location: location, length: length)))
                location += length
            case "hardBreak":
                textRanges.append((index, NSRange(location: location, length: 1)))
                location += 1
            case "mention", "embed": location += 1
            default: continue
            }
        }
        // A detected value can span adjacent text nodes or a line break. Replace
        // it once at its first fragment and remove its remaining fragments,
        // preserving node IDs/order and leaving opaque atoms untouched.
        let applicable = matches.filter { match in
            textRanges.reduce(0) { $0 + NSIntersectionRange($1.range, match.range).length } == match.range.length
        }
        var nodes = document.nodes
        for textRange in textRanges {
            let fragments = applicable.compactMap { match -> (NSRange, String)? in
                let overlap = NSIntersectionRange(match.range, textRange.range)
                guard overlap.length > 0 else { return nil }
                return (NSRange(location: overlap.location - textRange.range.location, length: overlap.length),
                        overlap.location == match.range.location ? match.placeholder : "")
            }.sorted { $0.0.location > $1.0.location }
            guard !fragments.isEmpty else { continue }
            let original = nodes[textRange.nodeIndex].kind == "hardBreak" ? "\n" : (nodes[textRange.nodeIndex].source ?? "")
            let replacement = NSMutableString(string: original)
            for (range, text) in fragments { replacement.replaceCharacters(in: range, with: text) }
            nodes[textRange.nodeIndex] = .text(id: nodes[textRange.nodeIndex].id, source: replacement as String)
        }
        let mappings = PIIDetector.mappings(for: applicable, excludedIds: effectiveOptions.excludedIds)

        return ComposerDocumentPIIRedactionResult(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            mappings: mappings
        )
    }

    static func rewriteKnownPIIPlaceholders(
        document: ComposerDocumentV1,
        mappings: [PIIMapping],
        excludedOriginals: Set<String> = [],
        excludedPlaceholders: Set<String> = []
    ) -> ComposerDocumentPIIRewriteResult {
        guard !mappings.isEmpty else {
            return ComposerDocumentPIIRewriteResult(document: document, appliedMappings: [])
        }

        var nodes = document.nodes
        var appliedMappings: [PIIMapping] = []
        for (index, node) in nodes.enumerated() {
            guard node.kind == "text", let source = node.source else { continue }
            let rewrite = PIIDetector.rewriteKnownPIIPlaceholders(
                in: source,
                mappings: mappings,
                excludedOriginals: excludedOriginals,
                excludedPlaceholders: excludedPlaceholders
            )
            guard rewrite.text != source else { continue }
            nodes[index] = .text(id: node.id, source: rewrite.text)
            appliedMappings.append(contentsOf: rewrite.appliedMappings)
        }

        return ComposerDocumentPIIRewriteResult(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            appliedMappings: PIIDetector.mergePIIMappings(appliedMappings)
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
