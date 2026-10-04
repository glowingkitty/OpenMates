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
//          frontend/packages/ui/src/components/embeds/electronics/PcbSchematicEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/electronics/PcbSchematicEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/sheets/SheetEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/sheets/SheetEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/file/FileEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.surface-parity

// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open
import Combine
import SwiftUI
import WebKit
import AVFoundation
import ZIPFoundation
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

private struct EmbedSheetViewportHeightKey: EnvironmentKey {
    static let defaultValue: CGFloat? = nil
}

extension EnvironmentValues {
    /// Available fullscreen content height below the measured Sheet header.
    /// Nil permits natural sizing for standalone content.
    var embedSheetViewportHeight: CGFloat? {
        get { self[EmbedSheetViewportHeightKey.self] }
        set { self[EmbedSheetViewportHeightKey.self] = newValue }
    }
}

struct AppleCodeEmbedContent: Equatable {
    let code: String
    let hasSourcePayload: Bool
    let language: String
    let filename: String?
    let lineCount: Int

    init(data: [String: AnyCodable]?) {
        let root = data ?? [:]
        let resolved = Self.contentDictionary(in: root)
        hasSourcePayload = [resolved, root].contains { dictionary in
            ["code", "code_content", "content"].contains { dictionary[$0]?.value is String }
        }
        let rawCode = Self.string(resolved, keys: ["code", "code_content"])
            ?? Self.string(root, keys: ["code", "code_content"])
            ?? Self.contentString(in: resolved)
            ?? Self.contentString(in: root)
            ?? ""
        let languageHint = Self.string(resolved, keys: ["language"])
            ?? Self.string(root, keys: ["language"])
        let filenameHint = Self.metadataString(resolved, keys: ["filename", "path", "name"])
            ?? Self.metadataString(root, keys: ["filename", "path", "name"])
        let parsed = Self.parse(rawCode, language: languageHint, filename: filenameHint)
        code = parsed.code
        language = parsed.language
        filename = parsed.filename
        lineCount = Self.int(resolved, keys: ["line_count", "lineCount"])
            ?? Self.int(root, keys: ["line_count", "lineCount"])
            ?? Self.countLines(parsed.code)
    }

    static func parse(_ rawCode: String, language: String?, filename: String?) -> (code: String, language: String, filename: String?) {
        let normalized = rawCode
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        let firstNewline = normalized.firstIndex(of: "\n")
        let firstLine = String(normalized[..<(firstNewline ?? normalized.endIndex)])
            .replacingOccurrences(of: #"\s+$"#, with: "", options: .regularExpression)
        let header = parseLanguagePathHeader(firstLine)
        let code: String
        if header != nil, let firstNewline {
            code = String(normalized[normalized.index(after: firstNewline)...])
        } else if header != nil {
            code = ""
        } else {
            code = normalized
        }
        let usefulLanguage = language?.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedLanguage: String
        if let usefulLanguage,
           !usefulLanguage.isEmpty,
           !["text", "plaintext"].contains(usefulLanguage.lowercased()) {
            resolvedLanguage = usefulLanguage
        } else {
            resolvedLanguage = header?.language ?? ""
        }
        let usefulFilename = normalizedFilename(filename)
        return (code, resolvedLanguage, usefulFilename ?? header?.filename)
    }

    /// Null metadata denotes absence; real names such as null.md remain names.
    static func normalizedFilename(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed.lowercased() == "null" ? nil : trimmed
    }

    var previewFilename: String? {
        filename?.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init)
    }

    private static func metadataString(_ root: [String: AnyCodable], keys: [String]) -> String? {
        keys.lazy.compactMap { normalizedFilename(root[$0]?.value as? String) }.first
    }

    private static func contentDictionary(in root: [String: AnyCodable]) -> [String: AnyCodable] {
        for key in ["decodedContent", "decoded_content", "data"] {
            if let dictionary = root[key]?.value as? [String: Any] {
                return dictionary.mapValues(AnyCodable.init)
            }
            if let dictionary = root[key]?.value as? [String: AnyCodable] { return dictionary }
        }
        if let content = root["content"]?.value as? String {
            let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8),
               let dictionary = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               isRecognizedCodeWrapper(dictionary) {
                return dictionary.mapValues(AnyCodable.init)
            }
        }
        return root
    }

    private static func contentString(in root: [String: AnyCodable]) -> String? {
        root["content"]?.value as? String
    }

    private static func isRecognizedCodeWrapper(_ dictionary: [String: Any]) -> Bool {
        guard dictionary["code"] is String || dictionary["code_content"] is String else { return false }
        if dictionary["code_content"] is String { return true }
        if let type = dictionary["type"] as? String,
           ["code", "code-code"].contains(type.lowercased()) {
            return true
        }
        return ["language", "filename", "path", "line_count", "lineCount"].contains {
            dictionary[$0] != nil
        }
    }

    private static func string(_ root: [String: AnyCodable], keys: [String]) -> String? {
        keys.lazy.compactMap { root[$0]?.value as? String }.first { !$0.isEmpty }
    }

    private static func int(_ root: [String: AnyCodable], keys: [String]) -> Int? {
        for key in keys {
            if let value = root[key]?.value as? Int { return value }
            if let value = root[key]?.value as? String, let parsed = Int(value) { return parsed }
        }
        return nil
    }

    private static func parseLanguagePathHeader(_ line: String) -> (language: String, filename: String)? {
        let pattern = #"^([a-zA-Z0-9_+.#-]{1,32}):(.{1,512})$"#
        guard let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)),
              let languageRange = Range(match.range(at: 1), in: line),
              let filenameRange = Range(match.range(at: 2), in: line) else { return nil }
        let language = String(line[languageRange]).lowercased()
        let filename = String(line[filenameRange]).trimmingCharacters(in: .whitespacesAndNewlines)
        let knownURISchemes: Set<String> = [
            "data", "file", "ftp", "git", "http", "https", "mailto", "ssh", "urn", "vscode", "ws", "wss"
        ]
        let isHierarchicalURI = filename.hasPrefix("//")
        let isWindowsDrivePath = language.count == 1 && (filename.hasPrefix("\\") || filename.hasPrefix("/"))
        guard !language.allSatisfy(\.isNumber),
              !knownURISchemes.contains(language),
              !isHierarchicalURI,
              !isWindowsDrivePath,
              filename.contains(".") || filename.contains("/") || filename.contains("\\") else { return nil }
        return (language, filename)
    }

    private static func countLines(_ code: String) -> Int {
        guard !code.isEmpty else { return 0 }
        let content = code.hasSuffix("\n") ? String(code.dropLast()) : code
        return content.isEmpty ? 0 : content.components(separatedBy: "\n").count
    }
}

enum AppleCodeEmbedPreviewState: Equatable {
    case source
    case processing
    case empty

    init(content: AppleCodeEmbedContent, status: EmbedStatus) {
        if !content.code.isEmpty {
            self = .source
        } else {
            self = status == .processing ? .processing : .empty
        }
    }

    var accessibilityIdentifier: String {
        switch self {
        case .source: "code-embed-source-preview"
        case .processing: "code-embed-processing"
        case .empty: "code-embed-empty"
        }
    }
}

/// Generated application card and workspace shell. The preview uses the
/// application manifest's file and entrypoint counts, matching the web card.
struct ApplicationEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var fileRefs: [[String: Any]] { data?["file_refs"]?.value as? [[String: Any]] ?? [] }
    private var entrypoints: [Any] { data?["entrypoints"]?.value as? [Any] ?? [] }
    private var fileCount: Int { fileRefs.count }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing2) {
                placeholder
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                    .overlay(RoundedRectangle(cornerRadius: .radius3).stroke(Color.grey20))
                HStack(spacing: .spacing2) {
                    Text("\(fileCount) \(fileCount == 1 ? "file" : "files")")
                    if !entrypoints.isEmpty {
                        Text("\(entrypoints.count) \(entrypoints.count == 1 ? "entrypoint" : "entrypoints")")
                    }
                }
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("application-preview-details")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                VStack(spacing: .spacing3) {
                    RoundedRectangle(cornerRadius: .radius3)
                        .fill(Color.grey10)
                        .frame(width: 180, height: 110)
                    Text("Preview not started")
                        .font(.omH4).fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Text("Start the preview to run this generated app in an isolated sandbox.")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing8)

                VStack(alignment: .leading, spacing: .spacing4) {
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text("Preview not started").font(.omSmall).fontWeight(.semibold)
                        Text("IDLE").font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.spacing3)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))

                    Text("Logs").font(.omH4).fontWeight(.semibold)
                    Text("Start the preview to run this generated app in an isolated sandbox.")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                    Text("Files").font(.omH4).fontWeight(.semibold)
                    ForEach(Array(fileRefs.enumerated()), id: \.offset) { _, file in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(file["path"] as? String ?? "File")
                                .font(.omSmall).foregroundStyle(Color.fontPrimary)
                            Text(file["role"] as? String ?? "source")
                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.spacing2)
                        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                    }
                }
                .padding(.spacing2)
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("application-fullscreen-workspace")
        }
    }

    private var placeholder: some View {
        ZStack {
            VStack(alignment: .leading, spacing: .spacing2) {
                Capsule().fill(Color.grey30).frame(width: 34, height: 8)
                Capsule().fill(Color.grey30).frame(maxWidth: .infinity).frame(height: 10)
                Capsule().fill(Color.grey30).frame(width: 132, height: 10)
                RoundedRectangle(cornerRadius: .radius3)
                    .fill(Color.grey30.opacity(0.7))
                    .frame(height: 54)
            }
            .padding(.spacing3)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            Icon("play", size: 14)
                .foregroundStyle(.white)
                .frame(width: 42, height: 42)
                .background(LinearGradient.appCode, in: Circle())
                .shadow(color: .black.opacity(0.2), radius: 7, y: 4)
        }
        .clipped()
        .accessibilityIdentifier("application-preview-screenshot")
    }
}

/// Lazily subscribes to owner outputs only when the renderer has owner context.
@MainActor
private final class CodeEmbedOwnerOutputs: ObservableObject {
    private var store: CodeRunOutputStore?
    private var observation: AnyCancellable?

    func hydrate(chatId: String, embedId: String, embed: EmbedRecord?) async {
        if store == nil {
            let ownerStore = CodeRunOutputStore.shared
            store = ownerStore
            observation = ownerStore.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
            objectWillChange.send()
        }
        await store?.hydrate(chatId: chatId, embedId: embedId, embed: embed)
    }

    func output(chatId: String, embedId: String) -> CodeRunOutput? {
        store?.output(chatId: chatId, embedId: embedId)
    }
}

struct CodeEmbedRenderer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let data: [String: AnyCodable]?
    let embed: EmbedRecord?
    let embedId: String
    let chatId: String?
    let mode: EmbedDisplayMode
    var hasPIIMappings = false
    var piiMappings: [PIIMapping] = []
    var isPIIRevealed = false
    var onTogglePII: () -> Void = {}
    var previewActive = false
    var codeRunViewModel: CodeRunViewModel?
    var isLargePreview = false
    @StateObject private var savedOutputs = CodeEmbedOwnerOutputs()
    @State private var sourceViewportWidth: CGFloat = 0
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var content: AppleCodeEmbedContent { AppleCodeEmbedContent(data: data) }
    private var code: String { content.code }
    private var displayCode: String { EmbedPIIText.render(code, mappings: piiMappings, revealed: isPIIRevealed) }
    private var language: String { content.language }
    private var filename: String? { content.filename }
    private var lineCount: Int { content.lineCount }
    private var previewState: AppleCodeEmbedPreviewState {
        AppleCodeEmbedPreviewState(content: content, status: embed?.status ?? .finished)
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: 0) {
                if let savedOutputPreview {
                    Text(savedOutputPreview)
                        .font(.omTiny.monospaced())
                        .foregroundStyle(Color.grey10)
                        .lineLimit(isLargePreview ? 18 : 8)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .padding(.spacing4)
                        .background(Color.grey100)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        .accessibilityIdentifier("code-run-output-preview")
                } else if previewState == .processing {
                    VStack(spacing: .spacing4) {
                        Circle()
                            .fill(LinearGradient.primary)
                            .frame(width: 12, height: 12)
                        Text(LocalizationManager.shared.text("common.processing"))
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if previewState == .empty {
                    Icon("coding", size: 48)
                        .foregroundStyle(Color.fontTertiary)
                        .opacity(0.3)
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
            .accessibilityIdentifier(savedOutputPreview != nil ? "code-run-output-preview" : previewState.accessibilityIdentifier)
            .task(id: embedId) {
                guard recipientMediaContext == nil, let chatId, !chatId.isEmpty else { return }
                #if DEBUG
                if chatId == "dev-embed-preview-chat" { return }
                #endif
                await savedOutputs.hydrate(chatId: chatId, embedId: embedId, embed: embed)
            }

        case .fullscreen:
            VStack(spacing: 0) {
                if hasPIIMappings {
                    EmbedPIIToggle(isRevealed: isPIIRevealed, action: onTogglePII)
                }
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

                        if let codeRunViewModel {
                            CodeRunPanelOverlay(
                                viewModel: codeRunViewModel,
                                content: CodeRunTerminalView(
                                    viewModel: codeRunViewModel,
                                    savedOutput: savedRunOutput,
                                    chatId: chatId,
                                    embedId: embedId,
                                    file: runClientFile,
                                    onViewCode: { codeRunViewModel.closePanel() }
                                )
                                .padding(.top, .spacing8)
                                .padding(.horizontal, horizontalSizeClass == .compact ? .spacing4 : .spacing10)
                            )
                        }
                    }
                }
            }
            .background(Color.grey10)
            .task(id: embedId) {
                guard recipientMediaContext == nil, let chatId, !chatId.isEmpty else { return }
                await savedOutputs.hydrate(chatId: chatId, embedId: embedId, embed: embed)
            }
        }
    }

    private var outputPaneActive: Bool {
        previewActive
    }

    @ViewBuilder
    private func codeSourcePanel(isSplit: Bool) -> some View {
        ScrollView([.horizontal, .vertical], showsIndicators: true) {
            CodeLinesView(
                code: displayCode,
                language: language,
                showsLineNumbers: true,
                fontSize: isSplit ? 13 : 15,
                clipsLongLines: false,
                gutterWidth: 40
            )
                .padding(.top, .spacing6)
                .padding(.bottom, .spacing8)
                .padding(.trailing, .spacing4)
                // Match the web's width: 100% code-lines-container while
                // permitting intrinsic long-line overflow horizontally.
                .frame(minWidth: sourceViewportWidth, alignment: .topLeading)
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { sourceViewportWidth = $0 }
        .background(Color.grey10)
        .accessibilityIdentifier("code-source-panel")
    }

    @ViewBuilder
    private var outputPanel: some View {
        if previewActive, isPreviewable {
            CodePreviewPane(code: displayCode, language: language, filename: filename)
                .frame(minHeight: 420)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
        } else if let codeRunViewModel {
            CodeRunTerminalView(viewModel: codeRunViewModel, savedOutput: savedRunOutput,
                                chatId: chatId, embedId: embedId, file: runClientFile,
                                onViewCode: { codeRunViewModel.closePanel() })
                .frame(minHeight: 420)
        } else {
            EmptyView()
        }
    }

    private var runClientFile: CodeRunClientFile {
        CodeRunClientFile(embedId: embedId, code: displayCode, language: language, filename: filename, isTarget: true)
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
        displayCode.components(separatedBy: "\n").prefix(isLargePreview ? 21 : 8).joined(separator: "\n")
    }

    private var savedOutputPreview: String? {
        guard recipientMediaContext == nil, let chatId,
              let output = savedOutputs.output(chatId: chatId, embedId: embedId)?.output else { return nil }
        return CodeRunPreviewText.lastLines(output, limit: isLargePreview ? 18 : 8)
    }

    private var savedRunOutput: CodeRunOutput? {
        guard recipientMediaContext == nil, let chatId else { return nil }
        return savedOutputs.output(chatId: chatId, embedId: embedId)
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

private struct CodeRunPanelOverlay<Content: View>: View {
    @ObservedObject var viewModel: CodeRunViewModel
    let content: Content

    var body: some View {
        if viewModel.isPanelOpen {
            content
        }
    }
}

enum CodeRunPreviewText {
    static func lastLines(_ output: String, limit: Int) -> String? {
        var lines = output.components(separatedBy: "\n")
        while lines.last == "" { lines.removeLast() }
        let result = lines.suffix(max(limit, 0)).joined(separator: "\n")
        return result.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : result
    }
}

enum EmbedPIIText {
    static func render(_ text: String, mappings: [PIIMapping], revealed: Bool) -> String {
        guard !mappings.isEmpty else { return text }
        if revealed { return PIIDetector.restorePII(in: text, mappings: mappings) }
        var hidden = text
        for mapping in mappings.sorted(by: { $0.original.count > $1.original.count }) where !mapping.original.isEmpty {
            hidden = hidden.replacingOccurrences(of: mapping.original, with: mapping.placeholder)
        }
        return hidden
    }
}

private struct EmbedPIIToggle: View {
    let isRevealed: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: .spacing3) {
                Icon(isRevealed ? "hidden" : "visible", size: 16)
                Text(isRevealed ? AppStrings.piiHide : AppStrings.piiShow)
                    .font(.omXs.weight(.semibold))
            }
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing4)
        .background(Color.grey0)
        .accessibilityLabel(isRevealed ? AppStrings.piiHide : AppStrings.piiShow)
        .accessibilityValue(isRevealed ? "true" : "false")
        .accessibilityIdentifier("embed-pii-toggle")
    }
}

// MARK: - Generated audio

struct GeneratedAudioEmbedRenderer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let data: [String: AnyCodable]?
    let status: EmbedStatus
    let skillId: String
    let mode: EmbedDisplayMode

    @State private var player: AVAudioPlayer?
    @State private var isPlaying = false
    @State private var isLoading = false
    @State private var elapsed: TimeInterval = 0
    @State private var loadFailed = false

    private var payload: GeneratedAudioEmbedPayload { GeneratedAudioEmbedPayload(data) }
    private var identifierPrefix: String { skillId == "speak" ? "audio-speak" : "audio-generate" }
    private var skillName: String {
        AppStrings.localized(skillId == "speak" ? "app_skills.audio.speak" : "app_skills.audio.generate")
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing5) {
                HStack(spacing: .spacing4) {
                    playbackButton(compact: true)
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(skillName)
                            .font(.omP)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                        Text(payload.metadata)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                    }
                }

                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.localized("embeds.music_generate.prompt_label"))
                        .font(.omMicro)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontTertiary)
                    Text(payload.prompt ?? skillName)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(3)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("\(identifierPrefix)-preview")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing8) {
                HStack(spacing: .spacing8) {
                    playbackButton(compact: false)
                    VStack(alignment: .leading, spacing: .spacing3) {
                        audioProgress
                        Text("\(Self.duration(elapsed)) / \(Self.duration(effectiveDuration))")
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(.spacing10)
                .background(Color.grey0)
                .overlay(alignment: .bottom) { Rectangle().fill(Color.grey20).frame(height: 1) }

                VStack(alignment: .leading, spacing: .spacing6) {
                    detail(AppStrings.localized("embeds.music_generate.prompt_label"), payload.prompt ?? skillName)
                    detail(AppStrings.localized("embeds.music_generate.model_label"), payload.model ?? "ElevenLabs")
                    detail(AppStrings.localized("embeds.music_generate.duration"), Self.duration(effectiveDuration))
                }
                .padding(.spacing10)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("\(identifierPrefix)-fullscreen")
        }
    }

    @ViewBuilder
    private func playbackButton(compact: Bool) -> some View {
        if status == .processing {
            ProgressView()
                .tint(Color.buttonPrimary)
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .accessibilityIdentifier("\(identifierPrefix)-loading")
        } else if status == .error || loadFailed {
            Icon("warning", size: compact ? 22 : 28)
                .foregroundStyle(Color.error)
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .accessibilityIdentifier("\(identifierPrefix)-error")
        } else {
            Button {
                togglePlayback()
            } label: {
                Group {
                    if isLoading { ProgressView().tint(Color.grey0) }
                    else { Icon(isPlaying ? "pause" : "play", size: compact ? 18 : 22).foregroundStyle(Color.grey0) }
                }
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .background(LinearGradient.appAudio)
                .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(isLoading || !payload.hasPlayableMedia)
            .accessibilityLabel(isPlaying ? AppStrings.localized("audio.pause") : AppStrings.localized("audio.play"))
            .accessibilityIdentifier("\(identifierPrefix)-\(compact ? "preview" : "fullscreen")-play-button")
        }
    }

    private var audioProgress: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.grey20)
                Capsule().fill(LinearGradient.appAudio)
                    .frame(width: proxy.size.width * progress)
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                guard proxy.size.width > 0 else { return }
                seek(value.location.x / proxy.size.width)
            })
        }
        .frame(height: 10)
        .accessibilityElement()
        .accessibilityLabel(AppStrings.localized("audio.playback_progress"))
        .accessibilityValue("\(Int(progress * 100))%")
        .accessibilityIdentifier("\(identifierPrefix)-fullscreen-waveform")
        .task(id: isPlaying) {
            while !Task.isCancelled, isPlaying, let player {
                elapsed = player.currentTime
                if !player.isPlaying { isPlaying = false }
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
        }
    }

    private var effectiveDuration: TimeInterval { max(player?.duration ?? 0, payload.duration ?? 0) }
    private var progress: Double { effectiveDuration > 0 ? min(max(elapsed / effectiveDuration, 0), 1) : 0 }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label).font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
            Text(value).font(.omP).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
        }
    }

    private func seek(_ value: Double) {
        let next = min(max(value, 0), 1) * effectiveDuration
        elapsed = next
        player?.currentTime = next
    }

    private func togglePlayback() {
        do { try recipientMediaContext?.checkCurrent() } catch { return }
        if let player {
            if player.isPlaying { player.pause() } else { player.play() }
            isPlaying = player.isPlaying
            return
        }
        guard payload.hasPlayableMedia else { return }
        isLoading = true
        loadFailed = false
        Task {
            do {
                let bytes = try await payload.loadAudio(recipientMediaContext: recipientMediaContext)
                #if os(iOS)
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
                try AVAudioSession.sharedInstance().setActive(true)
                #endif
                try recipientMediaContext?.checkCurrent()
                let audioPlayer = try AVAudioPlayer(data: bytes)
                try recipientMediaContext?.track(audioPlayer)
                audioPlayer.prepareToPlay()
                audioPlayer.play()
                player = audioPlayer
                isPlaying = true
            } catch {
                loadFailed = true
            }
            isLoading = false
        }
    }

    fileprivate static func duration(_ seconds: TimeInterval) -> String {
        let value = max(0, Int(seconds.rounded(.down)))
        return "\(value / 60):\(String(format: "%02d", value % 60))"
    }
}

private struct GeneratedAudioEmbedPayload {
    let prompt: String?
    let model: String?
    let mode: String?
    let duration: Double?
    let directURL: String?
    let s3BaseURL: String?
    let s3Key: String?
    let aesKey: String?
    let aesNonce: String?
    let encryption: String?

    init(_ data: [String: AnyCodable]?) {
        let raw = Self.flattened(data)
        prompt = Self.string(raw, ["prompt", "text_preview", "text"])
        model = Self.string(raw, ["model"])
        mode = Self.string(raw, ["mode", "voice", "generation_type"])
        let original = Self.dictionary(Self.dictionary(raw?["files"]?.value)?["original"])
        duration = Self.number(raw?["duration_seconds"]?.value) ?? Self.number(original?["duration_seconds"])
        if let encoded = Self.string(raw, ["audio_base64"]) {
            let mime = Self.string(raw, ["mime_type"]) ?? "audio/mpeg"
            directURL = "data:\(mime);base64,\(encoded)"
        } else {
            directURL = Self.string(raw, ["previewAudioUrl", "preview_audio_url", "audio_url"])
        }
        s3BaseURL = Self.string(raw, ["s3_base_url"])
        s3Key = Self.string(original, ["s3_key"]) ?? Self.string(raw, ["files_original_s3_key"])
        aesKey = Self.string(raw, ["aes_key"])
        aesNonce = Self.string(raw, ["aes_nonce"])
        encryption = Self.string(original, ["encryption"]) ?? Self.string(raw, ["files_original_encryption"])
    }

    var modeLabel: String? { mode?.replacingOccurrences(of: "_", with: " ").capitalized }
    var metadata: String {
        [model ?? "ElevenLabs", duration.map { GeneratedAudioEmbedRenderer.duration($0) }]
            .compactMap { $0 }.joined(separator: " · ")
    }
    var hasPlayableMedia: Bool { directURL != nil || (s3Key != nil && aesKey != nil) }

    @MainActor func loadAudio(recipientMediaContext: RecipientMediaContext? = nil) async throws -> Data {
        if let directURL {
            if directURL.hasPrefix("data:"), let comma = directURL.firstIndex(of: ",") {
                let encoded = String(directURL[directURL.index(after: comma)...])
                guard let data = Data(base64Encoded: encoded) else { throw URLError(.cannotDecodeContentData) }
                try recipientMediaContext?.checkCurrent()
                if recipientMediaContext != nil, data.count > RecipientMediaTransport.maximumMediaBytes { throw URLError(.dataLengthExceedsMaximum) }
                return data
            }
            guard let url = URL(string: directURL) else { throw URLError(.badURL) }
            return try await RecipientMediaContext.download(context: recipientMediaContext, url: url)
        }
        guard let s3Key, let aesKey else { throw URLError(.badURL) }
        return try await RecipientMediaContext.fetchAndDecrypt(context: recipientMediaContext,
            s3Url: s3BaseURL ?? "",
            aesKeyHex: aesKey,
            aesNonceHex: aesNonce,
            encryption: encryption,
            s3Key: s3Key
        )
    }

    private static func flattened(_ data: [String: AnyCodable]?) -> [String: AnyCodable]? {
        guard var data else { return nil }
        if let results = data["results"]?.value as? [[String: Any]], let first = results.first {
            for (key, value) in first { data[key] = AnyCodable(value) }
        }
        return data
    }

    private static func dictionary(_ value: Any?) -> [String: Any]? {
        if let value = value as? [String: Any] { return value }
        if let value = value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return nil
    }

    private static func string(_ data: [String: AnyCodable]?, _ keys: [String]) -> String? {
        for key in keys { if let value = data?[key]?.value as? String, !value.isEmpty { return value } }
        return nil
    }

    private static func string(_ data: [String: Any]?, _ keys: [String]) -> String? {
        for key in keys { if let value = data?[key] as? String, !value.isEmpty { return value } }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return nil
    }
}

// MARK: - Notebook

/// Inert Jupyter notebook renderer. Execution remains a separate capability;
/// this view only normalizes and presents the stored notebook document.
struct NotebookEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var payload: NotebookEmbedPayload { NotebookEmbedPayload(data) }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if payload.cells.isEmpty {
                    Text(AppStrings.localized("embeds.notebook_empty"))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                } else {
                    ForEach(Array(payload.cells.prefix(3))) { cell in
                        notebookCell(cell, compact: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("notebook-preview")

        case .fullscreen:
            if payload.cells.isEmpty {
                Text(AppStrings.localized("embeds.notebook_empty"))
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.top, .spacing8)
                    .accessibilityIdentifier("notebook-fullscreen")
            } else {
                LazyVStack(alignment: .leading, spacing: .spacing6) {
                HStack(spacing: .spacing3) {
                    Icon("coding", size: 24)
                        .foregroundStyle(LinearGradient.appCode)
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(payload.filename)
                            .font(.omH4)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                        Text(payload.summary)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }

                    ForEach(payload.cells) { cell in
                        notebookCell(cell, compact: false)
                    }
                }
                .padding(.spacing8)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("notebook-fullscreen")
            }
        }
    }

    private func notebookCell(_ cell: NotebookEmbedCell, compact: Bool) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text("\(cell.index + 1). \(cell.kind.uppercased())")
                .font(.omMicro)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontTertiary)

            if cell.kind == "code" {
                CodeLinesView(
                    code: compact ? cell.previewSource : cell.source,
                    language: payload.language,
                    showsLineNumbers: !compact,
                    fontSize: compact ? 11 : 13,
                    clipsLongLines: compact
                )
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                if compact {
                    Text(cell.firstLine).font(.omSmall).foregroundStyle(Color.fontPrimary).lineLimit(2)
                } else {
                    ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(cell.source)),
                        identifier: "notebook-cell-\(cell.index)-text")
                }
            }

            if !compact, let output = cell.output, !output.isEmpty {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.localized("embeds.notebook_output"))
                        .font(.omMicro)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontSecondary)
                    ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(output), pointSize: 13),
                        identifier: "notebook-cell-\(cell.index)-output")
                }
                .padding(.spacing4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .accessibilityIdentifier("notebook-cell-output-\(cell.index)")
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(Color.grey40)
                .frame(width: 3)
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityIdentifier(compact ? "notebook-preview-cell" : "notebook-cell-\(cell.index)")
    }
}

private struct NotebookEmbedCell: Identifiable {
    let index: Int
    let kind: String
    let source: String
    let output: String?
    var id: Int { index }
    var firstLine: String { source.split(whereSeparator: \.isNewline).first.map(String.init) ?? "" }
    var previewSource: String { source.split(whereSeparator: \.isNewline).prefix(3).joined(separator: "\n") }
}

private struct NotebookEmbedPayload {
    let filename: String
    let language: String
    let cells: [NotebookEmbedCell]

    init(_ data: [String: AnyCodable]?) {
        let root = data?.mapValues(\.value) ?? [:]
        let notebook = Self.notebookDictionary(root) ?? [:]
        let metadata = Self.dictionary(notebook["metadata"]) ?? [:]
        let kernelspec = Self.dictionary(metadata["kernelspec"]) ?? [:]
        let languageInfo = Self.dictionary(metadata["language_info"]) ?? [:]
        let explicitLanguage = Self.string(root["language"])
        language = (explicitLanguage ?? Self.string(kernelspec["language"])
            ?? Self.string(languageInfo["name"]) ?? Self.string(kernelspec["name"]) ?? "unknown")
            .lowercased()
            .replacingOccurrences(of: "python3", with: "python")

        let rawFilename = Self.string(root["filename"]) ?? "notebook.ipynb"
        let leaf = rawFilename.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? "notebook.ipynb"
        filename = leaf.lowercased().hasSuffix(".ipynb") ? leaf : "\(leaf).ipynb"

        cells = Self.array(notebook["cells"]).enumerated().compactMap { index, rawCell in
            guard let cell = Self.dictionary(rawCell) else { return nil }
            let kind = Self.string(cell["cell_type"]) ?? "raw"
            let source = Self.sourceText(cell["source"])
            let output = Self.outputText(cell["outputs"])
            return NotebookEmbedCell(index: index, kind: kind, source: source, output: output)
        }
    }

    @MainActor var summary: String {
        let key = cells.count == 1 ? "embeds.notebook_cell_singular" : "embeds.notebook_cell_plural"
        return "\(cells.count) \(AppStrings.localized(key)), \(AppStrings.localized("embeds.notebook_type"))"
    }

    private static func notebookDictionary(_ root: [String: Any]) -> [String: Any]? {
        if let notebook = dictionary(root["notebook"]) { return notebook }
        if let content = dictionary(root["content"]) { return content }
        if let content = string(root["content"]),
           let decoded = try? JSONSerialization.jsonObject(with: Data(content.utf8)),
           let dictionary = decoded as? [String: Any] { return dictionary }
        return array(root["cells"]).isEmpty ? nil : root
    }

    private static func sourceText(_ value: Any?) -> String {
        if let value = string(value) { return value }
        return array(value).compactMap(string).joined()
    }

    private static func outputText(_ value: Any?) -> String? {
        let outputs = array(value)
        let lines = outputs.compactMap { item -> String? in
            guard let output = dictionary(item) else { return string(item) }
            if let text = output["text"] { return sourceText(text) }
            if let traceback = output["traceback"] { return sourceText(traceback) }
            if let data = dictionary(output["data"]), let plain = data["text/plain"] { return sourceText(plain) }
            let error = [string(output["ename"]), string(output["evalue"])].compactMap { $0 }
            return error.isEmpty ? nil : error.joined(separator: ": ")
        }.filter { !$0.isEmpty }
        return lines.isEmpty ? nil : lines.joined(separator: "\n")
    }

    private static func dictionary(_ value: Any?) -> [String: Any]? {
        if let value = value as? [String: Any] { return value }
        if let value = value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return nil
    }

    private static func array(_ value: Any?) -> [Any] {
        if let value = value as? [Any] { return value }
        if let value = value as? [AnyCodable] { return value.map(\.value) }
        return []
    }

    private static func string(_ value: Any?) -> String? {
        if let value = value as? String, !value.isEmpty { return value }
        if let value = value as? AnyCodable { return string(value.value) }
        return nil
    }
}

// MARK: - Safe file metadata

struct FileEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let status: EmbedStatus
    private var payload: FileEmbedPayload { FileEmbedPayload(data) }

    var body: some View {
        switch mode {
        case .preview:
            Group {
                if status == .processing {
                    Text(AppStrings.localized("apps.file"))
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    VStack(spacing: .spacing4) {
                        Icon("files", size: 46)
                            .foregroundStyle(LinearGradient.appFiles)
                        Text(payload.filename)
                            .font(.omP)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(1)
                        if !payload.metadata.isEmpty {
                            Text(payload.metadata)
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                                .lineLimit(1)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("file-embed-preview")

        case .fullscreen:
            // The rendered web card remains a row on phones: its source
            // container query currently has no named ancestor to activate it.
            HStack(alignment: .center, spacing: .spacing12) {
                fileIcon
                fileDetails
            }
            .padding(.spacing16)
            .frame(maxWidth: 748, alignment: .leading)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey25, lineWidth: 1) }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("file-embed-fullscreen")
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing16)
            .frame(maxWidth: .infinity)
        }
    }

    private var fileIcon: some View {
        // FileEmbedFullscreen's raw .icon.files span currently has no mask.
        // Reproduce its rendered grey fallback block rather than an SVG glyph.
        RoundedRectangle(cornerRadius: .radius6)
            .fill(LinearGradient(stops: [
                .init(color: Color.grey20, location: 0.0904),
                .init(color: Color.grey30, location: 0.9006)
            ], startPoint: .topLeading, endPoint: .bottomTrailing))
            .frame(width: 68, height: 68)
            .accessibilityHidden(true)
    }

    private var fileDetails: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(payload.path)
                .font(.omH4)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .textSelection(.enabled)
            Text(payload.metadata)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            if payload.availableDownloadURL == nil {
                Text(AppStrings.localized("app_skills.code.run.download_unavailable"))
                    .font(.omSmall)
                    .foregroundStyle(Color.warning)
                    .accessibilityIdentifier("file-download-unavailable")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct FileEmbedPayload {
    let path: String
    let filename: String
    let mimeType: String
    let sizeBytes: Int64?
    let downloadURL: URL?
    let downloadExpiresAt: TimeInterval?

    init(_ data: [String: AnyCodable]?) {
        let pathValue = Self.string(data, keys: ["normalized_path", "path", "filename"]) ?? "File"
        path = pathValue
        filename = Self.string(data, keys: ["filename"])
            ?? pathValue.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init)
            ?? pathValue
        mimeType = Self.string(data, keys: ["mime_type"]) ?? "application/octet-stream"
        sizeBytes = Self.number(data?["size_bytes"]?.value).map { Int64($0) }
        downloadURL = Self.string(data, keys: ["download_url"]).flatMap(URL.init(string:))
        downloadExpiresAt = Self.number(data?["download_expires_at"]?.value)
    }

    var metadata: String {
        [mimeType, sizeBytes.map(Self.formatBytes)].compactMap { $0 }.joined(separator: " · ")
    }

    var availableDownloadURL: URL? {
        availableDownloadURL(at: Date().timeIntervalSince1970)
    }

    func availableDownloadURL(at now: TimeInterval) -> URL? {
        guard let downloadURL else { return nil }
        guard let downloadExpiresAt, downloadExpiresAt != 0 else { return downloadURL }
        return downloadExpiresAt > now ? downloadURL : nil
    }

    private static func string(_ data: [String: AnyCodable]?, keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty { return value }
        }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? Int64 { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return nil
    }

    private static func formatBytes(_ count: Int64) -> String {
        if count < 1024 { return "\(count) B" }
        if count < 1_048_576 { return String(format: "%.1f KB", locale: Locale(identifier: "en_US_POSIX"), Double(count) / 1024) }
        return String(format: "%.1f MB", locale: Locale(identifier: "en_US_POSIX"), Double(count) / 1_048_576)
    }
}

private struct CodeRunTerminalView: View {
    @ObservedObject var viewModel: CodeRunViewModel
    let savedOutput: CodeRunOutput?
    let chatId: String?
    let embedId: String
    let file: CodeRunClientFile
    let onViewCode: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            viewCodeButton
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(displayEvents) { event in
                        ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(event.text),
                            pointSize: 15, color: color(for: event.kind), monospace: true, bold: true),
                            identifier: "code-run-output-selection-\(event.id)")
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .accessibilityIdentifier("code-run-output-text")
                            .accessibilityLabel(event.text)
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
        .overlay(alignment: .topLeading) {
            Color.clear.frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityIdentifier("code-run-terminal")
                .allowsHitTesting(false)
        }
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

    private var displayEvents: [CodeRunEvent] {
        if viewModel.status != .idle || !viewModel.events.isEmpty { return viewModel.events }
        if let savedOutput, !savedOutput.events.isEmpty { return savedOutput.events }
        guard let output = savedOutput?.output, !output.isEmpty else { return [] }
        return [CodeRunEvent(kind: .stdout, text: output, timestamp: savedOutput?.savedAt ?? 0)]
    }

    private var copyableOutput: String {
        if viewModel.status != .idle || !viewModel.events.isEmpty { return viewModel.programOutputText }
        return savedOutput?.output ?? ""
    }

    private func copyOutput() {
        guard !copyableOutput.isEmpty else { return }
        #if os(iOS)
        UIPasteboard.general.string = copyableOutput
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(copyableOutput, forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.codeRunOutputCopied, type: .success)
    }

    private var terminalActions: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if viewModel.isActive {
                terminalAction(viewModel.isCancelling ? AppStrings.codeRunCancelling : AppStrings.codeRunStop, disabled: viewModel.isCancelling) {
                    viewModel.cancel()
                }
            }
            terminalAction(AppStrings.codeRunAskFollowup, disabled: true) {}
            terminalAction(AppStrings.codeRunCopyOutput, disabled: copyableOutput.isEmpty,
                           identifier: "code-run-copy-output") {
                copyOutput()
            }
            terminalAction(AppStrings.codeRunAgain, disabled: viewModel.isActive) {
                Task { await viewModel.start(chatId: chatId, embedId: embedId, file: file) }
            }
        }
    }

    private func terminalAction(_ title: String, disabled: Bool,
                                identifier: String? = nil, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text("> \(title)")
                .font(.system(size: 15, weight: .bold, design: .monospaced))
                .foregroundStyle(disabled ? Color(hex: 0x707070) : Color(hex: 0xBCBCBC))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .help(Text(title))
        .accessibilityLabel(title)
        .accessibilityIdentifier(identifier ?? title)
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
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        if !clipsLongLines {
            HStack(alignment: .top, spacing: .spacing4) {
                if showsLineNumbers {
                    VStack(alignment: .trailing, spacing: 0) {
                        ForEach(Array(lines.enumerated()), id: \.offset) { index, _ in
                            Text("\(index + 1)")
                                .font(.system(size: fontSize, design: .monospaced))
                                .foregroundStyle(Color.grey60)
                                .frame(width: gutterWidth, height: fontSize * 1.6, alignment: .trailing)
                        }
                    }
                    .textSelection(.disabled)
                }
                ReadOnlySelectableText(content: CodeSelectableSource.attributed(code: code, language: language,
                    fontSize: fontSize, colorScheme: colorScheme), identifier: "code-readonly-source", wrapsText: false)
                    .fixedSize(horizontal: true, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
        } else {
            previewLines
        }
    }

    private var previewLines: some View {
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

/// Continuous source storage preserves selected newlines/indentation without
/// copying the separately rendered, non-selectable line-number gutter.
@MainActor
enum CodeSelectableSource {
    static func attributed(code: String, language: String, fontSize: CGFloat, colorScheme: ColorScheme) -> NSAttributedString {
        var source = AttributedString()
        let lines = code.components(separatedBy: "\n")
        for (index, line) in lines.enumerated() {
            if index > 0 { source.append(AttributedString("\n")) }
            for token in CodeSyntaxHighlighter.tokens(for: line, language: language, colorScheme: colorScheme) {
                var run = AttributedString(token.text)
                run.foregroundColor = token.color
                source.append(run)
            }
        }
        return ReadOnlySelectableText.attributed(source, pointSize: fontSize, monospace: true, lineHeight: fontSize * 1.6)
    }
}

private struct HighlightedCodeLine: View {
    @Environment(\.colorScheme) private var colorScheme
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
        for token in CodeSyntaxHighlighter.tokens(for: line, language: language, colorScheme: colorScheme) {
            var chunk = AttributedString(token.text)
            chunk.foregroundColor = token.color
            result += chunk
        }
        return result
    }
}

struct CodeSyntaxHighlighter {
    private let colors: SyntaxColor

    struct Token {
        let text: String
        let color: Color
    }

    static func tokens(for line: String, language: String, colorScheme: ColorScheme = .dark) -> [Token] {
        CodeSyntaxHighlighter(colors: SyntaxColor(colorScheme: colorScheme)).tokenize(line, language: language)
    }

    private func tokenize(_ line: String, language: String) -> [Token] {
        if isHTMLLike(language) {
            return htmlTokens(for: line)
        }
        if isCSSLike(language) || line.contains("--") || line.contains("{") || line.contains(":") {
            return cssTokens(for: line)
        }
        return genericTokens(for: line)
    }

    private func genericTokens(for line: String) -> [Token] {
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
                tokens.append(Token(text: String(line[start..<index]), color: colors.string))
            } else if line[index].isNumber {
                let start = index
                while index < line.endIndex, line[index].isNumber {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: colors.number))
            } else {
                let start = index
                index = line.index(after: index)
                tokens.append(Token(text: String(line[start..<index]), color: colors.base))
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: colors.base)] : tokens
    }

    private func htmlTokens(for line: String) -> [Token] {
        var tokens: [Token] = []
        var index = line.startIndex
        while index < line.endIndex {
            if line[index...].hasPrefix("<!--") {
                let end = line[index...].range(of: "-->")?.upperBound ?? line.endIndex
                tokens.append(Token(text: String(line[index..<end]), color: colors.comment))
                index = end
            } else if line[index] == "<",
                      let end = line[index...].firstIndex(of: ">") {
                appendHTMLTagTokens(String(line[index...end]), to: &tokens)
                index = line.index(after: end)
            } else {
                let start = index
                // A clipped tag or literal '<' must still consume source text.
                index = line.index(after: index)
                while index < line.endIndex, line[index] != "<" {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: colors.base))
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: colors.base)] : tokens
    }

    private func appendHTMLTagTokens(_ tag: String, to tokens: inout [Token]) {
        let delimiters = CharacterSet(charactersIn: "</>=")
        var current = ""
        var inString: Character?
        for scalar in tag.unicodeScalars {
            let char = Character(scalar)
            if let quote = inString {
                current.append(char)
                if char == quote {
                    tokens.append(Token(text: current, color: colors.string))
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
                tokens.append(Token(text: String(char), color: colors.punctuation))
            } else if CharacterSet.whitespaces.contains(scalar) {
                flushHTMLWord(current, to: &tokens)
                current = ""
                tokens.append(Token(text: String(char), color: colors.base))
            } else {
                current.append(char)
            }
        }
        if !current.isEmpty {
            if inString != nil {
                tokens.append(Token(text: current, color: colors.string))
            } else {
                flushHTMLWord(current, to: &tokens)
            }
        }
    }

    private func flushHTMLWord(_ text: String, to tokens: inout [Token]) {
        guard !text.isEmpty else { return }
        if text.hasPrefix("!") || text.lowercased() == "doctype" {
            tokens.append(Token(text: text, color: colors.meta))
        } else if text.first?.isLetter == true {
            let color = tokens.last?.text == "<" || tokens.last?.text == "/" ? colors.name : colors.attribute
            tokens.append(Token(text: text, color: color))
        } else {
            tokens.append(Token(text: text, color: colors.base))
        }
    }

    private func cssTokens(for line: String) -> [Token] {
        var tokens: [Token] = []
        var index = line.startIndex
        while index < line.endIndex {
            if line[index...].hasPrefix("/*"),
               let end = line[index...].range(of: "*/")?.upperBound {
                tokens.append(Token(text: String(line[index..<end]), color: colors.comment))
                index = end
            } else if line[index] == "#" {
                let start = index
                index = line.index(after: index)
                while index < line.endIndex, line[index].isHexDigit {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: colors.number))
            } else if line[index] == "\"" || line[index] == "'" {
                let quote = line[index]
                let start = index
                index = line.index(after: index)
                while index < line.endIndex, line[index] != quote {
                    index = line.index(after: index)
                }
                if index < line.endIndex { index = line.index(after: index) }
                tokens.append(Token(text: String(line[start..<index]), color: colors.string))
            } else if line[index].isNumber {
                let start = index
                while index < line.endIndex, line[index].isNumber || line[index] == "." || line[index] == "%" {
                    index = line.index(after: index)
                }
                tokens.append(Token(text: String(line[start..<index]), color: colors.number))
            } else if line[index].isLetter || line[index] == "-" {
                let start = index
                while index < line.endIndex, line[index].isLetter || line[index].isNumber || line[index] == "-" || line[index] == "_" {
                    index = line.index(after: index)
                }
                let word = String(line[start..<index])
                let next = line[index...].first { !$0.isWhitespace }
                tokens.append(Token(text: word, color: next == ":" ? colors.attribute : colors.name))
            } else {
                tokens.append(Token(text: String(line[index]), color: colors.base))
                index = line.index(after: index)
            }
        }
        return tokens.isEmpty ? [Token(text: line, color: colors.base)] : tokens
    }

    private func isHTMLLike(_ language: String) -> Bool {
        ["html", "htm", "xml", "svg", "svelte"].contains(language.lowercased())
    }

    private func isCSSLike(_ language: String) -> Bool {
        ["css", "scss", "sass", "less"].contains(language.lowercased())
    }
}

/// The web preview's explicit GitHub light overrides and existing GitHub dark
/// palette. These are syntax theme values, not application design tokens.
private struct SyntaxColor {
    let colorScheme: ColorScheme

    private func color(light: UInt32, dark: UInt32) -> Color {
        Color(hex: colorScheme == .light ? light : dark)
    }

    var base: Color { colorScheme == .light ? Color(hex: 0x24292E) : Color.grey100 }
    var punctuation: Color { color(light: 0x24292E, dark: 0x79C0FF) }
    var name: Color { color(light: 0xB31D28, dark: 0x7EE787) }
    var attribute: Color { color(light: 0x005CC5, dark: 0x79C0FF) }
    var string: Color { color(light: 0x032F62, dark: 0xA5D6FF) }
    var number: Color { color(light: 0x005CC5, dark: 0xD2A8FF) }
    var meta: Color { color(light: 0x005CC5, dark: 0x79C0FF) }
    var comment: Color { color(light: 0x6A737D, dark: 0x8B949E) }
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

    final class Coordinator {
        var loadedHTML: String?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        WKWebView()
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.loadedHTML != html else { return }
        context.coordinator.loadedHTML = html
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#elseif os(macOS)
private struct CodeHTMLPreview: NSViewRepresentable {
    let html: String

    final class Coordinator {
        var loadedHTML: String?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        WKWebView()
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.loadedHTML != html else { return }
        context.coordinator.loadedHTML = html
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#endif

struct CodeGetDocsEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    static func libraryID(from data: [String: AnyCodable]?) -> String? {
        guard let data else { return nil }
        let results = (data["results"]?.value as? [[String: Any]])
            ?? (data["results"]?.value as? [[String: AnyCodable]])?.map { $0.mapValues(\.value) }
            ?? []
        let first = results.first ?? [:]
        if let value = first["library_id"] as? String, !value.isEmpty { return value }
        if let library = first["library"] as? [String: Any],
           let value = library["id"] as? String, !value.isEmpty { return value }
        if let library = first["library"] as? [String: AnyCodable],
           let value = library["id"]?.value as? String, !value.isEmpty { return value }
        return data["library"]?.value as? String
    }

    private var title: String? { Self.libraryID(from: data) }
    private var documentation: String? {
        firstResultString(["documentation", "content", "text"])
            ?? firstString(["documentation", "content"])
    }
    private var question: String? { firstString(["question", "query"]) }
    private var previewWordCount: Int? {
        firstInt(["word_count", "wordCount"]) ?? firstResultInt(["word_count", "wordCount"])
    }
    private var fullWordCount: Int {
        documentation?.split(whereSeparator: \.isWhitespace).count ?? 0
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
                if let wordCount = previewWordCount {
                    Text("\(wordCount.formatted()) words")
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)

        case .fullscreen:
            VStack(spacing: .spacing8) {
                if fullWordCount > 0 {
                    Text("via Context7: \(fullWordCount.formatted()) words")
                        .font(.omSmall)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey70)
                        .frame(maxWidth: .infinity)
                }
                if let documentation, !documentation.isEmpty {
                    RichMarkdownView(content: documentation, isUserMessage: false)
                        .environment(\.messageTextSelection, nil)
                        .environment(\.readOnlyTextSelection, true)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                        .padding(.spacing12)
                        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 30))
                        .shadow(color: .black.opacity(0.1), radius: 8, y: -4)
                } else {
                    Text("No documentation available")
                        .font(.omP)
                        .foregroundStyle(Color.grey70)
                        .frame(maxWidth: .infinity, minHeight: 200)
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing12)
            .padding(.bottom, 120)
            .accessibilityIdentifier("code-get-docs-fullscreen")
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

    var body: some View {
        DocumentCanvasView(source: DocumentCanvasSource(data: data), mode: mode)
    }
}

struct SheetRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    var hasPIIMappings = false
    var piiMappings: [PIIMapping] = []
    var isPIIRevealed = false
    var onTogglePII: () -> Void = {}
    var onDisplayedRowsChange: (([[String]]) -> Void)? = nil
    var isLargePreview = false

    private var table: ParsedSheetTable {
        ParsedSheetTable(data: data).applyingPII(mappings: piiMappings, revealed: isPIIRevealed)
    }

    var body: some View {
        switch mode {
        case .preview:
            SheetPreviewTable(table: table, isLargePreview: isLargePreview)

        case .fullscreen:
            SheetFullscreenTable(table: table, hasPIIMappings: hasPIIMappings,
                                 isPIIRevealed: isPIIRevealed, onTogglePII: onTogglePII,
                                 onDisplayedRowsChange: onDisplayedRowsChange)
        }
    }
}

private struct SheetPreviewTable: View {
    let table: ParsedSheetTable
    let isLargePreview: Bool

    // This table explicitly uses the browser's Apple system font stack,
    // overriding the surrounding Lexend UI. Rendered reference: 11px/1.3
    // compact, 13px/1.3 large; header overflow counter is 9px.
    private var cellFontSize: CGFloat { isLargePreview ? 13 : 11 }

    private var maxRows: Int { isLargePreview ? 8 : 4 }
    private var remainingRowCount: Int { max(table.rows.count - maxRows, 0) }

    var body: some View {
        GeometryReader { geometry in
            let columns = SheetPreviewColumns(headers: table.headers, rows: Array(table.rows.prefix(maxRows)),
                                              budget: isLargePreview ? max(geometry.size.width - 20, 0) : 260)
            let visibleHeaders = Array(table.headers.prefix(columns.visibleCount))
            let visibleRows = Array(table.rows.prefix(maxRows))
            let hiddenColumnCount = max(table.headers.count - visibleHeaders.count, 0)
            // HTML table auto layout stretches large tables across their container.
            let naturalWidth = columns.widths.prefix(columns.visibleCount).reduce(0, +) + (hiddenColumnCount > 0 ? 45 : 0)
            let extraWidth = max(geometry.size.width - naturalWidth, 0) / CGFloat(max(visibleHeaders.count, 1))
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
                                sheetCell(visibleHeaders[index], isHeader: true, width: columns.widths[index] + extraWidth)
                            }
                            if hiddenColumnCount > 0 {
                                sheetCell("+\(hiddenColumnCount)", isHeader: true, isMuted: true, width: 45)
                            }
                        }
                        ForEach(visibleRows.indices, id: \.self) { rowIndex in
                            GridRow {
                                ForEach(visibleHeaders.indices, id: \.self) { colIndex in
                                    sheetCell(visibleRows[rowIndex].indices.contains(colIndex) ? visibleRows[rowIndex][colIndex] : "", isHeader: false, alternate: rowIndex.isMultiple(of: 2) == false, width: columns.widths[colIndex] + extraWidth)
                                }
                                if hiddenColumnCount > 0 {
                                    sheetCell("", isHeader: false, isMuted: true, alternate: rowIndex.isMultiple(of: 2) == false, width: 45)
                                }
                            }
                        }
                        if remainingRowCount > 0 {
                            GridRow {
                                Text("+\(remainingRowCount) more rows")
                                    .font(.system(size: cellFontSize))
                                    .italic()
                                    .foregroundStyle(Color.grey50)
                                    .padding(.vertical, 3)
                                    .frame(maxWidth: .infinity)
                                    .gridCellColumns(visibleHeaders.count + (hiddenColumnCount > 0 ? 1 : 0))
                                    .background(Color.grey25)
                                    .accessibilityIdentifier("sheet-preview-more-rows")
                            }
                        }
                    }
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(.top, 15)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .clipped()
            .accessibilityIdentifier("sheet-preview-table")
        }
    }

    private func sheetCell(_ text: String, isHeader: Bool, isMuted: Bool = false, alternate: Bool = false, width: CGFloat) -> some View {
        Text(text)
            .font(.system(size: isMuted && isHeader ? 9 : cellFontSize))
            .fontWeight(isHeader ? .semibold : .regular)
            .foregroundStyle(isMuted ? Color.fontTertiary : (isHeader ? Color.fontPrimary : Color.fontSecondary))
            .lineLimit(1)
            .padding(.horizontal, .spacing4)
            .frame(height: cellFontSize * 1.3 + .spacing4 + 1)
            .frame(width: width, alignment: .leading)
            .background(isHeader || alternate || isMuted ? Color.grey10 : Color.clear)
            .overlay(
                Rectangle()
                    .stroke(Color.grey25, lineWidth: 1)
            )
    }
}

// SheetEmbedPreview.svelte measures each column from visible text (8px per
// character, clamped to 60...200) and shows the columns that fit a 260px card.
struct SheetPreviewColumns {
    let widths: [CGFloat]
    let visibleCount: Int

    init(headers: [String], rows: [[String]], budget: CGFloat = 260) {
        widths = headers.indices.map { index in
            let length = max(headers[index].count, rows.map { $0.indices.contains(index) ? $0[index].count : 0 }.max() ?? 0)
            return min(max(CGFloat(length * 8), 60), 200)
        }
        var used: CGFloat = 0
        var count = 0
        for width in widths {
            if count > 0 && used + width > budget { break }
            used += width
            count += 1
        }
        visibleCount = count
    }
}

private struct SheetFullscreenTable: View {
    let table: ParsedSheetTable
    var hasPIIMappings = false
    var isPIIRevealed = false
    var onTogglePII: () -> Void = {}
    var onDisplayedRowsChange: (([[String]]) -> Void)? = nil
    @State private var sortColumnIndex: Int?
    @State private var sortAscending = true
    @State private var showFilters = false
    @State private var filters: [String] = []
    @Environment(\.embedSheetViewportHeight) private var viewportHeight

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
            if hasPIIMappings {
                EmbedPIIToggle(isRevealed: isPIIRevealed, action: onTogglePII)
            }
            if showFilters {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: .spacing3) {
                        ForEach(table.headers.indices, id: \.self) { index in
                            TextField(table.headers[index], text: bindingForFilter(index))
                                .accessibilityIdentifier("sheet-filter-input-\(index)")
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
        .frame(maxWidth: .infinity)
        .frame(height: viewportHeight)
        .onAppear {
            filters = Array(repeating: "", count: table.headers.count)
            onDisplayedRowsChange?(displayRows)
        }
        .onChange(of: displayRows) { _, rows in onDisplayedRowsChange?(rows) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sheet-fullscreen-table")
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
        let maxRowLen = displayRows.map { $0.indices.contains(index) ? $0[index].count : 0 }.max() ?? 0
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
// SheetEmbedFullscreen.svelte overrides its normal Lexend typography with the
// system font and switches spacing at the browser viewport's 768px breakpoint.
struct SheetFullscreenTableMetrics {
    let viewportWidth: CGFloat
    var isMobile: Bool { viewportWidth <= 768 }
    // CSS widths/min-widths use content-box; the collapsed grid contributes one pixel.
    var gutterWidth: CGFloat { (isMobile ? 32 : 40) + horizontalPadding * 2 + 1 }
    var horizontalPadding: CGFloat { isMobile ? .spacing4 : .spacing6 }
    var verticalPadding: CGFloat { isMobile ? 5 : .spacing3 }
    var letterVerticalPadding: CGFloat { isMobile ? 5 : .spacing1 }
    var font: UIFont { .systemFont(ofSize: isMobile ? 12 : 13, weight: .medium) }
    var headerFont: UIFont { .systemFont(ofSize: font.pointSize, weight: .semibold) }
    var letterFont: UIFont { .systemFont(ofSize: 11, weight: .medium) }
    var lineHeight: CGFloat { floor(font.pointSize * 1.4 * 64) / 64 }
    var letterRowHeight: CGFloat { 22 + letterVerticalPadding * 2 + 1 }
    var headerRowHeight: CGFloat { lineHeight + verticalPadding * 2 + 1.5 }

    func contentWidth(for columnWidth: CGFloat) -> CGFloat {
        max(1, columnWidth - horizontalPadding * 2 - 1)
    }

    /// CSS auto table layout shrinks preferred <col> widths toward each header
    /// minimum when the wrapper is narrow, then overflows rather than squeezing
    /// the 80px content-box minimum or the nowrap header and sort control.
    func resolvedColumnWidths(headers: [String], preferredWidths: [CGFloat], availableWidth: CGFloat) -> [CGFloat] {
        let minimums = headers.map { header in
            let textWidth = (header as NSString).size(withAttributes: [.font: headerFont]).width
            return max(80, textWidth + .spacing2 + 10) + horizontalPadding * 2 + 1
        }
        let preferred = minimums.enumerated().map { index, minimum in
            max(minimum, preferredWidths.indices.contains(index) ? preferredWidths[index] : minimum)
        }
        let minimumTotal = minimums.reduce(gutterWidth + 1, +)
        let preferredTotal = preferred.reduce(gutterWidth + 1, +)
        guard preferredTotal > minimumTotal else { return minimums }
        let fraction = min(1, max(0, (availableWidth - minimumTotal) / (preferredTotal - minimumTotal)))
        return zip(minimums, preferred).map { minimum, desired in minimum + (desired - minimum) * fraction }
    }

    func attributedValue(_ text: String) -> NSAttributedString {
        let paragraph = NSMutableParagraphStyle()
        paragraph.minimumLineHeight = lineHeight
        paragraph.maximumLineHeight = lineHeight
        paragraph.lineBreakMode = .byWordWrapping
        return NSAttributedString(string: text, attributes: [
            .font: font, .foregroundColor: UIColor(Color.fontPrimary), .paragraphStyle: paragraph
        ])
    }

    func rowHeight(values: [String], columnWidths: [CGFloat]) -> CGFloat {
        var textHeight = lineHeight
        for (index, value) in values.enumerated() where columnWidths.indices.contains(index) {
            // Use the same TextKit engine as the selectable UITextView cells,
            // including break-word fallback when a word exceeds the column.
            let storage = NSTextStorage(attributedString: attributedValue(value))
            let manager = NSLayoutManager()
            let container = NSTextContainer(size: CGSize(
                width: contentWidth(for: columnWidths[index]),
                height: .greatestFiniteMagnitude))
            container.lineFragmentPadding = 0
            container.lineBreakMode = .byWordWrapping
            manager.addTextContainer(container)
            storage.addLayoutManager(manager)
            manager.ensureLayout(for: container)
            textHeight = max(textHeight, manager.usedRect(for: container).height)
        }
        return textHeight + verticalPadding * 2 + 1
    }
}

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
        layout.configure(headers: headers, rows: rows, widths: columnWidths,
                         viewportWidth: 0)
        let collectionView = UICollectionView(frame: .zero, collectionViewLayout: layout)
        // The representable owns the table's AX node; SwiftUI may flatten its
        // enclosing VStack while preserving these native cells and controls.
        collectionView.accessibilityIdentifier = "sheet-fullscreen-table"
        collectionView.backgroundColor = UIColor(Color.grey20)
        collectionView.alwaysBounceVertical = true
        collectionView.alwaysBounceHorizontal = true
        collectionView.showsVerticalScrollIndicator = true
        collectionView.showsHorizontalScrollIndicator = true
        collectionView.contentInset.top = 0
        collectionView.dataSource = context.coordinator
        collectionView.delegate = context.coordinator
        collectionView.register(SheetFullscreenCollectionCell.self, forCellWithReuseIdentifier: SheetFullscreenCollectionCell.reuseIdentifier)
        return collectionView
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UICollectionView, context: Context) -> CGSize? {
        guard let layout = uiView.collectionViewLayout as? SheetFullscreenCollectionLayout else { return nil }
        layout.configure(headers: headers, rows: rows, widths: columnWidths,
                         viewportWidth: uiView.window?.bounds.width ?? proposal.width ?? columnWidths.reduce(40, +),
                         availableWidth: proposal.width)
        // Fullscreen content sits inside a vertical SwiftUI ScrollView, whose
        // height proposal is nil. UICollectionView has no intrinsic height;
        // provide the table's extent so its visible cells do not collapse.
        return CGSize(
            width: proposal.width ?? layout.columnWidths.reduce(0, +),
            height: proposal.height ?? (layout.totalContentHeight + uiView.contentInset.vertical)
        )
    }

    func updateUIView(_ collectionView: UICollectionView, context: Context) {
        context.coordinator.parent = self
        if let layout = collectionView.collectionViewLayout as? SheetFullscreenCollectionLayout {
            layout.configure(headers: headers, rows: rows, widths: columnWidths,
                             viewportWidth: collectionView.window?.bounds.width ?? collectionView.bounds.width,
                             availableWidth: collectionView.bounds.width > 0 ? collectionView.bounds.width : nil)
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
            let metrics = (collectionView.collectionViewLayout as? SheetFullscreenCollectionLayout)?.metrics
                ?? SheetFullscreenTableMetrics(viewportWidth: collectionView.bounds.width)
            cell.configure(with: cellModel(for: indexPath.item), metrics: metrics)
            cell.onActivate = { [weak self, weak collectionView] in
                guard let self, let collectionView else { return }
                self.collectionView(collectionView, didSelectItemAt: indexPath)
            }
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
                return .init(text: header, kind: .header(columnIndex: columnIndex,
                                                       ascending: isActive ? parent.sortAscending : nil))
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

final class SheetFullscreenCollectionLayout: UICollectionViewLayout {
    var columnWidths: [CGFloat] = []
    private(set) var metrics = SheetFullscreenTableMetrics(viewportWidth: 0)
    private var rowHeights: [CGFloat] = []
    private var rowOffsets: [CGFloat] = []
    private var measuredRows: [[String]] = []
    private var measuredHeaders: [String] = []
    private var measuredWidths: [CGFloat] = []
    private var columnOffsets: [CGFloat] = []
    private var contentSize = CGSize.zero
    private var rowCount: Int { rowHeights.count }

    func configure(headers: [String], rows: [[String]], widths: [CGFloat], viewportWidth: CGFloat,
                   availableWidth: CGFloat? = nil) {
        let newMetrics = SheetFullscreenTableMetrics(viewportWidth: viewportWidth)
        let resolvedWidths = newMetrics.resolvedColumnWidths(headers: headers, preferredWidths: widths,
                                                            availableWidth: availableWidth ?? viewportWidth)
        let needsMeasurement = rowHeights.isEmpty || rows != measuredRows || headers != measuredHeaders || resolvedWidths != measuredWidths
            || newMetrics.isMobile != metrics.isMobile
        metrics = newMetrics
        columnWidths = [metrics.gutterWidth] + resolvedWidths
        if needsMeasurement {
            measuredRows = rows
            measuredHeaders = headers
            measuredWidths = resolvedWidths
            rowHeights = [metrics.letterRowHeight, metrics.headerRowHeight]
                + rows.enumerated().map { index, values in
                    metrics.rowHeight(values: values, columnWidths: resolvedWidths) + (index == 0 ? 0.5 : 0)
                }
            rowOffsets = []
            var y: CGFloat = 0
            for height in rowHeights { rowOffsets.append(y); y += height }
        }
        invalidateLayout()
    }

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
            width: max(x + 1, collectionView.bounds.width + 1),
            height: max(totalContentHeight, collectionView.bounds.height - collectionView.adjustedContentInset.vertical + 1)
        )
    }

    override var collectionViewContentSize: CGSize {
        contentSize
    }

    override func layoutAttributesForElements(in rect: CGRect) -> [UICollectionViewLayoutAttributes]? {
        guard !columnWidths.isEmpty, rowCount > 0 else { return [] }

        // Sticky headers and gutter must remain in the attribute set even when
        // their original frames are outside the current visible rect.
        let visibleRows = intersectingRange(offsets: rowOffsets, lengths: rowHeights, min: rect.minY, max: rect.maxY)
        let visibleColumns = intersectingRange(offsets: columnOffsets, lengths: columnWidths, min: rect.minX, max: rect.maxX)
        let rowRange = Set(visibleRows).union([0, 1]).sorted()
        let columnRange = Set(visibleColumns).union([0]).sorted()
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
            y: rowOffsets[row],
            width: columnWidths[column],
            height: rowHeights[row]
        )
        if let collectionView {
            if row < 2 {
                let stickyTop = collectionView.bounds.minY
                itemAttributes.frame.origin.y = max(rowOffsets[row], stickyTop + rowOffsets[row])
                itemAttributes.zIndex = 3
            }
            if column == 0 {
                itemAttributes.frame.origin.x = max(0, collectionView.bounds.minX + collectionView.adjustedContentInset.left)
                itemAttributes.zIndex = row < 2 ? 4 : 2
            }
        }
        return itemAttributes
    }

    override func shouldInvalidateLayout(forBoundsChange newBounds: CGRect) -> Bool {
        true
    }

    var totalContentHeight: CGFloat {
        (rowOffsets.last ?? 0) + (rowHeights.last ?? 0)
    }

    private func intersectingRange(offsets: [CGFloat], lengths: [CGFloat], min: CGFloat, max: CGFloat) -> Range<Int> {
        guard !offsets.isEmpty else { return 0..<0 }
        func lowerBound(_ predicate: (Int) -> Bool) -> Int {
            var low = 0, high = offsets.count
            while low < high {
                let middle = (low + high) / 2
                if predicate(middle) { high = middle } else { low = middle + 1 }
            }
            return low
        }
        let first = lowerBound { offsets[$0] + lengths[$0] >= min }
        let end = lowerBound { offsets[$0] > max }
        return first..<Swift.max(first, end)
    }
}

private final class SheetFullscreenCollectionCell: UICollectionViewCell {
    static let reuseIdentifier = "SheetFullscreenCollectionCell"

    enum Kind {
        case filter(isActive: Bool)
        case columnLetter
        case header(columnIndex: Int, ascending: Bool?)
        case rowHeader
        case value(isAlternate: Bool)
    }

    struct Model {
        let text: String
        let kind: Kind
    }

    private let label = UILabel()
    private let valueTextView = UITextView()
    private let headerLabel = UILabel()
    private let filterGlyph = SheetFullscreenControlGlyphView()
    private let filterBackground = UIView()
    private let sortGlyph = SheetFullscreenControlGlyphView()
    private let headerStack = UIStackView()
    private let gridBorder = CAShapeLayer()
    private let emphasizedBorder = CAShapeLayer()
    private let gutterBorder = CAShapeLayer()
    private var metrics = SheetFullscreenTableMetrics(viewportWidth: 0)
    private var kind: Kind = .columnLetter
    var onActivate: (() -> Void)?

    override init(frame: CGRect) {
        super.init(frame: frame)
        contentView.addSubview(label)
        contentView.addSubview(valueTextView)
        contentView.addSubview(filterBackground)
        contentView.addSubview(filterGlyph)
        filterBackground.layer.cornerRadius = 3
        filterBackground.isUserInteractionEnabled = false
        contentView.addSubview(headerStack)
        headerStack.axis = .horizontal
        headerStack.alignment = .center
        headerStack.spacing = .spacing2
        headerStack.addArrangedSubview(headerLabel)
        headerStack.addArrangedSubview(sortGlyph)
        headerLabel.numberOfLines = 1
        headerLabel.lineBreakMode = .byTruncatingTail
        headerLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        sortGlyph.translatesAutoresizingMaskIntoConstraints = false
        filterGlyph.accessibilityIdentifier = "sheet-filter-glyph"
        sortGlyph.accessibilityIdentifier = "sheet-sort-glyph"
        label.numberOfLines = 1
        label.lineBreakMode = .byTruncatingTail
        valueTextView.backgroundColor = .clear
        valueTextView.isEditable = false
        valueTextView.isSelectable = true
        valueTextView.isScrollEnabled = false
        valueTextView.textContainer.lineBreakMode = .byWordWrapping
        valueTextView.textContainer.maximumNumberOfLines = 0
        valueTextView.textContainer.lineFragmentPadding = 0
        NSLayoutConstraint.activate([
            sortGlyph.widthAnchor.constraint(equalToConstant: 10),
            sortGlyph.heightAnchor.constraint(equalToConstant: 10),
        ])
        contentView.clipsToBounds = true
        gridBorder.fillColor = nil
        gridBorder.lineWidth = 1
        emphasizedBorder.fillColor = nil
        emphasizedBorder.lineWidth = 2
        gutterBorder.fillColor = nil
        gutterBorder.lineWidth = 2
        contentView.layer.addSublayer(gridBorder)
        contentView.layer.addSublayer(emphasizedBorder)
        contentView.layer.addSublayer(gutterBorder)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(with model: Model, metrics: SheetFullscreenTableMetrics) {
        self.metrics = metrics
        kind = model.kind
        label.isHidden = false
        valueTextView.isHidden = true
        filterGlyph.isHidden = true
        filterBackground.isHidden = true
        headerStack.isHidden = true
        isAccessibilityElement = false
        accessibilityIdentifier = nil
        accessibilityLabel = nil
        accessibilityTraits = []
        label.text = model.text
        label.textAlignment = .left
        label.font = metrics.font
        label.textColor = UIColor(Color.fontPrimary)
        gridBorder.strokeColor = UIColor(Color.grey25).cgColor
        emphasizedBorder.strokeColor = UIColor(Color.grey30).cgColor
        gutterBorder.strokeColor = UIColor(Color.grey30).cgColor

        switch model.kind {
        case .filter(let isActive):
            label.isHidden = true
            filterGlyph.isHidden = false
            filterBackground.isHidden = false
            filterBackground.backgroundColor = isActive
                ? UIColor(AppGradientPalette.colors(for: "primary").start).withAlphaComponent(0.12) : .clear
            filterGlyph.glyph = .filter
            filterGlyph.tintColor = UIColor(isActive ? AppGradientPalette.colors(for: "primary").start : Color.fontTertiary)
            isAccessibilityElement = true
            accessibilityIdentifier = "sheet-filter-toggle"
            accessibilityLabel = LocalizationManager.shared.text("activity.filter")
            accessibilityTraits = isActive ? [.button, .selected] : .button
            contentView.backgroundColor = UIColor(Color.grey10)
        case .columnLetter:
            label.font = metrics.letterFont
            label.textAlignment = .center
            label.textColor = UIColor(Color.fontTertiary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .header(let columnIndex, let ascending):
            label.isHidden = true
            headerStack.isHidden = false
            headerLabel.text = model.text
            headerLabel.font = metrics.headerFont
            headerLabel.textColor = UIColor(Color.fontPrimary)
            sortGlyph.glyph = .sort(ascending: ascending)
            sortGlyph.alpha = ascending == nil ? 0.35 : 1
            sortGlyph.tintColor = UIColor(ascending == nil ? Color.fontSecondary : AppGradientPalette.colors(for: "primary").start)
            isAccessibilityElement = true
            accessibilityIdentifier = "sheet-sort-column-\(columnIndex)"
            accessibilityLabel = model.text
            accessibilityTraits = ascending == nil ? .button : [.button, .selected]
            contentView.backgroundColor = UIColor(Color.grey10)
        case .rowHeader:
            label.font = .systemFont(ofSize: 11, weight: .medium)
            label.textAlignment = .center
            label.textColor = UIColor(Color.fontTertiary)
            contentView.backgroundColor = UIColor(Color.grey10)
        case .value(let isAlternate):
            label.isHidden = true
            valueTextView.isHidden = false
            valueTextView.attributedText = metrics.attributedValue(model.text)
            valueTextView.textContainerInset = UIEdgeInsets(top: metrics.verticalPadding, left: 0,
                                                          bottom: metrics.verticalPadding, right: 0)
            contentView.backgroundColor = UIColor(isAlternate ? Color.grey10 : Color.grey20)
        }
        setNeedsLayout()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let availableWidth = metrics.contentWidth(for: contentView.bounds.width)
        label.frame = CGRect(x: metrics.horizontalPadding + 0.5, y: metrics.verticalPadding,
                             width: availableWidth, height: label.font.pointSize * 1.4)
        valueTextView.frame = CGRect(x: metrics.horizontalPadding + 0.5, y: 0,
                                     width: availableWidth, height: contentView.bounds.height)
        headerStack.frame = CGRect(x: metrics.horizontalPadding + 0.5, y: metrics.verticalPadding,
                                   width: min(availableWidth, headerLabel.intrinsicContentSize.width + .spacing2 + 10),
                                   height: metrics.lineHeight)
        filterGlyph.frame = CGRect(x: (contentView.bounds.width - 12) / 2,
                                   y: metrics.letterVerticalPadding + 5, width: 12, height: 12)
        filterBackground.frame = CGRect(x: (contentView.bounds.width - 22) / 2,
                                        y: metrics.letterVerticalPadding, width: 22, height: 22)
        gridBorder.path = UIBezierPath(rect: contentView.bounds).cgPath
        let border = UIBezierPath()
        emphasizedBorder.lineWidth = 2
        switch kind {
        case .filter, .columnLetter:
            emphasizedBorder.lineWidth = 1
            label.frame.origin.y = metrics.letterVerticalPadding
            border.move(to: CGPoint(x: 0, y: contentView.bounds.height - 0.5))
            border.addLine(to: CGPoint(x: contentView.bounds.width, y: contentView.bounds.height - 0.5))
        case .header:
            border.move(to: CGPoint(x: 0, y: contentView.bounds.height - 1))
            border.addLine(to: CGPoint(x: contentView.bounds.width, y: contentView.bounds.height - 1))
        case .rowHeader:
            if label.text?.isEmpty == true {
                border.move(to: CGPoint(x: 0, y: contentView.bounds.height - 1))
                border.addLine(to: CGPoint(x: contentView.bounds.width, y: contentView.bounds.height - 1))
            }
        case .value: break
        }
        let gutter = UIBezierPath()
        switch kind {
        case .filter, .rowHeader:
            gutter.move(to: CGPoint(x: contentView.bounds.width - 1, y: 0))
            gutter.addLine(to: CGPoint(x: contentView.bounds.width - 1, y: contentView.bounds.height))
        default: break
        }
        emphasizedBorder.path = border.cgPath
        gutterBorder.path = gutter.cgPath
    }

    override func accessibilityActivate() -> Bool {
        guard accessibilityTraits.contains(.button), let onActivate else { return false }
        onActivate()
        return true
    }
}

// Exact inline SVG paths from SheetEmbedFullscreen.svelte. The bundled generic
// filter/sort assets have different silhouettes from these spreadsheet controls.
private final class SheetFullscreenControlGlyphView: UIView {
    enum Glyph {
        case filter
        case sort(ascending: Bool?)
    }

    var glyph: Glyph = .filter { didSet { setNeedsDisplay() } }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isOpaque = false
        isAccessibilityElement = false
        contentMode = .redraw
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func tintColorDidChange() {
        super.tintColorDidChange()
        setNeedsDisplay()
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        context.scaleBy(x: bounds.width / 24, y: bounds.height / 24)
        tintColor.setStroke()
        let path = UIBezierPath()
        func polyline(_ points: [CGPoint]) {
            guard let first = points.first else { return }
            path.move(to: first)
            for point in points.dropFirst() { path.addLine(to: point) }
        }
        switch glyph {
        case .filter:
            polyline([CGPoint(x: 22, y: 3), CGPoint(x: 2, y: 3), CGPoint(x: 10, y: 12.46),
                      CGPoint(x: 10, y: 19), CGPoint(x: 14, y: 21), CGPoint(x: 14, y: 12.46)])
            path.close()
            path.lineWidth = 2.5
        case .sort(let ascending):
            path.lineWidth = ascending == nil ? 1.5 : 3
            if let ascending {
                polyline(ascending ? [CGPoint(x: 18, y: 15), CGPoint(x: 12, y: 9), CGPoint(x: 6, y: 15)]
                                   : [CGPoint(x: 6, y: 9), CGPoint(x: 12, y: 15), CGPoint(x: 18, y: 9)])
            } else {
                polyline([CGPoint(x: 8, y: 10), CGPoint(x: 12, y: 6), CGPoint(x: 16, y: 10)])
                polyline([CGPoint(x: 8, y: 14), CGPoint(x: 12, y: 18), CGPoint(x: 16, y: 14)])
            }
        }
        path.stroke()
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
    let displayRowCount: Int
    let displayColCount: Int

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

        let declaredRows = EmbedFieldReader.int(data ?? [:], keys: ["row_count", "rows"])
        let declaredColumns = EmbedFieldReader.int(data ?? [:], keys: ["col_count", "cols"])

        guard lines.count >= 2 else {
            headers = []
            rows = []
            displayRowCount = max(declaredRows ?? 0, 0)
            displayColCount = max(declaredColumns ?? 0, 0)
            return
        }

        let parsedHeaders = ParsedSheetTable.parseRow(lines[0])
        headers = parsedHeaders
        rows = lines.dropFirst(2).map { line in
            let cells = ParsedSheetTable.parseRow(line)
            return parsedHeaders.indices.map { cells.indices.contains($0) ? cells[$0] : "" }
        }
        displayRowCount = declaredRows.flatMap { $0 > 0 ? $0 : nil } ?? rows.count
        displayColCount = declaredColumns.flatMap { $0 > 0 ? $0 : nil } ?? headers.count
    }

    var rowCount: Int { rows.count }

    func applyingPII(mappings: [PIIMapping], revealed: Bool) -> ParsedSheetTable {
        guard !mappings.isEmpty else { return self }
        return ParsedSheetTable(data: [
            "table": AnyCodable(EmbedPIIText.render(markdown, mappings: mappings, revealed: revealed)),
            "title": AnyCodable(EmbedPIIText.render(title ?? "", mappings: mappings, revealed: revealed)),
            "row_count": AnyCodable(displayRowCount), "col_count": AnyCodable(displayColCount)
        ])
    }
    var colCount: Int { headers.count }
    var dimensionsText: String {
        "\(displayRowCount) \(displayRowCount == 1 ? "row" : "rows") × \(displayColCount) \(displayColCount == 1 ? "column" : "columns")"
    }
    var tsv: String {
        tsv(rows: rows)
    }
    func tsv(rows selectedRows: [[String]]) -> String {
        ([headers] + selectedRows)
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

// SheetEmbedFullscreen.svelte exports an Office Open XML workbook. Build the
// same format in memory so the share/save flow never exposes a temporary table
// directory or leaves its source rows on disk.
struct SheetXLSXExporter {
    enum ExportError: Error { case emptyTable, archiveUnavailable }

    static func makeData(table: ParsedSheetTable, rows: [[String]]? = nil) throws -> Data {
        guard !table.headers.isEmpty else { throw ExportError.emptyTable }
        let archive = try Archive(data: Data(), accessMode: .create)
        let sheetName = validSheetName(table.title ?? "Table")
        let files: [(String, String)] = [
            ("[Content_Types].xml", """
            <?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>
            """),
            ("_rels/.rels", """
            <?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>
            """),
            ("xl/workbook.xml", """
            <?xml version="1.0" encoding="UTF-8"?>
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="\(escapeXML(sheetName))" sheetId="1" r:id="rId1"/></sheets></workbook>
            """),
            ("xl/_rels/workbook.xml.rels", """
            <?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>
            """),
            ("xl/styles.xml", """
            <?xml version="1.0" encoding="UTF-8"?>
            <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>
            """),
            ("xl/worksheets/sheet1.xml", worksheetXML(table, rows: rows ?? table.rows))
        ]
        for (path, xml) in files {
            let data = Data(xml.utf8)
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(data.count)) { position, size in
                data.subdata(in: Int(position)..<min(Int(position) + size, data.count))
            }
        }
        guard let result = archive.data else { throw ExportError.archiveUnavailable }
        return result
    }

    private static func worksheetXML(_ table: ParsedSheetTable, rows selectedRows: [[String]]) -> String {
        let rows = [table.headers] + selectedRows
        let lastColumn = columnName(table.headers.count - 1)
        var xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><dimension ref=\"A1:\(lastColumn)\(rows.count)\"/><sheetData>"
        for (rowIndex, row) in rows.enumerated() {
            let number = rowIndex + 1
            xml += "<row r=\"\(number)\">"
            for columnIndex in table.headers.indices {
                let text = row.indices.contains(columnIndex) ? row[columnIndex] : ""
                let style = rowIndex == 0 ? " s=\"1\"" : ""
                xml += "<c r=\"\(columnName(columnIndex))\(number)\" t=\"inlineStr\"\(style)><is><t xml:space=\"preserve\">\(escapeXML(text))</t></is></c>"
            }
            xml += "</row>"
        }
        return xml + "</sheetData></worksheet>"
    }

    private static func columnName(_ index: Int) -> String {
        var value = index + 1
        var name = ""
        while value > 0 {
            value -= 1
            name = String(UnicodeScalar(65 + value % 26)!) + name
            value /= 26
        }
        return name
    }

    private static func validSheetName(_ proposed: String) -> String {
        let invalid = CharacterSet(charactersIn: "[]:*?/\\")
        let cleaned = String(String.UnicodeScalarView(proposed.unicodeScalars.filter { !invalid.contains($0) }))
        let bounded = String(cleaned.prefix(31)).trimmingCharacters(in: .whitespacesAndNewlines)
        return bounded.isEmpty ? "Table" : bounded
    }

    private static func escapeXML(_ value: String) -> String {
        let valid = String(String.UnicodeScalarView(value.unicodeScalars.filter {
            $0.value == 9 || $0.value == 10 || $0.value == 13 || $0.value >= 32
        }))
        return valid.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&apos;")
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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

struct PcbSchematicEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let status: EmbedStatus
    var embedID: String? = nil

    private var schematic: PcbSchematicSummary { PcbSchematicSummary(data: data ?? [:]) }

    var body: some View {
        switch mode {
        case .preview:
            PcbSchematicPreview(schematic: schematic, status: status)
        case .fullscreen:
            PcbSchematicFullscreen(schematic: schematic, data: data, embedID: embedID)
        }
    }
}

private struct PcbSchematicPreview: View {
    let schematic: PcbSchematicSummary
    let status: EmbedStatus

    var body: some View {
        if status == .processing {
            Text(AppStrings.localized("embeds.processing"))
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if schematic.code.isEmpty {
            VStack(spacing: .spacing4) {
                Icon("pcbdesign", size: .spacing16)
                    .foregroundStyle(LinearGradient.appElectronics)
                Text(AppStrings.pcbSchematicTitle)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            CodeLinesView(
                code: schematic.previewCode,
                language: schematic.language,
                showsLineNumbers: true,
                fontSize: 12,
                clipsLongLines: true
            )
            .padding(.top, .spacing5)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .clipped()
        }
    }
}

private struct PcbSchematicFullscreen: View {
    let schematic: PcbSchematicSummary
    let data: [String: AnyCodable]?
    let embedID: String?
    @Environment(\.recipientMediaContext) private var recipient
    @Environment(\.nativePCBTransport) private var injectedTransport
    @StateObject private var actions = NativePCBSchematicActions()
    @StateObject private var exporter = NativeEmbedActionController()
    @State private var prepareTask: Task<Void, Never>?
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    var body: some View {
        Group {
            if horizontalSizeClass == .compact {
                VStack(spacing: .spacing6) {
                    if schematic.code.isEmpty {
                        Color.clear.frame(height: 170)
                    } else {
                        sourcePanel
                    }
                    compilePanel
                }
            } else {
                HStack(alignment: .top, spacing: .spacing6) {
                    sourcePanel
                    compilePanel
                        .frame(minWidth: 280, maxWidth: 360)
                }
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing8)
        .padding(.bottom, .spacing8)
        .task(id: embedID) { actions.initialize(data) }
        .onDisappear { prepareTask?.cancel(); actions.cancel(); exporter.cancel() }
    }

    private func transport() async throws -> NativePCBTransport {
        // Shared recipients have no owner-authorized compile API capability.
        guard recipient == nil else { throw CancellationError() }
        if let injectedTransport { return injectedTransport }
        return try await NativePCBSchematicActions.accountTransport()
    }
    private func prepare() {
        guard let embedID, !actions.preparing, recipient == nil else { return }
        prepareTask = Task {
            do { await actions.prepare(embedID: embedID, transport: try await transport()) }
            catch is CancellationError { }
            catch { ToastManager.shared.show(AppStrings.error, type: .error) }
        }
    }
    private func download(_ artifact: NativePCBArtifact) {
        guard recipient == nil else { return }
        let profile = ServerProfile.current()
        let scope = OfflineStore.shared.scopeGeneration
        let teamEpoch = TeamWorkspaceContext.shared.contextEpoch
        let teamID = TeamWorkspaceContext.shared.teamID
        exporter.download(load: {
            try await actions.download(artifact, transport: try await transport())
        }, validate: {
            guard recipient == nil, ServerProfile.current() == profile,
                  OfflineStore.shared.scopeGeneration == scope,
                  TeamWorkspaceContext.shared.contextEpoch == teamEpoch,
                  TeamWorkspaceContext.shared.teamID == teamID else { throw CancellationError() }
        })
    }

    private var sourcePanel: some View {
        ScrollView([.horizontal, .vertical], showsIndicators: true) {
            CodeLinesView(
                code: schematic.code,
                language: schematic.language,
                showsLineNumbers: true,
                fontSize: 14,
                clipsLongLines: false,
                gutterWidth: 56
            )
            .padding(.vertical, .spacing6)
            .padding(.trailing, .spacing8)
        }
        .frame(maxWidth: .infinity, minHeight: 420, alignment: .topLeading)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .accessibilityIdentifier("pcb-schematic-source-panel")
    }

    private var compilePanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing6) {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Button(action: prepare) {
                        Text(actions.preparing ? AppStrings.localized("embeds.electronics.pcb_schematic.preparing") : AppStrings.pcbSchematicPrepareFiles)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(embedID == nil || actions.preparing || recipient != nil)
                    .accessibilityIdentifier("pcb-schematic-prepare-files")
                    if !actions.logs.isEmpty || actions.error != nil {
                        Button(actions.showLogs ? AppStrings.localized("embeds.electronics.pcb_schematic.hide_logs") : AppStrings.localized("embeds.electronics.pcb_schematic.show_logs")) {
                            actions.showLogs.toggle()
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("pcb-schematic-show-logs")
                    }
                    Group {
                        Text(actions.status)
                            .font(.omXs)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing2)
                            .background(Color.grey25)
                            .clipShape(Capsule())
                    }
                    Text(AppStrings.pcbSchematicSafetyNote)
                        .font(.omXs)
                        .foregroundStyle(Color.grey70)
                        .lineSpacing(.spacing1)
                    if let compileError = actions.error, !actions.showLogs {
                        Text(compileError)
                            .font(.omXs)
                            .foregroundStyle(Color.error)
                            .textSelection(.enabled)
                    }
                }

                if !actions.artifacts.isEmpty && !actions.showLogs {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(AppStrings.pcbSchematicArtifacts)
                            .font(.omSmall)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                        ForEach(actions.artifacts) { artifact in
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Button(artifact.name) { download(artifact) }
                                    .font(.omXs)
                                    .fontWeight(.semibold)
                                    .disabled(actions.compileID == nil || recipient != nil || exporter.isDownloading)
                                    .accessibilityIdentifier("pcb-schematic-artifact-\(artifact.id)")
                                if let type = artifact.type {
                                    Text(type)
                                        .font(.omXs)
                                        .foregroundStyle(Color.grey70)
                                }
                            }
                            .padding(.spacing3)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        }
                    }
                    .accessibilityIdentifier("pcb-schematic-artifacts")
                }

                if actions.showLogs {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(AppStrings.pcbSchematicLogs)
                            .font(.omSmall)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                        Text(!actions.logs.isEmpty ? actions.logs : actions.error ?? AppStrings.localized("embeds.electronics.pcb_schematic.no_logs"))
                            .font(.omXs)
                            .monospaced()
                            .foregroundStyle(Color.grey0)
                            .textSelection(.enabled)
                            .padding(.spacing4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.grey100)
                            .clipShape(RoundedRectangle(cornerRadius: .radius3))
                    }
                    .accessibilityIdentifier("pcb-schematic-logs")
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .accessibilityIdentifier("pcb-schematic-compile-panel")
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

private struct PcbSchematicArtifact: Identifiable {
    let id: String
    let name: String
    let type: String?
}

@MainActor private struct PcbSchematicSummary {
    let code: String
    let language: String
    let compileStatus: String?
    let compileError: String?
    let logs: String?
    let artifacts: [PcbSchematicArtifact]

    init(data: [String: AnyCodable]) {
        code = (EmbedFieldReader.string(data, keys: ["code", "codeContent"]) ?? "")
            .replacingOccurrences(of: #"\""#, with: #"""#)
            .replacingOccurrences(of: #"\/"#, with: "/")
        language = EmbedFieldReader.string(data, keys: ["language"]) ?? "atopile"
        compileStatus = EmbedFieldReader.string(data, keys: ["compile_status"])
        compileError = EmbedFieldReader.string(data, keys: ["compile_error", "error"])
        logs = EmbedFieldReader.string(data, keys: ["compile_logs"])
        artifacts = Self.artifacts(from: data)
    }

    var previewCode: String {
        code.components(separatedBy: "\n").prefix(8).joined(separator: "\n")
    }

    private static func artifacts(from data: [String: AnyCodable]) -> [PcbSchematicArtifact] {
        guard let manifest = data["artifact_manifest"]?.value as? [String: Any],
              let files = manifest["files"] as? [[String: Any]]
        else { return [] }

        return files.compactMap { file in
            guard let name = CodeRendererValue.string(file, key: "name") else { return nil }
            return PcbSchematicArtifact(
                id: CodeRendererValue.string(file, key: "id") ?? name,
                name: name,
                type: CodeRendererValue.string(file, key: "type")
            )
        }
    }
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
