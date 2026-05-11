// Code and document embed renderers.

import SwiftUI
import WebKit

struct CodeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    var previewActive = false

    private var code: String {
        (data?["code"]?.value as? String ?? "")
            .replacingOccurrences(of: #"\""#, with: #"""#)
            .replacingOccurrences(of: #"\/"#, with: "/")
    }
    private var language: String { data?["language"]?.value as? String ?? "" }
    private var filename: String? { data?["filename"]?.value as? String }
    private var lineCount: Int {
        data?["lineCount"]?.value as? Int
            ?? data?["line_count"]?.value as? Int
            ?? code.components(separatedBy: "\n").count
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: 0) {
                if code.isEmpty {
                    VStack(spacing: .spacing4) {
                        Circle()
                            .fill(LinearGradient.primary)
                            .frame(width: 12, height: 12)
                        Text(LocalizationManager.shared.text("common.processing"))
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    CodeLinesView(code: previewCode, language: language, showsLineNumbers: true, fontSize: 12)
                        .padding(.top, .spacing5)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            if previewActive, isPreviewable {
                CodePreviewPane(code: code, language: language, filename: filename)
                    .frame(minHeight: 420)
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
            } else {
                ScrollView([.horizontal, .vertical], showsIndicators: true) {
                    CodeLinesView(code: code, language: language, showsLineNumbers: true, fontSize: 15)
                        .padding(.top, .spacing6)
                        .padding(.bottom, .spacing8)
                        .padding(.trailing, .spacing4)
                }
            }
        }
    }

    private var isPreviewable: Bool {
        let lang = language.lowercased()
        let name = filename?.lowercased() ?? ""
        return ["html", "htm", "markdown", "md", "xml"].contains(lang)
            || name.hasSuffix(".html")
            || name.hasSuffix(".htm")
            || name.hasSuffix(".md")
            || name.hasSuffix(".markdown")
    }

    private var previewCode: String {
        code.components(separatedBy: "\n").prefix(21).joined(separator: "\n")
    }

    private var codeInfoText: String {
        let lineText = lineCount == 1 ? "line" : "lines"
        let lang = languageDisplayName
        return lang.isEmpty ? "\(lineCount) \(lineText)" : "\(lineCount) \(lineText), \(lang)"
    }

    private var languageDisplayName: String {
        switch language.lowercased() {
        case "html", "htm": return "HTML"
        case "css": return "CSS"
        case "javascript", "js": return "JavaScript"
        case "typescript", "ts": return "TypeScript"
        case "markdown", "md": return "Markdown"
        case "python", "py": return "Python"
        default: return language.uppercased()
        }
    }
}

private struct CodeLinesView: View {
    let code: String
    let language: String
    let showsLineNumbers: Bool
    let fontSize: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                HStack(alignment: .top, spacing: .spacing4) {
                    if showsLineNumbers {
                        Text("\(index + 1)")
                            .font(.system(size: fontSize, design: .monospaced))
                            .foregroundStyle(Color.grey60)
                            .frame(width: 34, alignment: .trailing)
                    }
                    HighlightedCodeLine(line: line, language: language, fontSize: fontSize)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .textSelection(.enabled)
    }

    private var lines: [String] {
        let split = code.components(separatedBy: "\n")
        return split.isEmpty ? [""] : split
    }
}

private struct HighlightedCodeLine: View {
    let line: String
    let language: String
    let fontSize: CGFloat

    var body: some View {
        Text(attributedLine)
            .font(.system(size: fontSize, design: .monospaced))
            .fixedSize(horizontal: true, vertical: false)
    }

    private var attributedLine: AttributedString {
        var result = AttributedString()
        for token in CodeSyntaxHighlighter.tokens(for: line, language: language) {
            var chunk = AttributedString(token.text)
            chunk.foregroundColor = token.color
            result += chunk
        }
        return result
    }
}

private enum CodeSyntaxHighlighter {
    struct Token {
        let text: String
        let color: Color
    }

    static func tokens(for line: String, language: String) -> [Token] {
        if isHTMLLike(language) {
            return htmlTokens(for: line)
        }
        if isCSSLike(language) || line.contains("--") || line.contains("{") || line.contains(":") {
            return cssTokens(for: line)
        }
        return genericTokens(for: line)
    }

    private static func genericTokens(for line: String) -> [Token] {
        var tokens: [Token] = []
        var index = line.startIndex
        while index < line.endIndex {
            if line[index] == "\"" || line[index] == "'" {
                let quote = line[index]
                let start = index
                index = line.index(after: index)
                while index < line.endIndex, line[index] != quote {
                    index = line.index(after: index)
                }
                if index < line.endIndex { index = line.index(after: index) }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.string))
            } else if line[index].isNumber {
                let start = index
                while index < line.endIndex, line[index].isNumber {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.number))
            } else {
                let start = index
                index = line.index(after: index)
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.base))
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: SyntaxColor.base)] : tokens
    }

    private static func htmlTokens(for line: String) -> [Token] {
        var tokens: [Token] = []
        var index = line.startIndex
        while index < line.endIndex {
            if line[index...].hasPrefix("<!--"),
               let end = line[index...].range(of: "-->")?.upperBound {
                tokens.append(Token(text: String(line[index..<end]), color: SyntaxColor.comment))
                index = end
            } else if line[index] == "<",
                      let end = line[index...].firstIndex(of: ">") {
                appendHTMLTagTokens(String(line[index...end]), to: &tokens)
                index = line.index(after: end)
            } else {
                let start = index
                while index < line.endIndex, line[index] != "<" {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.base))
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: SyntaxColor.base)] : tokens
    }

    private static func appendHTMLTagTokens(_ tag: String, to tokens: inout [Token]) {
        let delimiters = CharacterSet(charactersIn: "</>=")
        var current = ""
        var inString: Character?
        for scalar in tag.unicodeScalars {
            let char = Character(scalar)
            if let quote = inString {
                current.append(char)
                if char == quote {
                    tokens.append(Token(text: current, color: SyntaxColor.string))
                    current = ""
                    inString = nil
                }
            } else if char == "\"" || char == "'" {
                flushHTMLWord(current, to: &tokens)
                current = String(char)
                inString = char
            } else if delimiters.contains(scalar) {
                flushHTMLWord(current, to: &tokens)
                current = ""
                tokens.append(Token(text: String(char), color: SyntaxColor.punctuation))
            } else if CharacterSet.whitespaces.contains(scalar) {
                flushHTMLWord(current, to: &tokens)
                current = ""
                tokens.append(Token(text: String(char), color: SyntaxColor.base))
            } else {
                current.append(char)
            }
        }
        if !current.isEmpty {
            if inString != nil {
                tokens.append(Token(text: current, color: SyntaxColor.string))
            } else {
                flushHTMLWord(current, to: &tokens)
            }
        }
    }

    private static func flushHTMLWord(_ text: String, to tokens: inout [Token]) {
        guard !text.isEmpty else { return }
        if text.hasPrefix("!") || text.lowercased() == "doctype" {
            tokens.append(Token(text: text, color: SyntaxColor.meta))
        } else if text.first?.isLetter == true {
            let color = tokens.last?.text == "<" || tokens.last?.text == "/" ? SyntaxColor.name : SyntaxColor.attribute
            tokens.append(Token(text: text, color: color))
        } else {
            tokens.append(Token(text: text, color: SyntaxColor.base))
        }
    }

    private static func cssTokens(for line: String) -> [Token] {
        var tokens: [Token] = []
        var index = line.startIndex
        while index < line.endIndex {
            if line[index...].hasPrefix("/*"),
               let end = line[index...].range(of: "*/")?.upperBound {
                tokens.append(Token(text: String(line[index..<end]), color: SyntaxColor.comment))
                index = end
            } else if line[index] == "#" {
                let start = index
                index = line.index(after: index)
                while index < line.endIndex, line[index].isHexDigit {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.number))
            } else if line[index] == "\"" || line[index] == "'" {
                let quote = line[index]
                let start = index
                index = line.index(after: index)
                while index < line.endIndex, line[index] != quote {
                    index = line.index(after: index)
                }
                if index < line.endIndex { index = line.index(after: index) }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.string))
            } else if line[index].isNumber {
                let start = index
                while index < line.endIndex, line[index].isNumber || line[index] == "." || line[index] == "%" {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: SyntaxColor.number))
            } else if line[index].isLetter || line[index] == "-" {
                let start = index
                while index < line.endIndex, line[index].isLetter || line[index].isNumber || line[index] == "-" || line[index] == "_" {
                    index = line.index(after: index)
                }
                let word = String(line[start..<index])
                let next = line[index...].first { !$0.isWhitespace }
                tokens.append(Token(text: word, color: next == ":" ? SyntaxColor.attribute : SyntaxColor.name))
            } else {
                tokens.append(Token(text: String(line[index]), color: SyntaxColor.base))
                index = line.index(after: index)
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: SyntaxColor.base)] : tokens
    }

    private static func isHTMLLike(_ language: String) -> Bool {
        ["html", "htm", "xml", "svg", "svelte"].contains(language.lowercased())
    }

    private static func isCSSLike(_ language: String) -> Bool {
        ["css", "scss", "sass", "less"].contains(language.lowercased())
    }
}

private enum SyntaxColor {
    static let base = Color.grey100
    static let punctuation = Color(hex: 0x79C0FF)
    static let name = Color(hex: 0x7EE787)
    static let attribute = Color(hex: 0x79C0FF)
    static let string = Color(hex: 0xA5D6FF)
    static let number = Color(hex: 0xD2A8FF)
    static let meta = Color(hex: 0x79C0FF)
    static let comment = Color(hex: 0x8B949E)
}

private struct CodePreviewPane: View {
    let code: String
    let language: String
    let filename: String?

    var body: some View {
        CodeHTMLPreview(html: previewHTML)
            .background(Color.grey0)
    }

    private var previewHTML: String {
        if isMarkdown {
            return """
            <!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
            body{font-family:-apple-system,BlinkMacSystemFont,"Inter",sans-serif;padding:24px;background:#fff;color:#111;line-height:1.55}
            code{background:#eef2f7;border-radius:6px;padding:2px 5px} pre{background:#111827;color:#f9fafb;border-radius:10px;padding:16px;overflow:auto}
            </style></head><body>\(markdownHTML)</body></html>
            """
        }
        return code
    }

    private var isMarkdown: Bool {
        let lang = language.lowercased()
        let name = filename?.lowercased() ?? ""
        return lang == "markdown" || lang == "md" || name.hasSuffix(".md") || name.hasSuffix(".markdown")
    }

    private var markdownHTML: String {
        code
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { line -> String in
                if line.hasPrefix("# ") { return "<h1>\(escapeHTML(String(line.dropFirst(2))))</h1>" }
                if line.hasPrefix("## ") { return "<h2>\(escapeHTML(String(line.dropFirst(3))))</h2>" }
                if line.isEmpty { return "<br>" }
                return "<p>\(escapeHTML(String(line)))</p>"
            }
            .joined()
    }

    private func escapeHTML(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}

#if os(iOS)
private struct CodeHTMLPreview: UIViewRepresentable {
    let html: String

    func makeUIView(context: Context) -> WKWebView {
        WKWebView()
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#elseif os(macOS)
private struct CodeHTMLPreview: NSViewRepresentable {
    let html: String

    func makeNSView(context: Context) -> WKWebView {
        WKWebView()
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#endif

struct DocsRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var html: String? { data?["html"]?.value as? String }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title {
                    Text(title)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(2)
                }
                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }
                if let content {
                    Text(content)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(4)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }
                Text(content ?? html ?? "")
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .textSelection(.enabled)
            }
        }
    }
}

struct SheetRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var table: ParsedSheetTable { ParsedSheetTable(data: data) }

    var body: some View {
        switch mode {
        case .preview:
            SheetPreviewTable(table: table)

        case .fullscreen:
            SheetFullscreenTable(table: table)
        }
    }
}

private struct SheetPreviewTable: View {
    let table: ParsedSheetTable

    private let maxRows = 4
    private var visibleHeaders: [String] { Array(table.headers.prefix(4)) }
    private var visibleRows: [[String]] { Array(table.rows.prefix(maxRows)).map { Array($0.prefix(4)) } }
    private var hiddenColumnCount: Int { max(table.headers.count - visibleHeaders.count, 0) }
    private var remainingRowCount: Int { max(table.rows.count - maxRows, 0) }

    var body: some View {
        VStack(spacing: 0) {
            if table.headers.isEmpty {
                VStack(spacing: .spacing3) {
                    Icon("table", size: 38)
                        .foregroundStyle(Color.grey70)
                    Text(LocalizationManager.shared.text("embeds.table"))
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontSecondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Grid(horizontalSpacing: 0, verticalSpacing: 0) {
                    GridRow {
                        ForEach(visibleHeaders.indices, id: \.self) { index in
                            sheetCell(visibleHeaders[index], isHeader: true)
                        }
                        if hiddenColumnCount > 0 {
                            sheetCell("+\(hiddenColumnCount)", isHeader: true, isMuted: true)
                        }
                    }
                    ForEach(visibleRows.indices, id: \.self) { rowIndex in
                        GridRow {
                            ForEach(visibleHeaders.indices, id: \.self) { colIndex in
                                sheetCell(visibleRows[rowIndex].indices.contains(colIndex) ? visibleRows[rowIndex][colIndex] : "", isHeader: false, alternate: rowIndex.isMultiple(of: 2) == false)
                            }
                            if hiddenColumnCount > 0 {
                                sheetCell("", isHeader: false, isMuted: true, alternate: rowIndex.isMultiple(of: 2) == false)
                            }
                        }
                    }
                    if remainingRowCount > 0 {
                        GridRow {
                            Text("+\(remainingRowCount) more rows")
                                .font(.omMicro)
                                .italic()
                                .foregroundStyle(Color.grey50)
                                .padding(.vertical, 3)
                                .frame(maxWidth: .infinity)
                                .gridCellColumns(visibleHeaders.count + (hiddenColumnCount > 0 ? 1 : 0))
                                .background(Color.grey25)
                        }
                    }
                }
                .padding(.top, .spacing5)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipped()
    }

    private func sheetCell(_ text: String, isHeader: Bool, isMuted: Bool = false, alternate: Bool = false) -> some View {
        Text(text)
            .font(isHeader ? .omMicro : .omMicro)
            .fontWeight(isHeader ? .bold : .semibold)
            .foregroundStyle(isMuted ? Color.grey50 : (isHeader ? Color.grey80 : Color.grey80))
            .lineLimit(1)
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .frame(minWidth: 60, maxWidth: 140, alignment: .leading)
            .background(isHeader ? Color.grey25 : (alternate ? Color.grey20 : Color.grey10))
            .overlay(
                Rectangle()
                    .stroke(Color.grey30, lineWidth: 0.7)
            )
    }
}

private struct SheetFullscreenTable: View {
    let table: ParsedSheetTable
    @State private var sortColumnIndex: Int?
    @State private var sortAscending = true
    @State private var showFilters = false
    @State private var filters: [String] = []

    private var displayRows: [[String]] {
        var rows = table.rows
        if filters.count == table.headers.count {
            rows = rows.filter { row in
                filters.enumerated().allSatisfy { index, filter in
                    filter.isEmpty || (row.indices.contains(index) && row[index].localizedCaseInsensitiveContains(filter))
                }
            }
        }
        if let sortColumnIndex {
            rows = rows.sorted { lhs, rhs in
                let left = lhs.indices.contains(sortColumnIndex) ? lhs[sortColumnIndex] : ""
                let right = rhs.indices.contains(sortColumnIndex) ? rhs[sortColumnIndex] : ""
                let result = left.localizedStandardCompare(right) == .orderedAscending
                return sortAscending ? result : !result
            }
        }
        return rows
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if showFilters {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: .spacing3) {
                        ForEach(table.headers.indices, id: \.self) { index in
                            TextField(table.headers[index], text: bindingForFilter(index))
                                .textFieldStyle(.plain)
                                .font(.omXs)
                                .foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing4)
                                .padding(.vertical, .spacing2)
                                .frame(width: 140)
                                .background(Color.grey10)
                                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Color.grey30, lineWidth: 1))
                        }
                    }
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing3)
                }
                .background(Color.grey10)
            }

            ScrollView([.horizontal, .vertical], showsIndicators: true) {
                if table.headers.isEmpty {
                    Text("No table data available")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                        .frame(maxWidth: .infinity, minHeight: 200)
                } else {
                    Grid(horizontalSpacing: 0, verticalSpacing: 0) {
                        GridRow {
                            sheetHeaderGutter
                            ForEach(table.headers.indices, id: \.self) { index in
                                Text(columnLetter(index))
                                    .font(.omTiny)
                                    .fontWeight(.medium)
                                    .foregroundStyle(Color.fontTertiary)
                                    .frame(width: columnWidth(index), alignment: .center)
                                    .padding(.vertical, .spacing1)
                                    .background(Color.grey10)
                                    .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
                            }
                        }

                        GridRow {
                            Text("")
                                .frame(width: 40)
                                .padding(.vertical, .spacing3)
                                .background(Color.grey10)
                                .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
                            ForEach(table.headers.indices, id: \.self) { index in
                                Button {
                                    cycleSort(index)
                                } label: {
                                    HStack(spacing: .spacing2) {
                                        Text(table.headers[index])
                                            .font(.omXs)
                                            .fontWeight(.bold)
                                            .foregroundStyle(Color.fontPrimary)
                                            .lineLimit(1)
                                        Icon(sortIcon(for: index), size: 10)
                                            .foregroundStyle(sortColumnIndex == index ? Color.buttonPrimary : Color.fontTertiary)
                                    }
                                    .frame(width: columnWidth(index), alignment: .leading)
                                    .padding(.horizontal, .spacing6)
                                    .padding(.vertical, .spacing3)
                                    .background(Color.grey10)
                                    .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
                                }
                                .buttonStyle(.plain)
                            }
                        }

                        ForEach(displayRows.indices, id: \.self) { rowIndex in
                            GridRow {
                                Text("\(rowIndex + 1)")
                                    .font(.omTiny)
                                    .foregroundStyle(Color.fontTertiary)
                                    .frame(width: 40)
                                    .padding(.vertical, .spacing3)
                                    .background(Color.grey10)
                                    .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
                                ForEach(table.headers.indices, id: \.self) { colIndex in
                                    Text(displayRows[rowIndex].indices.contains(colIndex) ? displayRows[rowIndex][colIndex] : "")
                                        .font(.omXs)
                                        .fontWeight(.semibold)
                                        .foregroundStyle(Color.fontPrimary)
                                        .textSelection(.enabled)
                                        .frame(width: columnWidth(colIndex), alignment: .leading)
                                        .padding(.horizontal, .spacing6)
                                        .padding(.vertical, .spacing3)
                                        .background(rowIndex.isMultiple(of: 2) ? Color.grey20 : Color.grey10)
                                        .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
                                }
                            }
                        }
                    }
                    .padding(.top, 70)
                }
            }
        }
        .onAppear {
            filters = Array(repeating: "", count: table.headers.count)
        }
    }

    private var sheetHeaderGutter: some View {
        Button {
            showFilters.toggle()
            if !showFilters {
                filters = Array(repeating: "", count: table.headers.count)
            }
        } label: {
            Icon("filter", size: 14)
                .foregroundStyle(showFilters ? Color.buttonPrimary : Color.fontTertiary)
                .frame(width: 40, height: 24)
                .background(Color.grey10)
                .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
        }
        .buttonStyle(.plain)
    }

    private func bindingForFilter(_ index: Int) -> Binding<String> {
        Binding(
            get: {
                filters.indices.contains(index) ? filters[index] : ""
            },
            set: { value in
                if filters.count != table.headers.count {
                    filters = Array(repeating: "", count: table.headers.count)
                }
                filters[index] = value
            }
        )
    }

    private func cycleSort(_ index: Int) {
        if sortColumnIndex == index {
            if sortAscending {
                sortAscending = false
            } else {
                sortColumnIndex = nil
                sortAscending = true
            }
        } else {
            sortColumnIndex = index
            sortAscending = true
        }
    }

    private func sortIcon(for index: Int) -> String {
        "sort"
    }

    private func columnWidth(_ index: Int) -> CGFloat {
        let headerLen = table.headers.indices.contains(index) ? table.headers[index].count : 0
        let maxRowLen = table.rows.map { $0.indices.contains(index) ? $0[index].count : 0 }.max() ?? 0
        return min(max(CGFloat(max(headerLen, maxRowLen) * 8), 80), 320)
    }

    private func columnLetter(_ index: Int) -> String {
        var value = index + 1
        var result = ""
        while value > 0 {
            let remainder = (value - 1) % 26
            result = String(UnicodeScalar(65 + remainder)!) + result
            value = (value - 1) / 26
        }
        return result
    }
}

struct ParsedSheetTable {
    let title: String?
    let headers: [String]
    let rows: [[String]]
    let markdown: String

    init(data: [String: AnyCodable]?) {
        var markdown = ParsedSheetTable.firstString(data, ["table", "code", "content", "markdown"]) ?? ""
        var title = ParsedSheetTable.firstString(data, ["title"])
        if title == nil, let match = markdown.range(of: #"<!--\s*title:\s*"([^"]+)"\s*-->"#, options: .regularExpression) {
            let comment = String(markdown[match])
            title = comment
                .replacingOccurrences(of: #"<!--\s*title:\s*""#, with: "", options: .regularExpression)
                .replacingOccurrences(of: #""\s*-->"#, with: "", options: .regularExpression)
            markdown.removeSubrange(match)
        }

        self.title = title
        self.markdown = markdown.trimmingCharacters(in: .whitespacesAndNewlines)
        let lines = self.markdown
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && $0.contains("|") }

        guard lines.count >= 2 else {
            headers = []
            rows = []
            return
        }

        let parsedHeaders = ParsedSheetTable.parseRow(lines[0])
        headers = parsedHeaders
        rows = lines.dropFirst(2).map { line in
            let cells = ParsedSheetTable.parseRow(line)
            return parsedHeaders.indices.map { cells.indices.contains($0) ? cells[$0] : "" }
        }
    }

    var rowCount: Int { rows.count }
    var colCount: Int { headers.count }
    var dimensionsText: String {
        "\(rowCount) \(rowCount == 1 ? "row" : "rows") × \(colCount) \(colCount == 1 ? "column" : "columns")"
    }
    var tsv: String {
        ([headers] + rows)
            .map { $0.map { $0.replacingOccurrences(of: "\t", with: " ") }.joined(separator: "\t") }
            .joined(separator: "\n")
    }

    private static func parseRow(_ line: String) -> [String] {
        var content = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if content.hasPrefix("|") { content.removeFirst() }
        if content.hasSuffix("|") { content.removeLast() }
        return content.split(separator: "|", omittingEmptySubsequences: false)
            .map { stripInlineMarkdown(String($0).trimmingCharacters(in: .whitespacesAndNewlines)) }
    }

    private static func stripInlineMarkdown(_ text: String) -> String {
        text
            .replacingOccurrences(of: #"\*\*(.+?)\*\*"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"__(.+?)__"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"\*(.+?)\*"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"_(.+?)_"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"~~(.+?)~~"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"`(.+?)`"#, with: "$1", options: .regularExpression)
    }

    private static func firstString(_ data: [String: AnyCodable]?, _ keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }
}
