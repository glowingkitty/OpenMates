// Rich markdown renderer — full block-level rendering for AI chat messages.
// Handles fenced code blocks with syntax highlighting, blockquotes, headers,
// tables, horizontal rules, and lists. Falls back to Apple's built-in
// AttributedString for inline formatting (bold, italic, links, inline code).
// Replaces the previous inline-only MarkdownText view for assistant messages.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/DemoMessageContent.svelte
//          frontend/packages/ui/src/components/embeds/ExampleChatsGroup.svelte
//          frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
// CSS:     ChatEmbedPreview.svelte <style>
//          .chat-embed-card { width:300px; height:200px; border-radius:30px;
//            box-shadow:0 8px 24px rgba(0,0,0,.16),0 2px 6px rgba(0,0,0,.1) }
//          .card-icon { width:32px; height:32px }
//          .card-title { font-size:var(--font-size-p); font-weight:700 }
//          .card-summary { font-size:var(--font-size-xxs); font-weight:500 }
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

// MARK: - Block parser

/// Parses raw markdown text into a sequence of typed blocks for rendering.
/// Handles fenced code blocks (```lang), blockquotes (>), headers (#),
/// horizontal rules (---), and unordered/ordered lists. Everything else
/// is treated as a paragraph with inline markdown formatting.
enum MarkdownBlock {
    case paragraph(String)
    case codeBlock(language: String?, code: String)
    case blockquote(String)
    case header(level: Int, text: String)
    case horizontalRule
    case unorderedList([String])
    case orderedList([String])
    case table(headers: [String], rows: [[String]])
    case demoGroup(DemoGroupKind)
    case embedGroup([String])

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
        "[[ai_models_group]]": .aiModels,
        "[[for_developers_embed]]": .forDevelopers
    ]

    static func parse(_ text: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        let lines = text.components(separatedBy: "\n")
        var i = 0

        while i < lines.count {
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if let group = demoPlaceholders[trimmed] {
                blocks.append(.demoGroup(group))
                i += 1
                continue
            }

            if let embedId = parseEmbedPlaceholder(trimmed) {
                var ids = [embedId]
                i += 1
                while i < lines.count {
                    let nextTrimmed = lines[i].trimmingCharacters(in: .whitespaces)
                    if nextTrimmed.isEmpty {
                        i += 1
                        continue
                    }
                    guard let nextId = parseEmbedPlaceholder(nextTrimmed) else { break }
                    ids.append(nextId)
                    i += 1
                }
                blocks.append(.embedGroup(ids))
                continue
            }

            // Fenced code block
            if trimmed.hasPrefix("```") {
                let lang = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                let language = lang.isEmpty ? nil : lang
                var codeLines: [String] = []
                i += 1
                while i < lines.count {
                    if lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                        i += 1
                        break
                    }
                    codeLines.append(lines[i])
                    i += 1
                }
                blocks.append(.codeBlock(language: language, code: codeLines.joined(separator: "\n")))
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
                if pTrimmed.isEmpty || pTrimmed.hasPrefix("```") || pTrimmed.hasPrefix("#")
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

        return blocks
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

    private static func parseEmbedPlaceholder(_ line: String) -> String? {
        guard line.hasPrefix("[[embed:"), line.hasSuffix("]]") else { return nil }
        let start = line.index(line.startIndex, offsetBy: 8)
        let end = line.index(line.endIndex, offsetBy: -2)
        guard start < end else { return nil }
        return String(line[start..<end])
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
    let isUserMessage: Bool
    let onOpenPublicChat: ((String) -> Void)?
    let embedLookup: [String: EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: ((EmbedRecord) -> Void)?
    private let blocks: [MarkdownBlock]

    init(
        content: String,
        isUserMessage: Bool,
        onOpenPublicChat: ((String) -> Void)? = nil,
        embedLookup: [String: EmbedRecord] = [:],
        allEmbedRecords: [String: EmbedRecord] = [:],
        onEmbedTap: ((EmbedRecord) -> Void)? = nil
    ) {
        self.content = content
        self.isUserMessage = isUserMessage
        self.onOpenPublicChat = onOpenPublicChat
        self.embedLookup = embedLookup
        self.allEmbedRecords = allEmbedRecords
        self.onEmbedTap = onEmbedTap
        self.blocks = MarkdownParser.parse(content)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                blockView(for: block)
            }
        }
    }

    @ViewBuilder
    private func blockView(for block: MarkdownBlock) -> some View {
        switch block {
        case .paragraph(let text):
            InlineMarkdownText(content: text, isUserMessage: isUserMessage)

        case .codeBlock(let language, let code):
            CodeBlockView(language: language, code: code)

        case .blockquote(let text):
            BlockquoteView(text: text, isUserMessage: isUserMessage)

        case .header(let level, let text):
            HeaderView(level: level, text: text, isUserMessage: isUserMessage)

        case .horizontalRule:
            Divider()
                .padding(.vertical, .spacing2)

        case .unorderedList(let items):
            ListBlockView(items: items, ordered: false, isUserMessage: isUserMessage)

        case .orderedList(let items):
            ListBlockView(items: items, ordered: true, isUserMessage: isUserMessage)

        case .table(let headers, let rows):
            TableBlockView(headers: headers, rows: rows, isUserMessage: isUserMessage)

        case .demoGroup(let kind):
            DemoRichGroupView(kind: kind, onOpenPublicChat: onOpenPublicChat)

        case .embedGroup(let ids):
            let embeds = ids.compactMap { embedLookup[$0] }
            if !embeds.isEmpty {
                let groups = EmbedGrouper.group(embeds)
                ForEach(groups) { group in
                    GroupedEmbedView(group: group, allEmbedRecords: allEmbedRecords) { embed in
                        onEmbedTap?(embed)
                    }
                }
            }
        }
    }
}

// MARK: - Inline markdown (paragraphs, list items)

struct InlineMarkdownText: View {
    let content: String
    let isUserMessage: Bool
    private let attributedContent: AttributedString

    init(content: String, isUserMessage: Bool) {
        self.content = content
        self.isUserMessage = isUserMessage
        self.attributedContent = (try? AttributedString(markdown: content, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(content)
    }

    var body: some View {
        Text(attributedContent)
            .font(.omP)
            .fontWeight(.medium)
            .foregroundStyle(isUserMessage ? Color.fontButton : Color.grey100)
            .lineSpacing(2)
            .textSelection(.enabled)
    }
}

// MARK: - Code block with syntax highlighting and copy button

struct CodeBlockView: View {
    let language: String?
    let code: String
    @State private var copied = false

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
                Text(highlightedCode)
                    .font(.system(size: 13, design: .monospaced))
                    .textSelection(.enabled)
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

        guard let language = language?.lowercased() else { return result }

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

    var body: some View {
        HStack(spacing: .spacing3) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(Color.buttonPrimary.opacity(0.5))
                .frame(width: 3)

            InlineMarkdownText(content: text, isUserMessage: isUserMessage)
                .opacity(0.85)
        }
        .padding(.vertical, .spacing1)
    }
}

// MARK: - Header

struct HeaderView: View {
    let level: Int
    let text: String
    let isUserMessage: Bool

    var body: some View {
        Text(text)
            .font(headerFont)
            .fontWeight(.semibold)
            .foregroundStyle(isUserMessage ? Color.fontButton : Color.grey100)
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

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                HStack(alignment: .top, spacing: .spacing2) {
                    Text(ordered ? "\(index + 1)." : "•")
                        .font(.omP)
                        .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontSecondary)
                        .frame(width: ordered ? 24 : 12, alignment: .trailing)

                    InlineMarkdownText(content: item, isUserMessage: isUserMessage)
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

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                // Header row
                HStack(spacing: 0) {
                    ForEach(Array(headers.enumerated()), id: \.offset) { _, header in
                        Text(header)
                            .font(.omSmall)
                            .fontWeight(.semibold)
                            .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontPrimary)
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
                            Text(cell)
                                .font(.omSmall)
                                .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontPrimary)
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

enum DemoGroupKind {
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
    case forDevelopers
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
        case .forDevelopers:
            return [
                .init(id: "demo-for-developers", title: AppStrings.demoForDevelopersTitle, subtitle: AppStrings.demoForDevelopersDescription, appId: "code", icon: "code")
            ]
        }
    }

    var body: some View {
        if !items.isEmpty {
            ScrollView(.horizontal, showsIndicators: true) {
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
                    .font(style == .large ? .omH3 : .omH4)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .minimumScaleFactor(0.78)

                if !item.subtitle.isEmpty {
                    Text(item.subtitle)
                        .font(.omXxs)
                        .fontWeight(.semibold)
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
