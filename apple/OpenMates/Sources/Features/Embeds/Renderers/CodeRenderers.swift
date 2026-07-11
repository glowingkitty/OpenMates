// Code and document embed renderers.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/CodeEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/code/CodePreviewPane.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/electronics/ElectronicsComponentEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/electronics/ElectronicsComponentEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import WebKit
#if os(iOS)
import UIKit
#endif

struct CodeEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let embedId: String
    let chatId: String?
    let mode: EmbedDisplayMode
    var previewActive = false
    var codeRunViewModel: CodeRunViewModel?
    var isLargePreview = false
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

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
                    CodeLinesView(
                        code: previewCode,
                        language: language,
                        showsLineNumbers: true,
                        fontSize: 12,
                        clipsLongLines: true
                    )
                        .padding(.top, .spacing5)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .clipped()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(spacing: 0) {
                if previewActive {
                    GeometryReader { proxy in
                        HStack(spacing: 1) {
                            if horizontalSizeClass != .compact {
                                codeSourcePanel(isSplit: true)
                                    .frame(width: proxy.size.width * 0.3)
                            }

                            outputPanel
                                .frame(width: horizontalSizeClass == .compact ? proxy.size.width : proxy.size.width * 0.7)
                        }
                        .background(Color.grey20)
                    }
                    .frame(minHeight: 420)
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                } else {
                    ZStack(alignment: .top) {
                        codeSourcePanel(isSplit: false)

                        if let codeRunViewModel, codeRunViewModel.isPanelOpen {
                            CodeRunTerminalView(
                                viewModel: codeRunViewModel,
                                chatId: chatId,
                                embedId: embedId,
                                file: runClientFile,
                                onViewCode: { codeRunViewModel.closePanel() }
                            )
                            .padding(.top, .spacing8)
                            .padding(.horizontal, horizontalSizeClass == .compact ? .spacing4 : .spacing10)
                        }
                    }
                }
            }
            .background(Color.grey10)
        }
    }

    private var outputPaneActive: Bool {
        previewActive
    }

    @ViewBuilder
    private func codeSourcePanel(isSplit: Bool) -> some View {
        ScrollView([.horizontal, .vertical], showsIndicators: true) {
            CodeLinesView(
                code: code,
                language: language,
                showsLineNumbers: true,
                fontSize: isSplit ? 13 : 15,
                clipsLongLines: false,
                gutterWidth: isSplit ? 40 : 40
            )
                .padding(.top, .spacing6)
                .padding(.bottom, .spacing8)
                .padding(.trailing, .spacing4)
        }
        .background(Color.grey10)
        .accessibilityIdentifier("code-source-panel")
    }

    @ViewBuilder
    private var outputPanel: some View {
        if previewActive, isPreviewable {
            CodePreviewPane(code: code, language: language, filename: filename)
                .frame(minHeight: 420)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
        } else if let codeRunViewModel {
            CodeRunTerminalView(viewModel: codeRunViewModel, chatId: chatId, embedId: embedId, file: runClientFile, onViewCode: { codeRunViewModel.closePanel() })
                .frame(minHeight: 420)
        } else {
            EmptyView()
        }
    }

    private var runClientFile: CodeRunClientFile {
        CodeRunClientFile(embedId: embedId, code: code, language: language, filename: filename, isTarget: true)
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
        code.components(separatedBy: "\n").prefix(isLargePreview ? 21 : 8).joined(separator: "\n")
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

private struct CodeRunTerminalView: View {
    @ObservedObject var viewModel: CodeRunViewModel
    let chatId: String?
    let embedId: String
    let file: CodeRunClientFile
    let onViewCode: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            viewCodeButton
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(viewModel.events) { event in
                        Text(event.text)
                            .font(.system(size: 15, weight: .bold, design: .monospaced))
                            .foregroundStyle(color(for: event.kind))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }
                .padding(.vertical, .spacing4)
            }

            Rectangle()
                .fill(Color(hex: 0x8D8D8D))
                .frame(height: 1)

            terminalActions
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing6)
        .frame(maxWidth: 760, minHeight: 420, alignment: .topLeading)
        .background(Color(hex: 0x242424))
        .clipShape(RoundedRectangle(cornerRadius: 32))
        .shadow(color: .black.opacity(0.28), radius: 24, x: 0, y: 14)
        .accessibilityIdentifier("code-run-terminal")
    }

    private var viewCodeButton: some View {
        Button(action: onViewCode) {
            HStack(spacing: .spacing4) {
                ChevronShape()
                    .stroke(Color(hex: 0xBCBCBC), style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
                    .frame(width: 14, height: 22)
                Text(AppStrings.codeRunViewCode)
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color(hex: 0xBCBCBC))
            }
        }
        .buttonStyle(.plain)
        .help(Text(AppStrings.codeRunViewCode))
        .accessibilityLabel(AppStrings.codeRunViewCode)
    }

    private var statusText: String {
        let fileText = "\(viewModel.files.count) file\(viewModel.files.count == 1 ? "" : "s") included"
        return viewModel.files.isEmpty ? viewModel.status.rawValue : "\(viewModel.status.rawValue) · \(fileText)"
    }

    private var terminalActions: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if viewModel.isActive {
                terminalAction(viewModel.isCancelling ? AppStrings.codeRunCancelling : AppStrings.codeRunStop, disabled: viewModel.isCancelling) {
                    viewModel.cancel()
                }
            }
            terminalAction(AppStrings.codeRunAskFollowup, disabled: true) {}
            terminalAction(AppStrings.codeRunCopyOutput, disabled: viewModel.programOutputText.isEmpty) {
                viewModel.copyOutput()
            }
            terminalAction(AppStrings.codeRunAgain, disabled: viewModel.isActive) {
                Task { await viewModel.start(chatId: chatId, embedId: embedId, file: file) }
            }
        }
        .accessibilityIdentifier("code-run-terminal-actions")
    }

    private func terminalAction(_ title: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text("> \(title)")
                .font(.system(size: 15, weight: .bold, design: .monospaced))
                .foregroundStyle(disabled ? Color(hex: 0x707070) : Color(hex: 0xBCBCBC))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .help(Text(title))
        .accessibilityLabel(title)
    }

    private func color(for kind: CodeRunEvent.Kind) -> Color {
        switch kind {
        case .status: return Color(hex: 0x7DD3FC)
        case .stdout: return Color(hex: 0xD1D5DB)
        case .stderr: return Color(hex: 0xFCA5A5)
        }
    }
}

private struct ChevronShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        return path
    }
}

private struct CodeLinesView: View {
    let code: String
    let language: String
    let showsLineNumbers: Bool
    let fontSize: CGFloat
    let clipsLongLines: Bool
    var gutterWidth: CGFloat = 34

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                HStack(alignment: .top, spacing: .spacing4) {
                    if showsLineNumbers {
                        Text("\(index + 1)")
                            .font(.system(size: fontSize, design: .monospaced))
                            .foregroundStyle(Color.grey60)
                            .frame(width: gutterWidth, alignment: .trailing)
                    }
                    HighlightedCodeLine(
                        line: line,
                        language: language,
                        fontSize: fontSize,
                        clipsLongLines: clipsLongLines
                    )
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .clipped()
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .clipped()
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
    let clipsLongLines: Bool

    var body: some View {
        if clipsLongLines {
            Text(attributedLine)
                .font(.system(size: fontSize, design: .monospaced))
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .clipped()
        } else {
            Text(attributedLine)
                .font(.system(size: fontSize, design: .monospaced))
                .fixedSize(horizontal: true, vertical: false)
                .lineLimit(1)
        }
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

struct CodeGetDocsEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? {
        firstString(["title", "library_id", "library"])
            ?? firstResultString(["library_id", "id", "library_title", "title"])
    }
    private var html: String? { data?["html"]?.value as? String }
    private var content: String? {
        firstString(["content", "documentation", "html"])
            ?? firstResultString(["content", "documentation", "text"])
    }
    private var question: String? { firstString(["question", "query"]) }
    private var wordCount: Int? {
        firstInt(["word_count", "wordCount"]) ?? firstResultInt(["word_count", "wordCount"])
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title {
                    Text(title)
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.grey100)
                        .monospaced()
                        .lineLimit(2)
                }
                if let question {
                    Text(question)
                        .font(.omSmall)
                        .foregroundStyle(Color.grey80)
                        .lineLimit(2)
                }
                Text("via Context7")
                    .font(.omSmall)
                    .foregroundStyle(Color.grey70)
                if let wordCount {
                    Text("\(wordCount.formatted()) words")
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let title {
                    Text(title)
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey100)
                        .monospaced()
                }
                if let question {
                    Text(question)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                }
                if let wordCount {
                    Text("\(wordCount.formatted()) words")
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

    private var firstResult: [String: Any]? {
        if let results = data?["results"]?.value as? [[String: Any]], let first = results.first {
            return first
        }
        if let results = data?["results"]?.value as? [[String: AnyCodable]], let first = results.first {
            return first.mapValues(\.value)
        }
        if let result = data?["result"]?.value as? [String: Any] {
            return result
        }
        if let result = data?["result"]?.value as? [String: AnyCodable] {
            return result.mapValues(\.value)
        }
        return nil
    }

    private func firstString(_ keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private func firstInt(_ keys: [String]) -> Int? {
        for key in keys {
            if let value = data?[key]?.value as? Int {
                return value
            }
            if let value = data?[key]?.value as? String, let int = Int(value) {
                return int
            }
        }
        return nil
    }

    private func firstResultString(_ keys: [String]) -> String? {
        guard let firstResult else { return nil }
        for key in keys {
            if let value = firstResult[key] as? String, !value.isEmpty {
                return value
            }
            if key == "library_id",
               let library = firstResult["library"] as? [String: Any],
               let value = library["id"] as? String,
               !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private func firstResultInt(_ keys: [String]) -> Int? {
        guard let firstResult else { return nil }
        for key in keys {
            if let value = firstResult[key] as? Int {
                return value
            }
            if let value = firstResult[key] as? String, let int = Int(value) {
                return int
            }
        }
        return nil
    }
}

struct DocsRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var html: String? { data?["html"]?.value as? String }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? {
        if let value = data?["word_count"]?.value as? Int { return value }
        if let value = data?["word_count"]?.value as? String { return Int(value) }
        return nil
    }

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
                    Text("\(wordCount.formatted()) words")
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
                    Text("\(wordCount.formatted()) words")
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

            sheetTableBody
        }
        .onAppear {
            filters = Array(repeating: "", count: table.headers.count)
        }
    }

    @ViewBuilder
    private var sheetTableBody: some View {
        if table.headers.isEmpty {
            Text("No table data available")
                .font(.omSmall)
                .foregroundStyle(Color.fontTertiary)
                .frame(maxWidth: .infinity, minHeight: 200)
        } else {
            #if os(iOS)
            SheetFullscreenCollectionTable(
                headers: table.headers,
                rows: displayRows,
                columnWidths: table.headers.indices.map(columnWidth),
                sortColumnIndex: sortColumnIndex,
                sortAscending: sortAscending,
                showFilters: showFilters,
                onToggleFilters: toggleFilters,
                onSortColumn: cycleSort
            )
            #else
            swiftUITableBody
            #endif
        }
    }

    private var swiftUITableBody: some View {
        ScrollView([.horizontal, .vertical], showsIndicators: true) {
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

    private var sheetHeaderGutter: some View {
        Button {
            toggleFilters()
        } label: {
            Icon("filter", size: 14)
                .foregroundStyle(showFilters ? Color.buttonPrimary : Color.fontTertiary)
                .frame(width: 40, height: 24)
                .background(Color.grey10)
                .overlay(Rectangle().stroke(Color.grey30, lineWidth: 0.7))
        }
        .buttonStyle(.plain)
    }

    private func toggleFilters() {
        showFilters.toggle()
        if !showFilters {
            filters = Array(repeating: "", count: table.headers.count)
        }
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

#if os(iOS)
private struct SheetFullscreenCollectionTable: UIViewRepresentable {
    let headers: [String]
    let rows: [[String]]
    let columnWidths: [CGFloat]
    let sortColumnIndex: Int?
    let sortAscending: Bool
    let showFilters: Bool
    let onToggleFilters: () -> Void
    let onSortColumn: (Int) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> UICollectionView {
        let layout = SheetFullscreenCollectionLayout()
        let collectionView = UICollectionView(frame: .zero, collectionViewLayout: layout)
        collectionView.backgroundColor = UIColor(Color.grey20)
        collectionView.alwaysBounceVertical = true
        collectionView.alwaysBounceHorizontal = true
        collectionView.showsVerticalScrollIndicator = true
        collectionView.showsHorizontalScrollIndicator = true
        collectionView.contentInset.top = 70
        collectionView.dataSource = context.coordinator
        collectionView.delegate = context.coordinator
        collectionView.register(SheetFullscreenCollectionCell.self, forCellWithReuseIdentifier: SheetFullscreenCollectionCell.reuseIdentifier)
        return collectionView
    }

    func updateUIView(_ collectionView: UICollectionView, context: Context) {
        context.coordinator.parent = self
        if let layout = collectionView.collectionViewLayout as? SheetFullscreenCollectionLayout {
            layout.columnWidths = [40] + columnWidths
            layout.rowCount = rows.count + 2
            layout.invalidateLayout()
        }
        collectionView.reloadData()
    }

    final class Coordinator: NSObject, UICollectionViewDataSource, UICollectionViewDelegate {
        var parent: SheetFullscreenCollectionTable

        init(_ parent: SheetFullscreenCollectionTable) {
            self.parent = parent
        }

        func collectionView(_ collectionView: UICollectionView, numberOfItemsInSection section: Int) -> Int {
            (parent.rows.count + 2) * (parent.headers.count + 1)
        }

        func collectionView(_ collectionView: UICollectionView, cellForItemAt indexPath: IndexPath) -> UICollectionViewCell {
            let cell = collectionView.dequeueReusableCell(
                withReuseIdentifier: SheetFullscreenCollectionCell.reuseIdentifier,
                for: indexPath
            ) as! SheetFullscreenCollectionCell
            cell.configure(with: cellModel(for: indexPath.item))
            return cell
        }

        func collectionView(_ collectionView: UICollectionView, didSelectItemAt indexPath: IndexPath) {
            let position = position(for: indexPath.item)
            if position.row == 0 && position.column == 0 {
                parent.onToggleFilters()
            } else if position.row == 1 && position.column > 0 {
                parent.onSortColumn(position.column - 1)
            }
        }

        private func cellModel(for item: Int) -> SheetFullscreenCollectionCell.Model {
            let position = position(for: item)
            if position.row == 0 {
                if position.column == 0 {
                    return .init(text: "", kind: .filter(isActive: parent.showFilters))
                }
                return .init(text: columnLetter(position.column - 1), kind: .columnLetter)
            }

            if position.row == 1 {
                if position.column == 0 {
                    return .init(text: "", kind: .rowHeader)
                }
                let columnIndex = position.column - 1
                let header = parent.headers.indices.contains(columnIndex) ? parent.headers[columnIndex] : ""
                let isActive = parent.sortColumnIndex == columnIndex
                let sortIndicator = isActive ? (parent.sortAscending ? " ↑" : " ↓") : " ↕"
                return .init(text: header + sortIndicator, kind: .header(isActive: isActive))
            }

            let rowIndex = position.row - 2
            if position.column == 0 {
                return .init(text: "\(rowIndex + 1)", kind: .rowHeader)
            }
            let columnIndex = position.column - 1
            let row = parent.rows.indices.contains(rowIndex) ? parent.rows[rowIndex] : []
            let value = row.indices.contains(columnIndex) ? row[columnIndex] : ""
            return .init(text: value, kind: .value(isAlternate: !rowIndex.isMultiple(of: 2)))
        }

        private func position(for item: Int) -> (row: Int, column: Int) {
            let columnCount = parent.headers.count + 1
            return (item / columnCount, item % columnCount)
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
}

private final class SheetFullscreenCollectionLayout: UICollectionViewLayout {
    var columnWidths: [CGFloat] = []
    var rowCount = 0
    private let rowHeights: [CGFloat] = [24, 44]
    private let dataRowHeight: CGFloat = 44
    private var columnOffsets: [CGFloat] = []
    private var contentSize = CGSize.zero

    override func prepare() {
        super.prepare()
        guard let collectionView else { return }

        columnOffsets = []
        var x: CGFloat = 0
        for width in columnWidths {
            columnOffsets.append(x)
            x += width
        }

        contentSize = CGSize(
            width: max(x, collectionView.bounds.width + 1),
            height: max(totalContentHeight, collectionView.bounds.height - collectionView.adjustedContentInset.vertical + 1)
        )
    }

    override var collectionViewContentSize: CGSize {
        contentSize
    }

    override func layoutAttributesForElements(in rect: CGRect) -> [UICollectionViewLayoutAttributes]? {
        guard !columnWidths.isEmpty, rowCount > 0 else { return [] }

        let rowRange = visibleRowRange(intersecting: rect)
        let columnRange = visibleColumnRange(intersecting: rect)
        var visibleAttributes: [UICollectionViewLayoutAttributes] = []

        for row in rowRange {
            for column in columnRange {
                let indexPath = IndexPath(item: row * columnWidths.count + column, section: 0)
                if let itemAttributes = layoutAttributesForItem(at: indexPath) {
                    visibleAttributes.append(itemAttributes)
                }
            }
        }
        return visibleAttributes
    }

    override func layoutAttributesForItem(at indexPath: IndexPath) -> UICollectionViewLayoutAttributes? {
        guard !columnWidths.isEmpty else { return nil }
        let column = indexPath.item % columnWidths.count
        let row = indexPath.item / columnWidths.count
        guard row < rowCount, column < columnWidths.count, column < columnOffsets.count else { return nil }

        let itemAttributes = UICollectionViewLayoutAttributes(forCellWith: indexPath)
        itemAttributes.frame = CGRect(
            x: columnOffsets[column],
            y: yOffset(for: row),
            width: columnWidths[column],
            height: height(for: row)
        )
        return itemAttributes
    }

    override func shouldInvalidateLayout(forBoundsChange newBounds: CGRect) -> Bool {
        true
    }

    private var totalContentHeight: CGFloat {
        guard rowCount > 0 else { return 0 }
        return (0..<rowCount).reduce(CGFloat(0)) { total, row in
            total + height(for: row)
        }
    }

    private func height(for row: Int) -> CGFloat {
        rowHeights.indices.contains(row) ? rowHeights[row] : dataRowHeight
    }

    private func yOffset(for row: Int) -> CGFloat {
        guard row > 0 else { return 0 }
        return (0..<row).reduce(CGFloat(0)) { total, item in
            total + height(for: item)
        }
    }

    private func visibleRowRange(intersecting rect: CGRect) -> Range<Int> {
        guard rowCount > 0 else { return 0..<0 }
        let headerHeight = rowHeights.reduce(0, +)
        let first: Int
        if rect.minY < rowHeights[0] {
            first = 0
        } else if rect.minY < headerHeight {
            first = 1
        } else {
            first = min(max(Int((rect.minY - headerHeight) / dataRowHeight) + rowHeights.count, 0), rowCount)
        }

        let lastExclusive: Int
        if rect.maxY <= rowHeights[0] {
            lastExclusive = 1
        } else if rect.maxY <= headerHeight {
            lastExclusive = min(2, rowCount)
        } else {
            lastExclusive = min(Int(ceil((rect.maxY - headerHeight) / dataRowHeight)) + rowHeights.count, rowCount)
        }

        return min(first, lastExclusive)..<max(first, lastExclusive)
    }

    private func visibleColumnRange(intersecting rect: CGRect) -> Range<Int> {
        guard !columnWidths.isEmpty else { return 0..<0 }
        let first = columnOffsets.firstIndex { offset in
            let column = columnOffsets.firstIndex(of: offset) ?? 0
            return offset + columnWidths[column] >= rect.minX
        } ?? 0
        let last = columnOffsets.lastIndex { offset in offset <= rect.maxX } ?? (columnWidths.count - 1)
        return first..<min(last + 2, columnWidths.count)
    }
}

private final class SheetFullscreenCollectionCell: UICollectionViewCell {
    static let reuseIdentifier = "SheetFullscreenCollectionCell"

    enum Kind {
        case filter(isActive: Bool)
        case columnLetter
        case header(isActive: Bool)
        case rowHeader
        case value(isAlternate: Bool)
    }

    struct Model {
        let text: String
        let kind: Kind
    }

    private let label = UILabel()
    private let valueTextView = UITextView()

    override init(frame: CGRect) {
        super.init(frame: frame)
        contentView.addSubview(label)
        contentView.addSubview(valueTextView)
        label.translatesAutoresizingMaskIntoConstraints = false
        label.numberOfLines = 1
        label.lineBreakMode = .byTruncatingTail
        valueTextView.translatesAutoresizingMaskIntoConstraints = false
        valueTextView.backgroundColor = .clear
        valueTextView.isEditable = false
        valueTextView.isScrollEnabled = false
        valueTextView.textContainer.lineBreakMode = .byTruncatingTail
        valueTextView.textContainer.maximumNumberOfLines = 1
        valueTextView.textContainerInset = UIEdgeInsets(top: 3, left: 0, bottom: 3, right: 0)
        valueTextView.textContainer.lineFragmentPadding = 0
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 8),
            label.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -8),
            label.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 3),
            label.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -3),
            valueTextView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 8),
            valueTextView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -8),
            valueTextView.topAnchor.constraint(equalTo: contentView.topAnchor),
            valueTextView.bottomAnchor.constraint(equalTo: contentView.bottomAnchor),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(with model: Model) {
        label.isHidden = false
        valueTextView.isHidden = true
        label.text = model.text
        label.textAlignment = .left
        label.font = UIFont(name: FontRegistration.fontFamily, size: 13) ?? .systemFont(ofSize: 13, weight: .semibold)
        label.textColor = UIColor(Color.fontPrimary)
        contentView.layer.borderWidth = 0.7
        contentView.layer.borderColor = UIColor(Color.grey30).cgColor

        switch model.kind {
        case .filter(let isActive):
            label.text = LocalizationManager.shared.text("activity.filter")
            label.font = UIFont(name: FontRegistration.fontFamily, size: 11) ?? .systemFont(ofSize: 11, weight: .medium)
            label.textAlignment = .center
            label.textColor = UIColor(isActive ? Color.buttonPrimary : Color.fontTertiary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .columnLetter:
            label.font = UIFont(name: FontRegistration.fontFamily, size: 11) ?? .systemFont(ofSize: 11, weight: .medium)
            label.textAlignment = .center
            label.textColor = UIColor(Color.fontTertiary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .header(let isActive):
            label.font = UIFont(name: FontRegistration.fontFamily, size: 13) ?? .systemFont(ofSize: 13, weight: .bold)
            label.textColor = UIColor(isActive ? Color.buttonPrimary : Color.fontPrimary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .rowHeader:
            label.font = UIFont(name: FontRegistration.fontFamily, size: 11) ?? .systemFont(ofSize: 11, weight: .medium)
            label.textAlignment = .center
            label.textColor = UIColor(Color.fontTertiary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .value(let isAlternate):
            label.isHidden = true
            valueTextView.isHidden = false
            valueTextView.text = model.text
            valueTextView.font = UIFont(name: FontRegistration.fontFamily, size: 13) ?? .systemFont(ofSize: 13, weight: .semibold)
            valueTextView.textColor = UIColor(Color.fontPrimary)
            label.font = UIFont(name: FontRegistration.fontFamily, size: 13) ?? .systemFont(ofSize: 13, weight: .semibold)
            label.textColor = UIColor(Color.fontPrimary)
            contentView.backgroundColor = UIColor(isAlternate ? Color.grey20 : Color.grey10)
        }
    }
}

private extension UIEdgeInsets {
    var vertical: CGFloat { top + bottom }
}
#endif

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

struct CodeRepoEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var repository: CodeRepoSummary { CodeRepoSummary(data: data ?? [:]) }

    var body: some View {
        switch mode {
        case .preview:
            CodeRepoPreview(repository: repository)
        case .fullscreen:
            CodeRepoFullscreen(repository: repository)
        }
    }
}

private struct CodeRepoPreview: View {
    let repository: CodeRepoSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing5) {
                RepoAvatar(url: repository.ownerAvatarURL, size: .spacing16)
                VStack(alignment: .leading, spacing: 0) {
                    Text(repository.owner)
                        .font(.omXxs)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(1)
                    Text(repository.name)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey100)
                        .lineLimit(1)
                }
            }

            if let description = repository.description {
                Text(description)
                    .font(.omXs)
                    .foregroundStyle(Color.grey80)
                    .lineLimit(2)
            }

            HStack(spacing: .spacing5) {
                Text("★ \(repository.compactStars)")
                Text("⑂ \(repository.compactForks)")
                Text("! \(repository.compactOpenIssues)")
            }
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.grey80)

            if !repository.metadata.isEmpty {
                Text(repository.metadata)
                    .font(.omXxs)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }
            if let updatedAt = repository.updatedAt {
                Text(updatedAt)
                    .font(.omXxs)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityIdentifier("code-repo-preview-details")
    }
}

private struct CodeRepoFullscreen: View {
    let repository: CodeRepoSummary

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                NativeEmbedDetailCard {
                    HStack(spacing: .spacing6) {
                        RepoAvatar(url: repository.ownerAvatarURL, size: .spacing20)
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(repository.owner)
                                .font(.omSmall)
                                .foregroundStyle(Color.grey70)
                            Text(repository.name)
                                .font(.omH3)
                                .fontWeight(.bold)
                                .foregroundStyle(Color.fontPrimary)
                        }
                    }
                    if let description = repository.description {
                        Text(description)
                            .font(.omP)
                            .foregroundStyle(Color.grey80)
                            .lineSpacing(.spacing2)
                    }
                    if let url = repository.url {
                        Text(url)
                            .font(.omXs)
                            .foregroundStyle(Color.buttonPrimary)
                            .textSelection(.enabled)
                    }
                }

                LazyVGrid(columns: repositoryMetricColumns, spacing: .spacing5) {
                    NativeEmbedMetricTile(label: "★", value: repository.stars.formatted())
                    NativeEmbedMetricTile(label: "⑂", value: repository.forks.formatted())
                    NativeEmbedMetricTile(label: "!", value: repository.openIssues.formatted())
                    NativeEmbedMetricTile(label: "◉", value: repository.watchers.formatted())
                }

                if !repository.projectDetails.isEmpty {
                    NativeEmbedDetailCard {
                        ForEach(repository.projectDetails, id: \.self) { detail in
                            Text(detail)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontPrimary)
                                .textSelection(.enabled)
                        }
                    }
                }

                if !repository.languages.isEmpty {
                    NativeEmbedDetailCard {
                        ForEach(repository.languages, id: \.name) { language in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                HStack {
                                    Text(language.name)
                                    Spacer()
                                    Text(language.percent.formatted(.number.precision(.fractionLength(1))) + "%")
                                }
                                .font(.omSmall)
                                .foregroundStyle(Color.fontPrimary)
                                GeometryReader { proxy in
                                    ZStack(alignment: .leading) {
                                        Capsule().fill(Color.grey20)
                                        Capsule()
                                            .fill(LinearGradient.appCode)
                                            .frame(width: proxy.size.width * CGFloat(min(max(language.percent, 0), 100) / 100))
                                    }
                                }
                                .frame(height: .spacing4)
                            }
                        }
                    }
                }

                if !repository.contributors.isEmpty {
                    NativeEmbedDetailCard {
                        ForEach(repository.contributors, id: \.login) { contributor in
                            HStack(spacing: .spacing5) {
                                RepoAvatar(url: contributor.avatarURL, size: .spacing16)
                                Text(contributor.login)
                                    .font(.omSmall)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(Color.fontPrimary)
                                Spacer()
                                Text(contributor.contributions.formatted())
                                    .font(.omXs)
                                    .foregroundStyle(Color.grey70)
                            }
                        }
                    }
                }
            }
            .padding(.spacing8)
            .frame(maxWidth: 860, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("code-repo-fullscreen")
    }

    private var repositoryMetricColumns: [GridItem] {
        [GridItem(.adaptive(minimum: 120), spacing: .spacing5)]
    }
}

struct ElectronicsComponentEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var component: ElectronicsComponentSummary { ElectronicsComponentSummary(data: data ?? [:]) }

    var body: some View {
        switch mode {
        case .preview:
            ElectronicsComponentPreview(component: component)
        case .fullscreen:
            ElectronicsComponentFullscreen(component: component)
        }
    }
}

private struct ElectronicsComponentPreview: View {
    let component: ElectronicsComponentSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(component.title)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)
            if !component.subtitle.isEmpty {
                Text(component.subtitle)
                    .font(.omXxs)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }
            LazyVGrid(columns: metricColumns, spacing: .spacing4) {
                ForEach(component.previewMetrics) { metric in
                    NativeEmbedMetricTile(label: metric.label, value: metric.value)
                }
            }
            HStack(spacing: .spacing4) {
                if let regulatorType = component.regulatorType { Text(regulatorType) }
                if let provider = component.provider { Text(provider) }
            }
            .font(.omXxs)
            .foregroundStyle(Color.grey70)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityIdentifier("electronics-component-preview")
    }

    private var metricColumns: [GridItem] {
        [GridItem(.flexible()), GridItem(.flexible())]
    }
}

private struct ElectronicsComponentFullscreen: View {
    let component: ElectronicsComponentSummary

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing6) {
                NativeEmbedDetailCard {
                    if let provider = component.provider {
                        Text(provider.uppercased())
                            .font(.omXs)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.buttonPrimary)
                    }
                    Text(component.title)
                        .font(.omH2)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                    if let description = component.description {
                        Text(description)
                            .font(.omP)
                            .foregroundStyle(Color.grey70)
                            .lineSpacing(.spacing2)
                    }
                    ForEach(component.links) { link in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(link.label)
                                .font(.omXs)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.buttonPrimary)
                            Text(link.value)
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                                .textSelection(.enabled)
                        }
                    }
                }

                ElectronicsDetailSection(
                    title: AppStrings.localized("embeds.electronics.performance"),
                    metrics: component.performanceMetrics
                )
                ElectronicsDetailSection(
                    title: AppStrings.localized("embeds.electronics.electrical"),
                    metrics: component.electricalMetrics
                )
            }
            .padding(.spacing6)
            .frame(maxWidth: 1000, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("electronics-component-fullscreen")
    }
}

private struct ElectronicsDetailSection: View {
    let title: String
    let metrics: [NativeEmbedMetric]

    var body: some View {
        if !metrics.isEmpty {
            NativeEmbedDetailCard {
                Text(title)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: .spacing3)], spacing: .spacing3) {
                    ForEach(metrics) { metric in
                        NativeEmbedMetricTile(label: metric.label, value: metric.value)
                    }
                }
            }
        }
    }
}

private struct NativeEmbedDetailCard<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            content()
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey20, lineWidth: 1))
        .shadow(color: .black.opacity(0.06), radius: .spacing8, x: 0, y: .spacing2)
    }
}

private struct NativeEmbedMetricTile: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(label.uppercased())
                .font(.omMicro)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey60)
            Text(value)
                .font(.omXs)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

private struct RepoAvatar: View {
    let url: String?
    let size: CGFloat

    var body: some View {
        if let url, let imageURL = URL(string: url) {
            CachedRemoteImage(url: imageURL) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                avatarPlaceholder
            }
            .frame(width: size, height: size)
            .clipShape(Circle())
        } else {
            avatarPlaceholder
                .frame(width: size, height: size)
                .clipShape(Circle())
        }
    }

    private var avatarPlaceholder: some View {
        LinearGradient.appCode
            .overlay(Icon("github", size: size / 2).foregroundStyle(Color.grey0))
    }
}

private struct NativeEmbedMetric: Identifiable {
    let label: String
    let value: String
    var id: String { label }
}

private struct NativeEmbedLink: Identifiable {
    let label: String
    let value: String
    var id: String { value }
}

private struct CodeRepoSummary {
    struct Language {
        let name: String
        let percent: Double
    }

    struct Contributor {
        let login: String
        let contributions: Int
        let avatarURL: String?
    }

    let url: String?
    let name: String
    let owner: String
    let ownerAvatarURL: String?
    let description: String?
    let primaryLanguage: String?
    let license: String?
    let stars: Int
    let forks: Int
    let openIssues: Int
    let watchers: Int
    let updatedAt: String?
    let projectDetails: [String]
    let languages: [Language]
    let contributors: [Contributor]

    init(data: [String: AnyCodable]) {
        url = EmbedFieldReader.string(data, keys: ["html_url", "url"])
        let fullName = EmbedFieldReader.string(data, keys: ["full_name"]) ?? url ?? ""
        name = EmbedFieldReader.string(data, keys: ["name"]) ?? fullName.split(separator: "/").last.map(String.init) ?? fullName
        owner = EmbedFieldReader.string(data, keys: ["owner_login"]) ?? fullName.split(separator: "/").first.map(String.init) ?? ""
        ownerAvatarURL = EmbedFieldReader.string(data, keys: ["owner_avatar_url"])
        description = EmbedFieldReader.string(data, keys: ["description"])
        primaryLanguage = EmbedFieldReader.string(data, keys: ["primary_language"])
        let spdx = EmbedFieldReader.string(data, keys: ["license_spdx_id"])
        let licenseValue = spdx == "NOASSERTION" ? EmbedFieldReader.string(data, keys: ["license_name"]) : spdx ?? EmbedFieldReader.string(data, keys: ["license_name"])
        license = licenseValue
        stars = CodeRendererValue.int(data, keys: ["stars"]) ?? 0
        forks = CodeRendererValue.int(data, keys: ["forks"]) ?? 0
        openIssues = CodeRendererValue.int(data, keys: ["open_issues"]) ?? 0
        watchers = CodeRendererValue.int(data, keys: ["watchers"]) ?? 0
        updatedAt = CodeRendererValue.date(EmbedFieldReader.string(data, keys: ["updated_at"]))
        projectDetails = [
            EmbedFieldReader.string(data, keys: ["default_branch"]),
            licenseValue,
            CodeRendererValue.date(EmbedFieldReader.string(data, keys: ["created_at"])),
            CodeRendererValue.date(EmbedFieldReader.string(data, keys: ["pushed_at"])),
            EmbedFieldReader.string(data, keys: ["latest_release_tag"]),
            EmbedFieldReader.string(data, keys: ["latest_commit_message"])?.split(separator: "\n").first.map(String.init),
        ].compactMap { $0 }
        languages = EmbedFieldReader.dictionaryArray(data, key: "languages").compactMap { row in
            guard let name = CodeRendererValue.string(row, key: "language") else { return nil }
            return Language(name: name, percent: CodeRendererValue.double(row, key: "percent") ?? 0)
        }
        contributors = EmbedFieldReader.dictionaryArray(data, key: "contributors").compactMap { row in
            guard let login = CodeRendererValue.string(row, key: "login") else { return nil }
            return Contributor(
                login: login,
                contributions: CodeRendererValue.int(row, key: "contributions") ?? 0,
                avatarURL: CodeRendererValue.string(row, key: "avatar_url")
            )
        }
    }

    var metadata: String { [primaryLanguage, license].compactMap { $0 }.joined(separator: " · ") }
    var compactStars: String { CodeRendererValue.compactCount(stars) }
    var compactForks: String { CodeRendererValue.compactCount(forks) }
    var compactOpenIssues: String { CodeRendererValue.compactCount(openIssues) }
}

@MainActor private struct ElectronicsComponentSummary {
    let title: String
    let provider: String?
    let topology: String?
    let packageName: String?
    let regulatorType: String?
    let description: String?
    let previewMetrics: [NativeEmbedMetric]
    let performanceMetrics: [NativeEmbedMetric]
    let electricalMetrics: [NativeEmbedMetric]
    let links: [NativeEmbedLink]

    init(data: [String: AnyCodable]) {
        let titleValue = EmbedFieldReader.string(data, keys: ["part_number", "base_part_number", "title"])
        let providerValue = EmbedFieldReader.string(data, keys: ["provider"])
        let topologyValue = EmbedFieldReader.string(data, keys: ["topology"])
        let packageValue = EmbedFieldReader.string(data, keys: ["package"])
        let regulatorTypeValue = EmbedFieldReader.string(data, keys: ["regulator_type"])
        provider = providerValue
        title = titleValue ?? providerValue ?? ""
        topology = topologyValue
        packageName = packageValue
        regulatorType = regulatorTypeValue
        description = EmbedFieldReader.string(data, keys: ["description"])

        let efficiency = CodeRendererValue.metric(data, key: "efficiency_percent", suffix: "%")
        let bomCost = CodeRendererValue.metric(data, key: "bom_cost_usd", suffix: " USD")
        let bomCount = CodeRendererValue.metric(data, key: "bom_count")
        let footprint = CodeRendererValue.metric(data, key: "footprint_mm2", suffix: " mm²")
        let frequency = CodeRendererValue.metric(data, key: "frequency_hz", suffix: " Hz")
        let outputCurrent = CodeRendererValue.metric(data, key: "max_output_current_a", suffix: " A")
        let outputRipple = CodeRendererValue.metric(data, key: "output_ripple_vpp", suffix: " Vpp")

        previewMetrics = Self.metrics([
            ("efficiency", efficiency), ("bom_cost", bomCost),
            ("footprint", footprint), ("bom_count", bomCount),
        ])
        performanceMetrics = Self.metrics([
            ("efficiency", efficiency), ("bom_cost", bomCost), ("bom_count", bomCount),
            ("footprint", footprint), ("frequency", frequency),
            ("output_current", outputCurrent), ("output_ripple", outputRipple),
        ])

        let inputVoltage = CodeRendererValue.range(data, minimum: "input_voltage_min_v", maximum: "input_voltage_max_v", suffix: " V")
        let outputVoltage = CodeRendererValue.range(data, minimum: "output_voltage_min_v", maximum: "output_voltage_max_v", suffix: " V")
        let isolated = CodeRendererValue.bool(data, key: "isolated").map {
            AppStrings.localized($0 ? "embeds.electronics.yes" : "embeds.electronics.no")
        }
        electricalMetrics = Self.metrics([
            ("input_voltage", inputVoltage), ("output_voltage", outputVoltage),
            ("topology", topologyValue), ("regulator_type", regulatorTypeValue),
            ("control_mode", EmbedFieldReader.string(data, keys: ["control_mode"])), ("isolated", isolated),
        ])

        let linkValues = [
            (AppStrings.localized("embeds.electronics.product_page"), EmbedFieldReader.string(data, keys: ["product_url"])),
            (AppStrings.localized("embeds.electronics.datasheet"), EmbedFieldReader.string(data, keys: ["datasheet_url"])),
        ]
        links = linkValues.compactMap { item in
            item.1.map { NativeEmbedLink(label: item.0, value: $0) }
        }
    }

    var subtitle: String { [topology, packageName].compactMap { $0 }.joined(separator: " / ") }

    private static func metrics(_ values: [(String, String?)]) -> [NativeEmbedMetric] {
        values.compactMap { key, value in
            value.map { NativeEmbedMetric(label: AppStrings.localized("embeds.electronics.\(key)"), value: $0) }
        }
    }
}

private enum CodeRendererValue {
    static func int(_ data: [String: AnyCodable], keys: [String]) -> Int? {
        for key in keys {
            if let value = data[key]?.value as? Int { return value }
            if let value = data[key]?.value as? Double { return Int(value) }
            if let value = data[key]?.value as? String, let parsed = Int(value) { return parsed }
        }
        return nil
    }

    static func int(_ data: [String: Any], key: String) -> Int? {
        if let value = data[key] as? Int { return value }
        if let value = data[key] as? Double { return Int(value) }
        if let value = data[key] as? String { return Int(value) }
        return nil
    }

    static func double(_ data: [String: Any], key: String) -> Double? {
        if let value = data[key] as? Double { return value }
        if let value = data[key] as? Int { return Double(value) }
        if let value = data[key] as? String { return Double(value) }
        return nil
    }

    static func string(_ data: [String: Any], key: String) -> String? {
        guard let value = data[key] as? String, !value.isEmpty else { return nil }
        return value
    }

    static func bool(_ data: [String: AnyCodable], key: String) -> Bool? {
        if let value = data[key]?.value as? Bool { return value }
        if let value = data[key]?.value as? Int { return value == 1 }
        if let value = data[key]?.value as? String {
            if value == "true" || value == "1" { return true }
            if value == "false" || value == "0" { return false }
        }
        return nil
    }

    static func metric(_ data: [String: AnyCodable], key: String, suffix: String = "") -> String? {
        guard let value = number(data, key: key) else { return nil }
        return value.formatted(.number.precision(.fractionLength(0...2))) + suffix
    }

    static func range(_ data: [String: AnyCodable], minimum: String, maximum: String, suffix: String) -> String? {
        let values = [number(data, key: minimum), number(data, key: maximum)]
            .compactMap { $0?.formatted(.number.precision(.fractionLength(0...2))) }
        guard !values.isEmpty else { return nil }
        return values.joined(separator: " – ") + suffix
    }

    static func compactCount(_ value: Int) -> String {
        guard value >= 1_000 else { return value.formatted() }
        return (Double(value) / 1_000).formatted(.number.precision(.fractionLength(value >= 10_000 ? 0 : 1))) + "k"
    }

    static func date(_ value: String?) -> String? {
        guard let value else { return nil }
        let parser = ISO8601DateFormatter()
        guard let date = parser.date(from: value) else { return value }
        return date.formatted(.dateTime.month(.abbreviated).day().year())
    }

    private static func number(_ data: [String: AnyCodable], key: String) -> Double? {
        if let value = data[key]?.value as? Double { return value }
        if let value = data[key]?.value as? Int { return Double(value) }
        if let value = data[key]?.value as? String { return Double(value) }
        return nil
    }
}
