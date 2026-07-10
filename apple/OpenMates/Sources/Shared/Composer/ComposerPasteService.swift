// Native clipboard classification matching the web composer priority order.
// Typed embed payloads win over presentation formats and plain-text fallbacks.
// Conversion decisions retain original source for visible recovery on failure.
// Classification is deterministic and performs no network or persistence work.
// Platform paste adapters apply the returned decision at the live selection.

import Foundation

struct ComposerPastePayload: Sendable {
    let plainText: String?
    let html: String?
    let customEmbed: ComposerNodeV1?
    let sourceCodeLanguage: String?

    init(
        plainText: String? = nil,
        html: String? = nil,
        customEmbed: ComposerNodeV1? = nil,
        sourceCodeLanguage: String? = nil
    ) {
        self.plainText = plainText
        self.html = html
        self.customEmbed = customEmbed
        self.sourceCodeLanguage = sourceCodeLanguage
    }
}

enum ComposerPasteConversion: Equatable, Sendable {
    case code
    case document
    case sheet
    case url
}

enum ComposerPasteDecision: Equatable, Sendable {
    case insertText(String)
    case insertEmbed(ComposerNodeV1)
    case convert(ComposerPasteConversion, source: String)
}

struct ComposerPasteService {
    private enum Thresholds {
        static let documentCharacters = 1_800
        static let documentWords = 180
        static let documentLines = 10
    }

    func classify(_ payload: ComposerPastePayload) -> ComposerPasteDecision {
        if let customEmbed = payload.customEmbed {
            return .insertEmbed(customEmbed)
        }
        let source = payload.plainText ?? ""
        if payload.sourceCodeLanguage?.isEmpty == false || isFencedCode(source) {
            return .convert(.code, source: source)
        }
        if isTable(source) || payload.html?.localizedCaseInsensitiveContains("<table") == true {
            return .convert(.sheet, source: source)
        }
        if isDocument(source) || containsDocumentHTML(payload.html) {
            return .convert(.document, source: source)
        }
        if isStandaloneURL(source) {
            return .convert(.url, source: source)
        }
        return .insertText(source)
    }

    private func isFencedCode(_ source: String) -> Bool {
        source.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("```")
    }

    private func isTable(_ source: String) -> Bool {
        let lines = source.split(separator: "\n", omittingEmptySubsequences: false)
        return lines.count > 1 && lines.allSatisfy { $0.contains("\t") }
    }

    private func isDocument(_ source: String) -> Bool {
        let trimmed = source.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.range(of: #"(?m)^#{1,6}\s+\S"#, options: .regularExpression) != nil {
            return true
        }
        let words = trimmed.split(whereSeparator: \.isWhitespace).count
        let lines = trimmed.split(separator: "\n").filter { !$0.isEmpty }.count
        return trimmed.count >= Thresholds.documentCharacters
            || words >= Thresholds.documentWords
            || lines >= Thresholds.documentLines
    }

    private func containsDocumentHTML(_ html: String?) -> Bool {
        guard let html = html?.lowercased() else { return false }
        return ["<article", "<section", "<h1", "<h2", "<ul", "<ol"]
            .contains { html.contains($0) }
    }

    private func isStandaloneURL(_ source: String) -> Bool {
        let trimmed = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.contains(where: \.isWhitespace),
              let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased() else {
            return false
        }
        return (scheme == "https" || scheme == "http") && url.host != nil
    }
}
