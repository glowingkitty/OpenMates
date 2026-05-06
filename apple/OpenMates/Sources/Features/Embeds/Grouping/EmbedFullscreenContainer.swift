// Fullscreen embed container with navigation between embeds in a group.
// Supports prev/next navigation arrows, child embed loading for composite types,
// and the full slide-up presentation matching the web app.

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct EmbedFullscreenContainer: View {
    let embeds: [EmbedRecord]
    let initialEmbedId: String
    let allEmbedRecords: [String: EmbedRecord]
    let chatId: String?
    var onClose: () -> Void = {}

    @State private var currentIndex: Int = 0
    @State private var selectedChildEmbed: EmbedRecord?
    @State private var showChildFullscreen = false
    @State private var isPresented = false
    @State private var codePreviewActive = false
    @State private var shareTarget: EmbedRecord?

    private var currentEmbed: EmbedRecord? {
        guard currentIndex >= 0 && currentIndex < embeds.count else { return nil }
        return embeds[currentIndex]
    }

    private var currentEmbedType: EmbedType? {
        guard let currentEmbed else { return nil }
        return EmbedType(rawValue: currentEmbed.type)
    }

    private var isCodeEmbed: Bool {
        currentEmbedType == .codeCode
    }

    private var isSheetEmbed: Bool {
        currentEmbedType == .sheetsSheet
    }

    private var isCodePreviewable: Bool {
        guard let payload = currentEmbed?.codePayload else { return false }
        let language = payload.language.lowercased()
        let filename = payload.filename?.lowercased() ?? ""
        return ["html", "htm", "markdown", "md", "xml"].contains(language)
            || filename.hasSuffix(".html")
            || filename.hasSuffix(".htm")
            || filename.hasSuffix(".md")
            || filename.hasSuffix(".markdown")
    }

    private var childEmbeds: [EmbedRecord] {
        guard let embed = currentEmbed else { return [] }
        return embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
    }

    var body: some View {
        return GeometryReader { proxy in
            ZStack(alignment: .top) {
                if let embed = currentEmbed {
                    ScrollView {
                        VStack(spacing: 0) {
                            EmbedFullscreenHeader(
                                embed: embed,
                                hasPreviousEmbed: currentIndex > 0,
                                hasNextEmbed: currentIndex < embeds.count - 1,
                                onNavigatePrevious: { withAnimation { currentIndex -= 1 } },
                                onNavigateNext: { withAnimation { currentIndex += 1 } }
                            )
                            EmbedContentView(
                                embed: embed,
                                mode: .fullscreen,
                                allEmbedRecords: allEmbedRecords,
                                codePreviewActive: codePreviewActive,
                                onOpenEmbed: { child in
                                    selectedChildEmbed = child
                                    showChildFullscreen = true
                                }
                            )
                                .padding(.horizontal, .spacing8)
                                .padding(.vertical, .spacing10)

                            if !embed.isAppSkillUse && !childEmbeds.isEmpty {
                                childEmbedSection
                            }
                        }
                    }
                    .background(Color.grey20)
                    .containerRelativeFrame([.horizontal, .vertical])

                    EmbedFullscreenTopBar(
                        embed: embed,
                        showCopy: isCodeEmbed || isSheetEmbed,
                        showDownload: isCodeEmbed || isSheetEmbed,
                        showPreview: isCodePreviewable,
                        previewActive: codePreviewActive,
                        onClose: closeWithAnimation,
                        onShare: { shareEmbed(embed) },
                        onCopy: { copyEmbedContent(embed) },
                        onDownload: { downloadCodeFile(embed) },
                        onTogglePreview: { codePreviewActive.toggle() },
                        onReportIssue: { reportIssue(embed) }
                    )
                }

                if showChildFullscreen, let child = selectedChildEmbed {
                    EmbedFullscreenContainer(
                        embeds: [child],
                        initialEmbedId: child.id,
                        allEmbedRecords: allEmbedRecords,
                        chatId: chatId,
                        onClose: {
                            showChildFullscreen = false
                            selectedChildEmbed = nil
                        }
                    )
                }
            }
            .offset(y: isPresented ? 0 : proxy.size.height)
            .animation(.easeOut(duration: 0.28), value: isPresented)
        }
        .ignoresSafeArea()
        .onAppear {
            currentIndex = embeds.firstIndex(where: { $0.id == initialEmbedId }) ?? 0
            isPresented = true
        }
        .sheet(item: $shareTarget) { embed in
            ShareEmbedView(embedId: embed.id, chatId: chatId ?? "")
        }
    }

    private func closeWithAnimation() {
        withAnimation(.easeIn(duration: 0.22)) {
            isPresented = false
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.22) {
            onClose()
        }
    }

    // MARK: - Child embeds

    private var childEmbedSection: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Divider().padding(.horizontal, .spacing6)

            Text("\(LocalizationManager.shared.text("embed.results")) (\(childEmbeds.count))")
                .font(.omP).fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing6)

            let groups = EmbedGrouper.group(childEmbeds)
            ForEach(groups) { group in
                GroupedEmbedView(group: group, allEmbedRecords: allEmbedRecords) { embed in
                    selectedChildEmbed = embed
                    showChildFullscreen = true
                }
                .padding(.horizontal, .spacing6)
            }
        }
        .padding(.bottom, .spacing8)
    }

    private func shareEmbed(_ embed: EmbedRecord) {
        if chatId?.isEmpty == false {
            shareTarget = embed
            return
        }
        Task {
            let url = await APIClient.shared.webAppURL.appendingPathComponent("embed/\(embed.id)")
            #if os(iOS)
            let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = scene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
            #endif
        }
    }

    private func copyEmbedContent(_ embed: EmbedRecord) {
        if let payload = embed.codePayload {
            copyToClipboard(payload.code)
            ToastManager.shared.show("Code copied to clipboard", type: .success)
            return
        }
        if let table = sheetTable(for: embed), !table.tsv.isEmpty {
            copyToClipboard(table.tsv)
            ToastManager.shared.show("Table copied to clipboard", type: .success)
            return
        }
        guard let data = embed.data, case .raw(let dict) = data else { return }
        let text = dict.compactMap { key, val -> String? in
            guard let str = val.value as? String else { return nil }
            return "\(key): \(str)"
        }.joined(separator: "\n")
        copyToClipboard(text)
    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }

    private func downloadCodeFile(_ embed: EmbedRecord) {
        if let table = sheetTable(for: embed), currentEmbedType == .sheetsSheet {
            downloadSheet(table, from: embed)
            return
        }
        guard let payload = embed.codePayload else { return }
        let filename = payload.filename ?? defaultCodeFilename(language: payload.language)
        #if os(macOS)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename
        panel.canCreateDirectories = true
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try payload.code.write(to: url, atomically: true, encoding: .utf8)
                ToastManager.shared.show("Code file downloaded", type: .success)
            } catch {
                ToastManager.shared.show("Failed to download code file", type: .error)
            }
        }
        #elseif os(iOS)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        do {
            try payload.code.write(to: url, atomically: true, encoding: .utf8)
            let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = scene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
        } catch {
            ToastManager.shared.show("Failed to download code file", type: .error)
        }
        #endif
    }

    private func defaultCodeFilename(language: String) -> String {
        switch language.lowercased() {
        case "html", "htm": return "index.html"
        case "css": return "style.css"
        case "javascript", "js": return "script.js"
        case "typescript", "ts": return "script.ts"
        case "markdown", "md": return "README.md"
        case "python", "py": return "main.py"
        default: return "code.txt"
        }
    }

    private func sheetTable(for embed: EmbedRecord) -> ParsedSheetTable? {
        guard EmbedType(rawValue: embed.type) == .sheetsSheet,
              let data = embed.data,
              case .raw(let dict) = data else { return nil }
        return ParsedSheetTable(data: dict)
    }

    private func downloadSheet(_ table: ParsedSheetTable, from embed: EmbedRecord) {
        let baseName = (table.title?.isEmpty == false ? table.title : "table") ?? "table"
        let filename = "\(baseName).tsv"
        #if os(macOS)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename
        panel.canCreateDirectories = true
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try table.tsv.write(to: url, atomically: true, encoding: .utf8)
                ToastManager.shared.show("Table downloaded", type: .success)
            } catch {
                ToastManager.shared.show("Failed to download table", type: .error)
            }
        }
        #elseif os(iOS)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        do {
            try table.tsv.write(to: url, atomically: true, encoding: .utf8)
            let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = scene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
        } catch {
            ToastManager.shared.show("Failed to download table", type: .error)
        }
        #endif
    }

    private func reportIssue(_ embed: EmbedRecord) {
        ToastManager.shared.show("Report issue", type: .info)
    }
}

// MARK: - Embed top bar

private struct EmbedFullscreenTopBar: View {
    let embed: EmbedRecord
    let showCopy: Bool
    let showDownload: Bool
    let showPreview: Bool
    let previewActive: Bool
    let onClose: () -> Void
    let onShare: () -> Void
    let onCopy: () -> Void
    let onDownload: () -> Void
    let onTogglePreview: () -> Void
    let onReportIssue: () -> Void

    var body: some View {
        HStack(alignment: .center) {
            HStack(spacing: .spacing3) {
                topButton(icon: "share", label: AppStrings.share, action: onShare)
                if showCopy {
                    topButton(icon: "copy", label: AppStrings.copy, action: onCopy)
                }
                if showDownload {
                    topButton(icon: "download", label: "Download", action: onDownload)
                }
                if showPreview {
                    topButton(
                        icon: "preview",
                        label: previewActive ? "Hide preview" : "Show preview",
                        isActive: previewActive,
                        action: onTogglePreview
                    )
                }
                topButton(icon: "bug", label: LocalizationManager.shared.text("header.report_issue"), action: onReportIssue)
            }

            Spacer()

            topButton(icon: "minimize", label: "Minimize", action: onClose)
                .accessibilityIdentifier("embed-minimize")
        }
        .padding(.horizontal, .spacing10)
        .padding(.top, .spacing6)
        .frame(maxWidth: .infinity, alignment: .top)
        .allowsHitTesting(true)
    }

    private func topButton(icon: String, label: String, isActive: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 24)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 34, height: 34)
                .padding(3)
                .background(isActive ? Color.primary.opacity(0.25) : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: 40))
                .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

// MARK: - Fullscreen header

struct EmbedFullscreenHeader: View {
    let embed: EmbedRecord
    var hasPreviousEmbed = false
    var hasNextEmbed = false
    var onNavigatePrevious: () -> Void = {}
    var onNavigateNext: () -> Void = {}

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var animateHeader = false

    private var embedType: EmbedType? { EmbedType(rawValue: embed.type) }
    private var appId: String { embed.appId ?? embedType?.appId ?? "web" }
    private var headerHeight: CGFloat { horizontalSizeClass == .compact ? 190 : 240 }
    private var skillIconName: String {
        switch embed.skillId {
        case "search": return "search"
        case "read": return "visible"
        default:
            return AppIconView.iconName(forAppId: appId)
        }
    }

    var body: some View {
        ZStack {
            AppGradientBackground(appId: appId)

            livingOrb(color: .white.opacity(0.22), size: 220)
                .offset(x: animateHeader ? -86 : -148, y: animateHeader ? -52 : -94)
                .animation(.easeInOut(duration: 19).repeatForever(autoreverses: true), value: animateHeader)
            livingOrb(color: .white.opacity(0.16), size: 220)
                .offset(x: animateHeader ? 154 : 92, y: animateHeader ? 72 : 116)
                .animation(.easeInOut(duration: 23).repeatForever(autoreverses: true), value: animateHeader)
            livingOrb(color: .white.opacity(0.18), size: 190)
                .offset(x: animateHeader ? 48 : 110, y: animateHeader ? -10 : 32)
                .animation(.easeInOut(duration: 29).repeatForever(autoreverses: true), value: animateHeader)

            decorativeIcon(alignment: .leading)
                .offset(x: animateHeader ? -165 : -185, y: animateHeader ? 62 : 78)
                .rotationEffect(.degrees(animateHeader ? -8 : -16))
                .animation(.linear(duration: 16).repeatForever(autoreverses: true), value: animateHeader)
            decorativeIcon(alignment: .trailing)
                .offset(x: animateHeader ? 165 : 185, y: animateHeader ? 78 : 62)
                .rotationEffect(.degrees(animateHeader ? 8 : 16))
                .animation(.linear(duration: 16).repeatForever(autoreverses: true), value: animateHeader)

            VStack(spacing: .spacing2) {
                Icon(skillIconName, size: 38)
                    .foregroundStyle(.white)

                Text(headerTitle)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)

                if let subtitle = headerSubtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(.white.opacity(0.85))
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                }
            }
            .padding(.horizontal, .spacing12)

            if hasNextEmbed {
                headerNavigationButton(direction: .left, action: onNavigateNext)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, .spacing4)
            }

            if hasPreviousEmbed {
                headerNavigationButton(direction: .right, action: onNavigatePrevious)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.trailing, .spacing4)
            }
        }
        .frame(height: headerHeight)
        .clipShape(.rect(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
        .shadow(color: .black.opacity(0.22), radius: 18, x: 0, y: 10)
        .onAppear { animateHeader = true }
    }

    private func decorativeIcon(alignment: Alignment) -> some View {
        Icon(skillIconName, size: horizontalSizeClass == .compact ? 90 : 126)
            .foregroundStyle(.white.opacity(0.4))
            .frame(maxWidth: .infinity, alignment: alignment)
    }

    private func livingOrb(color: Color, size: CGFloat) -> some View {
        Circle()
            .fill(color)
            .frame(width: size, height: size)
            .blur(radius: 28)
    }

    private enum HeaderNavDirection {
        case left
        case right
    }

    private func headerNavigationButton(direction: HeaderNavDirection, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon("back", size: 18)
                .foregroundStyle(.white.opacity(0.85))
                .rotationEffect(direction == .left ? .degrees(0) : .degrees(180))
                .frame(width: 36, height: 36)
                .background(Color.grey50.opacity(0.5))
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
    }

    private var headerTitle: String {
        if let payload = embed.codePayload {
            return payload.filename ?? "Code snippet"
        }
        if let table = sheetTable {
            return table.title ?? LocalizationManager.shared.text("embeds.table")
        }
        if let connection = travelConnection {
            return connection.routeFull ?? EmbedType.travelConnection.displayName
        }
        if embedType == .travelConnections, let first = travelSearchConnections.first {
            return [first.routeFull, first.departureDateText].compactMap { $0 }.joined(separator: " · ")
        }
        guard let data = embed.data, case .raw(let dict) = data else {
            return embedType?.displayName ?? embed.type
        }
        return (dict["query"]?.value as? String)
            ?? (dict["title"]?.value as? String)
            ?? (dict["name"]?.value as? String)
            ?? embedType?.displayName
            ?? embed.type
    }

    private var headerSubtitle: String? {
        if let payload = embed.codePayload {
            let lineText = payload.lineCount == 1 ? "line" : "lines"
            let language = payload.languageDisplayName
            return language.isEmpty ? "\(payload.lineCount) \(lineText)" : "\(payload.lineCount) \(lineText), \(language)"
        }
        if let table = sheetTable {
            return table.dimensionsText
        }
        if let connection = travelConnection {
            return [connection.priceText.map { "\($0) | \(connection.tripTypeLabel)" }, connection.metaLine].compactMap { $0 }.joined(separator: "\n")
        }
        if embedType == .travelConnections {
            let count = travelSearchConnections.count
            let minPrice = travelSearchConnections.compactMap(\.priceNumber).min()
            let currency = travelSearchConnections.first?.currency ?? "EUR"
            var parts: [String] = []
            if count > 0 { parts.append("\(count) \(count == 1 ? "connection" : "connections")") }
            if let minPrice { parts.append("from \(currency) \(String(format: "%.0f", minPrice))") }
            return parts.joined(separator: " · ")
        }
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        if let provider = dict["provider"]?.value as? String {
            return "via \(provider == "Brave" ? "Brave Search" : provider)"
        }
        if let pageAge = dict["page_age"]?.value as? String {
            return pageAge
        }
        return dict["url"]?.value as? String
    }

    private var sheetTable: ParsedSheetTable? {
        guard embedType == .sheetsSheet,
              let data = embed.data,
              case .raw(let dict) = data else { return nil }
        return ParsedSheetTable(data: dict)
    }

    private var travelConnection: TravelConnectionSummary? {
        guard embedType == .travelConnection,
              let data = embed.rawData else { return nil }
        return TravelConnectionSummary(embedId: embed.id, data: data)
    }

    private var travelSearchConnections: [TravelConnectionSummary] {
        guard embedType == .travelConnections else { return [] }
        return TravelConnectionSummary.list(from: embed.rawData)
    }
}

private struct CodePayload {
    let code: String
    let language: String
    let filename: String?
    let lineCount: Int

    var languageDisplayName: String {
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

private extension EmbedRecord {
    var codePayload: CodePayload? {
        guard EmbedType(rawValue: type) == .codeCode,
              let data,
              case .raw(let dict) = data else { return nil }
        let rawCode = dict["code"]?.value as? String ?? ""
        let language = dict["language"]?.value as? String ?? ""
        let filename = dict["filename"]?.value as? String
        let code = rawCode
            .replacingOccurrences(of: #"\""#, with: #"""#)
            .replacingOccurrences(of: #"\/"#, with: "/")
        let lineCount = dict["lineCount"]?.value as? Int
            ?? dict["line_count"]?.value as? Int
            ?? code.components(separatedBy: "\n").count
        return CodePayload(code: code, language: language, filename: filename, lineCount: lineCount)
    }
}
