// Fullscreen embed container with navigation between embeds in a group.
// Supports prev/next navigation arrows, child embed loading for composite types,
// and the full slide-up presentation matching the web app.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/EmbedHeader.svelte
//          frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte
//          frontend/packages/ui/src/components/embeds/web/WebsiteEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
    var onOpenEmbed: (EmbedRecord, EmbedRecord) -> Void = { _, _ in }
    var onClose: () -> Void = {}
    var isSidePanel = false
    var showChat = false
    var onShowChat: () -> Void = {}

    @State private var selection = EmbedFullscreenSelection()
    @State private var isPresented = false
    #if DEBUG
    @State private var debugPresentationReady = false
    @State private var debugPresentationGeneration = UUID()
    private var exposesPresentationReadiness: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-embed-presentation")
    }
    #endif
    @State private var codePreviewActive = false
    @State private var headerFrame: CGRect = .zero
    @State private var moreActionsOpen = false
    @State private var shareContext: AppleShareContext?
    @State private var selectedVersionNumber: Int?
    @State private var restoreConfirmVersion: Int?
    @StateObject private var codeRunViewModel = CodeRunViewModel()
    @Environment(\.openURL) private var openURL

    private var currentEmbed: EmbedRecord? {
        guard let id = selection.resolvedID(in: embeds, initialID: initialEmbedId) else { return nil }
        return embeds.first { $0.id == id }
    }

    private var currentIndex: Int {
        embeds.firstIndex { $0.id == currentEmbed?.id } ?? 0
    }

    private func navigateFullscreen(by offset: Int) {
        guard selection.move(by: offset, in: embeds, initialID: initialEmbedId) else { return }
        resetPerEmbedState()
    }

    private func resetPerEmbedState() {
        codePreviewActive = false
        selectedVersionNumber = nil
        restoreConfirmVersion = nil
        codeRunViewModel.cleanup()
    }

    private var currentEmbedType: EmbedType? {
        guard let currentEmbed else { return nil }
        return EmbedType.normalized(rawValue: currentEmbed.type)
    }

    private var isCodeEmbed: Bool {
        currentEmbedType == .codeCode
    }

    private var isSheetEmbed: Bool {
        currentEmbedType == .sheetsSheet
    }

    private var usesEdgeToEdgeContent: Bool {
        switch currentEmbedType {
        // These renderers own their responsive content gutters. Adding generic
        // fullscreen padding shifts the web grid and shrinks website snippets.
        case .webSearch, .webWebsite, .eventsEvent, .travelConnection, .travelStay:
            return true
        default:
            return false
        }
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
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return explicit }
        return allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
    }

    var body: some View {
        // Capture the system insets before the full-bleed content ignores them.
        // A GeometryReader inside ignoresSafeArea reports the expanded region;
        // using that region for the controls put Minimize under the status bar.
        GeometryReader { safeArea in
            fullscreenContent(safeAreaInsets: safeArea.safeAreaInsets)
                .coordinateSpace(name: "embed-fullscreen-coordinate")
        }
        #if DEBUG
        .overlay(alignment: .topLeading) {
            if exposesPresentationReadiness {
                Color.clear.frame(width: 1, height: 1).accessibilityElement()
                    .accessibilityIdentifier("embed-presentation-state")
                    .accessibilityLabel(debugPresentationReady ? "ready" : "presenting")
                    .allowsHitTesting(false)
            }
        }
        #endif
        .onAppear {
            selection.reconcile(in: embeds, initialID: initialEmbedId)
            #if DEBUG
            if exposesPresentationReadiness {
                let generation = UUID()
                debugPresentationGeneration = generation
                debugPresentationReady = false
                // XCTest can see and hit-test a control while its containing
                // surface is still moving. Observe the actual existing slide
                // completion, not a guessed delay or an early `isHittable`.
                withAnimation(.easeOut(duration: 0.28), completionCriteria: .removed) {
                    isPresented = true
                } completion: {
                    guard debugPresentationGeneration == generation, isPresented else { return }
                    debugPresentationReady = true
                }
            } else {
                isPresented = true
            }
            #else
            isPresented = true
            #endif
        }
        .onChange(of: embeds.map(\.id)) { _, _ in
            let previousID = selection.selectedID
            selection.reconcile(in: embeds, initialID: initialEmbedId)
            if selection.selectedID != previousID { resetPerEmbedState() }
        }
        .onChange(of: initialEmbedId) { _, _ in
            selection = EmbedFullscreenSelection()
            selection.reconcile(in: embeds, initialID: initialEmbedId)
            resetPerEmbedState()
        }
        .onDisappear {
            #if DEBUG
            debugPresentationGeneration = UUID()
            debugPresentationReady = false
            #endif
            codeRunViewModel.cleanup()
        }
    }

    private func fullscreenContent(safeAreaInsets: EdgeInsets) -> some View {
        GeometryReader { proxy in
            ZStack(alignment: .top) {
                if let embed = currentEmbed {
                    ScrollView {
                        VStack(spacing: 0) {
                            EmbedFullscreenHeader(
                                embed: embed,
                                hasPreviousEmbed: currentIndex > 0,
                                hasNextEmbed: currentIndex < embeds.count - 1,
                                onNavigatePrevious: { withAnimation { navigateFullscreen(by: -1) } },
                                onNavigateNext: { withAnimation { navigateFullscreen(by: 1) } },
                                headerCTA: headerCTA(for: embed),
                                topContentInset: safeAreaInsets.top,
                                viewportWidth: proxy.size.width
                            )
                            .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("embed-fullscreen-coordinate")) } action: { headerFrame = $0 }
                            .zIndex(2)

                            EmbedContentView(
                                embed: embed,
                                mode: .fullscreen,
                                allEmbedRecords: allEmbedRecords,
                                codePreviewActive: codePreviewActive,
                                codeRunViewModel: codeRunViewModel,
                                chatId: chatId,
                                onOpenEmbed: { child in
                                    onOpenEmbed(child, embed)
                                }
                            )
                                .padding(.horizontal, usesEdgeToEdgeContent ? 0 : .spacing8)
                                .padding(.vertical, usesEdgeToEdgeContent ? 0 : .spacing10)
                                .zIndex(0)

                            if shouldShowVersionTimeline(for: embed) {
                                versionTimeline(for: embed)
                            }

                            if !embed.isAppSkillUse && !childEmbeds.isEmpty {
                                childEmbedSection
                            }
                        }
                    }
                    .background(Color.grey20)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                    if moreActionsOpen {
                        Color.clear.contentShape(Rectangle()).onTapGesture { moreActionsOpen = false }
                            .accessibilityHidden(true)
                    }
                    EmbedFullscreenTopBar(
                        embed: embed,
                        showCopy: isCodeEmbed || isSheetEmbed,
                        showDownload: isCodeEmbed || isSheetEmbed,
                        showRun: isCodeRunnable,
                        runActive: codeRunViewModel.isActive,
                        showPreview: isCodePreviewable,
                        previewActive: codePreviewActive,
                        viewportWidth: proxy.size.width,
                        headerFrame: headerFrame,
                        moreOpen: $moreActionsOpen,
                        onClose: closeWithAnimation,
                        onShare: { shareEmbed(embed) },
                        onCopy: { copyEmbedContent(embed) },
                        onDownload: { downloadCodeFile(embed) },
                        onRun: { runCode(embed) },
                        onTogglePreview: { codePreviewActive.toggle() },
                        onReportIssue: { reportIssue(embed) },
                        showChat: showChat, onShowChat: onShowChat
                    )
                    .padding(.top, safeAreaInsets.top)
                    .padding(.leading, safeAreaInsets.leading)
                    .padding(.trailing, safeAreaInsets.trailing)
                }

                if let shareContext {
                    Color.black.opacity(0.35)
                        .ignoresSafeArea()
                        .onTapGesture { self.shareContext = nil }

                    VStack(spacing: 0) {
                        HStack {
                            Text(AppStrings.share)
                                .font(.omH3.weight(.semibold))
                                .foregroundStyle(Color.fontPrimary)
                            Spacer()
                            OMIconButton(icon: "close", label: AppStrings.close, size: 34) {
                                self.shareContext = nil
                            }
                        }
                        .padding(.spacing6)
                        .background(Color.grey0)

                        ShareEmbedView(
                            context: shareContext,
                            onClose: { self.shareContext = nil },
                            onGenerated: updateEmbedShareMetadata
                        )
                    }
                    .frame(maxWidth: 620, maxHeight: 760)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1))
                    .shadow(color: .black.opacity(0.18), radius: 24, x: 0, y: 12)
                    .padding(.spacing8)
                    .accessibilityIdentifier("embed-share-panel")
                }
            }
            .offset(y: isSidePanel || isPresented ? 0 : proxy.size.height)
            .animation(isSidePanel ? nil : .easeOut(duration: 0.28), value: isPresented)
        }
        .ignoresSafeArea()
    }

    private func headerCTA(for embed: EmbedRecord) -> EmbedHeaderCTA? {
        if EmbedType(rawValue: embed.type) == .codeCode,
           isCodeRunnable,
           let payload = embed.codePayload,
           let chatId,
           !chatId.isEmpty,
           !codeRunViewModel.isPanelOpen {
            return EmbedHeaderCTA(title: codeRunViewModel.ctaTitle, accessibilityIdentifier: "embed-run-button") {
                runCode(embed, payload: payload)
            }
        }

        guard let type = EmbedType.normalized(rawValue: embed.type),
              let data = rawData(for: embed) else {
            return nil
        }

        switch type {
        case .webWebsite:
            guard let url = firstString(["url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider(host(from: url))) {
                openExternalURL(url)
            }

        case .imagesImageResult:
            if let imageURL = firstString(["image_url", "thumbnail_original", "image", "url"], in: data) {
                return EmbedHeaderCTA(title: AppStrings.imageSearchOpenImage) {
                    openExternalURL(imageURL)
                }
            }
            if let sourceURL = firstString(["source_page_url"], in: data) {
                return EmbedHeaderCTA(title: AppStrings.imageSearchViewSource) {
                    openExternalURL(sourceURL)
                }
            }
            return nil

        case .eventsEvent:
            guard let url = firstString(["url", "booking_url"], in: data) else { return nil }
            let event = EventResultSummary(embedId: embed.id, data: data)
            let provider = event.providerLabel ?? host(from: url)
            let normalizedProvider = event.provider?.lowercased() ?? ""
            let title: String
            if ["luma", "eventbrite", "meetup"].contains(normalizedProvider) {
                title = AppStrings.registerOnProvider(provider)
            } else if ["classictic", "berlin_philharmonic", "bachtrack", "ticketmaster", "eventim", "dice"].contains(normalizedProvider) {
                title = AppStrings.bookOnProvider(provider)
            } else {
                title = AppStrings.openOnProvider(provider)
            }
            return EmbedHeaderCTA(title: title) {
                openExternalURL(url)
            }

        case .travelConnection:
            let connection = TravelConnectionSummary(embedId: embed.id, data: data)
            if let bookingURL = connection.bookingURL {
                let provider = connection.bookingProvider ?? connection.carrierCodes.first ?? host(from: bookingURL)
                return EmbedHeaderCTA(title: AppStrings.bookOnProvider(provider)) {
                    openExternalURL(bookingURL)
                }
            }
            if let googleFlightsURL = connection.googleFlightsURL {
                return EmbedHeaderCTA(title: AppStrings.openGoogleFlights) {
                    openExternalURL(googleFlightsURL)
                }
            }
            return nil

        case .travelStay:
            guard let url = firstString(["link", "url", "booking_url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.viewOnGoogleHotels) {
                openExternalURL(url)
            }

        case .businessCompanyFinancialResult:
            guard let url = firstString(["source_url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.businessFinancialOpenFiling, accessibilityIdentifier: "business-open-sec-filing") {
                openExternalURL(url)
            }

        default:
            return nil
        }
    }

    private func rawData(for embed: EmbedRecord) -> [String: AnyCodable]? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        return dict
    }

    private func currentVersionNumber(for embed: EmbedRecord) -> Int {
        if let versionNumber = embed.versionNumber { return versionNumber }
        guard let data = rawData(for: embed) else { return 1 }
        if let value = data["version_number"]?.value as? Int { return value }
        if let value = data["current_source_version"]?.value as? Int { return value }
        return 1
    }

    private func timelineVersions(for embed: EmbedRecord) -> [EmbedVersionMetadata] {
        if !embed.versionHistory.isEmpty { return embed.versionHistory }
        let currentVersionNumber = currentVersionNumber(for: embed)
        guard currentVersionNumber > 1 else { return [] }
        return (1...currentVersionNumber).map {
            EmbedVersionMetadata(versionNumber: $0, createdAt: 0, hasSnapshot: $0 == 1, hasPatch: $0 > 1, contentHash: nil)
        }
    }

    private func selectedVersion(for embed: EmbedRecord) -> Int {
        selectedVersionNumber ?? currentVersionNumber(for: embed)
    }

    private func shouldShowVersionTimeline(for embed: EmbedRecord) -> Bool {
        timelineVersions(for: embed).count > 1
    }

    private func versionTimeline(for embed: EmbedRecord) -> some View {
        let versions = timelineVersions(for: embed)
        let currentVersion = currentVersionNumber(for: embed)
        let selectedVersion = selectedVersion(for: embed)

        return VStack(alignment: .leading, spacing: .spacing4) {
            HStack {
                Text("Version history")
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                Text("\(versions.count) versions")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(versions) { version in
                        let isSelected = version.versionNumber == selectedVersion
                        let isCurrent = version.versionNumber == currentVersion
                        Button {
                            selectedVersionNumber = version.versionNumber
                            restoreConfirmVersion = nil
                        } label: {
                            VStack(spacing: .spacing2) {
                                Circle()
                                    .fill(isCurrent ? Color.buttonPrimary : (isSelected ? Color.buttonPrimary : Color.grey30))
                                    .frame(width: 10, height: 10)
                                    .overlay(
                                        Circle()
                                            .stroke(Color.buttonPrimary.opacity(isSelected ? 0.25 : 0), lineWidth: 6)
                                    )
                                Text("v\(version.versionNumber)")
                                    .font(.omMicro)
                                    .foregroundStyle(isSelected ? Color.buttonPrimary : Color.fontSecondary)
                            }
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing3)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("embed-version-dot-\(version.versionNumber)")
                    }
                    if selectedVersion != currentVersion {
                        restoreButton(for: embed, selectedVersion: selectedVersion)
                    }
                }
                .padding(.vertical, .spacing2)
            }

            VStack(alignment: .leading, spacing: .spacing3) {
                Text(versionTimelineStatusText(selectedVersion: selectedVersion, currentVersion: currentVersion))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }

            if embed.versionHistoryReadonly {
                Text("Read-only shared history")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embed-version-readonly")
            }
        }
        .padding(.spacing5)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .overlay(
            RoundedRectangle(cornerRadius: .radius5)
                .stroke(Color.grey25, lineWidth: 1)
        )
        .padding(.horizontal, .spacing6)
        .padding(.bottom, .spacing5)
        .accessibilityIdentifier("embed-version-timeline")
    }

    private func restoreButton(for embed: EmbedRecord, selectedVersion: Int) -> some View {
        Button {
            guard !embed.versionHistoryReadonly else { return }
            restoreConfirmVersion = restoreConfirmVersion == selectedVersion ? nil : selectedVersion
        } label: {
            Text(restoreConfirmVersion == selectedVersion ? "Confirm restore v\(selectedVersion)" : "Restore v\(selectedVersion)")
                .font(.omXs)
                .fontWeight(.semibold)
                .foregroundStyle(Color.buttonPrimary)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
                .overlay(
                    RoundedRectangle(cornerRadius: .radius3)
                        .stroke(Color.buttonPrimary, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .disabled(embed.versionHistoryReadonly)
        .accessibilityIdentifier("embed-version-restore-button")
    }

    private func versionTimelineStatusText(selectedVersion: Int, currentVersion: Int) -> String {
        if selectedVersion == currentVersion { return "Current version v\(currentVersion)" }
        return "Viewing historical version v\(selectedVersion)"
    }

    private func firstString(_ keys: [String], in data: [String: AnyCodable]) -> String? {
        for key in keys {
            if let value = data[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private func host(from urlString: String) -> String {
        guard let host = URL(string: urlString)?.host else { return urlString }
        let parts = host.replacingOccurrences(of: "www.", with: "").split(separator: ".")
        guard parts.count > 2 else { return parts.joined(separator: ".") }
        let lastTwo = parts.suffix(2).joined(separator: ".")
        let twoPartTLDs = ["co.uk", "com.au", "co.nz", "org.uk", "com.br", "co.jp", "co.kr", "co.in", "com.mx", "com.cn"]
        if twoPartTLDs.contains(lastTwo), parts.count >= 3 {
            return parts.suffix(3).joined(separator: ".")
        }
        return lastTwo
    }

    private func openExternalURL(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        openURL(url)
    }

    private func closeWithAnimation() {
        if isSidePanel { onClose(); return }
        #if DEBUG
        debugPresentationReady = false
        #endif
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
                    if let currentEmbed {
                        onOpenEmbed(embed, currentEmbed)
                    }
                }
                .padding(.horizontal, .spacing6)
            }
        }
        .padding(.bottom, .spacing8)
    }

    private func shareEmbed(_ embed: EmbedRecord) {
        Task {
            guard let chatId, !chatId.isEmpty,
                  let key = await EmbedKeyManager.shared.key(
                    for: embed,
                    chatId: chatId,
                    allEmbeds: allEmbedRecords
                  ) else {
                ToastManager.shared.show(AppStrings.error, type: .error)
                return
            }
            shareContext = AppleShareContext(
                contentType: .embed,
                id: embed.id,
                title: embed.type,
                summary: nil,
                key: key,
                chatId: chatId
            )
        }
    }

    private func updateEmbedShareMetadata(_ url: URL, _ usedLongFallback: Bool, _ duration: ShareDuration) async {
        guard let shareContext else { return }
        do {
            let body: [String: Any] = [
                "embed_id": shareContext.id,
                "title": shareContext.title,
                "description": NSNull(),
                "is_shared": true
            ]
            let _: Data = try await APIClient.shared.request(.post, path: "/v1/share/embed/metadata", body: body)
            NativeDiagnostics.info(
                "Embed share metadata synced kind=\(usedLongFallback ? "long" : "short") duration=\(duration.rawValue)",
                category: "sharing"
            )
        } catch {
            NativeDiagnostics.warning("Embed share metadata sync failed", category: "sharing")
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

    private var isCodeRunnable: Bool {
        guard let payload = currentEmbed?.codePayload else { return false }
        return CodeRunSupport.isSupported(language: payload.language, filename: payload.filename)
    }

    private func runCode(_ embed: EmbedRecord) {
        guard let payload = embed.codePayload else { return }
        runCode(embed, payload: payload)
    }

    private func runCode(_ embed: EmbedRecord, payload: CodePayload) {
        guard let chatId, !chatId.isEmpty else {
            ToastManager.shared.show(AppStrings.loginSignup, type: .info)
            return
        }
        codePreviewActive = false
        codeRunViewModel.toggleRun(
            chatId: chatId,
            embedId: embed.id,
            file: CodeRunClientFile(
                embedId: embed.id,
                code: payload.code,
                language: payload.language,
                filename: payload.filename,
                isTarget: true
            )
        )
    }
}

// MARK: - Embed top bar

// HeaderActionMenu.svelte: container-width breakpoints, overflow count and order.
enum EmbedHeaderActionPolicy {
    static func usesMore(width: CGFloat, actionCount: Int, hasShare: Bool = true) -> Bool {
        actionCount + (hasShare && width < 460 ? 1 : 0) >= 2
    }
    static func reportShowsLabel(width: CGFloat) -> Bool { width >= 640 }
    static func menuWidth(toolbar: CGRect, anchor: CGRect) -> CGFloat {
        guard !toolbar.isEmpty, !anchor.isEmpty else { return 0 }
        // The toolbar includes its16pt outer padding; HeaderActionMenu's root
        // starts inside that padding. Reserve its8pt shadow clearance before
        // compensating for the left-anchored1.08 hover transform.
        return max(0, (toolbar.maxX - 16 - anchor.minX - 8) / 1.08)
    }
    static func overlaps(control: CGRect, header: CGRect) -> Bool {
        !header.isEmpty && control.intersects(header) && control.intersection(header).width > 0 && control.intersection(header).height > 0
    }
}

private struct EmbedFullscreenTopBar: View {
    let embed: EmbedRecord
    let showCopy: Bool
    let showDownload: Bool
    let showRun: Bool
    let runActive: Bool
    let showPreview: Bool
    let previewActive: Bool
    let viewportWidth: CGFloat
    let headerFrame: CGRect
    @Binding var moreOpen: Bool
    let onClose: () -> Void
    let onShare: () -> Void
    let onCopy: () -> Void
    let onDownload: () -> Void
    let onRun: () -> Void
    let onTogglePreview: () -> Void
    let onReportIssue: () -> Void
    var showChat = false
    var onShowChat: () -> Void = {}
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var focusedActionID: String?
    @State private var toolbarFrame: CGRect = .zero
    @State private var moreFrame: CGRect = .zero
    @State private var focusFirstMenuAction = false
    private struct Action: Identifiable {
        let id: String
        let icon: String
        let label: String
        var active = false
        let perform: () -> Void
    }
    private var share: Action { .init(id: "share", icon: "share", label: AppStrings.shareChat, perform: onShare) }
    private var actions: [Action] {
        var values: [Action] = []
        if showCopy { values.append(.init(id: "copy", icon: "copy", label: AppStrings.copy, perform: onCopy)) }
        if showDownload { values.append(.init(id: "download", icon: "download", label: AppStrings.download, perform: onDownload)) }
        if showRun { values.append(.init(id: "run", icon: "play", label: AppStrings.codeRun, active: runActive, perform: onRun)) }
        if showPreview { values.append(.init(id: "preview", icon: "preview", label: AppStrings.preview, active: previewActive, perform: onTogglePreview)) }
        return values
    }
    private var usesMore: Bool { EmbedHeaderActionPolicy.usesMore(width: viewportWidth, actionCount: actions.count) }
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            pill(.init(id: "report", icon: "bug", label: LocalizationManager.shared.text("header.report_issue"), perform: onReportIssue), label: EmbedHeaderActionPolicy.reportShowsLabel(width: viewportWidth))
            if viewportWidth >= 460 { pill(share) }
            if showChat {
                pill(.init(id: "show-chat", icon: "chat", label: LocalizationManager.shared.text("chat.show_chat"), perform: onShowChat), label: true)
            }

            if usesMore {
                pill(.init(id: "more", icon: "more", label: LocalizationManager.shared.text("common.more_actions"), perform: {
                    moreOpen.toggle()
                    if moreOpen { focusedActionID = "more" }
                }))
                    .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("embed-fullscreen-coordinate")) } action: { moreFrame = $0 }
                    .accessibilityValue(moreOpen ? "expanded" : "collapsed")
                    .overlay(alignment: .topLeading) {
                        if moreOpen {
                            ViewThatFits(in: .horizontal) {
                                menuActions.fixedSize(horizontal: true, vertical: true)
                                menuActions.frame(width: menuWidth, alignment: .leading)
                            }
                            // An overlay is proposed the trigger's41pt width.
                            // Supply the measured canvas explicitly; ViewThatFits
                            // uses natural pill widths unless wrapping is required.
                            .frame(width: menuWidth, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                            .task {
                                if focusFirstMenuAction, moreOpen {
                                    focusedActionID = viewportWidth < 460 ? "share" : actions.first?.id
                                    focusFirstMenuAction = false
                                }
                            }
                            .offset(y: 53)
                            .transition(.offset(y: -8).combined(with: .opacity))
                            .accessibilityElement(children: .contain)
                            .accessibilityIdentifier("embed-more-actions")
                        }
                    }.zIndex(3)
            } else {
                if viewportWidth < 460 { pill(share) }
                ForEach(actions) { pill($0) }
            }
            Spacer(minLength: 0)
            pill(.init(id: "close", icon: "close", label: AppStrings.close, perform: onClose))
                .accessibilityIdentifier("embed-minimize") // Preserve existing automation contract.
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .top)
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("embed-fullscreen-coordinate")) } action: { toolbarFrame = $0 }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: moreOpen)
        .onChange(of: embed.id) { _, _ in moreOpen = false; focusFirstMenuAction = false }
        .onChange(of: moreOpen) { _, open in if !open { focusFirstMenuAction = false } }
        .onKeyPress(.downArrow) {
            guard focusedActionID == "more", usesMore else { return .ignored }
            if moreOpen {
                focusedActionID = viewportWidth < 460 ? "share" : actions.first?.id
            } else {
                focusFirstMenuAction = true; moreOpen = true
            }
            return .handled
        }
        .onChange(of: usesMore) { _, value in if !value { moreOpen = false } }
        .onKeyPress(.escape) {
            guard moreOpen else { return .ignored }; moreOpen = false; focusedActionID = "more"; return .handled
        }
    }
    private var menuWidth: CGFloat { EmbedHeaderActionPolicy.menuWidth(toolbar: toolbarFrame, anchor: moreFrame) }
    private var menuActions: some View {
        VStack(alignment: .leading, spacing: 8) {
            if viewportWidth < 460 { pill(share, label: true, inMenu: true) }
            ForEach(actions) { pill($0, label: true, inMenu: true) }
        }
    }
    private func pill(_ action: Action, label: Bool = false, inMenu: Bool = false) -> some View {
        EmbedHeaderActionPill(icon: action.icon, label: action.label, showsLabel: label,
                              headerFrame: inMenu ? .zero : headerFrame, active: action.active, inMenu: inMenu) {
            if action.id != "more" { moreOpen = false }
            action.perform()
        }.focused($focusedActionID, equals: action.id)
            .accessibilityIdentifier("embed-\(action.id)-button")
    }
}

private struct EmbedHeaderActionPill: View {
    let icon: String
    let label: String
    let showsLabel: Bool
    let headerFrame: CGRect
    let active: Bool
    let inMenu: Bool
    let action: () -> Void
    @State private var frame: CGRect = .zero
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var overHeader: Bool { EmbedHeaderActionPolicy.overlaps(control: frame, header: headerFrame) }
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Icon(icon, size: 25)
                    .foregroundStyle(overHeader ? AnyShapeStyle(Color.white) : AnyShapeStyle(LinearGradient.primary))
                if showsLabel {
                    Text(label).font(.custom("Lexend Deca", size: 16).weight(.semibold))
                        .foregroundStyle(overHeader ? Color.white : Color.fontPrimary).padding(.trailing, 8)
                }
            }.padding(8)
                .background(overHeader ? Color.white.opacity(0.2) : Color.grey10)
                .clipShape(Capsule())
                .contentShape(Capsule())
        }.buttonStyle(EmbedHeaderPillInteractionStyle(anchor: inMenu ? .leading : .center))
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: overHeader)
            .help(Text(label)).accessibilityLabel(label)
            .accessibilityAddTraits(active ? .isSelected : [])
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("embed-fullscreen-coordinate")) } action: { frame = $0 }
            #if DEBUG
            .accessibilityValue(overHeader ? "header-overlay" : "content-control")
            #endif
    }
}
private struct EmbedHeaderPillInteractionStyle: ButtonStyle {
    let anchor: UnitPoint
    @State private var hovered = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.95 : hovered ? 1.08 : 1, anchor: anchor)
            .shadow(color: .black.opacity(0.15), radius: configuration.isPressed ? 2 : hovered ? 12 : 8, x: 0, y: 2)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: configuration.isPressed)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: hovered)
            .onHover { hovered = $0 }
    }
}

// MARK: - Fullscreen header

struct EmbedHeaderCTA {
    let title: String
    var accessibilityIdentifier: String?
    let action: () -> Void

    init(title: String, accessibilityIdentifier: String? = nil, action: @escaping () -> Void) {
        self.title = title
        self.accessibilityIdentifier = accessibilityIdentifier
        self.action = action
    }
}

struct EmbedFullscreenHeader: View {
    let embed: EmbedRecord
    var hasPreviousEmbed = false
    var hasNextEmbed = false
    var onNavigatePrevious: () -> Void = {}
    var onNavigateNext: () -> Void = {}
    var headerCTA: EmbedHeaderCTA?
    var topContentInset: CGFloat = 0
    var viewportWidth: CGFloat? = nil

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    // Match the web's width breakpoint, including narrow macOS windows and
    // iPad split views whose platform size class may remain regular.
    private var isNarrow: Bool { viewportWidth.map { $0 <= 730 } ?? (horizontalSizeClass == .compact) }
    private var embedType: EmbedType? { EmbedType.normalized(rawValue: embed.type) }
    private var appId: String { embed.appId ?? embedType?.appId ?? "web" }
    private var headerHeight: CGFloat {
        (isNarrow ? 190 : 240) + topContentInset
    }
    private var headerFrameHeight: CGFloat {
        headerHeight
    }
    private var ctaOffsetY: CGFloat {
        headerHeight - 22
    }
    private var skillIconName: String {
        switch embed.skillId {
        case "search": return "search"
        case "read": return "visible"
        default:
            return AppIconView.iconName(forAppId: appId)
        }
    }

    var body: some View {
        ZStack(alignment: .top) {
            headerPanel
                .frame(height: headerHeight)
                .clipShape(.rect(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
                .shadow(color: .black.opacity(0.22), radius: 18, x: 0, y: 10)

            if let headerCTA {
                headerCTAButton(headerCTA)
                    .offset(y: ctaOffsetY)
            }
        }
        .frame(width: viewportWidth, height: headerFrameHeight)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embed-fullscreen-header")
        .accessibilityValue(embed.id)
    }

    private var headerPanel: some View {
        ZStack {
            AppGradientBackground(appId: appId)
                .overlay { headerDecorations }
                .accessibilityHidden(true)

            VStack(spacing: .spacing2) {
                Icon(skillIconName, size: isNarrow ? 32 : 38)
                    .foregroundStyle(.white)

                Text(headerTitle)
                    .accessibilityIdentifier("embed-header-title")
                    .font(isNarrow ? .omLg : .omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)

                if let subtitle = headerSubtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(isNarrow ? .omXs : .omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(.white.opacity(0.85))
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                }
            }
            // Web max-width applies to its content box; padding is outside.
            // At390pt this permits350pt of content plus40pt horizontal padding.
            .frame(maxWidth: isNarrow ? 360 : 480)
            .padding(.horizontal, isNarrow ? .spacing10 : .spacing12)
            // The background still starts at the screen edge. Reserving the
            // system inset inside the taller panel moves only its foreground
            // below the inset top bar, keeping title and navigation unobscured.
            .padding(.top, topContentInset)

            if hasNextEmbed {
                headerNavigationButton(direction: .left, action: onNavigateNext)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, .spacing4)
                    .padding(.top, topContentInset)
            }

            if hasPreviousEmbed {
                headerNavigationButton(direction: .right, action: onNavigatePrevious)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.trailing, .spacing4)
                    .padding(.top, topContentInset)
            }
        }
    }

    // Decorations are a bounded overlay: transforms affect glyphs, never a
    // full-width HStack/frame. This also prevents decorative AX extent leakage.
    private var headerDecorations: some View {
        EmbedHeaderAnimatedDecorations(appID: appId, skillIcon: skillIconName, narrow: isNarrow)
    }

    private func headerCTAButton(_ cta: EmbedHeaderCTA) -> some View {
        Button(action: cta.action) {
            Text(cta.title)
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontButton)
                .lineLimit(1)
                .minimumScaleFactor(0.78)
                .padding(.horizontal, .spacing12)
                .padding(.vertical, .spacing6)
                .frame(minWidth: isNarrow ? 160 : 200)
                .background(Color.buttonPrimary)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
        }
        .buttonStyle(.plain)
        .help(Text(cta.title))
        .accessibilityLabel(cta.title)
        .accessibilityIdentifier(cta.accessibilityIdentifier ?? "embed-header-cta")
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
        .accessibilityLabel(direction == .left ? AppStrings.next : AppStrings.back)
        .accessibilityIdentifier(direction == .left ? "embed-next" : "embed-previous")
    }

    private var headerTitle: String {
        if let payload = embed.codePayload {
            return payload.filename ?? "Code snippet"
        }
        if let table = sheetTable {
            return table.title ?? LocalizationManager.shared.text("embeds.table")
        }
        if let connection = travelConnection {
            return connection.priceHeader ?? EmbedType.travelConnection.displayName
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
            return [connection.routeFull, connection.metaLine].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n")
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
        if embedType == .eventsEvent {
            let event = EventResultSummary(embedId: embed.id, data: dict)
            return [event.shortDate, event.shortLocation].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        }
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

private enum CodeRunSupport {
    private static let runnableLanguages: Set<String> = [
        "python", "py",
        "javascript", "js", "node",
        "typescript", "ts",
        "bash", "sh", "shell",
        "c",
        "cpp", "c++", "cplusplus",
        "rust", "rs",
        "go", "golang",
    ]

    private static let runnableExtensions: Set<String> = [
        ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".c", ".cc", ".cpp", ".cxx", ".rs", ".go",
    ]

    static func isSupported(language: String, filename: String?) -> Bool {
        let normalizedLanguage = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if runnableLanguages.contains(normalizedLanguage) { return true }
        guard let filename, let dotIndex = filename.lastIndex(of: ".") else { return false }
        return runnableExtensions.contains(String(filename[dotIndex...]).lowercased())
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

// Exact animations.css orbMorph1/2/3, orbDrift1/2/3, decoEnter/decoFloat.
// Interpolate each CSS keyframe interval with its own timing function; a sine
// approximation changes both positions and velocity at the supplied keyframes.
enum EmbedHeaderMotion {
    struct Frame { let time: Double; let values: [Double] }
    static let morph: [[Frame]] = [
        [.init(time: 0, values: [60,40,30,70,60,30,70,40]), .init(time: 0.25, values: [30,60,70,40,50,60,30,60]), .init(time: 0.5, values: [50,50,33,67,55,27,73,45]), .init(time: 0.75, values: [33,67,45,55,30,70,35,65]), .init(time: 1, values: [60,40,30,70,60,30,70,40])],
        [.init(time: 0, values: [40,60,60,40,40,40,60,60]), .init(time: 0.33, values: [65,35,40,60,60,45,55,40]), .init(time: 0.66, values: [35,65,55,45,45,55,40,60]), .init(time: 1, values: [40,60,60,40,40,40,60,60])],
        [.init(time: 0, values: [55,45,38,62,48,58,42,52]), .init(time: 0.2, values: [42,58,62,38,55,38,62,45]), .init(time: 0.4, values: [68,32,45,55,40,65,35,60]), .init(time: 0.6, values: [38,62,55,45,62,42,58,38]), .init(time: 0.8, values: [52,48,32,68,35,55,45,65]), .init(time: 1, values: [55,45,38,62,48,58,42,52])]
    ]
    static let drift: [[Frame]] = [
        [.init(time: 0, values: [0,0]), .init(time: 0.25, values: [130,60]), .init(time: 0.5, values: [160,10]), .init(time: 0.75, values: [60,100]), .init(time: 1, values: [0,0])],
        [.init(time: 0, values: [0,0]), .init(time: 0.3, values: [-140,-50]), .init(time: 0.6, values: [-80,-130]), .init(time: 0.85, values: [-160,-30]), .init(time: 1, values: [0,0])],
        [.init(time: 0, values: [0,0]), .init(time: 0.2, values: [-90,50]), .init(time: 0.45, values: [80,80]), .init(time: 0.7, values: [-40,-70]), .init(time: 1, values: [0,0])]
    ]
    static let morphDurations: [Double] = [11,13,17]
    static let driftDurations: [Double] = [19,23,29]
    private static let orbit: [Frame] = [
        .init(time: 0, values: [0,-12,0]), .init(time: 0.125, values: [7.07,-8.484,2]),
        .init(time: 0.25, values: [10,0,3]), .init(time: 0.375, values: [7.07,8.484,2]),
        .init(time: 0.5, values: [0,12,0]), .init(time: 0.625, values: [-7.07,8.484,-2]),
        .init(time: 0.75, values: [-10,0,-3]), .init(time: 0.875, values: [-7.07,-8.484,-2]),
        .init(time: 1, values: [0,-12,0])]
    static func interpolate(_ frames: [Frame], phase: Double, eased: Bool) -> [Double] {
        let phase = min(1, max(0, phase))
        guard let index = frames.indices.dropLast().first(where: { phase <= frames[$0 + 1].time }) else { return frames.last!.values }
        let a = frames[index], b = frames[index + 1]
        let fraction = (phase - a.time) / (b.time - a.time)
        let t = eased ? bezier(fraction, x1: 0.42, y1: 0, x2: 0.58, y2: 1) : fraction
        return zip(a.values, b.values).map { pair in pair.0 + (pair.1 - pair.0) * t }
    }
    static func loop(_ elapsed: Double, duration: Double) -> Double {
        max(0, elapsed).truncatingRemainder(dividingBy: duration) / duration
    }
    static func orb(index: Int, elapsed: Double, reduced: Bool) -> (radii: [Double], drift: [Double]) {
        // With animation:none there is no base border-radius on .orb (rectangle).
        guard !reduced else { return (Array(repeating: 0, count: 8), [0,0]) }
        return (interpolate(morph[index], phase: loop(elapsed, duration: morphDurations[index]), eased: true),
                interpolate(drift[index], phase: loop(elapsed, duration: driftDurations[index]), eased: true))
    }
    static func decoration(right: Bool, elapsed: Double, reduced: Bool) -> (x: Double, y: Double, degrees: Double, opacity: Double) {
        let base = right ? 15.0 : -15.0
        if reduced { return (0,0,0,0.4) } // CSS animation:none also removes transform tilt.
        // Right's negative float delay starts the later transform/opacity animation
        // immediately; CSS animation-list precedence overrides its entrance.
        if !right && elapsed < 0.7 {
            let t = bezier(min(1, max(0, (elapsed - 0.1) / 0.6)), x1: 0, y1: 0, x2: 0.58, y2: 1)
            return (0,40 * (1-t),base,0.4*t)
        }
        let values = interpolate(orbit, phase: loop(right ? elapsed + 8 : elapsed - 0.7, duration: 16), eased: false)
        return (values[0],values[1],base + values[2],0.4)
    }
    static func bezier(_ x: Double, x1: Double, y1: Double, x2: Double, y2: Double) -> Double {
        if x <= 0 { return 0 }; if x >= 1 { return 1 }
        func point(_ t: Double, _ a: Double, _ b: Double) -> Double {
            3*(1-t)*(1-t)*t*a + 3*(1-t)*t*t*b + t*t*t
        }
        var low = 0.0, high = 1.0
        for _ in 0..<18 {
            let mid = (low+high)/2
            if point(mid,x1,x2) < x { low = mid } else { high = mid }
        }
        return point((low+high)/2,y1,y2)
    }
    // CSS border-radius overlap normalization, including different x/y radii.
    static func orbPath(in rect: CGRect, percentages: [Double]) -> Path {
        let w = rect.width, h = rect.height
        var rx = percentages.prefix(4).map { CGFloat($0)/100*w }
        var ry = percentages.suffix(4).map { CGFloat($0)/100*h }
        let limits = [rx[0]+rx[1], rx[3]+rx[2], ry[0]+ry[3], ry[1]+ry[2]]
        let dimensions = [w,w,h,h]
        var factor: CGFloat = 1
        for index in limits.indices where limits[index] > 0 { factor = min(factor, dimensions[index]/limits[index]) }
        rx = rx.map { $0*factor }; ry = ry.map { $0*factor }
        let x = rect.minX, y = rect.minY, right = rect.maxX, bottom = rect.maxY
        let k: CGFloat = 0.5522847498307936
        var p = Path(); p.move(to: CGPoint(x: x+rx[0],y:y))
        p.addLine(to: CGPoint(x:right-rx[1],y:y))
        p.addCurve(to: CGPoint(x:right,y:y+ry[1]), control1: CGPoint(x:right-rx[1]+k*rx[1],y:y), control2: CGPoint(x:right,y:y+ry[1]-k*ry[1]))
        p.addLine(to: CGPoint(x:right,y:bottom-ry[2]))
        p.addCurve(to: CGPoint(x:right-rx[2],y:bottom), control1: CGPoint(x:right,y:bottom-ry[2]+k*ry[2]), control2: CGPoint(x:right-rx[2]+k*rx[2],y:bottom))
        p.addLine(to: CGPoint(x:x+rx[3],y:bottom))
        p.addCurve(to: CGPoint(x:x,y:bottom-ry[3]), control1: CGPoint(x:x+rx[3]-k*rx[3],y:bottom), control2: CGPoint(x:x,y:bottom-ry[3]+k*ry[3]))
        p.addLine(to: CGPoint(x:x,y:y+ry[0]))
        p.addCurve(to: CGPoint(x:x+rx[0],y:y), control1: CGPoint(x:x,y:y+ry[0]-k*ry[0]), control2: CGPoint(x:x+rx[0]-k*rx[0],y:y))
        p.closeSubpath(); return p
    }
}

// One Canvas owns all decorative frames. Text, header measurement and action
// controls never enter TimelineView, preventing the earlier per-frame layout work.
private struct EmbedHeaderAnimatedDecorations: View {
    let appID: String
    let skillIcon: String
    let narrow: Bool
    @State private var startedAt = Date()
    @State private var visible = true
    @Environment(\.accessibilityReduceMotion) private var reduced
    @Environment(\.workspacePaneIsVisible) private var paneVisible
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        TimelineView(.animation(paused: !WorkspaceMotionPolicy.shouldAnimate(paneVisible: paneVisible, scrollVisible: visible, sceneActive: scenePhase == .active, reduced: reduced))) { timeline in
            let elapsed = timeline.date.timeIntervalSince(startedAt)
            Canvas { context, size in
                let palette = AppGradientPalette.colors(for: appID)
                let anchors = [CGPoint(x: 70,y: 50),
                               CGPoint(x: size.width-70,y: size.height-50),
                               CGPoint(x: size.width*0.8-110,y: 130)]
                for index in 0..<3 {
                    let frame = EmbedHeaderMotion.orb(index: index, elapsed: elapsed, reduced: reduced)
                    let center = CGPoint(x: anchors[index].x + CGFloat(frame.drift[0]), y: anchors[index].y + CGFloat(frame.drift[1]))
                    let rect = CGRect(x:center.x-110,y:center.y-110,width:220,height:220)
                    let color = index == 1 ? palette.start : palette.end
                    var orb = context
                    orb.opacity = 0.55
                    orb.addFilter(.blur(radius: 28))
                    orb.drawLayer { layer in
                        layer.clip(to: EmbedHeaderMotion.orbPath(in: rect, percentages: frame.radii))
                        layer.fill(Path(rect), with: .radialGradient(Gradient(stops: [
                            .init(color:color,location:0), .init(color:color,location:0.4),
                            .init(color:color.opacity(0),location:0.85)]), center:center,
                            startRadius:0,endRadius:110 * sqrt(2)))
                    }
                }
                let glyph: CGFloat = narrow ? 90 : 126
                let inset: CGFloat = narrow ? 250 : 346
                for right in [false,true] {
                    guard let symbol = context.resolveSymbol(id: "glyph") else { continue }
                    let frame = EmbedHeaderMotion.decoration(right:right, elapsed:elapsed, reduced:reduced)
                    let x = size.width/2 + (right ? inset-glyph/2 : -inset+glyph/2)
                    let y = size.height+15-glyph/2
                    var icon = context
                    icon.opacity = frame.opacity
                    icon.translateBy(x:x+CGFloat(frame.x),y:y+CGFloat(frame.y))
                    icon.rotate(by:.degrees(frame.degrees))
                    icon.draw(symbol,at:.zero)
                }
            } symbols: {
                Icon(skillIcon,size:narrow ? 90 : 126).foregroundStyle(.white).tag("glyph")
            }
        }
        .clipped().allowsHitTesting(false).accessibilityHidden(true)
        .onGeometryChange(for: Bool.self) { $0.frame(in: .named("embed-fullscreen-coordinate")).maxY > 0 } action: { visible = $0 }
    }
}
