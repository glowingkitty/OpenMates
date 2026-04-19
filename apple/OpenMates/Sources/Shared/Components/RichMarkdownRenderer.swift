// Rich markdown renderer — full block-level rendering for AI chat messages.
// Handles fenced code blocks with syntax highlighting, blockquotes, headers,
// tables, horizontal rules, and lists. Falls back to Apple's built-in
// AttributedString for inline formatting (bold, italic, links, inline code).
// Replaces the previous inline-only MarkdownText view for assistant messages.

import SwiftUI

// MARK: - Block parser

/// Parses raw markdown text into a sequence of typed blocks for rendering.
/// Handles fenced code blocks (```lang), blockquotes (>), headers (#),
/// horizontal rules (---), and unordered/ordered lists. Everything else
/// is treated as a paragraph with inline markdown formatting.
enum MarkdownBlock: Identifiable {
    case paragraph(String)
    case codeBlock(language: String?, code: String)
    case blockquote(String)
    case header(level: Int, text: String)
    case horizontalRule
    case unorderedList([String])
    case orderedList([String])
    case table(headers: [String], rows: [[String]])

    var id: String {
        switch self {
        case .paragraph(let t): return "p-\(t.hashValue)"
        case .codeBlock(_, let c): return "code-\(c.hashValue)"
        case .blockquote(let t): return "bq-\(t.hashValue)"
        case .header(let l, let t): return "h\(l)-\(t.hashValue)"
        case .horizontalRule: return "hr-\(UUID().uuidString)"
        case .unorderedList(let items): return "ul-\(items.hashValue)"
        case .orderedList(let items): return "ol-\(items.hashValue)"
        case .table(let h, _): return "tbl-\(h.hashValue)"
        }
    }
}

enum MarkdownParser {
    static func parse(_ text: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        let lines = text.components(separatedBy: "\n")
        var i = 0

        while i < lines.count {
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

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
                    || pTrimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) != nil {
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

    private var blocks: [MarkdownBlock] {
        MarkdownParser.parse(content)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(blocks) { block in
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
        }
    }
}

// MARK: - Inline markdown (paragraphs, list items)

struct InlineMarkdownText: View {
    let content: String
    let isUserMessage: Bool

    var body: some View {
        Text(attributedContent)
            .font(.omP)
            .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontPrimary)
            .textSelection(.enabled)
    }

    private var attributedContent: AttributedString {
        (try? AttributedString(markdown: content, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(content)
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
                        Text(copied ? "Copied" : "Copy")
                            .font(.system(size: 11))
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
            .fontWeight(level <= 2 ? .bold : .semibold)
            .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontPrimary)
            .padding(.top, level <= 2 ? .spacing3 : .spacing2)
            .textSelection(.enabled)
    }

    private var headerFont: Font {
        switch level {
        case 1: return .omH1
        case 2: return .omH2
        case 3: return .omH3
        case 4: return .omH4
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
