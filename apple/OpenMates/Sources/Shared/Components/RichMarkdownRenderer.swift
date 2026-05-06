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
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

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
    case embedGroup([MarkdownEmbedReference])

}

struct MarkdownEmbedReference: Equatable {
    let value: String
    let isRef: Bool
    let isLargePreview: Bool
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
            InlineMarkdownText(
                content: text,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap
            )

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
            ListBlockView(
                items: items,
                ordered: false,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap
            )

        case .orderedList(let items):
            ListBlockView(
                items: items,
                ordered: true,
                isUserMessage: isUserMessage,
                allEmbedRecords: allEmbedRecords,
                onEmbedTap: onEmbedTap
            )

        case .table(let headers, let rows):
            TableBlockView(headers: headers, rows: rows, isUserMessage: isUserMessage)

        case .demoGroup(let kind):
            DemoRichGroupView(kind: kind, onOpenPublicChat: onOpenPublicChat)

        case .embedGroup(let references):
            let embeds = references.compactMap(resolveEmbed)
            if !embeds.isEmpty {
                if references.first?.isLargePreview == true {
                    LargeEmbedPreviewCarousel(embeds: embeds, allEmbedRecords: allEmbedRecords) { embed in
                        onEmbedTap?(embed)
                    }
                } else {
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

    private func resolveEmbed(_ reference: MarkdownEmbedReference) -> EmbedRecord? {
        if reference.isRef {
            return allEmbedRecords.values.first { record in
                record.rawData?["embed_ref"]?.value as? String == reference.value
            }
        }
        return embedLookup[reference.value] ?? allEmbedRecords[reference.value]
    }
}

private struct LargeEmbedPreviewCarousel: View {
    private enum Constants {
        static let expandedThreshold: CGFloat = 400
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
        containerWidth > Constants.expandedThreshold ? .large : .compact
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

struct InlineMarkdownText: View {
    let content: String
    let isUserMessage: Bool
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: ((EmbedRecord) -> Void)?
    @Environment(\.colorScheme) private var colorScheme
    private let attributedContent: AttributedString
    private let inlineTokens: [InlineMarkdownToken]
    private let needsCustomInlineLayout: Bool

    init(
        content: String,
        isUserMessage: Bool,
        allEmbedRecords: [String: EmbedRecord] = [:],
        onEmbedTap: ((EmbedRecord) -> Void)? = nil
    ) {
        self.content = content
        self.isUserMessage = isUserMessage
        self.allEmbedRecords = allEmbedRecords
        self.onEmbedTap = onEmbedTap
        self.attributedContent = (try? AttributedString(markdown: content, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(content)
        let shouldUseCustomInlineLayout = Self.shouldUseCustomInlineLayout(for: content)
        self.inlineTokens = shouldUseCustomInlineLayout ? InlineMarkdownTokenizer.parse(content) : []
        self.needsCustomInlineLayout = shouldUseCustomInlineLayout
    }

    private static func shouldUseCustomInlineLayout(for content: String) -> Bool {
        guard content.count <= 3_000 else { return false }
        return content.contains("(wiki:")
            || content.contains("(embed:")
            || content.contains("](")
    }

    var body: some View {
        if needsCustomInlineLayout {
            InlineMarkdownFlowLayout(spacing: 0, lineSpacing: 2) {
                ForEach(Array(inlineTokens.enumerated()), id: \.offset) { _, token in
                    tokenView(token)
                }
            }
            .textSelection(.disabled)
        } else {
            Text(styledAttributedContent)
                .font(.omP)
                .fontWeight(.medium)
                .lineSpacing(2)
                .textSelection(.enabled)
        }
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
        return content
    }

    @ViewBuilder
    private func tokenView(_ token: InlineMarkdownToken) -> some View {
        switch token {
        case .text(let text, let isBold):
            Text(text)
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .foregroundStyle(textColor(isBold: isBold))
                .fixedSize()
        case .inlineCode(let text):
            Text(text)
                .font(.system(size: 14, design: .monospaced))
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay {
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.grey30, lineWidth: 1)
                }
                .fixedSize()
        case .wiki(let displayText, let wikiTitle, let isBold):
            WikiInlineChip(displayText: displayText, wikiTitle: wikiTitle, isBold: isBold) { embed in
                onEmbedTap?(embed)
            }
        case .embed(let displayText, let embedRef, let isBold):
            EmbedInlineChip(
                displayText: displayText,
                embed: resolveEmbed(ref: embedRef),
                fallbackAppId: nil,
                isBold: isBold
            ) { embed in
                onEmbedTap?(embed)
            }
        case .link(let displayText, let url, let isInternal, let isBold):
            MarkdownLinkChip(
                displayText: displayText,
                urlString: url,
                isInternal: isInternal,
                isBold: isBold
            )
        }
    }

    private func textColor(isBold: Bool) -> Color {
        if isBold {
            return Color.markdownBoldText(for: colorScheme)
        }
        return isUserMessage ? Color.fontPrimary : Color.grey100
    }

    private func resolveEmbed(ref: String) -> EmbedRecord? {
        allEmbedRecords.values.first { record in
            record.rawData?["embed_ref"]?.value as? String == ref
        }
    }
}

private enum InlineMarkdownToken: Equatable {
    case text(String, isBold: Bool)
    case inlineCode(String)
    case wiki(displayText: String, wikiTitle: String, isBold: Bool)
    case embed(displayText: String, embedRef: String, isBold: Bool)
    case link(displayText: String, url: String, isInternal: Bool, isBold: Bool)
}

private enum InlineMarkdownTokenizer {
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

            let nextSpecial = nextSpecialIndex(in: source, from: index) ?? source.endIndex
            appendText(String(source[index..<nextSpecial]), isBold: isBold, to: &tokens)
            index = nextSpecial
        }

        return tokens
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
            if source[index...].hasPrefix("**") || source[index] == "[" || source[index] == "`" {
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
        .fixedSize()
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
        HStack(spacing: 3) {
            Circle()
                .fill(LinearGradient.appStudy)
                .frame(width: 20, height: 20)
                .overlay {
                    Icon("study", size: 10)
                        .foregroundStyle(Color.fontButton)
                }

            Text(displayText)
                .font(.omP)
                .fontWeight(isBold ? .semibold : .medium)
                .foregroundStyle(Color.wikiInlineText(for: colorScheme))
                .underline(isHovering)
        }
    }

    private var wikiEmbedRecord: EmbedRecord {
        let title = wikiTitle.replacingOccurrences(of: "_", with: " ")
        let encodedTitle = wikiTitle.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? wikiTitle
        let url = "https://en.wikipedia.org/wiki/\(encodedTitle)"
        let data: [String: AnyCodable] = [
            "title": AnyCodable(title),
            "summary": AnyCodable("Wikipedia article"),
            "url": AnyCodable(url)
        ]
        return EmbedRecord(
            id: "wiki-\(stableHash(wikiTitle))",
            type: EmbedType.wiki.rawValue,
            status: .finished,
            data: .raw(data),
            parentEmbedId: nil,
            appId: EmbedType.wiki.appId,
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-04-20T12:00:00Z"
        )
    }

    private func stableHash(_ value: String) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        return String(hash, radix: 16)
    }
}

private struct EmbedInlineChip: View {
    let displayText: String
    let embed: EmbedRecord?
    let fallbackAppId: String?
    let isBold: Bool
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
            .fixedSize()
            .opacity(isHovering ? 0.82 : 1)
            .contentShape(Rectangle())
            .onHover { hovering in
                updateHover(hovering, isClickable: true)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel(displayText)
        } else {
            chipContent
                .fixedSize()
                .opacity(isHovering ? 0.82 : 1)
                .accessibilityElement(children: .combine)
                .accessibilityLabel(displayText)
        }
    }

    private var chipContent: some View {
        HStack(spacing: 3) {
            Circle()
                .fill(AppIconView.gradient(forAppId: appId))
                .frame(width: 20, height: 20)
                .overlay {
                    Icon(AppIconView.iconName(forAppId: appId), size: 10)
                        .foregroundStyle(Color.fontButton)
                }

            Text(displayText)
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
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL
    @State private var isHovering = false

    var body: some View {
        if let destinationURL {
            Button {
                openURL(destinationURL)
            } label: {
                chipContent
            }
            .buttonStyle(.plain)
            .fixedSize()
            .opacity(isHovering ? 0.82 : 1)
            .contentShape(Rectangle())
            .onHover(perform: updateHover)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(displayText)
        } else {
            chipContent
                .fixedSize()
                .opacity(isHovering ? 0.82 : 1)
                .accessibilityElement(children: .combine)
                .accessibilityLabel(displayText)
        }
    }

    private var chipContent: some View {
        HStack(spacing: 3) {
            if isInternal {
                Circle()
                    .fill(LinearGradient.appOpenmates)
                    .frame(width: 20, height: 20)
                    .overlay {
                        Icon("openmates", size: 10)
                            .foregroundStyle(Color.fontButton)
                    }
            }

            Text(displayText)
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

private struct InlineMarkdownFlowLayout: Layout {
    let spacing: CGFloat
    let lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrangeSubviews(proposal: proposal, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arrangement = arrangeSubviews(proposal: ProposedViewSize(width: bounds.width, height: proposal.height), subviews: subviews)
        for (index, origin) in arrangement.origins.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                proposal: .unspecified
            )
        }
    }

    private func arrangeSubviews(proposal: ProposedViewSize, subviews: Subviews) -> (origins: [CGPoint], size: CGSize) {
        let maxWidth = proposal.width ?? .infinity
        var origins: [CGPoint] = []
        var cursor = CGPoint.zero
        var lineHeight: CGFloat = 0
        var measuredWidth: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if cursor.x > 0, cursor.x + size.width > maxWidth {
                cursor.x = 0
                cursor.y += lineHeight + lineSpacing
                lineHeight = 0
            }

            origins.append(cursor)
            cursor.x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            measuredWidth = max(measuredWidth, cursor.x)
        }

        return (origins, CGSize(width: min(measuredWidth, maxWidth), height: cursor.y + lineHeight))
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
            .foregroundStyle(isUserMessage ? Color.fontPrimary : Color.grey100)
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
                        onEmbedTap: onEmbedTap
                    )
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
                            .foregroundStyle(Color.fontPrimary)
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
                                .foregroundStyle(Color.fontPrimary)
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
