// Rich markdown renderer — full block-level rendering for AI chat messages.
// Handles fenced code blocks with syntax highlighting, blockquotes, headers,
// tables, horizontal rules, and lists. Falls back to Apple's built-in
// AttributedString for inline formatting (bold, italic, links, inline code).
// Replaces the previous inline-only MarkdownText view for assistant messages.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/DemoMessageContent.svelte
//          frontend/packages/ui/src/components/ReadOnlyMessage.svelte
//          frontend/packages/ui/src/components/embeds/SourceQuoteBlock.svelte
//          frontend/packages/ui/src/components/embeds/ExampleChatsGroup.svelte
//          frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte
//          frontend/packages/ui/src/components/embeds/EmbedLeafletMap.svelte
//          frontend/packages/ui/src/components/sub_chats/SubChatBatchPreview.svelte
//          frontend/packages/ui/src/components/interactive_questions/InteractiveQuestionContainer.svelte
// TypeScript: frontend/packages/ui/src/components/enter_message/utils/markdownParser.ts
//             frontend/packages/ui/src/components/enter_message/extensions/MarkdownExtensions.ts
//             frontend/packages/ui/src/message_parsing/parse_message.ts
// CSS:     ChatEmbedPreview.svelte <style>
//          SourceQuoteBlock.svelte .source-quote-block, .source-quote-text,
//            .source-quote-badge
//          frontend/packages/ui/src/styles/markdown.css
//          .chat-embed-card { width:300px; height:200px; border-radius:30px;
//            box-shadow:0 8px 24px rgba(0,0,0,.16),0 2px 6px rgba(0,0,0,.1) }
//          .card-icon { width:32px; height:32px }
//          .card-title { font-size:var(--font-size-p); font-weight:700 }
//          .card-summary { font-size:var(--font-size-xxs); font-weight:500 }
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
//                specifications/features/app-skills/web-search/specification.yml
// Assertions: chats.rendering.assistant-document-convergence,
//             chats.rendering.inline-entity-interaction, chats.surface.semantic-parity,
//             web-search.surface-parity

import Foundation
import SwiftUI
#if canImport(MapKit)
import MapKit
#endif
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// Resolves inline `embed:` links against both hydrated records and the
/// encrypted search parent's inline result fallback. Search child embeds can
/// arrive after the assistant text, so a citation must stay actionable while
/// the child graph is still hydrating.
enum MarkdownEmbedResolver {
    static func resolve(_ reference: String, in records: [String: EmbedRecord]) -> EmbedRecord? {
        if let exact = records[reference] { return exact }
        if let aliased = records.values.first(where: { record in
            let rawReference = record.rawData?["embed_ref"]?.value as? String
            return rawReference == reference || record.id == reference || record.id.hasSuffix(reference)
        }) {
            return aliased
        }

        for parent in records.values where parent.childEmbedIds.contains(reference) {
            let raw = parent.rawData ?? [:]
            let appId = parent.appId ?? EmbedFieldReader.string(raw, keys: ["app_id"])
            let skillId = parent.skillId ?? EmbedFieldReader.string(raw, keys: ["skill_id"])
            guard let appId, skillId == "search", ["web", "news", "images", "photos"].contains(appId) else {
                continue
            }
            let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: records)
            if let fallback = model.childEmbeds.first(where: { $0.id == reference }) {
                return fallback
            }
        }
        return nil
    }
}

private extension Color {
    /// Mirrors `--color-bold-text` from `frontend/packages/ui/src/tokens/sources/colors.yml`.
    static func markdownBoldText(for colorScheme: ColorScheme) -> Color {
        colorScheme == .dark ? Color(hex: 0xC9BBFF) : Color(hex: 0x503BA0)
    }

    /// Mirrors WikiInlineLink.svelte: light uses `--color-app-web-start`,
    /// dark uses `--color-app-web-end`.
    static func wikiInlineText(for colorScheme: ColorScheme) -> Color {
        colorScheme == .dark ? Color(hex: 0xFF763B) : Color(hex: 0xDE1E66)
    }
}

private extension LinearGradient {
    /// Mirrors ReadOnlyMessage.svelte's markdown link text gradient.
    static func markdownLinkText(for colorScheme: ColorScheme) -> LinearGradient {
        if colorScheme == .dark {
            return .omGradient(start: Color(hex: 0x6387FF), end: Color(hex: 0x7EA4FF))
        }
        return .primary
    }
}

enum SearchTextHighlighter {
    static func highlighted(_ text: String, query: String?) -> AttributedString {
        var attributed = AttributedString(text)
        highlightMatches(in: &attributed, query: query)
        return attributed
    }

    static func highlighted(_ text: String, ranges: [NSRange]) -> AttributedString {
        var attributed = AttributedString(text)
        highlightRanges(in: &attributed, sourceText: text, ranges: ranges)
        return attributed
    }

    static func attributed(_ text: String, query: String?, foregroundColor: Color) -> AttributedString {
        var attributed = AttributedString(text)
        attributed.foregroundColor = foregroundColor
        highlightMatches(in: &attributed, query: query)
        return attributed
    }

    static func attributed(_ text: String, ranges: [NSRange], foregroundColor: Color) -> AttributedString {
        var attributed = AttributedString(text)
        attributed.foregroundColor = foregroundColor
        highlightRanges(in: &attributed, sourceText: text, ranges: ranges)
        return attributed
    }

    static func highlightMatches(in attributed: inout AttributedString, query: String?) {
        guard let query else { return }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        var searchStart = attributed.startIndex
        while let range = attributed[searchStart...].range(of: trimmed, options: [.caseInsensitive, .diacriticInsensitive]) {
            attributed[range].backgroundColor = Color.highlightYellowSolid.opacity(0.4)
            searchStart = range.upperBound
        }
    }

    static func highlightRanges(in attributed: inout AttributedString, sourceText: String, ranges: [NSRange]) {
        guard !ranges.isEmpty else { return }
        for range in ranges {
            guard let sourceRange = Range(range, in: sourceText),
                  let start = AttributedString.Index(sourceRange.lowerBound, within: attributed),
                  let end = AttributedString.Index(sourceRange.upperBound, within: attributed) else {
                continue
            }
            attributed[start..<end].backgroundColor = Color.highlightYellowSolid.opacity(0.4)
        }
    }
}

/// Source excerpts are temporary fullscreen presentation state. They never enter
/// persisted EmbedRecord data, sync payloads, or diagnostics.
struct SourceQuoteTarget: Equatable {
    let embedID: String
    let text: String
}

private struct SourceQuoteOpenActionKey: EnvironmentKey {
    static var defaultValue: (@MainActor @Sendable (EmbedRecord, String) -> Void)? { nil }
}
private struct EmbedSourceQuoteTextKey: EnvironmentKey {
    static let defaultValue: String? = nil
}
extension EnvironmentValues {
    var sourceQuoteOpenAction: (@MainActor @Sendable (EmbedRecord, String) -> Void)? {
        get { self[SourceQuoteOpenActionKey.self] }
        set { self[SourceQuoteOpenActionKey.self] = newValue }
    }
    var embedSourceQuoteText: String? {
        get { self[EmbedSourceQuoteTextKey.self] }
        set { self[EmbedSourceQuoteTextKey.self] = newValue }
    }
}

struct SourceQuoteHighlightAnchor: Equatable {
    let id: String
    let frame: CGRect
}

struct SourceQuoteHighlightAnchorKey: PreferenceKey {
    static let defaultValue: [SourceQuoteHighlightAnchor] = []
    static func reduce(value: inout [SourceQuoteHighlightAnchor], nextValue: () -> [SourceQuoteHighlightAnchor]) {
        value.append(contentsOf: nextValue())
    }
}

/// One direct scroll-content ID avoids ScrollViewReader's nested ForEach frame
/// resolution. Aligning the same fractional point in content and viewport gives
/// offset = fraction * (contentHeight - viewportHeight).
enum SourceQuoteScrollPosition {
    static func unitAnchorY(sourceMidY: CGFloat, contentHeight: CGFloat, viewportHeight: CGFloat) -> CGFloat {
        let scrollableHeight = contentHeight - viewportHeight
        guard scrollableHeight > 0 else { return 0 }
        let centeredOffset = sourceMidY - viewportHeight / 2
        return min(1, max(0, centeredOffset / scrollableHeight))
    }
}

/// Mirrors UnifiedEmbedFullscreen's offset-preserving typographic normalization
/// and WebsiteEmbedFullscreen's verified six-word prefix/suffix fallback.
enum SourceQuoteMatcher {
    static func range(in text: String, quote: String?) -> NSRange? {
        guard let quote, !quote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let source = normalize(text)
        let target = normalize(quote).text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else { return nil }
        func resolve(_ query: String) -> NSRange? {
            let found = (source.text as NSString).range(of: query)
            guard found.location != NSNotFound, found.length > 0 else { return nil }
            let start = source.starts[found.location]
            let end = source.ends[NSMaxRange(found) - 1]
            return NSRange(location: start, length: end - start)
        }
        if let match = resolve(target) { return match }
        let words = target.split(separator: " ").map(String.init)
        if words.count > 6 {
            for count in stride(from: words.count - 1, through: 6, by: -1) {
                if let prefix = resolve(words.prefix(count).joined(separator: " ")) { return prefix }
                if let suffix = resolve(words.suffix(count).joined(separator: " ")) { return suffix }
            }
        }
        return nil
    }

    private static func normalize(_ text: String) -> (text: String, starts: [Int], ends: [Int]) {
        var units: [(value: UInt16, start: Int, end: Int)] = []
        var offset = 0
        for scalar in text.unicodeScalars {
            let original = String(scalar)
            let length = original.utf16.count
            let replacement: String
            switch scalar {
            case "…": replacement = "..."
            case "‘", "’", "‚", "‛": replacement = "'"
            case "“", "”", "„", "‟": replacement = "\""
            case "–", "—", "―": replacement = "-"
            default: replacement = CharacterSet.whitespacesAndNewlines.contains(scalar) ? " " : original.lowercased()
            }
            units.append(contentsOf: replacement.utf16.map { ($0, offset, offset + length) })
            offset += length
        }
        var normalized: [UInt16] = []
        var starts: [Int] = []
        var ends: [Int] = []
        var index = 0
        while index < units.count {
            let unit = units[index]
            if unit.value == 32, normalized.last == 32 { index += 1; continue }
            var end = unit.end
            if unit.value == 45, index + 1 < units.count, units[index + 1].value == 45 {
                index += 1
                end = units[index].end
            }
            normalized.append(unit.value)
            starts.append(unit.start)
            ends.append(end)
            index += 1
        }
        return (String(decoding: normalized, as: UTF16.self), starts, ends)
    }

    static func attributed(_ text: String, range: NSRange?) -> AttributedString {
        var result = AttributedString(text)
        guard let range, let source = Range(range, in: text),
              let start = AttributedString.Index(source.lowerBound, within: result),
              let end = AttributedString.Index(source.upperBound, within: result) else { return result }
        result[start..<end].backgroundColor = Color.highlightYellowSolid.opacity(0.4)
        result[start..<end].foregroundColor = Color.fontPrimary
        return result
    }
}

/// The identity belongs to the paragraph/snippet containing the highlighted
/// region, so ScrollViewReader centers content rather than the entire article.
struct SourceQuoteHighlightedText: View {
    let text: String
    let locationID: String
    var matchedRange: NSRange? = nil
    var matchLocally = true
    var pointSize: CGFloat = 16
    var textColor: Color = .fontPrimary
    var lineHeight: CGFloat = 24
    var italic = false
    @Environment(\.embedSourceQuoteText) private var quote

    var body: some View {
        let match = matchedRange ?? (matchLocally ? SourceQuoteMatcher.range(in: text, quote: quote) : nil)
        ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(
            SourceQuoteMatcher.attributed(text, range: match), pointSize: pointSize,
            color: textColor, lineHeight: lineHeight, italic: italic), identifier: locationID,
            textAccessibilityIdentifier: match == nil ? locationID : "embed-source-text-highlight")
            .id(locationID)
            .background {
                if match != nil {
                    GeometryReader { geometry in
                        Color.clear.preference(key: SourceQuoteHighlightAnchorKey.self, value: [
                            SourceQuoteHighlightAnchor(id: locationID,
                                frame: geometry.frame(in: .named("embed-fullscreen-source-content")))
                        ])
                    }
                }
            }
    }
}

/// Plain text readers retain their paragraph boundaries and match against the
/// entire document, including quotes crossing line breaks. Only the intersecting
/// source ranges get color; each paragraph supplies its own scroll anchor.
struct SourceQuoteTextDocument: View {
    let text: String
    let locationPrefix: String
    var textColor: Color = .fontPrimary
    var lineHeight: CGFloat = 24
    @Environment(\.embedSourceQuoteText) private var quote

    var body: some View {
        if let match = SourceQuoteMatcher.range(in: text, quote: quote) {
            let paragraphs = text.components(separatedBy: "\n\n")
            VStack(alignment: .leading, spacing: .spacing4) {
                ForEach(Array(paragraphs.enumerated()), id: \.offset) { index, paragraph in
                    let offset = paragraphs.prefix(index).reduce(0) { $0 + $1.utf16.count + 2 }
                    let overlap = NSIntersectionRange(match, NSRange(location: offset, length: paragraph.utf16.count))
                    let localRange = overlap.length > 0 ? NSRange(location: overlap.location - offset, length: overlap.length) : nil
                    SourceQuoteHighlightedText(text: paragraph, locationID: "\(locationPrefix)-\(index)",
                                               matchedRange: localRange, matchLocally: false, textColor: textColor, lineHeight: lineHeight)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        } else {
            ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(text),
                color: textColor, lineHeight: lineHeight), identifier: locationPrefix)
        }
    }
}

// MARK: - Block parser

/// Parses raw markdown text into a sequence of typed blocks for rendering.
/// Handles fenced code blocks (```lang), blockquotes (>), headers (#),
/// horizontal rules (---), and unordered/ordered lists. Everything else
/// is treated as a paragraph with inline markdown formatting.
enum MarkdownBlock: Equatable {
    case paragraph(String)
    case codeBlock(language: String?, code: String)
    case blockquote(String)
    case header(level: Int, text: String)
    case horizontalRule
    case unorderedList([String])
    case orderedList([String])
    case table(headers: [String], rows: [[String]])
    case demoGroup(DemoGroupKind)
    case embedGroup([MarkdownEmbedReference])
    case resultsView(AppleResultsViewDescriptor)
    case subChatBatch(SubChatBatchDescriptor)
    case interactiveQuestion(AppleInteractiveQuestionPayload)
    case interactiveQuestionFallback
    case hiddenProtocol

}

/// The virtual results view is a message node, not a persisted embed group.
/// Keep its source and highlight lists separate so hydration can resolve source
/// children and the UI can retain the same identity across streaming updates.
struct AppleResultsViewDescriptor: Codable, Equatable, Sendable {
    let title: String
    let embedRefs: [String]
    let sourceRefs: [String]
    let highlightRefs: [String]

    var hasReferences: Bool { !embedRefs.isEmpty || !sourceRefs.isEmpty }

    static func parse(_ code: String) -> AppleResultsViewDescriptor {
        var fields: [String: String] = [:]
        for rawLine in code.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#"), let separator = line.firstIndex(of: ":") else { continue }
            let key = line[..<separator].trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard ["title", "embeds", "sources", "highlight"].contains(key) else { continue }
            let value = line[line.index(after: separator)...].trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty { fields[key] = value }
        }
        func refs(_ key: String) -> [String] {
            var seen = Set<String>()
            return (fields[key] ?? "").split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty && seen.insert($0).inserted }
        }
        return AppleResultsViewDescriptor(
            title: fields["title"] ?? "Results view",
            embedRefs: refs("embeds"), sourceRefs: refs("sources"), highlightRefs: refs("highlight")
        )
    }
}

struct AppleInteractiveQuestionPayload: Decodable, Equatable {
    struct Option: Decodable, Equatable, Identifiable {
        let id: String
        let text: String
        let embedIds: [String]?

        private enum CodingKeys: String, CodingKey {
            case id
            case text
            case embedIds = "embed_ids"
        }
    }

    struct Field: Decodable, Equatable, Identifiable {
        let id: String
        let label: String
        let placeholder: String?
        let required: Bool?
    }

    let id: String
    let type: String
    let multiple: Bool?
    let customOptionId: String?
    let customPlaceholder: String?
    let question: String?
    let options: [Option]?
    let fields: [Field]?
    let cards: [Option]?
    let min: Double?
    let max: Double?
    let step: Double?
    let defaultValue: Double?
    let labels: [String: String]?
    let maxStars: Int?
    let requireComment: Bool?
    let commentPlaceholder: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case type
        case multiple
        case customOptionId = "custom_option_id"
        case customPlaceholder = "custom_placeholder"
        case question
        case options
        case fields
        case cards
        case min
        case max
        case step
        case defaultValue = "default"
        case labels
        case maxStars = "max_stars"
        case requireComment = "require_comment"
        case commentPlaceholder = "comment_placeholder"
    }

    var sliderLowerBound: Double { min ?? 0 }
    var sliderUpperBound: Double { max ?? 10 }
    var sliderStep: Double { step ?? 1 }
    var ratingMaximum: Int { Swift.max(1, maxStars ?? 5) }

    @MainActor
    func responseContent(response: [String: Any]) -> String {
        let displayText = displayText(for: response)
        let json = Self.prettyPrintedJSON(responseWithReferencedEmbedIds(response))
        return "\(displayText)\n\n```interactive_response\n\(json)\n```"
    }

    @MainActor
    func displayText(for response: [String: Any]) -> String {
        switch type {
        case "choice":
            let selection = response["selection"] as? [String] ?? []
            let customAnswer = (response["custom_answer"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let texts = (options ?? [])
                .filter { selection.contains($0.id) }
                .map { option in
                    if let customAnswer, !customAnswer.isEmpty, isCustomChoiceOption(option) {
                        return customAnswer
                    }
                    return option.text
                }
            return multiple == true ? texts.joined(separator: "\n") : texts.first ?? ""

        case "input":
            let inputs = response["inputs"] as? [String: String] ?? [:]
            return (fields ?? [])
                .compactMap { inputs[$0.id]?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: "\n")

        case "slider":
            let value: Double
            if let doubleValue = response["value"] as? Double {
                value = doubleValue
            } else if let intValue = response["value"] as? Int {
                value = Double(intValue)
            } else {
                value = 0
            }
            let label = labels?[Self.labelKey(for: value)]
            let renderedValue = Self.renderedNumber(value)
            return label.map { "\(renderedValue) (\($0))" } ?? renderedValue

        case "swipe":
            let swipes = response["swipes"] as? [String: String] ?? [:]
            return (cards ?? [])
                .map { card in
                    let label = swipes[card.id] == "like" ? AppStrings.yes : AppStrings.no
                    return "\(card.text): \(label)"
                }
                .joined(separator: "\n")

        case "rating":
            var lines = ["\(response["rating"] as? Int ?? 0)/\(ratingMaximum)"]
            if let comment = response["comment"] as? String,
               !comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                lines.append(comment.trimmingCharacters(in: .whitespacesAndNewlines))
            }
            return lines.joined(separator: "\n")

        default:
            return ""
        }
    }

    private static func prettyPrintedJSON(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]),
              let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }

    private static func labelKey(for value: Double) -> String {
        let rounded = value.rounded()
        if abs(value - rounded) < 0.0001 {
            return String(Int(rounded))
        }
        return renderedNumber(value)
    }

    private static func renderedNumber(_ value: Double) -> String {
        let rounded = value.rounded()
        if abs(value - rounded) < 0.0001 {
            return String(Int(rounded))
        }
        return String(value)
    }

    func isCustomChoiceOption(_ option: Option) -> Bool {
        if let customOptionId { return option.id == customOptionId }
        let normalizedText = option.text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return [
            "i give you my own answer",
            "my own answer",
            "own answer",
            "custom answer",
            "something else",
            "other"
        ].contains(where: { pattern in
            normalizedText == pattern || normalizedText.contains(pattern)
        })
    }

    private func responseWithReferencedEmbedIds(_ response: [String: Any]) -> [String: Any] {
        let embedIds: [String]
        switch type {
        case "choice":
            let selection = response["selection"] as? [String] ?? []
            embedIds = Self.uniqueEmbedIds(
                (options ?? [])
                    .filter { selection.contains($0.id) }
                    .flatMap { $0.embedIds ?? [] }
            )
        case "swipe":
            let swipes = response["swipes"] as? [String: String] ?? [:]
            embedIds = Self.uniqueEmbedIds(
                (cards ?? [])
                    .filter { swipes[$0.id] != nil }
                    .flatMap { $0.embedIds ?? [] }
            )
        default:
            embedIds = []
        }

        guard !embedIds.isEmpty else { return response }
        var enriched = response
        enriched["embed_ids"] = embedIds
        return enriched
    }

    private static func uniqueEmbedIds(_ embedIds: [String]) -> [String] {
        var seen = Set<String>()
        return embedIds.compactMap { rawId in
            let embedId = rawId.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !embedId.isEmpty, !seen.contains(embedId) else { return nil }
            seen.insert(embedId)
            return embedId
        }
    }
}

struct MarkdownEmbedReference: Equatable {
    let value: String
    let isRef: Bool
    let isLargePreview: Bool
    var type: String? = nil
}

enum AppleStandaloneEmbedPreviewPresentation {
    // Web parse_message.ts promotes standalone assistant embeds and non-code
    // groups. App skill cards, inline images, focus activation, user cards and
    // code groups retain their regular layout. Explicit [!] references keep
    // their existing large-preview intent, including search result citations.
    static func usesLargePreview(explicit: Bool, isUserMessage: Bool, embedTypes: [String]) -> Bool {
        if explicit { return true }
        guard !isUserMessage, !embedTypes.isEmpty else { return false }
        return embedTypes.allSatisfy { rawType in
            let baseType = rawType.hasSuffix("-group") ? String(rawType.dropLast(6)) : rawType
            guard !baseType.hasPrefix("app:"),
                  !["app_skill_use", "app-skill-use", "focus-mode-activation"].contains(baseType),
                  let type = EmbedType.normalized(rawValue: baseType), type != .image else { return false }
            return type != .codeCode || (embedTypes.count == 1 && !rawType.hasSuffix("-group"))
        }
    }

    static func variant(containerWidth: CGFloat) -> EmbedPreviewCardVariant {
        containerWidth > 400 ? .large : .compact
    }
}

struct MarkdownParsedBlock {
    let block: MarkdownBlock
    let sourceStartUTF8: Int
    let sourceEndUTF8: Int
}

enum MarkdownParser {
    private static let demoPlaceholders: [String: DemoGroupKind] = [
        "[[example_chats_group]]": .exampleChats,
        "[[dev_example_chats_group]]": .developerExampleChats,
        "[[app_store_group]]": .apps,
        "[[dev_app_store_group]]": .developerApps,
        "[[skills_group]]": .skills,
        "[[dev_skills_group]]": .developerSkills,
        "[[focus_modes_group]]": .focusModes,
        "[[dev_focus_modes_group]]": .developerFocusModes,
        "[[settings_memories_group]]": .memories,
        "[[dev_settings_memories_group]]": .developerMemories,
        "[[ai_models_group]]": .aiModels
    ]

    static func parse(_ text: String) -> [MarkdownBlock] {
        parseSpans(text).map(\.block)
    }

    /// The existing grammar emits source spans for streaming-tail reuse. It is
    /// still the sole parser for stable history and active streaming messages.
    static func parseSpans(_ text: String, isStreaming: Bool = false) -> [MarkdownParsedBlock] {
        var blocks: [MarkdownBlock] = []
        var spans: [MarkdownParsedBlock] = []
        let lines = text.components(separatedBy: "\n")
        var offsets: [Int] = []
        var offset = 0
        for line in lines { offsets.append(offset); offset += line.utf8.count + 1 }
        let sourceLength = text.utf8.count
        var i = 0

        while i < lines.count {
            let startLine = i
            let previousCount = blocks.count
            defer {
                let end = i < offsets.count ? offsets[i] : sourceLength
                for block in blocks.dropFirst(previousCount) {
                    spans.append(.init(block: block, sourceStartUTF8: offsets[startLine], sourceEndUTF8: end))
                }
            }
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if let group = demoPlaceholders[trimmed] {
                blocks.append(.demoGroup(group))
                i += 1
                continue
            }

            if let embed = parseEmbedPlaceholder(trimmed) {
                var embeds = [embed]
                i += 1
                while i < lines.count {
                    let nextTrimmed = lines[i].trimmingCharacters(in: .whitespaces)
                    if nextTrimmed.isEmpty {
                        i += 1
                        continue
                    }
                    guard let nextEmbed = parseEmbedPlaceholder(nextTrimmed),
                          nextEmbed.isLargePreview == embed.isLargePreview else { break }
                    embeds.append(nextEmbed)
                    i += 1
                }
                blocks.append(.embedGroup(embeds))
                continue
            }

            // Fenced code block
            if trimmed.hasPrefix("```") {
                let lang = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                let language = lang.isEmpty ? nil : lang
                var codeLines: [String] = []
                var isClosed = false
                i += 1
                while i < lines.count {
                    if lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                        isClosed = true
                        i += 1
                        break
                    }
                    codeLines.append(lines[i])
                    i += 1
                }
                let code = codeLines.joined(separator: "\n")
                if isStreaming && ChatMessageStreamingRenderPolicy.isInternalProtocolFence(
                    language: language ?? "", body: code, isClosed: isClosed
                ) {
                    blocks.append(.hiddenProtocol)
                } else if language == "interactive_response" {
                    blocks.append(.hiddenProtocol)
                } else if language == "interactive_question" {
                    if let payload = parseInteractiveQuestionPayload(code) {
                        blocks.append(.interactiveQuestion(payload))
                    } else {
                        blocks.append(.interactiveQuestionFallback)
                    }
                } else if isResultsViewLanguage(language) {
                    let descriptor = AppleResultsViewDescriptor.parse(code)
                    blocks.append(descriptor.hasReferences ? .resultsView(descriptor) : .hiddenProtocol)
                } else if SubChatBatchDescriptor.isProtocolMarker(code, language: language) {
                    if let descriptor = SubChatBatchDescriptor.parse(code) {
                        blocks.append(.subChatBatch(descriptor))
                    } else {
                        blocks.append(.hiddenProtocol)
                    }
                } else if let embed = parseFencedEmbedReference(language: language, code: code) {
                    blocks.append(.embedGroup([embed]))
                } else {
                    blocks.append(.codeBlock(language: language, code: code))
                }
                continue
            }

            // Table (line with pipes and a separator row below)
            if trimmed.contains("|") && i + 1 < lines.count {
                let nextTrimmed = lines[i + 1].trimmingCharacters(in: .whitespaces)
                if nextTrimmed.contains("---") && nextTrimmed.contains("|") {
                    let headers = parseTableRow(trimmed)
                    var rows: [[String]] = []
                    i += 2 // skip header + separator
                    while i < lines.count {
                        let rowLine = lines[i].trimmingCharacters(in: .whitespaces)
                        guard rowLine.contains("|") else { break }
                        rows.append(parseTableRow(rowLine))
                        i += 1
                    }
                    blocks.append(.table(headers: headers, rows: rows))
                    continue
                }
            }

            // Horizontal rule
            if trimmed == "---" || trimmed == "***" || trimmed == "___" {
                blocks.append(.horizontalRule)
                i += 1
                continue
            }

            // Headers
            if let headerMatch = parseHeader(trimmed) {
                blocks.append(.header(level: headerMatch.0, text: headerMatch.1))
                i += 1
                continue
            }

            // Blockquote
            if trimmed.hasPrefix(">") {
                var quoteLines: [String] = []
                while i < lines.count {
                    let qLine = lines[i].trimmingCharacters(in: .whitespaces)
                    guard qLine.hasPrefix(">") else { break }
                    quoteLines.append(String(qLine.dropFirst().trimmingCharacters(in: .init(charactersIn: " "))))
                    i += 1
                }
                blocks.append(.blockquote(quoteLines.joined(separator: "\n")))
                continue
            }

            // Unordered list
            if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") || trimmed.hasPrefix("+ ") {
                var items: [String] = []
                while i < lines.count {
                    let lLine = lines[i].trimmingCharacters(in: .whitespaces)
                    if lLine.hasPrefix("- ") || lLine.hasPrefix("* ") || lLine.hasPrefix("+ ") {
                        items.append(String(lLine.dropFirst(2)))
                        i += 1
                    } else {
                        break
                    }
                }
                blocks.append(.unorderedList(items))
                continue
            }

            // Ordered list
            if let _ = trimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) {
                var items: [String] = []
                while i < lines.count {
                    let lLine = lines[i].trimmingCharacters(in: .whitespaces)
                    if let range = lLine.range(of: #"^\d+\.\s"#, options: .regularExpression) {
                        items.append(String(lLine[range.upperBound...]))
                        i += 1
                    } else {
                        break
                    }
                }
                blocks.append(.orderedList(items))
                continue
            }

            // Empty line — skip
            if trimmed.isEmpty {
                i += 1
                continue
            }

            // Paragraph — collect consecutive non-empty, non-special lines
            var paraLines: [String] = []
            while i < lines.count {
                let pLine = lines[i]
                let pTrimmed = pLine.trimmingCharacters(in: .whitespaces)
                if pTrimmed.isEmpty || pTrimmed.hasPrefix("```") || parseHeader(pTrimmed) != nil
                    || pTrimmed.hasPrefix(">") || pTrimmed == "---" || pTrimmed == "***"
                    || pTrimmed.hasPrefix("- ") || pTrimmed.hasPrefix("* ")
                    || pTrimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) != nil
                    || demoPlaceholders[pTrimmed] != nil
                    || parseEmbedPlaceholder(pTrimmed) != nil {
                    break
                }
                paraLines.append(pLine)
                i += 1
            }
            if !paraLines.isEmpty {
                blocks.append(.paragraph(paraLines.joined(separator: "\n")))
            }
        }

        return spans
    }

    private static func parseHeader(_ line: String) -> (Int, String)? {
        let levels = [("######", 6), ("#####", 5), ("####", 4), ("###", 3), ("##", 2), ("#", 1)]
        for (prefix, level) in levels {
            if line.hasPrefix("\(prefix) ") {
                return (level, String(line.dropFirst(prefix.count + 1)))
            }
        }
        return nil
    }

    private static func parseInteractiveQuestionPayload(_ code: String) -> AppleInteractiveQuestionPayload? {
        guard let data = code.data(using: .utf8),
              let payload = try? JSONDecoder().decode(AppleInteractiveQuestionPayload.self, from: data),
              !payload.id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              ["choice", "input", "slider", "swipe", "rating"].contains(payload.type) else {
            return nil
        }
        return payload
    }

    private static func parseEmbedPlaceholder(_ line: String) -> MarkdownEmbedReference? {
        guard line.hasSuffix("]]") else { return nil }
        if line.hasPrefix("[[embed:") {
            let start = line.index(line.startIndex, offsetBy: 8)
            let end = line.index(line.endIndex, offsetBy: -2)
            guard start < end else { return nil }
            return MarkdownEmbedReference(value: String(line[start..<end]), isRef: false, isLargePreview: false)
        }
        guard line.hasPrefix("[[embedref:") else { return nil }
        let start = line.index(line.startIndex, offsetBy: 11)
        let end = line.index(line.endIndex, offsetBy: -2)
        guard start < end else { return nil }
        return MarkdownEmbedReference(value: String(line[start..<end]), isRef: true, isLargePreview: true)
    }

    private static func isResultsViewLanguage(_ language: String?) -> Bool {
        guard let language else { return false }
        let normalized = language
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .split(whereSeparator: \.isWhitespace)
            .first?
            .lowercased()
        return normalized == "embeds_map_view" || normalized == "embeds_results_view"
    }

    private static func parseFencedEmbedReference(language: String?, code: String) -> MarkdownEmbedReference? {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let language, !language.isEmpty, language.lowercased() != "json" {
            return nil
        }
        guard let data = trimmed.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String,
              let embedId = object["embed_id"] as? String,
              !embedId.isEmpty else {
            return nil
        }
        let isLargePreview = object["large_preview"] as? Bool ?? object["is_large_preview"] as? Bool ?? false
        return MarkdownEmbedReference(value: embedId, isRef: false, isLargePreview: isLargePreview, type: type)
    }

    private static func parseTableRow(_ line: String) -> [String] {
        line.split(separator: "|")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }
}

// MARK: - Block views

struct RichMarkdownView: View {
    let content: String
    let renderDocument: ChatHistoryRenderDocument?
    let progressiveRequest: ProgressiveMarkdownRequest?
    let isUserMessage: Bool
    let onOpenPublicChat: ((String) -> Void)?
    let parentChatID: String?
    let messageCreatedAt: String?
    let viewportWidth: CGFloat?
    let subChatStore: ChatStore?
    let onOpenSubChat: ((String) -> Void)?
    let subChatProgress: SubChatProgress?
    let completedSubChatIDs: Set<String>
    let embedLookup: [String: EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let hiddenEmbedIds: Set<String>
    let onEmbedTap: ((EmbedRecord) -> Void)?
    let onInteractiveQuestionSubmit: ((String) -> Void)?
    let searchHighlightQuery: String?
    private let blocks: [MarkdownBlock]

    init(
        content: String,
        renderDocument: ChatHistoryRenderDocument? = nil,
        progressiveRequest: ProgressiveMarkdownRequest? = nil,
        isUserMessage: Bool,
        onOpenPublicChat: ((String) -> Void)? = nil,
        parentChatID: String? = nil,
        messageCreatedAt: String? = nil,
        viewportWidth: CGFloat? = nil,
        subChatStore: ChatStore? = nil,
        onOpenSubChat: ((String) -> Void)? = nil,
        subChatProgress: SubChatProgress? = nil,
        completedSubChatIDs: Set<String> = [],
        embedLookup: [String: EmbedRecord] = [:],
        allEmbedRecords: [String: EmbedRecord] = [:],
        hiddenEmbedIds: Set<String> = [],
        onEmbedTap: ((EmbedRecord) -> Void)? = nil,
        onInteractiveQuestionSubmit: ((String) -> Void)? = nil,
        searchHighlightQuery: String? = nil
    ) {
        self.content = content
        self.renderDocument = renderDocument
        self.progressiveRequest = progressiveRequest
        self.isUserMessage = isUserMessage
        self.onOpenPublicChat = onOpenPublicChat
        self.parentChatID = parentChatID
        self.messageCreatedAt = messageCreatedAt
        self.viewportWidth = viewportWidth
        self.subChatStore = subChatStore
        self.onOpenSubChat = onOpenSubChat
        self.subChatProgress = subChatProgress
        self.completedSubChatIDs = completedSubChatIDs
        self.embedLookup = embedLookup
        self.allEmbedRecords = allEmbedRecords
        self.hiddenEmbedIds = hiddenEmbedIds
        self.onEmbedTap = onEmbedTap
        self.onInteractiveQuestionSubmit = onInteractiveQuestionSubmit
        self.searchHighlightQuery = searchHighlightQuery
        self.blocks = renderDocument == nil && progressiveRequest == nil ? MarkdownParser.parse(content) : []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let progressiveRequest {
                ProgressiveMarkdownBlocksView(request: progressiveRequest) { block in
                    if let markdown = block.markdown,
                       block.document.kind == .interactiveQuestion || block.document.kind == .demoGroup {
                        blockView(for: markdown)
                    } else {
                        documentBlockView(for: block.document)
                    }
                }
                .id(progressiveRequest.identity)
            } else if let renderDocument {
                ForEach(renderDocument.blocks) { block in
                    documentBlockView(for: block)
                }
            } else {
                ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                    blockView(for: block)
                }
            }
        }
    }

    @ViewBuilder
    private func documentBlockView(for block: ChatHistoryRenderBlock) -> some View {
        switch block.kind {
        case .paragraph:
            inlineText(block.text ?? "")
        case .heading:
            HeaderView(level: block.headingLevel ?? 1, text: block.text ?? "", isUserMessage: isUserMessage, searchHighlightQuery: searchHighlightQuery)
        case .codeBlock:
            CodeBlockView(language: block.language, code: block.text ?? "", searchHighlightQuery: searchHighlightQuery)
        case .blockquote:
            BlockquoteView(
                text: block.text ?? "",
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )
            .accessibilityIdentifier("generic-blockquote")
        case .sourceQuote:
            if let reference = block.embedReferences.first, let embed = resolveEmbed(reference) {
                SourceQuoteView(
                    quote: block.text ?? "",
                    embed: embed,
                    onEmbedTap: onEmbedTap,
                    searchHighlightQuery: searchHighlightQuery
                )
            } else {
                BlockquoteView(
                    text: block.text ?? "",
                    isUserMessage: isUserMessage,
                    allEmbedRecords: allEmbedRecords,
                    onEmbedTap: onEmbedTap,
                    searchHighlightQuery: searchHighlightQuery
                )
                .accessibilityIdentifier("source-quote-unavailable")
            }
        case .horizontalRule:
            Divider().padding(.vertical, .spacing2)
        case .unorderedList, .orderedList:
            ListBlockView(
                items: block.items,
                ordered: block.kind == .orderedList,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )
        case .table:
            TableBlockView(headers: block.tableHeaders, rows: block.tableRows, isUserMessage: isUserMessage, searchHighlightQuery: searchHighlightQuery)
        case .embedGroup:
            resolvedEmbedGroup(block.embedReferences.compactMap(resolveEmbed), isLargePreview: block.embedReferences.first?.isLargePreview == true)
        case .resultsView:
            if let descriptor = block.resultsView {
                resultsView(descriptor)
            }
        case .subChatBatch:
            if let descriptor = block.subChatBatch {
                SubChatBatchView(descriptor: descriptor, parentChatID: parentChatID ?? progressiveRequest?.identity.chatID ?? "",
                    messageCreatedAt: messageCreatedAt,
                    viewportWidth: viewportWidth,
                    store: subChatStore, progress: subChatProgress, completedSubChatIDs: completedSubChatIDs,
                    onOpenChat: onOpenSubChat)
            }
        case .interactiveQuestionFallback:
            interactiveQuestionFallback
        case .interactiveQuestion, .demoGroup, .hiddenProtocol:
            EmptyView()
        }
    }

    private func inlineText(_ text: String) -> some View {
        InlineMarkdownText(
            content: text,
            isUserMessage: isUserMessage,
            allEmbedRecords: allEmbedRecords,
            onEmbedTap: onEmbedTap,
            searchHighlightQuery: searchHighlightQuery
        )
    }

    private var interactiveQuestionFallback: some View {
        Text(AppStrings.interactiveQuestionFailed)
            .font(.omP)
            .foregroundStyle(Color.fontSecondary)
            .padding(.spacing4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
    }

    @ViewBuilder
    private func resolvedEmbedGroup(_ embeds: [EmbedRecord], isLargePreview: Bool) -> some View {
        let visibleEmbeds = embeds.filter { !hiddenEmbedIds.contains($0.id) }
        if !visibleEmbeds.isEmpty {
            if AppleStandaloneEmbedPreviewPresentation.usesLargePreview(
                explicit: isLargePreview, isUserMessage: isUserMessage, embedTypes: visibleEmbeds.map { $0.isAppSkillUse ? "app-skill-use" : $0.type }
            ) {
                LargeEmbedPreviewCarousel(embeds: visibleEmbeds, allEmbedRecords: allEmbedRecords) { embed in
                    onEmbedTap?(embed)
                }
            } else {
                ForEach(EmbedGrouper.groupForInlineDisplay(visibleEmbeds)) { group in
                    GroupedEmbedView(group: group, allEmbedRecords: allEmbedRecords) { embed in
                        onEmbedTap?(embed)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func blockView(for block: MarkdownBlock) -> some View {
        switch block {
        case .paragraph(let text):
            InlineMarkdownText(
                content: text,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )

        case .codeBlock(let language, let code):
            CodeBlockView(language: language, code: code, searchHighlightQuery: searchHighlightQuery)

        case .blockquote(let text):
            BlockquoteView(
                text: text,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )

        case .header(let level, let text):
            HeaderView(level: level, text: text, isUserMessage: isUserMessage, searchHighlightQuery: searchHighlightQuery)

        case .horizontalRule:
            Divider()
                .padding(.vertical, .spacing2)

        case .unorderedList(let items):
            ListBlockView(
                items: items,
                ordered: false,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )

        case .orderedList(let items):
            ListBlockView(
                items: items,
                ordered: true,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )

        case .table(let headers, let rows):
            TableBlockView(headers: headers, rows: rows, isUserMessage: isUserMessage, searchHighlightQuery: searchHighlightQuery)

        case .demoGroup(let kind):
            DemoRichGroupView(kind: kind, onOpenPublicChat: onOpenPublicChat)

        case .embedGroup(let references):
            resolvedEmbedGroup(references.compactMap(resolveEmbed), isLargePreview: references.first?.isLargePreview == true)

        case .resultsView(let descriptor):
            resultsView(descriptor)

        case .subChatBatch(let descriptor):
            SubChatBatchView(descriptor: descriptor, parentChatID: parentChatID ?? progressiveRequest?.identity.chatID ?? "",
                messageCreatedAt: messageCreatedAt,
                viewportWidth: viewportWidth,
                store: subChatStore, progress: subChatProgress, completedSubChatIDs: completedSubChatIDs,
                onOpenChat: onOpenSubChat)

        case .interactiveQuestion(let payload):
            AppleInteractiveQuestionCard(payload: payload, onSubmit: onInteractiveQuestionSubmit)

        case .interactiveQuestionFallback:
            interactiveQuestionFallback

        case .hiddenProtocol:
            EmptyView()
        }
    }

    private func resolveEmbed(_ reference: MarkdownEmbedReference) -> EmbedRecord? {
        if reference.isRef {
            return MarkdownEmbedResolver.resolve(reference.value, in: allEmbedRecords)
        }
        return embedLookup[reference.value] ?? allEmbedRecords[reference.value]
    }

    private func resultsView(_ descriptor: AppleResultsViewDescriptor) -> some View {
        AppleResultsView(
            descriptor: descriptor,
            embedLookup: embedLookup,
            allEmbedRecords: allEmbedRecords,
            hiddenEmbedIds: hiddenEmbedIds,
            onEmbedTap: onEmbedTap
        )
    }

    private func resolveEmbed(_ reference: ChatHistoryEmbedReference) -> EmbedRecord? {
        if reference.isReference {
            return MarkdownEmbedResolver.resolve(reference.id, in: allEmbedRecords)
        }
        return embedLookup[reference.id] ?? allEmbedRecords[reference.id]
    }
}

/// Native in-message counterpart to EmbedsMapView.svelte. The virtual block
/// references existing encrypted embeds; it never writes another embed.
struct AppleResultsView: View {
    @Environment(\.colorScheme) private var colorScheme
    let descriptor: AppleResultsViewDescriptor
    let embedLookup: [String: EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let hiddenEmbedIds: Set<String>
    let onEmbedTap: ((EmbedRecord) -> Void)?

    @State private var selectedTab: Tab = .map
    @State private var selectedCategory: String?
    @State private var filtersOpen = false
    @State private var rangeFilters: [String: ClosedRange<Double>] = [:]
    @State private var optionFilters: [String: Set<String>] = [:]
    @State private var weekIndex = 0
    #if canImport(MapKit)
    @State private var mapPosition: MapCameraPosition = .automatic
    @State private var mapVisibleRegion: MKCoordinateRegion?
    #endif
    @State private var mapSelectionIDs: Set<String> = []

    private enum Tab { case map, calendar }

    private static let utcMonthDayStyle: Date.FormatStyle = {
        var style = Date.FormatStyle().month(.abbreviated).day()
        style.timeZone = TimeZone(secondsFromGMT: 0)!
        return style
    }()
    private static let utcWeekdayStyle: Date.FormatStyle = {
        var style = Date.FormatStyle().weekday(.abbreviated).day()
        style.timeZone = TimeZone(secondsFromGMT: 0)!
        return style
    }()

    private var entries: [AppleResultsViewEntry] {
        AppleResultsViewEntry.resolve(descriptor, lookup: embedLookup, records: allEmbedRecords)
            .filter { !hiddenEmbedIds.contains($0.record.id) }
    }

    private var visibleEntries: [AppleResultsViewEntry] {
        let filtered = entries.filter {
            $0.matches(category: selectedCategory, ranges: rangeFilters, options: optionFilters)
        }
        let highlighted = Set(descriptor.highlightRefs)
        return filtered.sorted {
            let first = highlighted.contains($0.reference) || highlighted.contains($0.record.id)
            let second = highlighted.contains($1.reference) || highlighted.contains($1.record.id)
            return first && !second
        }
    }

    private func isHighlighted(_ entry: AppleResultsViewEntry) -> Bool {
        descriptor.highlightRefs.contains(entry.reference) || descriptor.highlightRefs.contains(entry.record.id)
    }

    private var mapEntries: [AppleResultsViewEntry] { visibleEntries.filter { $0.coordinate != nil || $0.route.count > 1 } }
    private var carouselEntries: [AppleResultsViewEntry] {
        mapSelectionIDs.isEmpty ? mapEntries : mapEntries.filter { mapSelectionIDs.contains($0.id) }
    }
    private var calendarEntries: [AppleResultsViewEntry] { visibleEntries.filter { $0.date != nil } }
    private var activeTab: Tab {
        selectedTab == .map && !mapEntries.isEmpty ? .map : .calendar
    }

    var body: some View {
        if !entries.isEmpty {
            VStack(spacing: 0) {
                Color.clear.frame(height: 23)

                if activeTab == .map, !mapEntries.isEmpty {
                    VStack(alignment: .trailing, spacing: 0) {
                        ScrollView(.horizontal) {
                            HStack(spacing: .spacing6) {
                                ForEach(carouselEntries) { entry in
                                    EmbedPreviewCard(embed: entry.record, allEmbedRecords: allEmbedRecords) {
                                        onEmbedTap?(entry.record)
                                    }
                                    .frame(width: 300, height: 200)
                                    .overlay {
                                        if mapSelectionIDs.contains(entry.id) {
                                            RoundedRectangle(cornerRadius: .radius8)
                                                .stroke(LinearGradient.primary, lineWidth: 3)
                                                .allowsHitTesting(false)
                                        }
                                    }
                                    .accessibilityIdentifier("embeds-map-view-card")
                                }
                            }
                            .padding(.horizontal, 14)
                            .padding(.top, 8)
                            .frame(height: 215, alignment: .top)
                        }
                        .frame(height: 215, alignment: .top)
                        .accessibilityIdentifier("embeds-map-view-carousel")

                        if !mapSelectionIDs.isEmpty {
                            Button {
                                mapSelectionIDs.removeAll()
                            } label: {
                                Text(AppStrings.mapShowAllResults)
                                    .font(.omXxs).fontWeight(.semibold)
                                    .foregroundStyle(Color.fontPrimary)
                                    .padding(.horizontal, 12).padding(.vertical, 8)
                                    .background(Color.grey0, in: Capsule())
                                    .overlay(Capsule().stroke(Color.grey30, lineWidth: 1))
                                    .contentShape(Capsule())
                            }
                            .buttonStyle(.plain)
                            .padding(.trailing, 16)
                            .frame(height: 42, alignment: .top)
                            .accessibilityIdentifier("embeds-map-view-show-all")
                        } else {
                            Color.clear.frame(height: 42)
                        }
                    }
                    .frame(height: 257)
                    #if canImport(MapKit)
                    ZStack {
                        mapPane
                            .accessibilityElement(children: .contain)
                            .accessibilityIdentifier("embeds-map-view-map")
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel(AppStrings.resultsViewMap)
                    .accessibilityIdentifier("embeds-results-view-panel-map")
                    .frame(height: 278)
                    .clipped()
                    #endif
                } else if !calendarEntries.isEmpty {
                    ZStack { calendarPane.accessibilityIdentifier("embeds-results-view-calendar") }
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel(AppStrings.resultsViewCalendar)
                    .accessibilityIdentifier("embeds-results-view-panel-calendar")
                    .frame(height: 535)
                }
            }
            // Fill the width proposed by the actual message container. The
            // approved responsive behavior removes the old652pt panel cap.
            .frame(maxWidth: .infinity)
            .background(Color.grey20)
            .clipShape(RoundedRectangle(cornerRadius: 23))
            .overlay(RoundedRectangle(cornerRadius: 23).stroke(Color.grey25, lineWidth: 1))
            .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
            .overlay(alignment: .topTrailing) {
                if Set(entries.map(\.category)).count > 1 || !rangeControls.isEmpty || !optionControls.isEmpty {
                    categoryControl
                        .frame(height: 42)
                        .padding(.trailing, 10)
                        .offset(y: -20)
                }
            }
            .overlay(alignment: .top) {
                if !mapEntries.isEmpty && !calendarEntries.isEmpty {
                    tabControl.offset(y: -20)
                }
            }
            .overlay(alignment: .topTrailing) {
                if filtersOpen { filterPanel.offset(y: 23) }
            }
            .padding(.top, .spacing10)
            .overlay(alignment: .topLeading) {
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement()
                    .accessibilityLabel(descriptor.title ?? AppStrings.resultsViewMap)
                    .accessibilityIdentifier("embeds-map-view")
                    .allowsHitTesting(false)
            }
        }
    }

    private var tabControl: some View {
        HStack(spacing: 0) {
            tabButton(.map, label: AppStrings.resultsViewMap, icon: "maps")
            tabButton(.calendar, label: AppStrings.resultsViewCalendar, icon: "calendar")
        }
        .frame(width: 170, height: 37)
        .background(Color.grey0)
        .clipShape(Capsule())
        .shadow(color: .black.opacity(0.16), radius: 5, x: 0, y: 4)
        .overlay(alignment: .topLeading) {
            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityLabel(AppStrings.resultsViewMap + ", " + AppStrings.resultsViewCalendar)
                .accessibilityIdentifier("embeds-results-view-tabs")
                .allowsHitTesting(false)
        }
    }

    private func tabButton(_ tab: Tab, label: String, icon: String) -> some View {
        Button {
            selectedTab = tab
        } label: {
            Icon(icon, size: 20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .foregroundStyle(activeTab == tab ? Color.fontButton : Color.fontSecondary)
                .background(activeTab == tab ? LinearGradient.primary : LinearGradient(colors: [.clear], startPoint: .leading, endPoint: .trailing))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(activeTab == tab ? .isSelected : [])
        .accessibilityIdentifier("embeds-results-view-tab-\(tab == .map ? "map" : "calendar")")
    }

    private var categoryControl: some View {
        Button {
            filtersOpen.toggle()
        } label: {
            Icon(filtersOpen ? "close" : "filter", size: 22)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 42, height: 42)
                .background(Color.grey0, in: Circle())
                .shadow(color: .black.opacity(0.08), radius: 5, y: 3)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(AppStrings.resultsViewFilter)
        .accessibilityIdentifier("embeds-map-view-filter-button")
    }

    private var rangeControls: [(key: String, label: String, values: [Double])] {
        let definitions = [
            ("departureMinutes", AppStrings.resultsViewDepartureTime),
            ("arrivalMinutes", AppStrings.resultsViewArrivalTime),
            ("durationMinutes", AppStrings.resultsViewDuration),
            ("transferMinutes", AppStrings.resultsViewTransferTime),
            ("price", AppStrings.resultsViewPrice),
        ]
        return definitions.compactMap { key, label in
            let values = entries.compactMap { $0.numericFacets[key] }
            guard let minimum = values.min(), let maximum = values.max(), minimum < maximum else { return nil }
            return (key: key, label: label, values: values)
        }
    }

    private var optionControls: [(key: String, label: String, values: [String])] {
        [("carriers", AppStrings.resultsViewCarrier), ("providers", AppStrings.resultsViewProvider)]
            .compactMap { key, label in
                let values = Array(Set(entries.flatMap { $0.optionFacets[key] ?? [] })).sorted()
                return values.count > 1 ? (key: key, label: label, values: values) : nil
            }
    }

    private var filterPanel: some View {
        VStack(spacing: 20) {
            VStack(spacing: 7) {
                Text(AppStrings.resultsViewRemaining(visible: visibleEntries.count, total: entries.count))
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embeds-map-view-filter-summary")
                Button {
                    selectedCategory = nil
                    rangeFilters.removeAll()
                    optionFilters.removeAll()
                } label: {
                    HStack(spacing: 7) {
                        ResultsLucideIcon(.trash).frame(width: 17, height: 17)
                        Text(AppStrings.resultsViewClearFilters).font(.omXs)
                    }
                    .foregroundStyle(Color(hex: 0x4867CD))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("embeds-map-view-clear-filters")
            }
            .frame(maxWidth: .infinity)

            ScrollView(.vertical) {
                VStack(alignment: .leading, spacing: 25) {
                    if Set(entries.map(\.category)).count > 1 {
                        filterSectionTitle(AppStrings.resultsViewType, icon: "filter")
                        ForEach(Array(Set(entries.map(\.category))).sorted(), id: \.self) { category in
                            filterOption(label: category.capitalized, selected: selectedCategory == category) {
                                selectedCategory = category
                            }
                        }
                    }
                    ForEach(rangeControls, id: \.key) { control in
                        VStack(alignment: .leading, spacing: 0) {
                            filterSectionTitle(control.label, icon: "clock")
                                .accessibilityIdentifier("embeds-map-view-filter-\(control.key)")
                            rangeControl(key: control.key, label: control.label, values: control.values)
                                .padding(.top, 12)
                        }
                    }
                    ForEach(optionControls, id: \.key) { control in
                        VStack(alignment: .leading, spacing: 12) {
                            filterSectionTitle(control.label, icon: "filter")
                                .accessibilityIdentifier("embeds-map-view-filter-\(control.key)")
                            ForEach(control.values, id: \.self) { value in
                                filterOption(label: value, selected: optionFilters[control.key]?.contains(value) ?? true) {
                                    var selected = optionFilters[control.key] ?? Set(control.values)
                                    if selected.contains(value) { selected.remove(value) } else { selected.insert(value) }
                                    optionFilters[control.key] = selected
                                }
                            }
                        }
                    }
                }
                .padding(.trailing, 14)
                .padding(.bottom, 20)
            }
            .accessibilityIdentifier("embeds-map-view-filter-scroll")
        }
        .padding(.top, 25)
        .padding(.horizontal, 16)
        .padding(.bottom, 16)
        .frame(maxWidth: .infinity)
        .frame(height: 535)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 23))
        .overlay(alignment: .topLeading) {
            Color.clear.frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityLabel(AppStrings.resultsViewFilter)
                .accessibilityIdentifier("embeds-map-view-filter-menu")
                .allowsHitTesting(false)
        }
    }

    private func filterSectionTitle(_ label: String, icon: String) -> some View {
        HStack(spacing: 20) {
            if icon == "clock" {
                ResultsLucideIcon(.clock).frame(width: 23, height: 23)
            } else {
                Icon(icon, size: 23).foregroundStyle(Color(hex: 0x4867CD))
            }
            Text(label).font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 8)
        .padding(.bottom, 7)
        .overlay(alignment: .bottom) { Color(hex: 0x4867CD).frame(height: 3) }
    }

    private func filterOption(label: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing2) {
                Text(label).font(.omXs)
                if selected { Icon("check", size: 14) }
            }
            .foregroundStyle(Color.fontPrimary)
            .padding(.spacing2)
            .background(selected ? Color.grey30 : Color.grey20)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
        }
        .buttonStyle(.plain)
    }

    private func rangeControl(key: String, label: String, values: [Double]) -> some View {
        let minimum = values.min() ?? 0
        let maximum = values.max() ?? 0
        return AppleResultsRangeControl(
            key: key, label: label, values: values,
            selection: Binding(
                get: { rangeFilters[key] ?? minimum...maximum },
                set: { rangeFilters[key] = $0 }
            )
        )
    }

    #if canImport(MapKit)
    // Apple owns the base map tiles; OpenMates retains the web result controls,
    // app-colored SVG pins, route styling, and explicit result selection.
    private struct ResultsMapMarker: Identifiable {
        let coordinate: CLLocationCoordinate2D
        var entries: [AppleResultsViewEntry]
        var endpoint: Bool
        var id: String {
            String(format: "%.6f:%.6f", coordinate.latitude, coordinate.longitude)
        }
    }

    private var mapMarkers: [ResultsMapMarker] {
        var markers: [ResultsMapMarker] = []
        var indices: [String: Int] = [:]
        for entry in mapEntries {
            let points = entry.route.isEmpty ? [entry.coordinate].compactMap { $0 } : entry.route
            for (index, coordinate) in points.enumerated() {
                let key = String(format: "%.6f:%.6f", coordinate.latitude, coordinate.longitude)
                let endpoint = index == 0 || index == points.count - 1
                if let existing = indices[key] {
                    markers[existing].entries.append(entry)
                    markers[existing].endpoint = markers[existing].endpoint || endpoint
                } else {
                    indices[key] = markers.count
                    markers.append(ResultsMapMarker(coordinate: coordinate, entries: [entry], endpoint: endpoint))
                }
            }
        }
        return markers
    }

    private var mapCoordinates: [CLLocationCoordinate2D] {
        mapEntries.flatMap { $0.route.isEmpty ? [$0.coordinate].compactMap { $0 } : $0.route }
    }

    private var mapGeometrySignature: String {
        mapCoordinates.map { String(format: "%.6f:%.6f", $0.latitude, $0.longitude) }.joined(separator: "|")
    }

    private func fitMapToResults() {
        guard let rect = AppleResultsMapCamera.fittedRect(coordinates: mapCoordinates) else { return }
        mapPosition = .rect(rect)
        // Keep only selection IDs that still survive the active filters.
        mapSelectionIDs.formIntersection(Set(mapEntries.map(\.id)))
    }

    private func zoomMap(by factor: Double) {
        guard let region = mapVisibleRegion else { return }
        mapPosition = .region(AppleResultsMapCamera.zoomed(region, factor: factor))
    }

    private var mapPane: some View {
        Map(position: $mapPosition, interactionModes: [.pan, .zoom]) {
            ForEach(mapEntries) { entry in
                if entry.route.count > 1 {
                    MapPolyline(coordinates: entry.route)
                        .stroke(mapSelectionIDs.isEmpty
                                ? AppGradientPalette.colors(for: "travel").start.opacity(0.8)
                                : mapSelectionIDs.contains(entry.id)
                                    ? AppGradientPalette.colors(for: "travel").end.opacity(0.8)
                                    : Color.grey50.opacity(0.5),
                                style: StrokeStyle(lineWidth: 5, lineCap: .round, dash: [10, 10]))
                }
            }
            ForEach(mapMarkers) { marker in
                Annotation(marker.entries.first?.title ?? AppStrings.resultsViewMap,
                           coordinate: marker.coordinate, anchor: .bottom) {
                    Button {
                        mapSelectionIDs = Set(marker.entries.map(\.id))
                    } label: {
                        Icon("maps", size: 40)
                            .foregroundStyle(AppGradientPalette.colors(for: marker.entries.first?.record.appId ?? "maps").start)
                            .frame(width: 40, height: 40)
                            .opacity(mapSelectionIDs.isEmpty || marker.entries.contains(where: { mapSelectionIDs.contains($0.id) }) ? 1 : 0.5)
                            .shadow(color: !mapSelectionIDs.isEmpty && marker.entries.contains(where: { mapSelectionIDs.contains($0.id) })
                                    ? Color.buttonPrimary.opacity(0.6) : .clear, radius: 3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(marker.entries.first?.title ?? AppStrings.resultsViewMap)
                    .accessibilityIdentifier(marker.endpoint
                        ? "embeds-map-view-endpoint-marker" : "embeds-map-view-stop-marker")
                }
                .annotationTitles(.hidden)
            }
        }
        .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll, showsTraffic: false))
        .mapControls { }
        .onMapCameraChange(frequency: .onEnd) { context in
            mapVisibleRegion = context.region
        }
        .onAppear { fitMapToResults() }
        .onChange(of: mapGeometrySignature) { _, _ in fitMapToResults() }
        .onChange(of: mapEntries.map(\.id)) { _, ids in
            mapSelectionIDs.formIntersection(Set(ids))
        }
        .overlay(alignment: .leading) {
            VStack(spacing: 0) {
                Button { zoomMap(by: 0.5) } label: {
                    Text("+").font(.system(size: 28, weight: .semibold)).frame(width: 57, height: 50)
                }
                .accessibilityLabel(AppStrings.zoomIn)
                .accessibilityIdentifier("embeds-map-view-zoom-in")
                Color.grey25.frame(width: 57, height: 1)
                Button { zoomMap(by: 2) } label: {
                    Text("−").font(.system(size: 28, weight: .semibold)).frame(width: 57, height: 50)
                }
                .accessibilityLabel(AppStrings.zoomOut)
                .accessibilityIdentifier("embeds-map-view-zoom-out")
            }
            .frame(width: 57)
            .foregroundStyle(LinearGradient.primary)
            .buttonStyle(.plain)
            .background(Color.grey0, in: Capsule())
            .clipShape(Capsule())
            .shadow(color: .black.opacity(0.15), radius: 6, y: 4)
            .padding(.leading, 14)
        }
    }
    #endif

    private struct CalendarLane: Identifiable {
        let entry: AppleResultsViewEntry
        let start: Double
        let end: Double
        var column: Int
        var columnCount: Int
        var id: String { entry.id }
    }

    // Match the web calendar's interval partitioning: overlapping results
    // share their day's width while retaining their actual start time.
    private func calendarLanes(_ segments: [(entry: AppleResultsViewEntry, start: Double, end: Double)]) -> [CalendarLane] {
        let sorted = segments.sorted { $0.start < $1.start }
        var lanes: [CalendarLane] = []
        var laneEnds: [Double] = []
        var groupStart = 0
        var groupEnd = -1.0
        func finishGroup() {
            for index in groupStart..<lanes.count { lanes[index].columnCount = max(1, laneEnds.count) }
        }
        for segment in sorted {
            if segment.start >= groupEnd {
                finishGroup()
                groupStart = lanes.count
                laneEnds.removeAll()
            }
            let column = laneEnds.firstIndex(where: { $0 <= segment.start }) ?? laneEnds.count
            if column == laneEnds.count { laneEnds.append(segment.end) }
            else { laneEnds[column] = segment.end }
            lanes.append(CalendarLane(entry: segment.entry, start: segment.start,
                                      end: segment.end, column: column, columnCount: 1))
            groupEnd = max(groupEnd, segment.end)
        }
        finishGroup()
        return lanes
    }

    private struct CalendarDay: Identifiable {
        let date: Date
        let dateOnly: [AppleResultsViewEntry]
        let lanes: [CalendarLane]
        var id: Date { date }
        // Web mobile days start at 88px. Keep that minimum per overlapping
        // event, rather than dropping the title when a lane becomes too narrow.
        var width: CGFloat { CGFloat(max(1, lanes.map(\.columnCount).max() ?? 1)) * 88 }
    }

    private var calendarPane: some View {
        var calendar = Calendar(identifier: .gregorian)
        calendar.firstWeekday = 2
        calendar.minimumDaysInFirstWeek = 4
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let weeks = Array(Set(calendarEntries.flatMap { entry -> [Date] in
            let first = entry.date.flatMap { calendar.dateInterval(of: .weekOfYear, for: $0)?.start }
            let last = entry.endDate.flatMap { calendar.dateInterval(of: .weekOfYear, for: $0)?.start }
            guard let first else { return [] }
            guard let last, last > first else { return [first] }
            return stride(from: first.timeIntervalSince1970, through: last.timeIntervalSince1970, by: 7 * 86400)
                .map { Date(timeIntervalSince1970: $0) }
        })).sorted()
        let index = min(weekIndex, max(0, weeks.count - 1))
        let weekStart = weeks.isEmpty ? Date() : weeks[index]
        let days = (0..<7).compactMap { offset -> CalendarDay? in
            guard let day = calendar.date(byAdding: .day, value: offset, to: weekStart) else { return nil }
            return CalendarDay(date: day,
                dateOnly: calendarEntries.filter {
                    $0.time == nil && $0.date.map { calendar.isDate($0, inSameDayAs: day) } == true
                },
                lanes: calendarLanes(calendarEntries.compactMap { $0.calendarSegment(on: day, calendar: calendar) }))
        }
        let timed = days.flatMap(\.lanes)
        let timelineStart = Int((timed.map(\.start).min() ?? 0) / 60) * 60
        let timelineHours = min(24 - timelineStart / 60, max(8,
            Int(ceil(((timed.map(\.end).max() ?? 0) - Double(timelineStart)) / 60))))
        let dateOnlyHeight = CGFloat(days.map { $0.dateOnly.count }.max() ?? 0) * 64
        let firstDayIndex = days.firstIndex { !$0.dateOnly.isEmpty || !$0.lanes.isEmpty } ?? 0
        let firstDay = days.isEmpty ? nil : days[firstDayIndex]
        let firstLane = firstDay?.dateOnly.isEmpty == true ? firstDay?.lanes.first : nil
        let firstEventX = (timed.isEmpty ? 0 : CGFloat(44)) + days.prefix(firstDayIndex).reduce(0) { $0 + $1.width }
        let firstEventY: CGFloat = firstLane.map { lane -> CGFloat in
            let minutesFromStart: CGFloat = CGFloat(lane.start - Double(timelineStart))
            let timedOffset: CGFloat = minutesFromStart / 60 * 46
            return timedOffset + 42 + dateOnlyHeight
        } ?? 0
        let revealKey = "\(weekStart.timeIntervalSince1970):\(firstDay?.id.timeIntervalSince1970 ?? 0):\(firstLane?.id ?? "date-only"):\(firstEventY)"
        return GeometryReader { viewport in
            let columnWidths = EmbedCalendarColumnLayout.widths(
                minimumWidths: days.map(\.width), availableWidth: max(0, viewport.size.width - 28),
                hasTimeColumn: !timed.isEmpty)
            let firstEventViewportX = firstEventX
                + columnWidths.prefix(firstDayIndex).reduce(0, +)
                - days.prefix(firstDayIndex).reduce(0) { $0 + $1.width }
            VStack(spacing: 8) {
                HStack(spacing: 20) {
                    weekButton(icon: "back", label: AppStrings.resultsViewPreviousWeek, enabled: index > 0) {
                        weekIndex -= 1
                    }
                    .accessibilityIdentifier("embeds-results-view-calendar-previous-week")
                    Text(AppStrings.resultsViewWeekNumber(
                        week: calendar.component(.weekOfYear, from: weekStart),
                        year: calendar.component(.yearForWeekOfYear, from: weekStart)
                    ))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity)
                        .accessibilityIdentifier("embeds-results-view-calendar-week-label")
                    weekButton(icon: "back", label: AppStrings.resultsViewNextWeek,
                               enabled: index < weeks.count - 1, flipped: true) {
                        weekIndex += 1
                    }
                    .accessibilityIdentifier("embeds-results-view-calendar-next-week")
                }
                // Web .calendar-week-toolbar is min(100%,260px), 36px high.
                // It belongs to the viewport, never the overflowing week grid.
                .frame(width: min(260, max(0, viewport.size.width - 28)), height: 36)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("embeds-results-view-calendar-toolbar")

                ScrollViewReader { proxy in
                    ScrollView([.horizontal, .vertical]) {
                        ZStack(alignment: .topLeading) {
                            calendarGrid(days: days, timelineStart: timelineStart,
                                         timelineHours: timelineHours, dateOnlyHeight: dateOnlyHeight,
                                         columnWidths: columnWidths)
                            Color.clear.frame(width: 1, height: 1)
                                .offset(x: firstEventViewportX, y: firstEventY)
                                .id("calendar-first-event")
                                .accessibilityHidden(true)
                        }
                        .padding(.horizontal, 14)
                        .padding(.bottom, 24)
                    }
                    .defaultScrollAnchor(.topLeading)
                    .frame(width: viewport.size.width)
                    .frame(maxHeight: .infinity)
                    .clipped()
                    .accessibilityIdentifier("embeds-results-view-calendar-scroll")
                    .task(id: revealKey) { @MainActor in
                        // Wait for the grid's first layout. A week/filter change
                        // reveals its first chronological event; body updates and
                        // manual scrolling keep the user's chosen position.
                        await Task.yield()
                        guard !Task.isCancelled else { return }
                        proxy.scrollTo("calendar-first-event", anchor: .topLeading)
                    }
                }
            }
            .padding(.top, 14)
            .frame(width: viewport.size.width, height: viewport.size.height)
        }
    }

    private func calendarGrid(days: [CalendarDay], timelineStart: Int,
                              timelineHours: Int, dateOnlyHeight: CGFloat,
                              columnWidths: [CGFloat]) -> some View {
        let hasTimed = days.contains { !$0.lanes.isEmpty }
        let timelineHeight = CGFloat(timelineHours) * 46
        return HStack(alignment: .top, spacing: 0) {
            if hasTimed {
                VStack(spacing: 0) {
                    Color.clear.frame(height: 42 + dateOnlyHeight)
                    ForEach(0...timelineHours, id: \.self) { hour in
                        Text(String(format: "%02d:00", timelineStart / 60 + hour))
                            .font(.omXxs)
                            .foregroundStyle(Color.fontPrimary)
                            .frame(width: 38, height: 46, alignment: .topTrailing)
                            .padding(.trailing, 6)
                    }
                }
                .frame(width: 44)
            }
            ForEach(Array(days.enumerated()), id: \.element.id) { index, day in
                let dayWidth = columnWidths[index]
                VStack(alignment: .leading, spacing: 0) {
                    Text(day.date.formatted(Self.utcWeekdayStyle))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                        .frame(width: dayWidth, height: 42)
                        .accessibilityIdentifier("embeds-results-view-calendar-day")
                    if dateOnlyHeight > 0 {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(day.dateOnly) { entry in
                                Button { onEmbedTap?(entry.record) } label: {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(entry.title).font(.omXs).fontWeight(.semibold).lineLimit(2)
                                        Text(day.date.formatted(Self.utcMonthDayStyle)).font(.omXxs)
                                    }
                                    .foregroundStyle(Color.fontPrimary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(6)
                                    .background(Color.grey30)
                                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                                }
                                .buttonStyle(.plain)
                                .frame(height: 64, alignment: .top)
                                .accessibilityIdentifier("embeds-results-view-calendar-date-only")
                            }
                        }
                        .frame(height: dateOnlyHeight, alignment: .top)
                    }
                    if hasTimed {
                        ZStack(alignment: .topLeading) {
                            ForEach(day.lanes) { lane in
                                calendarTimedEvent(lane, dayWidth: dayWidth, timelineStart: timelineStart)
                            }
                        }
                        .frame(width: dayWidth, height: timelineHeight, alignment: .topLeading)
                    }
                }
                .frame(width: dayWidth, alignment: .topLeading)
            }
        }
        .frame(width: (hasTimed ? 44 : 0) + columnWidths.reduce(0, +), alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embeds-results-view-calendar-week")
    }

    private func calendarTimedEvent(_ lane: CalendarLane, dayWidth: CGFloat, timelineStart: Int) -> some View {
        let columnWidth: CGFloat = dayWidth / CGFloat(lane.columnCount)
        let height: CGFloat = max(1, CGFloat(lane.end - lane.start) / 60 * 46)
        let horizontalOffset: CGFloat = CGFloat(lane.column) * columnWidth + 3
        let verticalOffset: CGFloat = CGFloat(lane.start - Double(timelineStart)) / 60 * 46
        let highlighted = isHighlighted(lane.entry)
        return Button { onEmbedTap?(lane.entry.record) } label: {
            ZStack(alignment: .topLeading) {
                Color.error.opacity(0.16)
                Text(lane.entry.title)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(3)
                    .padding(4)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .overlay(alignment: .leading) {
                (highlighted ? Color.fontPrimary : Color.error).frame(width: 3)
            }
            .clipShape(RoundedRectangle(cornerRadius: .radius2))
            .clipped()
        }
        .buttonStyle(.plain)
        .frame(width: columnWidth - 6, height: height)
        .offset(x: horizontalOffset, y: verticalOffset)
        .accessibilityLabel("\(lane.entry.title), \(lane.entry.time ?? "")")
        .accessibilityValue(highlighted ? "highlighted" : "normal")
        .accessibilityIdentifier("embeds-results-view-calendar-item")
    }

    private func weekButton(icon: String, label: String, enabled: Bool, flipped: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 17)
                .scaleEffect(x: flipped ? -1 : 1)
                .frame(width: 28, height: 28)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(label)
    }
}

/// The filter header and clear action use the same outlined Lucide geometry
/// as EmbedsMapView.svelte; the app's filled time asset has a different shape.
private struct ResultsLucideIcon: View {
    enum Kind { case clock, trash }
    let kind: Kind

    init(_ kind: Kind) { self.kind = kind }

    var body: some View {
        GeometryReader { geometry in
            Path { path in
                switch kind {
                case .clock:
                    path.addEllipse(in: CGRect(x: 2, y: 2, width: 20, height: 20))
                    path.move(to: CGPoint(x: 12, y: 6))
                    path.addLine(to: CGPoint(x: 12, y: 12))
                    path.addLine(to: CGPoint(x: 16, y: 12))
                case .trash:
                    path.move(to: CGPoint(x: 3, y: 6))
                    path.addLine(to: CGPoint(x: 21, y: 6))
                    path.move(to: CGPoint(x: 8, y: 6))
                    path.addLine(to: CGPoint(x: 8, y: 4))
                    path.addLine(to: CGPoint(x: 16, y: 4))
                    path.addLine(to: CGPoint(x: 16, y: 6))
                    path.move(to: CGPoint(x: 5, y: 6))
                    path.addLine(to: CGPoint(x: 6, y: 20))
                    path.addLine(to: CGPoint(x: 18, y: 20))
                    path.addLine(to: CGPoint(x: 19, y: 6))
                    path.move(to: CGPoint(x: 10, y: 11))
                    path.addLine(to: CGPoint(x: 10, y: 17))
                    path.move(to: CGPoint(x: 14, y: 11))
                    path.addLine(to: CGPoint(x: 14, y: 17))
                }
            }
            .applying(CGAffineTransform(scaleX: geometry.size.width / 24,
                                        y: geometry.size.height / 24))
            .stroke(Color(hex: 0x4867CD), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        }
        .accessibilityHidden(true)
    }
}

/// One distribution rail with two independently draggable and VoiceOver-
/// adjustable bounds, matching ResultsRangeFilter.svelte.
private struct AppleResultsRangeControl: View {
    let key: String
    let label: String
    let values: [Double]
    @Binding var selection: ClosedRange<Double>

    private let binCount = 36
    private let thumbSize: CGFloat = 28
    private let railColor = Color(hex: 0x059DB3) // app-travel-start token

    private var minimum: Double { values.min() ?? 0 }
    private var maximum: Double { values.max() ?? 0 }
    private var step: Double { key == "departureMinutes" || key == "arrivalMinutes" ? 5 : 1 }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            histogram
            GeometryReader { geometry in
                let usableWidth = max(1, geometry.size.width - thumbSize)
                let lowerX = thumbSize / 2 + CGFloat(fraction(selection.lowerBound)) * usableWidth
                let upperX = thumbSize / 2 + CGFloat(fraction(selection.upperBound)) * usableWidth
                ZStack(alignment: .topLeading) {
                    Capsule()
                        .fill(Color.grey40)
                        .frame(width: usableWidth, height: 6)
                        .offset(x: thumbSize / 2, y: 15)
                        .accessibilityElement()
                        .accessibilityLabel(label)
                        .accessibilityIdentifier("embeds-map-view-filter-\(key)-rail")
                    thumb(.lower, position: lowerX, usableWidth: usableWidth)
                    thumb(.upper, position: upperX, usableWidth: usableWidth)
                }
                .frame(height: 36)
                .coordinateSpace(name: "results-range-\(key)")
            }
            .frame(height: 36)
            HStack {
                Text(facetLabel(selection.lowerBound)).font(.omSmall).fontWeight(.bold)
                Spacer()
                Text(facetLabel(selection.upperBound)).font(.omSmall).fontWeight(.bold)
            }
            .frame(height: 42, alignment: .top)
        }
        .padding(.top, 12)
        .padding(.bottom, 8)
    }

    private var histogram: some View {
        let counts = (0..<binCount).map { index in
            values.filter { value in
                min(binCount - 1, Int(fraction(value) * Double(binCount))) == index
            }.count
        }
        let largest = max(1, counts.max() ?? 0)
        return ZStack(alignment: .bottom) {
            HStack(spacing: 3) {
                ForEach(0..<binCount, id: \.self) { _ in
                    Circle().fill(Color.grey50).frame(maxWidth: .infinity).frame(height: 4)
                }
            }
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(0..<binCount, id: \.self) { index in
                    let binStart = minimum + (maximum - minimum) * Double(index) / Double(binCount)
                    let binEnd = minimum + (maximum - minimum) * Double(index + 1) / Double(binCount)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(binEnd >= selection.lowerBound && binStart <= selection.upperBound ? railColor : Color.grey50)
                        .frame(maxWidth: .infinity)
                        .frame(height: counts[index] > 0 ? max(4, CGFloat(counts[index]) / CGFloat(largest) * 56) : 0)
                }
            }
        }
        .frame(height: 56, alignment: .bottom)
        .padding(.horizontal, thumbSize / 2)
        .accessibilityHidden(true)
    }

    private enum Side { case lower, upper }

    private func thumb(_ side: Side, position: CGFloat, usableWidth: CGFloat) -> some View {
        Circle()
            .fill(railColor)
            .frame(width: thumbSize, height: thumbSize)
            .contentShape(Circle())
            .gesture(DragGesture(minimumDistance: 0, coordinateSpace: .named("results-range-\(key)"))
                .onChanged { gesture in update(side, to: value(at: gesture.location.x, usableWidth: usableWidth)) })
            .accessibilityElement()
            .accessibilityLabel(label + ", " + (side == .lower ? AppStrings.resultsViewMinimum : AppStrings.resultsViewMaximum))
            .accessibilityValue(facetLabel(side == .lower ? selection.lowerBound : selection.upperBound))
            .accessibilityAdjustableAction { direction in
                switch direction {
                case .increment: update(side, to: (side == .lower ? selection.lowerBound : selection.upperBound) + step)
                case .decrement: update(side, to: (side == .lower ? selection.lowerBound : selection.upperBound) - step)
                @unknown default: break
                }
            }
            .accessibilityIdentifier("embeds-map-view-filter-\(key)-\(side == .lower ? "lower" : "upper")")
            .position(x: position, y: thumbSize / 2 + 4)
    }

    private func fraction(_ value: Double) -> Double {
        guard maximum > minimum else { return 0 }
        return min(1, max(0, (value - minimum) / (maximum - minimum)))
    }

    private func value(at x: CGFloat, usableWidth: CGFloat) -> Double {
        let raw = minimum + Double(min(1, max(0, (x - thumbSize / 2) / usableWidth))) * (maximum - minimum)
        return min(maximum, max(minimum, minimum + ((raw - minimum) / step).rounded() * step))
    }

    private func update(_ side: Side, to proposed: Double) {
        let value = min(maximum, max(minimum, proposed))
        if side == .lower { selection = min(value, selection.upperBound)...selection.upperBound }
        else { selection = selection.lowerBound...max(value, selection.lowerBound) }
    }

    private func facetLabel(_ value: Double) -> String {
        if key == "departureMinutes" || key == "arrivalMinutes" {
            return String(format: "%02d:%02d", Int(value) / 60, Int(value) % 60)
        }
        return String(Int(value.rounded()))
    }
}

#if canImport(MapKit)
/// Fits the actual result geometry, including routes crossing the date line.
/// A single location receives a neighborhood view instead of a zero-sized rect.
enum AppleResultsMapCamera {
    static func fittedRect(coordinates: [CLLocationCoordinate2D]) -> MKMapRect? {
        let points = coordinates.filter(CLLocationCoordinate2DIsValid).map(MKMapPoint.init)
        guard !points.isEmpty else { return nil }
        let worldWidth = MKMapRect.world.size.width
        let sortedX = points.map(\.x).sorted()
        var largestGap = -Double.infinity
        var startX = sortedX[0]
        for index in sortedX.indices {
            let next = index + 1 < sortedX.count ? sortedX[index + 1] : sortedX[0] + worldWidth
            if next - sortedX[index] > largestGap {
                largestGap = next - sortedX[index]
                startX = sortedX[(index + 1) % sortedX.count]
            }
        }
        let unwrappedX = points.map { $0.x < startX ? $0.x + worldWidth : $0.x }
        let minX = unwrappedX.min()!, maxX = unwrappedX.max()!
        let minY = points.map(\.y).min()!, maxY = points.map(\.y).max()!
        let center = MKMapPoint(x: (minX + maxX) / 2, y: (minY + maxY) / 2)
        let minimumSpan = 1_200 * MKMapPointsPerMeterAtLatitude(center.coordinate.latitude)
        // Leave room for the 40-point pins and the 57-point overlay controls
        // at phone width; extreme venues must remain visible and tappable.
        let width = min(worldWidth, max(minimumSpan, (maxX - minX) * 2.4))
        let height = min(worldWidth, max(minimumSpan, (maxY - minY) * 1.6))
        return MKMapRect(x: center.x - width / 2, y: center.y - height / 2,
                         width: width, height: height)
    }

    static func zoomed(_ region: MKCoordinateRegion, factor: Double) -> MKCoordinateRegion {
        MKCoordinateRegion(center: region.center,
                           span: MKCoordinateSpan(latitudeDelta: min(170, max(0.0002, region.span.latitudeDelta * factor)),
                                                  longitudeDelta: min(359, max(0.0002, region.span.longitudeDelta * factor))))
    }
}
#endif

struct AppleResultsViewEntry: Identifiable {
    let reference: String
    let record: EmbedRecord
    let title: String
    let category: String
    let date: Date?
    let time: String?
    let endDate: Date?
    let endTime: String?
    let numericFacets: [String: Double]
    let optionFacets: [String: [String]]
    #if canImport(MapKit)
    let coordinate: CLLocationCoordinate2D?
    let route: [CLLocationCoordinate2D]
    #endif

    var id: String { record.id }

    func matches(category: String?, ranges: [String: ClosedRange<Double>],
                 options: [String: Set<String>]) -> Bool {
        guard category == nil || self.category == category else { return false }
        for (key, range) in ranges {
            guard let value = numericFacets[key], range.contains(value) else { return false }
        }
        for (key, allowed) in options {
            guard let values = optionFacets[key], values.contains(where: allowed.contains) else { return false }
        }
        return true
    }

    static func resolve(_ descriptor: AppleResultsViewDescriptor,
                        lookup: [String: EmbedRecord], records: [String: EmbedRecord]) -> [AppleResultsViewEntry] {
        var references = descriptor.embedRefs
        for sourceRef in descriptor.sourceRefs {
            let normalized = sourceRef.hasPrefix("embed:") ? String(sourceRef.dropFirst(6)) : sourceRef
            guard let source = lookup[normalized] ?? MarkdownEmbedResolver.resolve(normalized, in: records) else { continue }
            references.append(contentsOf: source.childEmbedIds)
            let raw = source.rawData ?? [:]
            references.append(contentsOf: refList(raw["embed_ids"]?.value))
            references.append(contentsOf: refList(raw["child_embed_ids"]?.value))
        }
        var seenReferences = Set<String>()
        let uniqueReferences = references.compactMap { reference -> String? in
            let normalized = reference.hasPrefix("embed:") ? String(reference.dropFirst(6)) : reference
            return !normalized.isEmpty && seenReferences.insert(normalized).inserted ? normalized : nil
        }
        var seenRecords = Set<String>()
        return uniqueReferences.prefix(40).compactMap { normalized -> AppleResultsViewEntry? in
            guard let record = lookup[normalized] ?? MarkdownEmbedResolver.resolve(normalized, in: records),
                  seenRecords.insert(record.id).inserted else { return nil }
            let raw = record.rawData ?? [:]
            let origin = EventValue.string(raw, ["origin", "origin_name", "from"])
            let destination = EventValue.string(raw, ["destination", "destination_name", "to"])
            let title = origin.flatMap { start in destination.map { "\(start) -> \($0)" } }
                ?? EventValue.string(raw, ["title", "name", "displayName", "display_name", "summary"])
                ?? (raw["venue"]?.value as? [String: Any]).flatMap { $0["name"] as? String }
                ?? record.type
            let dateText = EventValue.string(raw, ["date", "datetime", "start_date", "scheduled_departure", "slot_datetime", "date_start", "departure", "start_time", "check_in_date", "check_in"])
            let date = dateText.flatMap(validDate)
            let time = dateText.flatMap { value -> String? in
                guard value.count >= 16 else { return nil }
                let separator = value.index(value.startIndex, offsetBy: 10)
                guard value[separator] == "T" || value[separator] == " " else { return nil }
                let start = value.index(after: separator)
                let end = value.index(start, offsetBy: 5)
                let candidate = String(value[start..<end])
                return candidate.range(of: #"^\d{2}:\d{2}$"#, options: .regularExpression) != nil ? candidate : nil
            }
            let arrivalText = EventValue.string(raw, ["arrival", "scheduled_arrival", "end_time", "date_end"])
            let endDate = arrivalText.flatMap(validDate)
            let endTime = arrivalText.flatMap { value -> String? in
                let pieces = value.split(whereSeparator: { $0 == "T" || $0 == " " })
                guard let last = pieces.last, last.contains(":") else { return nil }
                return String(last.prefix(5))
            }
            #if canImport(MapKit)
            let route = route(raw)
            let coordinate = coordinate(raw) ?? (route.count > 1 ? route.first : nil)
            guard coordinate != nil || date != nil else { return nil }
            #else
            guard date != nil else { return nil }
            #endif
            let type = "\(record.appId ?? ""):\(record.skillId ?? ""):\(record.type)".lowercased()
            let category = type.contains("event") ? "event" : type.contains("travel") || type.contains("connection") ? "route" : type.contains("stay") ? "stay" : "place"
            var numericFacets: [String: Double] = [:]
            if let departure = EventValue.string(raw, ["departure", "scheduled_departure", "slot_datetime", "start_time", "date_start"]),
               let minutes = timeMinutes(departure) { numericFacets["departureMinutes"] = minutes }
            if let arrival = EventValue.string(raw, ["arrival", "scheduled_arrival", "end_time", "date_end"]),
               let minutes = timeMinutes(arrival) { numericFacets["arrivalMinutes"] = minutes }
            if let duration = EventValue.double(raw, ["duration_minutes"]) ?? durationMinutes(EventValue.string(raw, ["duration"])) {
                numericFacets["durationMinutes"] = duration
            }
            if let price = EventValue.double(raw, ["price", "total_price", "min_price", "max_price"]) {
                numericFacets["price"] = price
            }
            let legs = raw["legs"]?.value as? [[String: Any]] ?? []
            let layovers = (raw["layovers"]?.value as? [[String: Any]] ?? [])
                + legs.flatMap { $0["layovers"] as? [[String: Any]] ?? [] }
            if let transfer = layovers.compactMap({ number($0["duration_minutes"]) }).min() {
                numericFacets["transferMinutes"] = transfer
            }
            var optionFacets: [String: [String]] = [:]
            for (key, fields) in [("carriers", ["carriers", "carrier"]),
                                  ("providers", ["provider", "booking_provider", "source_provider"])] {
                if let value = EventValue.string(raw, fields) {
                    optionFacets[key] = value.split(whereSeparator: { $0 == "|" || $0 == "," })
                        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                        .filter { !$0.isEmpty }
                }
            }
            return AppleResultsViewEntry(reference: normalized, record: record, title: title,
                                         category: category, date: date, time: time,
                                         endDate: endDate, endTime: endTime,
                                         numericFacets: numericFacets, optionFacets: optionFacets,
                                         coordinate: coordinate, route: route)
        }
    }

    private static func validDate(_ value: String) -> Date? {
        guard value.count >= 10 else { return nil }
        let prefix = String(value.prefix(10))
        guard prefix.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let parts = prefix.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3,
              let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])),
              calendar.component(.year, from: date) == parts[0],
              calendar.component(.month, from: date) == parts[1],
              calendar.component(.day, from: date) == parts[2] else { return nil }
        return date
    }

    func calendarSegment(on day: Date, calendar: Calendar) -> (entry: AppleResultsViewEntry, start: Double, end: Double)? {
        guard let date, let time, let startMinutes = Self.timeMinutes(time) else { return nil }
        let dayOffset = calendar.dateComponents([.day], from: date, to: day).day ?? 0
        let start = startMinutes - Double(dayOffset * 1440)
        let duration = numericFacets["durationMinutes"] ?? 60
        let end: Double
        if let endDate, let endTime, let endMinutes = Self.timeMinutes(endTime) {
            let endDayOffset = calendar.dateComponents([.day], from: date, to: endDate).day ?? 0
            end = Double(endDayOffset * 1440) + endMinutes - Double(dayOffset * 1440)
        } else {
            end = start + max(1, duration)
        }
        let clippedStart = max(0, start)
        let clippedEnd = min(1440, end)
        guard clippedEnd > clippedStart else { return nil }
        return (entry: self, start: clippedStart, end: clippedEnd)
    }

    private static func timeMinutes(_ value: String) -> Double? {
        let parts = value.split(whereSeparator: { $0 == "T" || $0 == " " })
        guard let time = parts.last, time.count >= 5 else { return nil }
        let pieces = String(time.prefix(5)).split(separator: ":")
        guard pieces.count == 2, let hour = Int(pieces[0]), let minute = Int(pieces[1]),
              (0...23).contains(hour), (0...59).contains(minute) else { return nil }
        return Double(hour * 60 + minute)
    }

    private static func durationMinutes(_ value: String?) -> Double? {
        guard let value else { return nil }
        let hours = value.range(of: #"\d+(?:\.\d+)?\s*h"#, options: .regularExpression)
            .flatMap { Double(value[$0].replacingOccurrences(of: "h", with: "").trimmingCharacters(in: .whitespaces)) }
        let minutes = value.range(of: #"\d+(?:\.\d+)?\s*m"#, options: .regularExpression)
            .flatMap { Double(value[$0].replacingOccurrences(of: "m", with: "").trimmingCharacters(in: .whitespaces)) }
        if hours != nil || minutes != nil { return (hours ?? 0) * 60 + (minutes ?? 0) }
        return Double(value)
    }

    private static func refList(_ value: Any?) -> [String] {
        if let values = value as? [String] { return values }
        if let values = value as? [Any] { return values.compactMap { $0 as? String } }
        if let value = value as? String {
            return value.split(whereSeparator: { $0 == "|" || $0 == "," })
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
        return []
    }

    #if canImport(MapKit)
    static func coordinate(_ raw: [String: AnyCodable]) -> CLLocationCoordinate2D? {
        let data = raw.mapValues(\.value)
        let venue = dictionary(data["venue"]) ?? [:]
        let location = dictionary(data["location"]) ?? [:]
        let coordinates = dictionary(data["coordinates"]) ?? [:]
        let gps = dictionary(data["gps_coordinates"]) ?? [:]
        let eventType = (data["event_type"] as? String ?? data["eventType"] as? String ?? "").lowercased()
        let venueName = (data["venue_name"] as? String ?? venue["name"] as? String ?? "").lowercased()
        guard eventType != "online", venueName != "online event" else { return nil }

        let candidates: [([String: Any], [(String, String)])] = [
            (data, [("venue_lat", "venue_lon"), ("venue_lat", "venue_lng"),
                    ("venue_latitude", "venue_longitude")]),
            (venue, [("lat", "lon"), ("lat", "lng"), ("latitude", "longitude")]),
            (data, [("location_lat", "location_lon"), ("location_lat", "location_lng"),
                    ("location_latitude", "location_longitude")]),
            (location, [("lat", "lon"), ("lat", "lng"), ("latitude", "longitude")]),
            (data, [("gps_coordinates_latitude", "gps_coordinates_longitude"),
                    ("gps_coordinates_latitude", "gps_coordinates_lon"),
                    ("gps_coordinates_latitude", "gps_coordinates_lng")]),
            (gps, [("latitude", "longitude"), ("lat", "lon"), ("lat", "lng")]),
            (coordinates, [("latitude", "longitude"), ("lat", "lon"), ("lat", "lng")]),
            (data, [("latitude", "longitude"), ("lat", "lon"), ("lat", "lng")]),
        ]
        for (source, pairs) in candidates {
            if let point = point(source, pairs: pairs) { return point }
        }
        return nil
    }

    private static func route(_ raw: [String: AnyCodable]) -> [CLLocationCoordinate2D] {
        let data = raw.mapValues(\.value)
        for key in ["route_points", "route", "path", "polyline_points"] {
            if let rows = data[key] as? [[String: Any]] {
                return rows.compactMap { point($0, pairs: [("lat", "lon"), ("lat", "lng"),
                                                        ("latitude", "longitude")]) }
            }
        }

        let segmentRows = data["segments"] as? [[String: Any]] ?? []
        let legs = data["legs"] as? [[String: Any]] ?? []
        let nestedRows = legs.flatMap { $0["segments"] as? [[String: Any]] ?? [] }
        var flatRows: [[String: Any]] = []
        for legIndex in 0..<8 {
            for segmentIndex in 0..<32 {
                let prefix = "legs_\(legIndex)_segments_\(segmentIndex)_"
                let keys = ["departure_latitude", "departure_longitude", "arrival_latitude", "arrival_longitude"]
                let row = Dictionary(uniqueKeysWithValues: keys.compactMap { key -> (String, Any)? in
                    data[prefix + key].map { (key, $0) }
                })
                if row.isEmpty {
                    if segmentIndex == 0 { break }
                    continue
                }
                flatRows.append(row)
            }
        }
        var points: [CLLocationCoordinate2D] = []
        for segment in segmentRows + nestedRows + flatRows {
            for prefix in ["departure", "arrival"] {
                if let candidate = point(segment, pairs: [("\(prefix)_latitude", "\(prefix)_longitude"),
                                                          ("\(prefix)_lat", "\(prefix)_lng"),
                                                          ("\(prefix)_lat", "\(prefix)_lon")]) {
                    if let last = points.last,
                       last.latitude == candidate.latitude && last.longitude == candidate.longitude { continue }
                    points.append(candidate)
                }
            }
        }
        if points.count > 1 { return points }

        let flightTrack = dictionary(data["flight_track"]) ?? [:]
        if let tracks = flightTrack["tracks"] as? [[String: Any]] {
            let points = tracks.compactMap { point($0, pairs: [("lat", "lon"), ("lat", "lng"),
                                                               ("latitude", "longitude")]) }
            if points.count > 1 { return points }
        }
        let origin = dictionary(data["origin"]) ?? [:]
        let destination = dictionary(data["destination"]) ?? [:]
        let originPoint = point(data, pairs: [("origin_lat", "origin_lon"), ("origin_lat", "origin_lng"),
                                              ("origin_latitude", "origin_longitude")])
            ?? point(origin, pairs: [("lat", "lon"), ("lat", "lng"), ("latitude", "longitude")])
        let destinationPoint = point(data, pairs: [("destination_lat", "destination_lon"),
                                                   ("destination_lat", "destination_lng"),
                                                   ("destination_latitude", "destination_longitude")])
            ?? point(destination, pairs: [("lat", "lon"), ("lat", "lng"), ("latitude", "longitude")])
        if let originPoint, let destinationPoint { return [originPoint, destinationPoint] }
        return []
    }

    private static func dictionary(_ value: Any?) -> [String: Any]? {
        if let value = value as? [String: Any] { return value }
        if let value = value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return nil
    }

    private static func point(_ data: [String: Any], pairs: [(String, String)]) -> CLLocationCoordinate2D? {
        for (latitudeKey, longitudeKey) in pairs {
            guard let latitude = number(data[latitudeKey]), let longitude = number(data[longitudeKey]) else { continue }
            let candidate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
            if CLLocationCoordinate2DIsValid(candidate) { return candidate }
        }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let number = value as? NSNumber { return number.doubleValue }
        if let value = value as? String { return Double(value) }
        return nil
    }
    #endif
}

private struct AppleInteractiveQuestionCard: View {
    let payload: AppleInteractiveQuestionPayload
    let onSubmit: ((String) -> Void)?
    @State private var selectedOptionIds: Set<String>
    @State private var customAnswer: String
    @State private var inputValues: [String: String]
    @State private var sliderValue: Double
    @State private var swipeValues: [String: String]
    @State private var rating: Int
    @State private var comment: String

    init(payload: AppleInteractiveQuestionPayload, onSubmit: ((String) -> Void)? = nil) {
        self.payload = payload
        self.onSubmit = onSubmit
        _selectedOptionIds = State(initialValue: [])
        _customAnswer = State(initialValue: "")
        _inputValues = State(initialValue: [:])
        _sliderValue = State(initialValue: payload.defaultValue ?? payload.sliderLowerBound)
        _swipeValues = State(initialValue: [:])
        _rating = State(initialValue: 0)
        _comment = State(initialValue: "")
    }

    private var questionBadgeColors: (foreground: Color, background: Color) {
        switch payload.type {
        case "input": return (Color(hex: 0x7950F2), Color(hex: 0xF3F0FF))
        case "slider": return (Color(hex: 0xD6336C), Color(hex: 0xFFF0F6))
        case "swipe": return (Color(hex: 0x0CA678), Color(hex: 0xE8F7F5))
        case "rating": return (Color(hex: 0xF08C00), Color(hex: 0xFFF9DB))
        default: return (Color(hex: 0x228BE6), Color(hex: 0xE7F5FF))
        }
    }

    private var questionTypeLabel: String {
        switch payload.type {
        case "choice": return "Choice"
        case "input": return "Form"
        case "slider": return "Scale"
        case "swipe": return "Swipe Decision"
        case "rating": return "Rating"
        default: return payload.type
        }
    }

    private var title: String {
        if let question = payload.question, !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return question
        }
        if let field = payload.fields?.first {
            return field.label
        }
        return AppStrings.interactiveQuestionFailed
    }

    private var rows: [String] {
        switch payload.type {
        case "choice":
            return payload.options?.map(\.text) ?? []
        case "input":
            return payload.fields?.map(\.label) ?? []
        case "swipe":
            return payload.cards?.map(\.text) ?? []
        default:
            return []
        }
    }

    private var canSubmit: Bool {
        switch payload.type {
        case "choice":
            return !selectedOptionIds.isEmpty && (!hasSelectedCustomOption || !customAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        case "input":
            let requiredFields = (payload.fields ?? []).filter { $0.required == true }
            if requiredFields.isEmpty {
                return inputValues.values.contains { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            }
            return requiredFields.allSatisfy { field in
                !(inputValues[field.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
        case "slider":
            return true
        case "swipe":
            return Set(swipeValues.keys) == Set((payload.cards ?? []).map(\.id))
        case "rating":
            let commentReady = payload.requireComment == true
                ? !comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                : true
            return rating > 0 && commentReady
        default:
            return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing12) {
            Text(questionTypeLabel)
                .font(.omTiny).fontWeight(.bold)
                .tracking(0.5)
                .textCase(.uppercase)
                // Web type-badge colors have no generated token counterpart.
                // InteractiveQuestionContainer.svelte: .*-badge.
                .foregroundStyle(questionBadgeColors.foreground)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing1)
                .background(questionBadgeColors.background)
                .clipShape(Capsule())
            Text(title)
                .font(.omH4)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontTertiary)

            if onSubmit != nil {
                interactiveControls
                questionFooter
            } else if !rows.isEmpty {
                VStack(alignment: .leading, spacing: .spacing8) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        answerButton(text: row, isSelected: false, action: {})
                            .disabled(true)
                    }
                }
            }
        }
        .padding(.spacing12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10)
        .overlay(
            RoundedRectangle(cornerRadius: .radius5)
                .stroke(Color.grey20, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("interactive-question-card")
    }

    @ViewBuilder
    private var interactiveControls: some View {
        switch payload.type {
        case "choice":
            VStack(alignment: .leading, spacing: .spacing8) {
                ForEach(payload.options ?? []) { option in
                    VStack(alignment: .leading, spacing: .spacing2) {
                        answerButton(
                            text: option.text,
                            isSelected: selectedOptionIds.contains(option.id)
                        ) {
                            if payload.multiple == true {
                                if selectedOptionIds.contains(option.id) {
                                    selectedOptionIds.remove(option.id)
                                } else {
                                    selectedOptionIds.insert(option.id)
                                }
                            } else {
                                selectedOptionIds = [option.id]
                            }
                            if !hasSelectedCustomOption {
                                customAnswer = ""
                            }
                        }
                        if selectedOptionIds.contains(option.id), payload.isCustomChoiceOption(option) {
                            TextField(payload.customPlaceholder ?? "", text: $customAnswer, axis: .vertical)
                                .textFieldStyle(OMTextFieldStyle())
                                .accessibilityIdentifier("interactive-question-custom-answer")
                        }
                    }
                }
            }

        case "input":
            VStack(alignment: .leading, spacing: .spacing3) {
                ForEach(payload.fields ?? []) { field in
                    TextField(field.placeholder ?? field.label, text: binding(for: field.id), axis: .vertical)
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("interactive-question-input-\(field.id)")
                }
            }

        case "slider":
            VStack(alignment: .leading, spacing: .spacing2) {
                Slider(
                    value: $sliderValue,
                    in: payload.sliderLowerBound...payload.sliderUpperBound,
                    step: payload.sliderStep
                )
                .tint(Color.buttonPrimary)
                Text(payload.displayText(for: ["value": sliderValue]))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }

        case "swipe":
            VStack(alignment: .leading, spacing: .spacing3) {
                ForEach(payload.cards ?? []) { card in
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(card.text)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                        HStack(spacing: .spacing3) {
                            swipeButton(cardId: card.id, value: "like", label: AppStrings.yes)
                            swipeButton(cardId: card.id, value: "dislike", label: AppStrings.no)
                        }
                    }
                }
            }

        case "rating":
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing2) {
                    ForEach(1...payload.ratingMaximum, id: \.self) { value in
                        Button {
                            rating = value
                        } label: {
                            Text(String(value))
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(value <= rating ? Color.fontButton : Color.fontPrimary)
                                .frame(width: 28, height: 28)
                                .background(value <= rating ? Color.buttonPrimary : Color.grey0)
                                .clipShape(Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("interactive-question-rating-\(value)")
                    }
                }
                if payload.requireComment == true || payload.commentPlaceholder != nil {
                    TextField(payload.commentPlaceholder ?? "", text: $comment, axis: .vertical)
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("interactive-question-rating-comment")
                }
            }

        default:
            EmptyView()
        }
    }

    private var questionFooter: some View {
        HStack(spacing: .spacing12) {
            Spacer(minLength: 0)
            Button {
                selectedOptionIds = []
                customAnswer = ""
                inputValues = [:]
                sliderValue = payload.defaultValue ?? payload.sliderLowerBound
                swipeValues = [:]
                rating = 0
                comment = ""
            } label: {
                Text(AppStrings.sketchClear)
                    .font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing16)
                    .frame(minHeight: 41)
                    .overlay {
                        RoundedRectangle(cornerRadius: .radius8)
                            .stroke(Color.grey40, lineWidth: 1)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("interactive-question-clear")
            submitButton
        }
        .padding(.top, .spacing12)
        .overlay(alignment: .top) { Rectangle().fill(Color.grey20).frame(height: 1) }
    }

    private var submitButton: some View {
        Button {
            onSubmit?(payload.responseContent(response: responsePayload()))
        } label: {
            Text(AppStrings.sendAction)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(canSubmit ? Color.fontButton : Color.grey50)
                .padding(.horizontal, .spacing16)
                .frame(minHeight: 41)
                .background {
                    if canSubmit { LinearGradient.primary } else { Color.grey30 }
                }
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
        .buttonStyle(.plain)
        .disabled(!canSubmit)
        .accessibilityIdentifier("interactive-question-submit")
    }

    private func answerButton(text: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: .spacing12) {
                choiceIndicator(isSelected: isSelected)
                    .frame(width: 18, height: 20)
                    .padding(.top, 2)
                Text(text)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing12)
            .padding(.vertical, .spacing8)
            .background(isSelected ? Color.grey0 : Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay {
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(isSelected ? Color.grey40 : Color.grey20, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("interactive-question-option")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    @ViewBuilder
    private func choiceIndicator(isSelected: Bool) -> some View {
        if payload.multiple == true {
            RoundedRectangle(cornerRadius: .radius1)
                .fill(Color.clear)
                .background {
                    if isSelected { LinearGradient.primary.clipShape(RoundedRectangle(cornerRadius: .radius1)) }
                }
                .overlay {
                    RoundedRectangle(cornerRadius: .radius1).stroke(Color.grey40, lineWidth: 2)
                    if isSelected { Icon("check", size: 14).foregroundStyle(Color.fontButton) }
                }
                .frame(width: 18, height: 18)
        } else {
            Circle()
                .stroke(Color.grey40, lineWidth: 2)
                .overlay {
                    if isSelected { Circle().fill(LinearGradient.primary).frame(width: 10, height: 10) }
                }
                .frame(width: 18, height: 18)
        }
    }

    private func swipeButton(cardId: String, value: String, label: String) -> some View {
        answerButton(text: label, isSelected: swipeValues[cardId] == value) {
            swipeValues[cardId] = value
        }
    }

    private func binding(for fieldId: String) -> Binding<String> {
        Binding(
            get: { inputValues[fieldId] ?? "" },
            set: { inputValues[fieldId] = $0 }
        )
    }

    private var hasSelectedCustomOption: Bool {
        (payload.options ?? []).contains { option in
            selectedOptionIds.contains(option.id) && payload.isCustomChoiceOption(option)
        }
    }

    private func responsePayload() -> [String: Any] {
        switch payload.type {
        case "choice":
            let orderedSelection = (payload.options ?? [])
                .map(\.id)
                .filter { selectedOptionIds.contains($0) }
            var response: [String: Any] = ["id": payload.id, "selection": orderedSelection]
            let trimmedCustomAnswer = customAnswer.trimmingCharacters(in: .whitespacesAndNewlines)
            if hasSelectedCustomOption && !trimmedCustomAnswer.isEmpty {
                response["custom_answer"] = trimmedCustomAnswer
            }
            return response
        case "input":
            let inputs = (payload.fields ?? []).reduce(into: [String: String]()) { result, field in
                let value = (inputValues[field.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty { result[field.id] = value }
            }
            return ["id": payload.id, "inputs": inputs]
        case "slider":
            return ["id": payload.id, "value": sliderValue]
        case "swipe":
            return ["id": payload.id, "swipes": swipeValues]
        case "rating":
            var response: [String: Any] = ["id": payload.id, "rating": rating]
            let trimmedComment = comment.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedComment.isEmpty { response["comment"] = trimmedComment }
            return response
        default:
            return ["id": payload.id]
        }
    }
}

private struct LargeEmbedPreviewCarousel: View {
    private enum Constants {
        static let compactArrowHeight: CGFloat = 200
        static let expandedArrowHeight: CGFloat = 400
    }

    let embeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: (EmbedRecord) -> Void
    @State private var selectedIndex = 0
    @State private var containerWidth: CGFloat = 0
    @State private var scrollWheelAccumulator: CGFloat = 0

    private var hasMultiple: Bool { embeds.count > 1 }
    private var variant: EmbedPreviewCardVariant {
        AppleStandaloneEmbedPreviewPresentation.variant(containerWidth: containerWidth)
    }
    private var arrowHeight: CGFloat {
        variant == .large ? Constants.expandedArrowHeight : Constants.compactArrowHeight
    }
    private var selectedEmbed: EmbedRecord? {
        guard embeds.indices.contains(selectedIndex) else { return embeds.first }
        return embeds[selectedIndex]
    }

    var body: some View {
        VStack(spacing: .spacing3) {
            ZStack {
                if let selectedEmbed {
                    EmbedPreviewCard(
                        embed: selectedEmbed,
                        allEmbedRecords: allEmbedRecords,
                        variant: variant
                    ) {
                        onEmbedTap(selectedEmbed)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityIdentifier("embed-preview-\(selectedEmbed.id)")
                }

                if hasMultiple {
                    HStack {
                        carouselArrow(icon: "back", label: AppStrings.previousInspiration) {
                            selectedIndex = (selectedIndex - 1 + embeds.count) % embeds.count
                        }

                        Spacer()

                        carouselArrow(icon: "back", label: AppStrings.nextInspiration, flipsHorizontally: true) {
                            selectedIndex = (selectedIndex + 1) % embeds.count
                        }
                    }
                }
            }
            .gesture(
                DragGesture(minimumDistance: 24)
                    .onEnded { value in
                        guard hasMultiple else { return }
                        let dx = value.translation.width
                        let dy = value.translation.height
                        guard abs(dx) > 45, abs(dx) > abs(dy) * 1.2 else { return }
                        withAnimation(.easeInOut(duration: 0.18)) {
                            if dx < 0 {
                                selectedIndex = (selectedIndex + 1) % embeds.count
                            } else {
                                selectedIndex = (selectedIndex - 1 + embeds.count) % embeds.count
                            }
                        }
                    }
            )
            #if os(macOS)
            .background(
                MacCarouselScrollWheelMonitor { delta in
                    guard hasMultiple else { return }
                    scrollWheelAccumulator += delta
                    guard abs(scrollWheelAccumulator) > 36 else { return }
                    withAnimation(.easeInOut(duration: 0.18)) {
                        if scrollWheelAccumulator > 0 {
                            selectedIndex = (selectedIndex + 1) % embeds.count
                        } else {
                            selectedIndex = (selectedIndex - 1 + embeds.count) % embeds.count
                        }
                    }
                    scrollWheelAccumulator = 0
                }
            )
            #endif

            if hasMultiple {
                HStack(spacing: 6) {
                    ForEach(embeds.indices, id: \.self) { index in
                        Button {
                            selectedIndex = index
                        } label: {
                            Capsule()
                                .fill(index == selectedIndex ? Color.grey100 : Color.grey70.opacity(0.65))
                                .frame(width: index == selectedIndex ? 18 : 7, height: 7)
                        }
                        .buttonStyle(.plain)
                        .help(Text("Go to slide \(index + 1) of \(embeds.count)"))
                        .accessibilityLabel("Go to slide \(index + 1) of \(embeds.count)")
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(.black.opacity(0.35))
                .clipShape(Capsule())
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, hasMultiple ? 8 : 0)
        .background {
            GeometryReader { proxy in
                Color.clear
                    .onAppear { containerWidth = proxy.size.width }
                    .onChange(of: proxy.size.width) { _, width in
                        containerWidth = width
                    }
            }
        }
    }

    private func carouselArrow(
        icon: String,
        label: String,
        flipsHorizontally: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Icon(icon, size: 22)
                .rotationEffect(.degrees(flipsHorizontally ? 180 : 0))
                .foregroundStyle(Color.grey100.opacity(0.85))
                .frame(width: 40, height: arrowHeight)
                .background(Color.clear)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(Text(label))
        .accessibilityLabel(label)
    }
}

#if os(macOS)
private struct MacCarouselScrollWheelMonitor: NSViewRepresentable {
    let onHorizontalScroll: (CGFloat) -> Void

    func makeNSView(context: Context) -> MonitorView {
        let view = MonitorView()
        view.onHorizontalScroll = onHorizontalScroll
        return view
    }

    func updateNSView(_ nsView: MonitorView, context: Context) {
        nsView.onHorizontalScroll = onHorizontalScroll
    }

    final class MonitorView: NSView {
        var onHorizontalScroll: ((CGFloat) -> Void)?
        private var monitor: Any?

        override init(frame frameRect: NSRect) {
            super.init(frame: frameRect)
            wantsLayer = false
        }

        required init?(coder: NSCoder) {
            super.init(coder: coder)
        }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if window == nil {
                removeMonitor()
            } else if monitor == nil {
                monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] event in
                    self?.handle(event)
                    return event
                }
            }
        }

        deinit {
            removeMonitor()
        }

        private func removeMonitor() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
                self.monitor = nil
            }
        }

        private func handle(_ event: NSEvent) {
            guard let window, let onHorizontalScroll else { return }
            let pointInWindow = event.locationInWindow
            guard pointInWindow.x >= 0,
                  pointInWindow.y >= 0,
                  pointInWindow.x <= window.frame.width,
                  pointInWindow.y <= window.frame.height else {
                return
            }
            let localPoint = convert(pointInWindow, from: nil)
            guard bounds.contains(localPoint) else { return }
            let horizontalDelta = abs(event.scrollingDeltaX) > abs(event.scrollingDeltaY) * 1.2
                ? event.scrollingDeltaX
                : (event.modifierFlags.contains(.shift) ? event.scrollingDeltaY : 0)
            guard abs(horizontalDelta) > 0 else { return }
            onHorizontalScroll(horizontalDelta)
        }
    }
}
#endif

// MARK: - Inline markdown (paragraphs, list items)

struct InlineMarkdownPreparationInput: Equatable {
    let content: String
    let searchHighlightQuery: String?
}

struct InlineMarkdownPreparedContent {
    let attributedContent: AttributedString
    let tokens: [InlineMarkdownToken]
    let highlightRanges: [[NSRange]]
    let customLayout: Bool
}

@MainActor
final class InlineMarkdownPreparationModel: ObservableObject {
    @Published private(set) var value: InlineMarkdownPreparedContent
    private(set) var input: InlineMarkdownPreparationInput
    private(set) var parseCount = 1
    private(set) var parsedUTF8: Int

    init(input: InlineMarkdownPreparationInput) {
        self.input = input
        parsedUTF8 = input.content.utf8.count
        value = InlineMarkdownText.prepare(input)
    }

    func update(_ input: InlineMarkdownPreparationInput) {
        guard self.input != input else { return }
        self.input = input
        value = InlineMarkdownText.prepare(input)
        parseCount += 1
        parsedUTF8 += input.content.utf8.count
    }
}

struct InlineMarkdownText: View {
    let content: String
    let isUserMessage: Bool
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: ((EmbedRecord) -> Void)?
    let searchHighlightQuery: String?
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.messageTextSelection) private var selectionContext
    @Environment(\.readOnlyTextSelection) private var readOnlySelection
    @StateObject private var preparation: InlineMarkdownPreparationModel
    private var attributedContent: AttributedString { preparation.value.attributedContent }
    private var inlineTokens: [InlineMarkdownToken] { preparation.value.tokens }
    private var inlineTokenHighlightRanges: [[NSRange]] { preparation.value.highlightRanges }
    private var needsCustomInlineLayout: Bool { preparation.value.customLayout }
    private var displayFormula: String? { MarkdownMathParser.singleDisplayFormula(in: content) }

    init(
        content: String,
        isUserMessage: Bool,
        allEmbedRecords: [String: EmbedRecord] = [:],
        onEmbedTap: ((EmbedRecord) -> Void)? = nil,
        searchHighlightQuery: String? = nil
    ) {
        self.content = content
        self.isUserMessage = isUserMessage
        self.allEmbedRecords = allEmbedRecords
        self.onEmbedTap = onEmbedTap
        self.searchHighlightQuery = searchHighlightQuery
        _preparation = StateObject(wrappedValue: InlineMarkdownPreparationModel(
            input: InlineMarkdownPreparationInput(content: content, searchHighlightQuery: searchHighlightQuery)))
    }

    fileprivate static func prepare(_ input: InlineMarkdownPreparationInput) -> InlineMarkdownPreparedContent {
        let content = input.content
        // References must remain interactive regardless of paragraph length.
        // The mounted preparation cache prevents reparsing on unrelated updates;
        // the existing flow keeps its bounded cache of measured width proposals.
        let customLayout = content.contains("(wiki:") || content.contains("(embed:") || content.contains("](")
            || MarkdownMathParser.containsFormula(in: content) || content.contains("@")
        let attributed = customLayout ? AttributedString() :
            ((try? AttributedString(markdown: content, options: .init(
                interpretedSyntax: .inlineOnlyPreservingWhitespace
            ))) ?? AttributedString(content))
        let tokens = customLayout ? InlineMarkdownTokenizer.parse(content) : []
        return InlineMarkdownPreparedContent(attributedContent: attributed, tokens: tokens,
            highlightRanges: customLayout ? Self.highlightRangesByToken(in: tokens, query: input.searchHighlightQuery) : [],
            customLayout: customLayout)
    }

    var body: some View {
        Group {
            if let displayFormula {
                MarkdownFormulaText(latex: displayFormula, display: true, isUserMessage: isUserMessage)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .textSelection(.enabled)
            } else if needsCustomInlineLayout {
                InlineMarkdownFlowLayout(spacing: 0, lineSpacing: 2) {
                    if selectionContext != nil || readOnlySelection {
                        ForEach(MessageSelectableInlineGroup.group(inlineTokens)) { group in
                            if group.isProse {
                                if let selectionContext {
                                    MessageSelectableText(content: selectableProse(group.tokens), context: selectionContext)
                                        .multilineTextAlignment(isUserMessage ? .trailing : .leading)
                                        .fixedSize(horizontal: false, vertical: true)
                                } else {
                                    ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(selectableProse(group.tokens)),
                                        identifier: "embed-markdown-prose-\(group.id)")
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            } else if let token = group.tokens.first {
                                tokenView(token, highlightRanges: highlightRanges(forTokenAt: group.id))
                            }
                        }
                    } else {
                        ForEach(Array(inlineTokens.enumerated()), id: \.offset) { index, token in
                            tokenView(token, highlightRanges: highlightRanges(forTokenAt: index))
                        }
                    }
                }
                .textSelection(.disabled)
            } else {
                standardText
                    .multilineTextAlignment(isUserMessage ? .trailing : .leading)
            }
        }
        .onChange(of: InlineMarkdownPreparationInput(content: content, searchHighlightQuery: searchHighlightQuery)) { _, input in
            preparation.update(input)
        }
    }

    @ViewBuilder private var standardText: some View {
        if let selectionContext {
            MessageSelectableText(content: styledAttributedContent, context: selectionContext)
        } else if readOnlySelection {
            ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(styledAttributedContent),
                identifier: "embed-markdown-text")
        } else {
            Text(styledAttributedContent)
                .font(.omP).fontWeight(.medium).lineSpacing(2).textSelection(.enabled)
        }
    }
    private func selectableProse(_ tokens: [InlineMarkdownToken]) -> AttributedString {
        var result = AttributedString()
        for token in tokens {
            guard case .text(let text, let bold) = token else { continue }
            var run = AttributedString(text); run.foregroundColor = textColor(isBold: bold)
            if bold { run.inlinePresentationIntent = .stronglyEmphasized }
            result.append(run)
        }
        SearchTextHighlighter.highlightMatches(in: &result, query: searchHighlightQuery)
        return result
    }

    private var styledAttributedContent: AttributedString {
        var content = attributedContent
        let baseColor = isUserMessage ? Color.fontPrimary : Color.grey100
        content.foregroundColor = baseColor
        for run in content.runs {
            if run.inlinePresentationIntent?.contains(.stronglyEmphasized) == true {
                content[run.range].foregroundColor = Color.markdownBoldText(for: colorScheme)
            }
        }
        SearchTextHighlighter.highlightMatches(in: &content, query: searchHighlightQuery)
        return content
    }

    @ViewBuilder
    private func tokenView(_ token: InlineMarkdownToken, highlightRanges: [NSRange]) -> some View {
        switch token {
        case .text(let text, let isBold):
            Text(highlightedText(text, isBold: isBold, highlightRanges: highlightRanges))
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .fixedSize(horizontal: false, vertical: true)
        case .inlineCode(let text):
            Group {
                if let selectionContext {
                    MessageSelectableText(content: highlightedText(text, isBold: false, highlightRanges: highlightRanges), context: selectionContext, monospace: true)
                } else if readOnlySelection {
                    ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(
                        highlightedText(text, isBold: false, highlightRanges: highlightRanges), pointSize: 14, monospace: true),
                        identifier: "embed-markdown-inline-code")
                } else {
                    Text(highlightedText(text, isBold: false, highlightRanges: highlightRanges))
                        .font(.system(size: 14, design: .monospaced))
                }
            }
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay {
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.grey30, lineWidth: 1)
                }
                .fixedSize()
        case .mention(let mention):
            NativeMentionLabel(mention: mention, highlightRanges: highlightRanges)
        case .math(let latex, let display):
            MarkdownFormulaText(latex: latex, display: display, isUserMessage: isUserMessage)
                .fixedSize(horizontal: false, vertical: true)
        case .wiki(let displayText, let wikiTitle, let isBold):
            WikiInlineChip(
                displayText: displayText,
                wikiTitle: wikiTitle,
                isBold: isBold,
                highlightRanges: highlightRanges
            ) { embed in
                onEmbedTap?(embed)
            }
        case .embed(let displayText, let embedRef, let isBold):
            EmbedInlineChip(
                displayText: displayText,
                embed: resolveEmbed(ref: embedRef),
                fallbackAppId: nil,
                isBold: isBold,
                highlightRanges: highlightRanges
            ) { embed in
                onEmbedTap?(embed)
            }
        case .link(let displayText, let url, let isInternal, let isBold):
            MarkdownLinkChip(
                displayText: displayText,
                urlString: url,
                isInternal: isInternal,
                isBold: isBold,
                highlightRanges: highlightRanges
            )
        }
    }

    private func highlightedText(_ text: String, isBold: Bool, highlightRanges: [NSRange]) -> AttributedString {
        SearchTextHighlighter.attributed(text, ranges: highlightRanges, foregroundColor: textColor(isBold: isBold))
    }

    private func highlightRanges(forTokenAt index: Int) -> [NSRange] {
        guard inlineTokenHighlightRanges.indices.contains(index) else { return [] }
        return inlineTokenHighlightRanges[index]
    }

    private static func highlightRangesByToken(in tokens: [InlineMarkdownToken], query: String?) -> [[NSRange]] {
        guard let query else { return Array(repeating: [NSRange](), count: tokens.count) }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return Array(repeating: [NSRange](), count: tokens.count) }

        let visibleText = tokens.map(\.searchText).joined()
        guard !visibleText.isEmpty else { return Array(repeating: [NSRange](), count: tokens.count) }

        var rangesByToken = Array(repeating: [NSRange](), count: tokens.count)
        var searchStart = visibleText.startIndex
        while let range = visibleText[searchStart...].range(of: trimmed, options: [.caseInsensitive, .diacriticInsensitive]) {
            let match = NSRange(range, in: visibleText)
            appendMatch(match, tokens: tokens, rangesByToken: &rangesByToken)
            searchStart = range.upperBound
        }
        return rangesByToken
    }

    private static func appendMatch(_ match: NSRange, tokens: [InlineMarkdownToken], rangesByToken: inout [[NSRange]]) {
        let matchStart = match.location
        let matchEnd = match.location + match.length
        var tokenStart = 0

        for (index, token) in tokens.enumerated() {
            let tokenLength = token.searchText.utf16.count
            let tokenEnd = tokenStart + tokenLength
            let overlapStart = max(matchStart, tokenStart)
            let overlapEnd = min(matchEnd, tokenEnd)
            if overlapStart < overlapEnd {
                rangesByToken[index].append(NSRange(
                    location: overlapStart - tokenStart,
                    length: overlapEnd - overlapStart
                ))
            }
            tokenStart = tokenEnd
            if tokenStart >= matchEnd { break }
        }
    }

    private func textColor(isBold: Bool) -> Color {
        if isBold {
            return Color.markdownBoldText(for: colorScheme)
        }
        return isUserMessage ? Color.fontPrimary : Color.grey100
    }

    private func resolveEmbed(ref: String) -> EmbedRecord? {
        MarkdownEmbedResolver.resolve(ref, in: allEmbedRecords)
    }
}

private struct MarkdownFormulaText: View {
    let latex: String
    let display: Bool
    let isUserMessage: Bool

    var body: some View {
        Text(MarkdownMathParser.displayText(for: latex))
            .font(display ? .omLg : .omP)
            .fontWeight(.medium)
            .foregroundStyle(isUserMessage ? Color.fontPrimary : Color.grey100)
            .lineSpacing(2)
            .accessibilityLabel(MarkdownMathParser.displayText(for: latex))
            .accessibilityIdentifier(display ? "markdown-math-display" : "markdown-math-inline")
    }
}

enum MarkdownMathParser {
    struct Formula {
        let latex: String
        let display: Bool
        let endIndex: String.Index
    }

    static func containsFormula(in source: String) -> Bool {
        var index = source.startIndex
        while index < source.endIndex {
            if source[index] == "$", formula(in: source, from: index) != nil { return true }
            index = source.index(after: index)
        }
        return false
    }

    static func singleDisplayFormula(in source: String) -> String? {
        let trimmed = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("$$"),
              let formula = formula(in: trimmed, from: trimmed.startIndex),
              formula.display,
              formula.endIndex == trimmed.endIndex else { return nil }
        return formula.latex
    }

    static func formula(in source: String, from start: String.Index) -> Formula? {
        guard source[start] == "$", !isEscaped(source, at: start) else { return nil }
        let afterFirst = source.index(after: start)
        let display = afterFirst < source.endIndex && source[afterFirst] == "$"
        if !display, isCurrencyLikeDollar(source, at: start) { return nil }

        let contentStart = display ? source.index(after: afterFirst) : afterFirst
        var cursor = contentStart
        while cursor < source.endIndex {
            guard source[cursor] == "$", !isEscaped(source, at: cursor) else {
                cursor = source.index(after: cursor)
                continue
            }
            if display {
                let next = source.index(after: cursor)
                guard next < source.endIndex, source[next] == "$" else {
                    cursor = next
                    continue
                }
                let latex = String(source[contentStart..<cursor]).trimmingCharacters(in: .whitespacesAndNewlines)
                guard !latex.isEmpty else { return nil }
                return Formula(latex: latex, display: true, endIndex: source.index(after: next))
            }
            let previous = cursor > source.startIndex ? source[source.index(before: cursor)] : Character("\0")
            let next = source.index(after: cursor)
            if previous != "$", (next == source.endIndex || source[next] != "$"),
               !isCurrencyLikeDollar(source, at: cursor),
               isInlineClosingBoundary(source, after: next) {
                let latex = String(source[contentStart..<cursor]).trimmingCharacters(in: .whitespacesAndNewlines)
                guard !latex.isEmpty, !latex.contains("\n") else { return nil }
                return Formula(latex: latex, display: false, endIndex: next)
            }
            // An inline formula cannot span another unescaped dollar. Treat an
            // invalid first closing candidate as plain text so shell variables
            // cannot absorb a later, valid formula.
            return nil
        }
        return nil
    }

    static func displayText(for latex: String) -> String {
        var value = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        value = replacing(pattern: #"\\frac\{([^{}]+)\}\{([^{}]+)\}"#, in: value, template: "($1)⁄($2)")
        value = replacing(pattern: #"\\sqrt\{([^{}]+)\}"#, in: value, template: "√($1)")
        value = replacing(pattern: #"\\(?:mathrm|mathbf|text|operatorname)\{([^{}]*)\}"#, in: value, template: "$1")
        let symbols = [
            "\\times": "×", "\\cdot": "·", "\\div": "÷", "\\pm": "±",
            "\\leq": "≤", "\\geq": "≥", "\\neq": "≠", "\\approx": "≈",
            "\\infty": "∞", "\\sum": "∑", "\\prod": "∏", "\\int": "∫",
            "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ",
            "\\epsilon": "ε", "\\theta": "θ", "\\lambda": "λ", "\\mu": "μ",
            "\\pi": "π", "\\rho": "ρ", "\\sigma": "σ", "\\phi": "φ", "\\omega": "ω",
            "\\Delta": "Δ", "\\Theta": "Θ", "\\Lambda": "Λ", "\\Pi": "Π", "\\Sigma": "Σ", "\\Omega": "Ω",
            "\\left": "", "\\right": "", "\\,": " ", "\\;": " ", "\\!": ""
        ]
        for (command, symbol) in symbols { value = value.replacingOccurrences(of: command, with: symbol) }
        value = replaceScripts(in: value, marker: "^", mapping: superscripts)
        value = replaceScripts(in: value, marker: "_", mapping: subscripts)
        value = value.replacingOccurrences(of: "{", with: "(").replacingOccurrences(of: "}", with: ")")
        value = replacing(pattern: #"\\([A-Za-z]+)"#, in: value, template: "$1")
        value = replacing(pattern: #"[ \t]+"#, in: value, template: " ")
        return value
    }

    private static let superscripts: [Character: Character] = [
        "0":"⁰", "1":"¹", "2":"²", "3":"³", "4":"⁴", "5":"⁵", "6":"⁶", "7":"⁷", "8":"⁸", "9":"⁹",
        "+":"⁺", "-":"⁻", "=":"⁼", "(":"⁽", ")":"⁾", "n":"ⁿ", "i":"ⁱ"
    ]
    private static let subscripts: [Character: Character] = [
        "0":"₀", "1":"₁", "2":"₂", "3":"₃", "4":"₄", "5":"₅", "6":"₆", "7":"₇", "8":"₈", "9":"₉",
        "+":"₊", "-":"₋", "=":"₌", "(":"₍", ")":"₎", "a":"ₐ", "e":"ₑ", "i":"ᵢ", "o":"ₒ", "r":"ᵣ", "u":"ᵤ", "v":"ᵥ", "x":"ₓ"
    ]

    private static func replaceScripts(in source: String, marker: Character, mapping: [Character: Character]) -> String {
        let characters = Array(source)
        var result = ""
        var index = 0
        while index < characters.count {
            guard characters[index] == marker, index + 1 < characters.count else {
                result.append(characters[index]); index += 1; continue
            }
            var payload: [Character] = []
            if characters[index + 1] == "{", let close = characters[(index + 2)...].firstIndex(of: "}") {
                payload = Array(characters[(index + 2)..<close])
                index = close + 1
            } else {
                payload = [characters[index + 1]]
                index += 2
            }
            if payload.allSatisfy({ mapping[$0] != nil }) {
                result.append(contentsOf: payload.compactMap { mapping[$0] })
            } else {
                result.append(marker)
                result.append("(")
                result.append(contentsOf: payload)
                result.append(")")
            }
        }
        return result
    }

    private static func replacing(pattern: String, in source: String, template: String) -> String {
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return source }
        return expression.stringByReplacingMatches(in: source, range: NSRange(source.startIndex..., in: source), withTemplate: template)
    }

    private static func isEscaped(_ source: String, at index: String.Index) -> Bool {
        guard index > source.startIndex else { return false }
        var cursor = source.index(before: index)
        var slashCount = 0
        while source[cursor] == "\\" {
            slashCount += 1
            guard cursor > source.startIndex else { break }
            cursor = source.index(before: cursor)
        }
        return slashCount % 2 == 1
    }

    private static func isInlineClosingBoundary(_ source: String, after closingDollar: String.Index) -> Bool {
        guard closingDollar < source.endIndex else { return true }
        let next = source[closingDollar]
        return !next.isLetter && !next.isNumber && next != "_"
    }

    private static func isCurrencyLikeDollar(_ source: String, at dollar: String.Index) -> Bool {
        var index = source.index(after: dollar)
        while index < source.endIndex, source[index].isWhitespace { index = source.index(after: index) }
        guard index < source.endIndex, source[index].isNumber else { return false }
        while index < source.endIndex, source[index].isNumber || [",", ".", "_"].contains(source[index]) {
            index = source.index(after: index)
        }
        if index < source.endIndex, source[index].isWhitespace {
            var lookAhead = index
            while lookAhead < source.endIndex, source[lookAhead].isWhitespace { lookAhead = source.index(after: lookAhead) }
            if lookAhead < source.endIndex, ["\\", "^", "_", "{", "}"].contains(source[lookAhead]) { return false }
        }
        guard index < source.endIndex else { return true }
        return source[index].isWhitespace || ")],.;:!?%*~".contains(source[index])
    }
}

enum InlineMarkdownToken: Equatable {
    case mention(NativeMentionPresentation)
    case text(String, isBold: Bool)
    case inlineCode(String)
    case math(String, display: Bool)
    case wiki(displayText: String, wikiTitle: String, isBold: Bool)
    case embed(displayText: String, embedRef: String, isBold: Bool)
    case link(displayText: String, url: String, isInternal: Bool, isBold: Bool)

    @MainActor var searchText: String {
        switch self {
        case .mention(let mention):
            return mention.label
        case .text(let text, _), .inlineCode(let text):
            return text
        case .math(let latex, _):
            return MarkdownMathParser.displayText(for: latex)
        case .wiki(let displayText, _, _),
             .embed(let displayText, _, _),
             .link(let displayText, _, _, _):
            return displayText
        }
    }
}

enum InlineMarkdownTokenizer {
    static func parse(_ source: String) -> [InlineMarkdownToken] {
        var tokens: [InlineMarkdownToken] = []
        var index = source.startIndex
        var isBold = false

        while index < source.endIndex {
            if source[index...].hasPrefix("**") {
                isBold.toggle()
                index = source.index(index, offsetBy: 2)
                continue
            }

            if source[index] == "`",
               let code = parseInlineCode(in: source, from: index) {
                tokens.append(.inlineCode(code.text))
                index = code.endIndex
                continue
            }

            if source[index] == "$",
               let formula = MarkdownMathParser.formula(in: source, from: index) {
                tokens.append(.math(formula.latex, display: formula.display))
                index = formula.endIndex
                continue
            }

            if source[index] == "@",
               (index == source.startIndex || source[source.index(before: index)].isWhitespace),
               let mention = parseMention(in: source, from: index) {
                tokens.append(.mention(mention.value))
                index = mention.endIndex
                continue
            }

            if source[index] == "[", let link = parseSpecialLink(in: source, from: index) {
                switch link.kind {
                case .wiki:
                    tokens.append(.wiki(displayText: link.displayText, wikiTitle: link.target, isBold: isBold))
                case .embed:
                    if link.displayText == "!" {
                        appendText(link.displayText, isBold: isBold, to: &tokens)
                    } else {
                        tokens.append(.embed(
                            displayText: displayText(for: link.displayText, embedRef: link.target),
                            embedRef: link.target,
                            isBold: isBold
                        ))
                    }
                case .link:
                    tokens.append(.link(
                        displayText: link.displayText,
                        url: link.target,
                        isInternal: isInternalLink(link.target),
                        isBold: isBold
                    ))
                }
                index = link.endIndex
                continue
            }

            // An unrecognised '[' or unmatched backtick is literal text.
            // Starting the fallback scan at the same character would return
            // that index again forever and hang the UI thread on stored chats.
            let nextSpecial = nextSpecialIndex(in: source, from: source.index(after: index)) ?? source.endIndex
            appendText(String(source[index..<nextSpecial]), isBold: isBold, to: &tokens)
            index = nextSpecial
        }

        return tokens
    }

    private static func parseMention(in source: String, from start: String.Index) -> (value: NativeMentionPresentation, endIndex: String.Index)? {
        var end = start
        while end < source.endIndex, !source[end].isWhitespace, !",!?;()[]".contains(source[end]) {
            end = source.index(after: end)
        }
        while end > start, source[source.index(before: end)] == "." { end = source.index(before: end) }
        guard let mention = NativeMentionPresentation.parse(String(source[start..<end])) else { return nil }
        return (mention, end)
    }

    private enum SpecialLinkKind {
        case wiki
        case embed
        case link
    }

    private static func parseInlineCode(
        in source: String,
        from start: String.Index
    ) -> (text: String, endIndex: String.Index)? {
        let contentStart = source.index(after: start)
        guard contentStart < source.endIndex,
              let close = source[contentStart...].firstIndex(of: "`") else {
            return nil
        }
        return (String(source[contentStart..<close]), source.index(after: close))
    }

    private static func parseSpecialLink(
        in source: String,
        from start: String.Index
    ) -> (kind: SpecialLinkKind, displayText: String, target: String, endIndex: String.Index)? {
        if start > source.startIndex {
            let previous = source.index(before: start)
            if source[previous] == "!" {
                return nil
            }
        }
        guard let closeBracket = source[start...].firstIndex(of: "]") else { return nil }
        let afterBracket = source.index(after: closeBracket)
        guard afterBracket < source.endIndex else { return nil }

        let kind: SpecialLinkKind
        let prefix: String
        if source[afterBracket...].hasPrefix("(wiki:") {
            kind = .wiki
            prefix = "(wiki:"
        } else if source[afterBracket...].hasPrefix("(embed:") {
            kind = .embed
            prefix = "(embed:"
        } else if source[afterBracket...].hasPrefix("(") {
            kind = .link
            prefix = "("
        } else {
            return nil
        }

        let titleStart = source.index(afterBracket, offsetBy: prefix.count)
        guard let closeParen = closingParenIndex(in: source, from: titleStart) else { return nil }

        let displayStart = source.index(after: start)
        let displayText = String(source[displayStart..<closeBracket])
        let rawTitle = String(source[titleStart..<closeParen])
        let target = rawTitle.removingPercentEncoding ?? rawTitle
        return (kind, displayText, target, source.index(after: closeParen))
    }

    private static func isInternalLink(_ href: String) -> Bool {
        let normalized = href.hasPrefix("/#") ? String(href.dropFirst()) : href
        if normalized.hasPrefix("#") { return true }
        guard let url = URL(string: href),
              let host = url.host?.replacingOccurrences(of: "www.", with: "") else {
            return false
        }
        return (host == "openmates.org" || host == "app.openmates.org" || host == "app.dev.openmates.org")
            && (url.fragment?.isEmpty == false || url.path.isEmpty || url.path == "/")
    }

    private static func closingParenIndex(in source: String, from start: String.Index) -> String.Index? {
        var index = start
        var nestedParens = 0
        while index < source.endIndex {
            let character = source[index]
            if character == "(" {
                nestedParens += 1
            } else if character == ")" {
                if nestedParens == 0 {
                    return index
                }
                nestedParens -= 1
            }
            index = source.index(after: index)
        }
        return nil
    }

    private static func displayText(for text: String, embedRef: String) -> String {
        guard text.count <= 3 else { return text }
        if let match = embedRef.range(of: #"^[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?"#, options: .regularExpression) {
            return String(embedRef[match])
        }
        return embedRef
    }

    private static func nextSpecialIndex(in source: String, from start: String.Index) -> String.Index? {
        var index = start
        while index < source.endIndex {
            if source[index...].hasPrefix("**") || source[index] == "[" || source[index] == "`" || source[index] == "$" || source[index] == "@" {
                return index
            }
            index = source.index(after: index)
        }
        return nil
    }

    private static func appendText(_ text: String, isBold: Bool, to tokens: inout [InlineMarkdownToken]) {
        guard !text.isEmpty else { return }
        var current = ""
        for character in text {
            current.append(character)
            if character.isWhitespace {
                tokens.append(.text(current, isBold: isBold))
                current = ""
            }
        }
        if !current.isEmpty {
            tokens.append(.text(current, isBold: isBold))
        }
    }
}

private struct WikiInlineChip: View {
    let displayText: String
    let wikiTitle: String
    let isBold: Bool
    let highlightRanges: [NSRange]
    let onTap: (EmbedRecord) -> Void
    @Environment(\.colorScheme) private var colorScheme
    @State private var isHovering = false

    var body: some View {
        Button {
            onTap(wikiEmbedRecord)
        } label: {
            chipContent
        }
        .buttonStyle(.plain)
        .fixedSize(horizontal: false, vertical: true)
        .opacity(isHovering ? 0.82 : 1)
        .contentShape(Rectangle())
        .onHover { hovering in
            isHovering = hovering
            #if os(macOS)
            if hovering {
                NSCursor.pointingHand.push()
            } else {
                NSCursor.pop()
            }
            #endif
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(displayText)
    }

    private var chipContent: some View {
        HStack(alignment: .top, spacing: 3) {
            Circle()
                .fill(LinearGradient.appStudy)
                .frame(width: 20, height: 20)
                .alignmentGuide(.top) { $0[.top] - 2.4 }
                .overlay {
                    Icon("study", size: 10)
                        .foregroundStyle(Color.fontButton)
                }

            Text(SearchTextHighlighter.highlighted(displayText, ranges: highlightRanges))
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .foregroundStyle(Color.wikiInlineText(for: colorScheme))
                .underline(isHovering)
        }
    }

    private var wikiEmbedRecord: EmbedRecord {
        WikiArticleIdentity(title: wikiTitle, language: LocalizationManager.shared.currentLanguage.code).inlineRecord()
    }

}

private struct EmbedInlineChip: View {
    let displayText: String
    let embed: EmbedRecord?
    let fallbackAppId: String?
    let isBold: Bool
    let highlightRanges: [NSRange]
    let onTap: (EmbedRecord) -> Void
    @Environment(\.colorScheme) private var colorScheme
    @State private var isHovering = false

    private var appId: String {
        embed?.appId ?? fallbackAppId ?? "web"
    }

    var body: some View {
        if let embed {
            Button {
                onTap(embed)
            } label: {
                chipContent
            }
            .buttonStyle(.plain)
            .fixedSize(horizontal: false, vertical: true)
            .opacity(isHovering ? 0.82 : 1)
            .contentShape(Rectangle())
            .onHover { hovering in
                updateHover(hovering, isClickable: true)
            }
            .accessibilityElement(children: .combine)
            .help(Text(displayText))
            .accessibilityLabel(displayText)
        } else {
            chipContent
                .fixedSize(horizontal: false, vertical: true)
                .opacity(isHovering ? 0.82 : 1)
                .accessibilityElement(children: .combine)
                .accessibilityLabel(displayText)
        }
    }

    private var chipContent: some View {
        HStack(alignment: .top, spacing: 3) {
            Circle()
                .fill(AppIconView.gradient(forAppId: appId))
                .frame(width: 20, height: 20)
                .alignmentGuide(.top) { $0[.top] - 2.4 }
                .overlay {
                    Icon(AppIconView.iconName(forAppId: appId), size: 10)
                        .foregroundStyle(Color.fontButton)
                }

            Text(SearchTextHighlighter.highlighted(displayText, ranges: highlightRanges))
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .foregroundStyle(Color.wikiInlineText(for: colorScheme))
                .underline(isHovering && embed != nil)
        }
    }

    private func updateHover(_ hovering: Bool, isClickable: Bool) {
        isHovering = hovering
        #if os(macOS)
        guard isClickable else { return }
        if hovering {
            NSCursor.pointingHand.push()
        } else {
            NSCursor.pop()
        }
        #endif
    }
}

private struct MarkdownLinkChip: View {
    let displayText: String
    let urlString: String
    let isInternal: Bool
    let isBold: Bool
    let highlightRanges: [NSRange]
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL
    @State private var isHovering = false

    static let internalBadgeIconName = "ai"

    var body: some View {
        if let destinationURL {
            Button {
                openURL(destinationURL)
            } label: {
                chipContent
            }
            .buttonStyle(.plain)
            .fixedSize(horizontal: false, vertical: true)
            .opacity(isHovering ? 0.82 : 1)
            .contentShape(Rectangle())
            .onHover(perform: updateHover)
            .accessibilityElement(children: .combine)
            .help(Text(displayText))
            .accessibilityLabel(displayText)
            .accessibilityValue(isInternal ? Self.internalBadgeIconName : "")
        } else {
            chipContent
                .fixedSize(horizontal: false, vertical: true)
                .opacity(isHovering ? 0.82 : 1)
                .accessibilityElement(children: .combine)
                .accessibilityLabel(displayText)
            .accessibilityValue(isInternal ? Self.internalBadgeIconName : "")
        }
    }

    private var chipContent: some View {
        HStack(alignment: .top, spacing: 3) {
            if isInternal {
                Circle()
                    .fill(LinearGradient.appOpenmates)
                    .frame(width: 20, height: 20)
                .alignmentGuide(.top) { $0[.top] - 2.4 }
                    .overlay {
                        Icon(Self.internalBadgeIconName, size: 10)
                            .foregroundStyle(Color.fontButton)
                    }
            }

            Text(SearchTextHighlighter.highlighted(displayText, ranges: highlightRanges))
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .foregroundStyle(LinearGradient.markdownLinkText(for: colorScheme))
                .underline(isHovering)
        }
    }

    private func updateHover(_ hovering: Bool) {
        isHovering = hovering
        #if os(macOS)
        if hovering {
            NSCursor.pointingHand.push()
        } else {
            NSCursor.pop()
        }
        #endif
    }

    private var destinationURL: URL? {
        if urlString.hasPrefix("#") || urlString.hasPrefix("/#") {
            let fragment = urlString.hasPrefix("/#") ? String(urlString.dropFirst(2)) : String(urlString.dropFirst())
            return URL(string: "https://app.openmates.org/#\(fragment)")
        }
        return URL(string: urlString)
    }
}

/// Geometry-only cache shared by measuring and placing one inline paragraph.
/// A long answer may contain hundreds of text/chip children. Measuring each
/// child twice during both phases made scrolling repeatedly reshape every word.
/// Keep intrinsic sizes until SwiftUI invalidates the children, and only measure
/// a constrained child when that child is wider than the entire line.
struct InlineMarkdownFlowMeasurements {
    struct Arrangement: Equatable {
        let origins: [CGPoint]
        let sizes: [CGSize]
        /// Nil preserves the unspecified proposal used for intrinsic sizes.
        /// A constrained chip can return a narrower width than it was offered;
        /// using that returned width for placement can change its line breaks.
        let proposedWidths: [CGFloat?]
        let size: CGSize
    }

    private struct Proposal: Hashable {
        let width: CGFloat
        let spacing: CGFloat
        let lineSpacing: CGFloat
    }

    let idealSizes: [CGSize]
    private var arrangements: [Proposal: Arrangement] = [:]
    private static let maximumCachedWidths = 3

    init(idealSizes: [CGSize]) {
        self.idealSizes = idealSizes
    }

    mutating func arrangement(
        width: CGFloat?,
        spacing: CGFloat,
        lineSpacing: CGFloat,
        measureConstrained: (Int, CGFloat) -> CGSize
    ) -> Arrangement {
        let maxWidth = width.map { max(0, $0) } ?? .infinity
        let proposal = Proposal(width: maxWidth, spacing: spacing, lineSpacing: lineSpacing)
        if let cached = arrangements[proposal] { return cached }
        var origins: [CGPoint] = []
        var sizes: [CGSize] = []
        var proposedWidths: [CGFloat?] = []
        origins.reserveCapacity(idealSizes.count)
        sizes.reserveCapacity(idealSizes.count)
        proposedWidths.reserveCapacity(idealSizes.count)
        var cursor = CGPoint.zero
        var lineHeight: CGFloat = 0
        var measuredWidth: CGFloat = 0

        for (index, idealSize) in idealSizes.enumerated() {
            if cursor.x > 0, cursor.x + idealSize.width > maxWidth {
                cursor.x = 0
                cursor.y += lineHeight + lineSpacing
                lineHeight = 0
            }
            let availableWidth = maxWidth.isFinite ? max(0, maxWidth - cursor.x) : idealSize.width
            let proposedWidth = min(idealSize.width, availableWidth)
            let isConstrained = proposedWidth < idealSize.width
            let size = isConstrained
                ? measureConstrained(index, proposedWidth)
                : idealSize

            origins.append(cursor)
            sizes.append(size)
            proposedWidths.append(isConstrained ? proposedWidth : nil)
            cursor.x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            measuredWidth = max(measuredWidth, cursor.x)
        }

        let arrangement = Arrangement(
            origins: origins,
            sizes: sizes,
            proposedWidths: proposedWidths,
            size: CGSize(width: min(measuredWidth, maxWidth), height: cursor.y + lineHeight)
        )
        // SwiftUI commonly probes zero, unconstrained, and actual widths. Keep
        // this per-paragraph cache bounded while the window is being resized.
        if arrangements.count >= Self.maximumCachedWidths { arrangements.removeAll(keepingCapacity: true) }
        arrangements[proposal] = arrangement
        return arrangement
    }
}

private struct InlineMarkdownFlowLayout: Layout {
    let spacing: CGFloat
    let lineSpacing: CGFloat

    func makeCache(subviews: Subviews) -> InlineMarkdownFlowMeasurements {
        InlineMarkdownFlowMeasurements(idealSizes: subviews.map { $0.sizeThatFits(.unspecified) })
    }

    func updateCache(_ cache: inout InlineMarkdownFlowMeasurements, subviews: Subviews) {
        // Font, content, and chip changes invalidate the intrinsic dimensions.
        cache = makeCache(subviews: subviews)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout InlineMarkdownFlowMeasurements) -> CGSize {
        arrangement(width: proposal.width, subviews: subviews, cache: &cache).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout InlineMarkdownFlowMeasurements) {
        // `proposal` is the same parent proposal that produced `bounds.size`.
        // Bounds can be narrower than that proposal because this flow hugs its
        // content. Rewrapping at bounds.width changes the measured row heights
        // during placement, which can destabilize the enclosing lazy transcript.
        let arrangement = arrangement(width: proposal.width, subviews: subviews, cache: &cache)
        for (index, origin) in arrangement.origins.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                anchor: .topLeading,
                proposal: ProposedViewSize(width: arrangement.proposedWidths[index], height: nil)
            )
        }
    }

    private func arrangement(width: CGFloat?, subviews: Subviews, cache: inout InlineMarkdownFlowMeasurements) -> InlineMarkdownFlowMeasurements.Arrangement {
        cache.arrangement(width: width, spacing: spacing, lineSpacing: lineSpacing) { index, proposedWidth in
            subviews[index].sizeThatFits(ProposedViewSize(width: proposedWidth, height: nil))
        }
    }
}

// MARK: - Code block with syntax highlighting and copy button

struct CodeBlockView: View {
    let language: String?
    let code: String
    let searchHighlightQuery: String?
    @State private var copied = false
    @Environment(\.readOnlyTextSelection) private var readOnlySelection

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header bar with language label and copy button
            HStack {
                if let language, !language.isEmpty {
                    Text(language)
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(Color.fontTertiary)
                }
                Spacer()
                Button {
                    copyCode()
                } label: {
                    HStack(spacing: 4) {
                        Icon(copied ? "check" : "copy", size: 11)
                        Text(copied ? AppStrings.copied : AppStrings.copy)
                            .font(.omMicro)
                    }
                    .foregroundStyle(Color.fontSecondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(Color.grey20)

            // Code content
            ScrollView(.horizontal, showsIndicators: false) {
                Group {
                    if readOnlySelection {
                        ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(highlightedCode,
                            pointSize: 13, monospace: true), identifier: "embed-markdown-code", wrapsText: false)
                            .fixedSize(horizontal: true, vertical: true)
                    } else {
                        Text(highlightedCode)
                            .font(.system(size: 13, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
                .padding(.spacing3)
            }
            .background(Color.grey10)
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay(
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(Color.grey20, lineWidth: 1)
        )
    }

    private var highlightedCode: AttributedString {
        // Apply keyword-level syntax coloring based on language hint.
        // This is a lightweight approach — full TreeSitter would be overkill for a chat app.
        var result = AttributedString(code)

        guard let language = language?.lowercased() else {
            SearchTextHighlighter.highlightMatches(in: &result, query: searchHighlightQuery)
            return result
        }

        let keywords: [String]
        switch language {
        case "swift":
            keywords = ["func", "let", "var", "struct", "class", "enum", "import", "return",
                         "if", "else", "guard", "switch", "case", "for", "while", "do", "try",
                         "catch", "throw", "async", "await", "private", "public", "static",
                         "protocol", "extension", "init", "self", "true", "false", "nil"]
        case "python", "py":
            keywords = ["def", "class", "import", "from", "return", "if", "elif", "else",
                         "for", "while", "try", "except", "finally", "with", "as", "yield",
                         "async", "await", "True", "False", "None", "self", "lambda", "pass",
                         "raise", "in", "not", "and", "or", "is"]
        case "javascript", "js", "typescript", "ts", "jsx", "tsx":
            keywords = ["function", "const", "let", "var", "return", "if", "else", "for",
                         "while", "do", "switch", "case", "break", "continue", "class",
                         "import", "export", "from", "async", "await", "try", "catch",
                         "throw", "new", "this", "true", "false", "null", "undefined",
                         "interface", "type", "enum"]
        case "html", "xml", "svelte":
            keywords = ["div", "span", "p", "a", "img", "script", "style", "head", "body",
                         "html", "link", "meta", "title", "section", "header", "footer",
                         "nav", "main", "article", "h1", "h2", "h3", "h4", "h5", "h6"]
        case "css", "scss":
            keywords = ["display", "position", "color", "background", "margin", "padding",
                         "border", "font", "width", "height", "flex", "grid", "none", "auto",
                         "inherit", "important"]
        case "sql":
            keywords = ["SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE",
                         "TABLE", "ALTER", "DROP", "JOIN", "LEFT", "RIGHT", "INNER", "ON",
                         "AND", "OR", "NOT", "IN", "NULL", "ORDER", "BY", "GROUP", "HAVING",
                         "LIMIT", "AS", "INTO", "VALUES", "SET"]
        case "bash", "sh", "shell", "zsh":
            keywords = ["if", "then", "else", "elif", "fi", "for", "while", "do", "done",
                         "case", "esac", "function", "return", "exit", "echo", "export",
                         "source", "local", "readonly", "declare"]
        case "rust", "rs":
            keywords = ["fn", "let", "mut", "struct", "enum", "impl", "trait", "pub", "use",
                         "mod", "return", "if", "else", "match", "for", "while", "loop",
                         "async", "await", "self", "Self", "true", "false", "None", "Some",
                         "Ok", "Err", "where", "type", "const", "static", "unsafe", "move"]
        case "go", "golang":
            keywords = ["func", "var", "const", "type", "struct", "interface", "return",
                         "if", "else", "for", "range", "switch", "case", "default", "break",
                         "continue", "go", "defer", "chan", "select", "import", "package",
                         "map", "nil", "true", "false", "make", "new", "append"]
        default:
            keywords = []
        }

        // Highlight keywords with a word-boundary check
        for keyword in keywords {
            var searchRange = result.startIndex..<result.endIndex
            while let range = result[searchRange].range(of: keyword) {
                // Check word boundaries
                let isWordStart = range.lowerBound == result.startIndex
                    || !result.characters[result.characters.index(before: range.lowerBound)].isLetter
                let isWordEnd = range.upperBound == result.endIndex
                    || !result.characters[range.upperBound].isLetter

                if isWordStart && isWordEnd {
                    result[range].foregroundColor = .purple
                }
                searchRange = range.upperBound..<result.endIndex
            }
        }

        // Highlight strings (simple double-quote detection)
        highlightPattern(&result, pattern: #""[^"]*""#, color: .green)
        // Highlight single-line comments
        highlightPattern(&result, pattern: #"//[^\n]*"#, color: .gray)
        highlightPattern(&result, pattern: #"#[^\n]*"#, color: .gray)

        SearchTextHighlighter.highlightMatches(in: &result, query: searchHighlightQuery)

        return result
    }

    private func highlightPattern(_ text: inout AttributedString, pattern: String, color: Color) {
        let plainString = String(text.characters)
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return }
        let matches = regex.matches(in: plainString, range: NSRange(plainString.startIndex..., in: plainString))

        for match in matches {
            guard let range = Range(match.range, in: plainString) else { continue }
            let attrStart = AttributedString.Index(range.lowerBound, within: text)
            let attrEnd = AttributedString.Index(range.upperBound, within: text)
            if let start = attrStart, let end = attrEnd {
                text[start..<end].foregroundColor = color
            }
        }
    }

    private func copyCode() {
        #if os(iOS)
        UIPasteboard.general.string = code
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        #endif
        copied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            copied = false
        }
    }
}

// MARK: - Blockquote

struct BlockquoteView: View {
    let text: String
    let isUserMessage: Bool
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: ((EmbedRecord) -> Void)?
    let searchHighlightQuery: String?

    private var sourceQuote: (quote: String, embed: EmbedRecord)? {
        let pattern = #"\[([^\]]+)\]\(embed:([^)]+)\)"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let quoteRange = Range(match.range(at: 1), in: text),
              let refRange = Range(match.range(at: 2), in: text) else { return nil }
        let ref = normalizedEmbedRef(String(text[refRange]))
        guard let embed = resolveSourceEmbed(ref) else { return nil }
        return (String(text[quoteRange]), embed)
    }

    var body: some View {
        if let sourceQuote {
            SourceQuoteView(
                quote: sourceQuote.quote,
                embed: sourceQuote.embed,
                onEmbedTap: onEmbedTap,
                searchHighlightQuery: searchHighlightQuery
            )
        } else {
            HStack(spacing: .spacing3) {
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(Color.buttonPrimary.opacity(0.5))
                    .frame(width: 3)

                InlineMarkdownText(
                    content: text,
                    isUserMessage: isUserMessage,
                    allEmbedRecords: allEmbedRecords,
                    onEmbedTap: onEmbedTap,
                    searchHighlightQuery: searchHighlightQuery
                )
                    .opacity(0.85)
            }
            .padding(.vertical, .spacing1)
        }
    }

    private func resolveSourceEmbed(_ ref: String) -> EmbedRecord? {
        if let exact = allEmbedRecords[ref] {
            return exact
        }
        return allEmbedRecords.values.first { record in
            if record.id == ref || record.id.hasSuffix(ref) {
                return true
            }
            let raw = record.rawData ?? [:]
            let refs = [
                firstString(in: raw, keys: ["embed_ref", "content_ref", "contentRef", "ref"]),
                firstString(in: raw, keys: ["source_ref", "sourceRef"])
            ].compactMap { $0?.replacingOccurrences(of: "embed:", with: "") }
            return refs.contains(ref)
        }
    }

    private func normalizedEmbedRef(_ ref: String) -> String {
        var cleaned = ref.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.hasPrefix("embed:") {
            cleaned = String(cleaned.dropFirst(6))
        }
        return cleaned
    }

    private func firstString(in data: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = data[key]?.value as? String, !value.isEmpty { return value }
            if key == "meta_url_favicon",
               let metaURL = data["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }

    private func host(from value: String?) -> String? {
        guard let value, let url = URL(string: value), let host = url.host else { return nil }
        return host.replacingOccurrences(of: "www.", with: "")
    }
}

private struct SourceQuoteView: View {
    let quote: String
    let embed: EmbedRecord
    let onEmbedTap: ((EmbedRecord) -> Void)?
    let searchHighlightQuery: String?
    @Environment(\.sourceQuoteOpenAction) private var openSourceQuote

    var body: some View {
        Button {
            if let openSourceQuote { openSourceQuote(embed, quote) }
            else { onEmbedTap?(embed) }
        } label: {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(SearchTextHighlighter.attributed(
                    "\"\(quote)\"",
                    query: searchHighlightQuery,
                    foregroundColor: Color.fontPrimary
                ))
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .italic()
                    .lineLimit(5)
                    .multilineTextAlignment(.leading)

                HStack(spacing: .spacing3) {
                    AppIconView(appId: embed.appId ?? EmbedType(rawValue: embed.type)?.appId ?? "web", size: 18)
                    Text(sourceLabel)
                        .font(.omMicro)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey60)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .background(Color.grey25)
            .overlay(alignment: .leading) {
                Rectangle()
                    .fill(AppIconView.gradient(forAppId: embed.appId ?? EmbedType(rawValue: embed.type)?.appId ?? "web"))
                    .frame(width: 3)
            }
            .clipShape(UnevenRoundedRectangle(topLeadingRadius: 0, bottomLeadingRadius: 0, bottomTrailingRadius: .radius3, topTrailingRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("source-quote-block")
        .accessibilityAddTraits(.isButton)
    }

    private var sourceLabel: String {
        let raw = embed.rawData ?? [:]
        for key in ["source", "source_domain"] {
            if let value = raw[key]?.value as? String, !value.isEmpty { return value }
        }
        for key in ["source_page_url", "url"] {
            if let value = raw[key]?.value as? String,
               let host = URL(string: value)?.host,
               !host.isEmpty {
                return host
            }
        }
        return EmbedType(rawValue: embed.type)?.displayName ?? embed.type
    }
}

// MARK: - Header

struct HeaderView: View {
    let level: Int
    let text: String
    let isUserMessage: Bool
    let searchHighlightQuery: String?

    var body: some View {
        Text(SearchTextHighlighter.attributed(
            text,
            query: searchHighlightQuery,
            foregroundColor: isUserMessage ? Color.fontPrimary : Color.grey100
        ))
            .font(headerFont)
            .fontWeight(.semibold)
            .padding(.top, level <= 2 ? .spacing3 : .spacing2)
            .textSelection(.enabled)
    }

    private var headerFont: Font {
        switch level {
        case 1: return .omXl
        case 2: return .omH3
        case 3: return .omLg
        default: return .omSmall
        }
    }
}

// MARK: - List

struct ListBlockView: View {
    let items: [String]
    let ordered: Bool
    let isUserMessage: Bool
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: ((EmbedRecord) -> Void)?
    let searchHighlightQuery: String?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                HStack(alignment: .top, spacing: .spacing2) {
                    Text(ordered ? "\(index + 1)." : "•")
                        .font(.omP)
                        .foregroundStyle(isUserMessage ? Color.fontPrimary : Color.fontSecondary)
                        .frame(width: ordered ? 24 : 12, alignment: .trailing)

                    InlineMarkdownText(
                        content: item,
                        isUserMessage: isUserMessage,
                        allEmbedRecords: allEmbedRecords,
                        onEmbedTap: onEmbedTap,
                        searchHighlightQuery: searchHighlightQuery
                    )
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .layoutPriority(1)
                }
            }
        }
        .padding(.leading, .spacing2)
    }
}

// MARK: - Table

struct TableBlockView: View {
    let headers: [String]
    let rows: [[String]]
    let isUserMessage: Bool
    let searchHighlightQuery: String?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                // Header row
                HStack(spacing: 0) {
                    ForEach(Array(headers.enumerated()), id: \.offset) { _, header in
                        Text(SearchTextHighlighter.attributed(
                            header,
                            query: searchHighlightQuery,
                            foregroundColor: Color.fontPrimary
                        ))
                            .font(.omSmall)
                            .fontWeight(.semibold)
                            .padding(.horizontal, .spacing3)
                            .padding(.vertical, .spacing2)
                            .frame(minWidth: 80, alignment: .leading)
                    }
                }
                .background(Color.grey10.opacity(0.5))

                Divider()

                // Data rows
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(spacing: 0) {
                        ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                            Text(SearchTextHighlighter.attributed(
                                cell,
                                query: searchHighlightQuery,
                                foregroundColor: Color.fontPrimary
                            ))
                                .font(.omSmall)
                                .padding(.horizontal, .spacing3)
                                .padding(.vertical, .spacing2)
                                .frame(minWidth: 80, alignment: .leading)
                        }
                    }
                    Divider()
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay(
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(Color.grey20, lineWidth: 1)
        )
    }
}

// MARK: - Demo placeholder groups

enum DemoGroupKind: Equatable {
    case exampleChats
    case developerExampleChats
    case apps
    case developerApps
    case skills
    case developerSkills
    case focusModes
    case developerFocusModes
    case memories
    case developerMemories
    case aiModels
}

private struct DemoRichGroupItem: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let appId: String
    let icon: String
}

@MainActor
private struct DemoRichGroupView: View {
    let kind: DemoGroupKind
    let onOpenPublicChat: ((String) -> Void)?

    private var items: [DemoRichGroupItem] {
        switch kind {
        case .exampleChats:
            return [
                .init(id: "example-gigantic-airplanes", title: AppStrings.exampleGiganticAirplanesTitle, subtitle: AppStrings.exampleGiganticAirplanesSummary, appId: "general_knowledge", icon: "plane"),
                .init(id: "example-artemis-ii-mission", title: AppStrings.exampleArtemisMissionTitle, subtitle: AppStrings.exampleArtemisMissionSummary, appId: "science", icon: "rocket"),
                .init(id: "example-beautiful-single-page-html", title: AppStrings.exampleBeautifulHtmlTitle, subtitle: AppStrings.exampleBeautifulHtmlSummary, appId: "software_development", icon: "code"),
                .init(id: "example-flights-berlin-bangkok", title: AppStrings.exampleFlightsBerlinBangkokTitle, subtitle: AppStrings.exampleFlightsBerlinBangkokSummary, appId: "general_knowledge", icon: "plane"),
                .init(id: "example-eu-chat-control-law", title: AppStrings.exampleEuChatControlTitle, subtitle: AppStrings.exampleEuChatControlSummary, appId: "legal_law", icon: "shield"),
                .init(id: "example-creativity-drawing-meetups-berlin", title: AppStrings.exampleCreativityDrawingTitle, subtitle: AppStrings.exampleCreativityDrawingSummary, appId: "general_knowledge", icon: "pencil")
            ]
        case .developerExampleChats:
            return [
                .init(id: "example-beautiful-single-page-html", title: AppStrings.exampleBeautifulHtmlTitle, subtitle: AppStrings.exampleBeautifulHtmlSummary, appId: "software_development", icon: "code")
            ]
        case .apps:
            return [
                translatedItem(id: "web", titleKey: "apps.web", subtitleKey: "apps.web.description", appId: "web", icon: "web"),
                translatedItem(id: "travel", titleKey: "apps.travel", subtitleKey: "apps.travel.description", appId: "travel", icon: "travel"),
                translatedItem(id: "videos", titleKey: "apps.videos", subtitleKey: "apps.videos.description", appId: "videos", icon: "videos"),
                translatedItem(id: "maps", titleKey: "apps.maps", subtitleKey: "apps.maps.description", appId: "maps", icon: "maps")
            ]
        case .developerApps:
            return [
                translatedItem(id: "code", titleKey: "apps.code", subtitleKey: "apps.code.description", appId: "code", icon: "code")
            ]
        case .skills:
            return [
                translatedItem(id: "web-search", titleKey: "app_skills.web.search", subtitleKey: "app_skills.web.search.description", appId: "web", icon: "search"),
                translatedItem(id: "videos-search", titleKey: "app_skills.videos.search", subtitleKey: "app_skills.videos.search.description", appId: "videos", icon: "videos"),
                translatedItem(id: "maps-search", titleKey: "app_skills.maps.search", subtitleKey: "app_skills.maps.search.description", appId: "maps", icon: "maps"),
                translatedItem(id: "travel-connections", titleKey: "app_skills.travel.search_connections", subtitleKey: "app_skills.travel.search_connections.description", appId: "travel", icon: "travel")
            ]
        case .developerSkills:
            return [
                translatedItem(id: "code-docs", titleKey: "app_skills.code.get_docs", subtitleKey: "app_skills.code.get_docs.description", appId: "code", icon: "code")
            ]
        case .focusModes:
            return [
                translatedItem(id: "research", titleKey: "app_focus_modes.web.research", subtitleKey: "app_focus_modes.web.research.description", appId: "web", icon: "insight"),
                translatedItem(id: "learning", titleKey: "app_focus_modes.code.learn_new_tech", subtitleKey: "app_focus_modes.code.learn_new_tech.description", appId: "study", icon: "books"),
                translatedItem(id: "planning", titleKey: "app_focus_modes.code.plan_project", subtitleKey: "app_focus_modes.code.plan_project.description", appId: "travel", icon: "travel")
            ]
        case .developerFocusModes:
            return [
                translatedItem(id: "code-review", titleKey: "app_focus_modes.code.test_git_repo", subtitleKey: "app_focus_modes.code.test_git_repo.description", appId: "code", icon: "code")
            ]
        case .memories:
            return [
                .init(id: "interests", title: AppStrings.memoriesTitle, subtitle: AppStrings.memoriesDescription, appId: "messages", icon: "insight"),
                .init(id: "settings", title: AppStrings.settingsMemories, subtitle: AppStrings.encryptionNotice, appId: "secrets", icon: "settings")
            ]
        case .developerMemories:
            return [
                .init(id: "developer-memory", title: AppStrings.memoriesTitle, subtitle: AppStrings.memoriesDescription, appId: "code", icon: "code")
            ]
        case .aiModels:
            return [
                .init(id: "auto", title: AppStrings.autoSelectModel, subtitle: AppStrings.autoSelectDescription, appId: "ai", icon: "ai"),
                .init(id: "simple", title: AppStrings.simpleRequests, subtitle: AppStrings.availableModels, appId: "ai", icon: "ai"),
                .init(id: "complex", title: AppStrings.complexRequests, subtitle: AppStrings.availableProviders, appId: "ai", icon: "ai")
            ]
        }
    }

    var body: some View {
        if !items.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing6) {
                    ForEach(items) { item in
                        DemoRichCard(item: item, style: cardStyle, onOpenPublicChat: onOpenPublicChat)
                    }
                }
                .padding(.vertical, .spacing2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing4)
        }
    }

    private var cardStyle: DemoRichCard.Style {
        switch kind {
        case .exampleChats, .developerExampleChats:
            return .large
        default:
            return .compact
        }
    }

    private func translatedItem(
        id: String,
        titleKey: String,
        subtitleKey: String,
        appId: String,
        icon: String
    ) -> DemoRichGroupItem {
        let title = AppStrings.localized(titleKey)
        let subtitle = AppStrings.localized(subtitleKey)
        return DemoRichGroupItem(
            id: id,
            title: title.hasPrefix("[T:") ? id.replacingOccurrences(of: "-", with: " ").capitalized : title,
            subtitle: subtitle.hasPrefix("[T:") ? "" : subtitle,
            appId: appId,
            icon: icon
        )
    }
}

@MainActor
private struct DemoRichCard: View {
    enum Style { case large, compact }

    let item: DemoRichGroupItem
    let style: Style
    let onOpenPublicChat: ((String) -> Void)?
    @State private var isHovering = false
    @State private var hoverX: CGFloat = 0
    @State private var hoverY: CGFloat = 0

    private var width: CGFloat { style == .large ? 300 : 256 }
    private var height: CGFloat { style == .large ? 200 : 148 }
    private var canOpenPublicChat: Bool {
        onOpenPublicChat != nil &&
        (item.id.hasPrefix("example-") || item.id.hasPrefix("demo-") ||
         item.id.hasPrefix("legal-") || item.id.hasPrefix("announcements-"))
    }

    var body: some View {
        Group {
            if canOpenPublicChat {
                Button {
                    onOpenPublicChat?(item.id)
                } label: {
                    cardContent
                }
                .buttonStyle(.plain)
                .accessibilityHint(AppStrings.openChat)
            } else {
                cardContent
            }
        }
        .accessibilityElement(children: .combine)
        .help(Text(item.title))
        .accessibilityLabel(item.title)
    }

    private var cardContent: some View {
        ZStack {
            CategoryMapping.gradient(for: item.appId)

            decorativeIcon(alignment: .bottomLeading, xOffset: -10, rotation: -15)
            decorativeIcon(alignment: .bottomTrailing, xOffset: 10, rotation: 15)

            VStack(spacing: .spacing4) {
                cardIcon(size: style == .large ? 34 : 28)
                    .foregroundStyle(.white)

                Text(item.title)
                    .font(style == .large ? .omP : .omSmall)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .minimumScaleFactor(0.78)

                if !item.subtitle.isEmpty {
                    Text(item.subtitle)
                        .font(.omXxs)
                        .fontWeight(.medium)
                        .foregroundStyle(.white.opacity(0.88))
                        .multilineTextAlignment(.center)
                        .lineLimit(style == .large ? 4 : 3)
                }
            }
            .padding(.horizontal, .spacing10)
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 1)
        }
        .frame(width: width, height: height)
        .clipShape(RoundedRectangle(cornerRadius: style == .large ? 30 : .radius5))
        .shadow(color: .black.opacity(0.18), radius: 12, x: 0, y: 6)
        .rotation3DEffect(.degrees(isHovering ? -hoverY * 3 : 0), axis: (x: 1, y: 0, z: 0), perspective: 1 / 800)
        .rotation3DEffect(.degrees(isHovering ? hoverX * 3 : 0), axis: (x: 0, y: 1, z: 0), perspective: 1 / 800)
        .scaleEffect(isHovering ? 0.985 : 1)
        .background(hoverTracker)
        .animation(.easeOut(duration: 0.15), value: isHovering)
    }

    private var hoverTracker: some View {
        GeometryReader { proxy in
            Color.clear
                #if os(macOS)
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let location):
                        let width = max(proxy.size.width, 1)
                        let height = max(proxy.size.height, 1)
                        hoverX = ((location.x / width) - 0.5) * 2
                        hoverY = ((location.y / height) - 0.5) * 2
                        isHovering = true
                    case .ended:
                        isHovering = false
                        hoverX = 0
                        hoverY = 0
                    }
                }
                #endif
        }
    }

    private func decorativeIcon(alignment: Alignment, xOffset: CGFloat, rotation: Double) -> some View {
        cardIcon(size: style == .large ? 80 : 64)
            .foregroundStyle(.white.opacity(0.24))
            .rotationEffect(.degrees(rotation))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: alignment)
            .offset(x: xOffset, y: 14)
    }

    @ViewBuilder
    private func cardIcon(size: CGFloat) -> some View {
        if canOpenPublicChat {
            LucideNativeIcon(item.icon, size: size)
        } else {
            Icon(item.icon, size: size)
        }
    }
}
