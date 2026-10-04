// Fullscreen embed container with navigation between embeds in a group.
// Supports prev/next navigation arrows, child embed loading for composite types,
// and the full slide-up presentation matching the web app.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/EmbedHeader.svelte
//          frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte
//          frontend/packages/ui/src/components/embeds/web/WebsiteEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/file/FileEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/projects/ProjectsPage.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
//                specifications/features/app-skills/code-run/specification.yml
// Assertions: chats.surface.semantic-parity,
//             code-run.artifacts.parent-child-navigation
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.files.connected-embed-previews
// Web source: frontend/packages/ui/src/components/apps/AppsWorkspace.svelte
// Specification: specifications/features/apps-workspace/specification.yml
// Assertion: apps.presentation.shared-detail-and-recency

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// Connected file content is a bounded preview. Its original download belongs
/// to the source transport, rather than the code snippet export action.
struct EmbedOriginalFileActions {
    let warning: String?
    let downloadLabel: String
    let readyLabel: String
    let isDownloading: Bool
    let progressLabel: String?
    let progressValue: String?
    let downloadURL: URL?
    let errorMessage: String?
    let onDownload: () -> Void
}

struct EmbedFullscreenContainer: View {
    let embeds: [EmbedRecord]
    let initialEmbedId: String
    let allEmbedRecords: [String: EmbedRecord]
    let chatId: String?
    var hasPIIMappings = false
    var piiMappings: [PIIMapping] = []
    var isPIIRevealed = false
    var onTogglePII: () -> Void = {}
    var onOpenEmbed: (EmbedRecord, EmbedRecord) -> Void = { _, _ in }
    var onClose: () -> Void = {}
    var onOpenShareSettings: (EmbedShareSettingsTarget) -> Void = { _ in }
    var isSidePanel = false
    /// Web `EmbedHeader` switches at the browser viewport breakpoint, not at
    /// the width of a side-by-side embed pane. This remains separate from the
    /// pane width used to size the header frame.
    var responsiveViewportWidth: CGFloat? = nil
    var showChat = false
    var onShowChat: () -> Void = {}
    var onReportEmbedIssue: ((EmbedRecord) -> Void)? = nil
    var highlightQuoteText: String? = nil
    var originalFileActions: EmbedOriginalFileActions? = nil
    var headerPresentation: EmbedFullscreenHeaderPresentation? = nil
    var contentOverride: AnyView? = nil

    @State private var quoteAnchor: SourceQuoteHighlightAnchor?
    @State private var quoteContentSize: CGSize = .zero
    @State private var presentationReady = false

    private struct QuoteContentSizeKey: PreferenceKey {
        static let defaultValue: CGSize = .zero
        static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
            let next = nextValue()
            value = CGSize(width: max(value.width, next.width), height: max(value.height, next.height))
        }
    }

    private struct QuoteScrollIdentity: Hashable {
        let anchor: String?
        let targetY: CGFloat
        let viewportHeight: CGFloat
        let quote: String?
        let width: CGFloat
        let height: CGFloat
        let presented: Bool
    }
    @State private var selection = EmbedFullscreenSelection()
    @State private var isPresented = false
    @State private var codePreviewActive = false
    @State private var sheetDisplayedRows: [[String]]?
    @State private var lastSavedRunEventTimestamp: Double?
    @State private var isSavingRunOutput = false
    @State private var headerFrame: CGRect = .zero
    @State private var moreActionsOpen = false
    @State private var hostingViews: [String: HostingDomainView] = [:]
    @State private var selectedVersionNumber: Int?
    @State private var restoreConfirmVersion: Int?
    @StateObject private var codeRunViewModel = CodeRunViewModel()
    @StateObject private var imageDownloadController = ImageOriginalDownloadController()
    @StateObject private var nativeActionController = NativeEmbedActionController()
    @StateObject private var designIconExport = NativeDesignIconExportState()
    @ObservedObject private var actionAccountScope = OfflineStore.shared
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    @Environment(\.embedReportIssueAction) private var reportIssueAction
    @ObservedObject private var savedCodeRuns = CodeRunOutputStore.shared
    @ObservedObject private var ownerEmbedPII = OwnerEmbedPIIStore.shared
    @Environment(\.openURL) private var openURL
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    // Domain siblings follow the parent checked pool, including unknown checks.
    private var navigationEmbeds: [EmbedRecord] {
        guard let initial = embeds.first(where: { $0.id == initialEmbedId }),
              HostingEmbedKind.isDomain(initial), let parentID = initial.parentEmbedId,
              let parent = allEmbedRecords[parentID], HostingEmbedKind.isSearch(parent) else { return embeds }
        let children = HostingSearchModel(embed: parent, allEmbedRecords: allEmbedRecords).children
        return children.contains(where: { $0.id == initialEmbedId }) ? children : embeds
    }

    private var currentEmbed: EmbedRecord? {
        guard let id = selection.resolvedID(in: navigationEmbeds, initialID: initialEmbedId) else { return nil }
        return navigationEmbeds.first { $0.id == id }
    }

    /// Resolve owner-only originals for the selected embed, never for the embed
    /// that originally opened this container. An unloaded sibling stays masked.
    private var currentPIIMappings: [PIIMapping] {
        guard let chatId, let embedId = currentEmbed?.id else { return piiMappings }
        return PIIDetector.mergePIIMappings(
            piiMappings + ownerEmbedPII.mappings(chatId: chatId, embedId: embedId)
        )
    }

    private var currentIndex: Int {
        navigationEmbeds.firstIndex { $0.id == currentEmbed?.id } ?? 0
    }

    private func navigateFullscreen(by offset: Int) {
        var nextSelection = selection
        guard nextSelection.move(by: offset, in: navigationEmbeds, initialID: initialEmbedId) else { return }
        selection = nextSelection
        resetPerEmbedState()
    }

    private func resetPerEmbedState() {
        quoteAnchor = nil
        codePreviewActive = false
        sheetDisplayedRows = nil
        lastSavedRunEventTimestamp = nil
        isSavingRunOutput = false
        selectedVersionNumber = nil
        restoreConfirmVersion = nil
        codeRunViewModel.cleanup()
        imageDownloadController.cancel()
        nativeActionController.cancel()
        designIconExport.clear()
        NativeImagePreviewer.shared.dismissAndClear()
    }

    private var currentEmbedType: EmbedType? {
        guard let currentEmbed else { return nil }
        return EmbedType.normalized(rawValue: currentEmbed.type)
    }

    private func imageDownloadData(for embed: EmbedRecord) -> [String: AnyCodable]? {
        if EmbedType.normalized(rawValue: embed.type) == .image { return embed.rawData }
        if embed.type == "app:images:view" {
            return ImageViewSkillModel(embed: embed, allEmbedRecords: allEmbedRecords).resolvedData
        }
        return nil
    }

    private func showsHeaderShare(for embed: EmbedRecord) -> Bool {
        if originalFileActions != nil { return false }
        switch EmbedType.normalized(rawValue: embed.type) {
        case .recording, .pdf, .audioGenerate, .audioSpeak, .wiki:
            return false
        case .image:
            guard let files = imageDownloadData(for: embed)?["files"]?.value as? [String: Any] else { return false }
            return files["original"] != nil
        default:
            if embed.type == "app:images:view" {
                guard let files = imageDownloadData(for: embed)?["files"]?.value as? [String: Any] else { return false }
                return files["original"] != nil
            }
            return true
        }
    }

    private var isCodeEmbed: Bool {
        currentEmbedType == .codeCode
    }

    private var isSheetEmbed: Bool {
        currentEmbedType == .sheetsSheet
    }

    private var usesEdgeToEdgeContent: Bool {
        if currentEmbedType == .mailEmail || currentEmbed.map(HostingEmbedKind.isSearch) == true || currentEmbedType == .hostingDomain { return true }
        switch currentEmbedType {
        // These renderers own their responsive content gutters. Adding generic
        // fullscreen padding shifts the web grid and shrinks website snippets.
        case .webSearch, .imagesSearch, .newsSearch, .videosSearch, .codeRepoSearch, .electronicsSearch, .maps, .mapsPlace,
             .webWebsite, .eventsEvent, .travelConnection, .travelStay, .healthSearch, .healthAppointment, .fileFile, .sheetsSheet, .mathPlot, .wiki:
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
        .modifier(HostingFullscreenAccessibility(embed: currentEmbed))
        .onAppear {
            selection.reconcile(in: navigationEmbeds, initialID: initialEmbedId)
            presentFullscreen()
        }
        .task(id: currentEmbed?.id) {
            guard let chatId, !chatId.isEmpty,
                  let embed = currentEmbed else { return }
            #if DEBUG
            if chatId == "dev-embed-preview-chat" { return }
            #endif
            _ = await ownerEmbedPII.load(chatId: chatId, embedId: embed.id)
            if EmbedType.normalized(rawValue: embed.type) == .codeCode {
                await savedCodeRuns.hydrate(chatId: chatId, embedId: embed.id, embed: embed)
            }
        }
        .onChange(of: embeds.map(\.id)) { _, _ in
            let previousID = selection.selectedID
            selection.reconcile(in: navigationEmbeds, initialID: initialEmbedId)
            if selection.selectedID != previousID { resetPerEmbedState() }
        }
        .onChange(of: initialEmbedId) { _, _ in
            selection = EmbedFullscreenSelection()
            selection.reconcile(in: navigationEmbeds, initialID: initialEmbedId)
            resetPerEmbedState()
            // Child fullscreen routes reuse this container when Close returns
            // to their parent. The child has already animated this surface out,
            // so make the newly selected parent visible again. Without this the
            // full-screen view remains mounted offscreen and intercepts the chat.
            if !isPresented { presentFullscreen() }
        }
        .onChange(of: codeRunViewModel.status) { _, status in
            saveFinishedCodeRunIfNeeded(status: status)
        }
        .onChange(of: actionAccountScope.scopeGeneration) { _, _ in
            nativeActionController.cancel()
            imageDownloadController.cancel()
            designIconExport.clear()
        }
        .onDisappear {
            codeRunViewModel.cleanup()
            imageDownloadController.cancel()
            nativeActionController.cancel()
            NativeImagePreviewer.shared.dismissAndClear()
        }
    }

    private func fullscreenContent(safeAreaInsets: EdgeInsets) -> some View {
        GeometryReader { proxy in
            ZStack(alignment: .top) {
                if let embed = currentEmbed {
                    if isSheetEmbed {
                        // The table owns vertical scrolling and cell reuse. A
                        // parent ScrollView proposes an unbounded height and
                        // otherwise mounts the complete sheet on the main actor.
                        VStack(spacing: 0) {
                            fullscreenHeader(for: embed, viewportWidth: proxy.size.width, topInset: safeAreaInsets.top)
                            GeometryReader { contentViewport in
                                fullscreenEmbedContent(for: embed)
                                    .environment(\.embedSheetViewportHeight,
                                                 max(1, contentViewport.size.height - safeAreaInsets.bottom))
                                    .padding(.bottom, safeAreaInsets.bottom)
                            }
                            if shouldShowVersionTimeline(for: embed) {
                                ScrollView { versionTimeline(for: embed) }
                                    .frame(maxHeight: 140)
                            }
                            if !embed.isAppSkillUse && !childEmbeds.isEmpty {
                                ScrollView { childEmbedSection }
                                    .frame(maxHeight: 140)
                            }
                        }
                        .background(Color.grey20)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("embed-fullscreen-scroll")
                    } else {
                    ScrollViewReader { scroll in
                    ScrollView {
                        VStack(spacing: 0) {
                            fullscreenHeader(for: embed, viewportWidth: proxy.size.width, topInset: safeAreaInsets.top)
                            originalFileStatus
                            fullscreenEmbedContent(for: embed)
                                .environment(\.mapsMapViewportHeight, max(150,
                                    proxy.size.height - EmbedFullscreenHeaderLayout.height(
                                        viewportWidth: proxy.size.width,
                                        fallbackCompact: false,
                                        topContentInset: safeAreaInsets.top) - safeAreaInsets.bottom))
                                // The web plot uses 100vh. Header safe-area padding
                                // must not reduce the graph's own viewport calculation.
                                .environment(\.mathPlotViewportHeight, max(0, proxy.size.height))
                            if shouldShowVersionTimeline(for: embed) {
                                versionTimeline(for: embed)
                            }

                            if !embed.isAppSkillUse && !HostingEmbedKind.isSearch(embed) && currentEmbedType != .webSearch && !childEmbeds.isEmpty {
                                childEmbedSection
                            }
                        }
                        .id("embed-fullscreen-quote-content")
                        .coordinateSpace(name: "embed-fullscreen-source-content")
                        .background {
                            GeometryReader { contentGeometry in
                                Color.clear.preference(key: QuoteContentSizeKey.self, value: contentGeometry.size)
                            }
                        }
                    }
                    .background(Color.grey20)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("embed-fullscreen-scroll")
                    .onPreferenceChange(SourceQuoteHighlightAnchorKey.self) { anchors in
                        quoteAnchor = anchors.first
                    }
                    .onPreferenceChange(QuoteContentSizeKey.self) { size in
                        quoteContentSize = size
                    }
                    .task(id: QuoteScrollIdentity(anchor: quoteAnchor?.id, targetY: quoteAnchor?.frame.midY ?? 0,
                                                  viewportHeight: proxy.size.height, quote: highlightQuoteText,
                                                  width: quoteContentSize.width, height: quoteContentSize.height,
                                                  presented: presentationReady)) {
                        guard presentationReady, let quoteAnchor, quoteContentSize.height > 0 else { return }
                        // Measure the source in content coordinates and address
                        // the single direct scroll child, not nested card IDs.
                        await Task.yield()
                        guard !Task.isCancelled else { return }
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.28)) {
                            let fraction = SourceQuoteScrollPosition.unitAnchorY(
                                sourceMidY: quoteAnchor.frame.midY, contentHeight: quoteContentSize.height,
                                viewportHeight: proxy.size.height)
                            scroll.scrollTo("embed-fullscreen-quote-content", anchor: UnitPoint(x: 0.5, y: fraction))
                        }
                    }
                    }

                    }

                    if moreActionsOpen {
                        Color.clear.contentShape(Rectangle()).onTapGesture {
                            traceFullscreenHeaderAction("dismiss-outside")
                            moreActionsOpen = false
                        }
                            .accessibilityHidden(true)
                    }
                    EmbedFullscreenTopBar(
                        embed: embed,
                        showCopy: HostingEmbedKind.isDomain(embed) || currentEmbedType == .mailEmail || (currentEmbedType == .designIconResult && designIconExport.svg != nil) || NativeEmbedDownload.hasCopySource(embed) || isCodeEmbed || isSheetEmbed || currentEmbedType == .videosVideo || currentEmbedType == .travelConnection
                            || ((currentEmbedType == .maps || currentEmbedType == .mapsPlace)
                                && MapsEmbedModel(embed.rawData).osmURL != nil),
                        showShare: showsHeaderShare(for: embed),
                        showDownload: originalFileActions != nil || isCodeEmbed || isSheetEmbed || currentEmbedType == .mindmapsMindmap
                            || (currentEmbedType == .designIconResult && designIconExport.svg != nil)
                            || NativeEmbedDownload.hasSource(embed)
                            || ImageOriginalDownloadController.canDownload(data: imageDownloadData(for: embed)),
                        showRun: isCodeRunnable,
                        runActive: codeRunViewModel.isActive,
                        showPreview: isCodePreviewable,
                        previewActive: codePreviewActive,
                        showCalendar: calendarFile(for: embed) != nil,
                        viewportWidth: responsiveViewportWidth ?? proxy.size.width,
                        headerFrame: headerFrame,
                        moreOpen: $moreActionsOpen,
                        onClose: closeWithAnimation,
                        onShare: { shareEmbed(embed) },
                        onCopy: { copyEmbedContent(embed) },
                        onDownload: {
                            if currentEmbedType == .designIconResult, let source = designIconExport.svg.flatMap({ StaticSVGImageSource(data: $0) }) {
                                let size = designIconExport.size
                                let name = NativeDesignIconActions.filename(data: embed.rawData, extension: "png")
                                let recipient = recipientMediaContext
                                nativeActionController.download(load: {
                                    .init(filename: name, bytes: try await NativeDesignIconActions.png(source, size: size), mimeType: "image/png")
                                }, validate: { try recipient?.checkCurrent() })
                            } else if let originalFileActions {
                                originalFileActions.onDownload()
                            } else if currentEmbedType == .mindmapsMindmap {
                                downloadMindMapFile(embed)
                            } else if isCodeEmbed || isSheetEmbed {
                                downloadCodeFile(embed)
                            } else if let imageData = imageDownloadData(for: embed), recipientMediaContext == nil {
                                imageDownloadController.download(data: imageData)
                            } else {
                                downloadOriginalFile(embed)
                            }
                        },
                        onRun: { runCode(embed) },
                        onTogglePreview: { codePreviewActive.toggle() },
                        onCalendar: { downloadCalendarFile(embed) },
                        onReportIssue: { reportIssue(embed) },
                        showReport: onReportEmbedIssue != nil || reportIssueAction != nil,
                        showChat: showChat, onShowChat: onShowChat,
                        downloadLabel: originalFileActions?.downloadLabel ?? AppStrings.download,
                        downloadDisabled: originalFileActions?.isDownloading ?? (nativeActionController.isDownloading || imageDownloadController.isDownloading),
                        downloadIdentifier: originalFileActions == nil ? "embed-download-button" : "project-remote-download",
                        hostingActions: hostingHeaderActions(for: embed)
                    )
                    .padding(.top, safeAreaInsets.top)
                    .padding(.leading, safeAreaInsets.leading)
                    .padding(.trailing, safeAreaInsets.trailing)
                }


            }
            .offset(y: isSidePanel || isPresented ? 0 : proxy.size.height)
        }
        .ignoresSafeArea()
        .overlay(alignment: .topLeading) {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-embed-presentation") {
                // A transparent Shape can be omitted from the accessibility
                // tree in the Projects overlay. Retain a text element whose
                // label reflects the real animation-completion callback.
                Text(" ").font(.omTiny).foregroundStyle(Color.clear)
                    .frame(width: 1, height: 1)
                    .accessibilityElement(children: .ignore)
                    .accessibilityHidden(false)
                    .accessibilityLabel(presentationReady ? "ready" : "presenting")
                    .accessibilityIdentifier("embed-presentation-state")
                    .allowsHitTesting(false)
            }
            #endif
        }
    }

    private func fullscreenHeader(for embed: EmbedRecord, viewportWidth: CGFloat, topInset: CGFloat) -> some View {
        EmbedFullscreenHeader(
            embed: embed,
            hasPreviousEmbed: currentIndex > 0,
            hasNextEmbed: currentIndex < navigationEmbeds.count - 1,
            onNavigatePrevious: { withAnimation { navigateFullscreen(by: -1) } },
            onNavigateNext: { withAnimation { navigateFullscreen(by: 1) } },
            headerCTA: headerCTA(for: embed),
            secondaryHeaderCTA: memoryHeaderCTA(for: embed),
            topContentInset: topInset,
            viewportWidth: viewportWidth,
            responsiveViewportWidth: responsiveViewportWidth,
            presentation: headerPresentation,
            contentUnderlapsCTA: healthMapHeaderUnderlap(for: embed) > 0,
            mailPIIMappings: currentPIIMappings,
            mailPIIRevealed: isPIIRevealed
        )
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("embed-fullscreen-coordinate")) } action: { headerFrame = $0 }
        .zIndex(2)
    }

    private var hostingViewBinding: Binding<HostingDomainView> {
        let parentID = currentEmbed.flatMap { HostingEmbedKind.isDomain($0) ? $0.parentEmbedId : $0.id } ?? initialEmbedId
        return Binding(get: { hostingViews[parentID] ?? .selected }, set: { hostingViews[parentID] = $0 })
    }

    private func hostingHeaderActions(for embed: EmbedRecord) -> [HostingHeaderAction] {
        guard HostingEmbedKind.isSearch(embed) else { return [] }
        let model = HostingSearchModel(embed: embed, allEmbedRecords: allEmbedRecords)
        let views = HostingDomainView.allCases.filter { $0 != .unknown || model.unknownCount > 0 }
        return views.map { view in
            let label: String
            switch view {
            case .selected: label = AppStrings.hosting(.selectedCount, ["count": String(model.resultCount)])
            case .available: label = AppStrings.hosting(.showAvailable)
            case .all: label = AppStrings.hosting(.showAll)
            case .inUse: label = AppStrings.hosting(.showInUse)
            case .unknown: label = AppStrings.hosting(.showUnknown)
            }
            return HostingHeaderAction(view: view, label: label, active: hostingViewBinding.wrappedValue == view) { hostingViewBinding.wrappedValue = view }
        }
    }

    private func memoryHeaderCTA(for embed: EmbedRecord) -> AnyView? {
        guard let config = NativeEmbedMemoryConfig.config(for: embed) else { return nil }
        return AnyView(NativeEmbedMemoryButton(config: config).id(embed.id))
    }

    private func fullscreenEmbedContent(for embed: EmbedRecord) -> some View {
        Group {
            if let contentOverride {
                contentOverride
            } else {
                EmbedContentView(
            embed: embed,
            mode: .fullscreen,
            allEmbedRecords: allEmbedRecords,
            codePreviewActive: codePreviewActive,
            codeRunViewModel: codeRunViewModel,
            chatId: chatId,
            hasPIIMappings: !currentPIIMappings.isEmpty || hasPIIMappings,
            piiMappings: currentPIIMappings,
            isPIIRevealed: isPIIRevealed,
            onTogglePII: onTogglePII,
            onOpenEmbed: { child in
                onOpenEmbed(child, embed)
            },
            onSheetDisplayedRowsChange: { sheetDisplayedRows = $0 }
                )
            }
        }
            .environment(\.embedSourceQuoteText, embed.id == initialEmbedId ? highlightQuoteText : nil)
            .environment(\.nativeDesignIconExportState, designIconExport)
            .environment(\.hostingDomainView, hostingViewBinding)
            .padding(.horizontal, usesEdgeToEdgeContent ? 0 : .spacing8)
            .padding(.vertical, usesEdgeToEdgeContent ? 0 : .spacing10)
            .padding(.top, -healthMapHeaderUnderlap(for: embed))
            .zIndex(0)
    }


    private func presentFullscreen() {
        presentationReady = false
        withAnimation(isSidePanel || reduceMotion ? nil : .easeOut(duration: 0.28), completionCriteria: .removed) {
            isPresented = true
        } completion: {
            presentationReady = isPresented
        }
    }

    private func headerCTA(for embed: EmbedRecord) -> EmbedHeaderCTA? {
        if HostingEmbedKind.isDomain(embed), let url = HostingDomainModel(embed).providerURL {
            return EmbedHeaderCTA(title: AppStrings.hosting(.openOnGandi), accessibilityIdentifier: "hosting-open-gandi") {
                openExternalURL(url.absoluteString)
            }
        }
        if EmbedType.normalized(rawValue: embed.type) == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: currentPIIMappings, revealed: isPIIRevealed)
            guard let url = mail.mailtoURL else { return nil }
            return EmbedHeaderCTA(title: AppStrings.localized("embeds.mail.open_mail_client"), accessibilityIdentifier: "mail-open-client", usesMailResponsiveSizing: true) { openURL(url) }
        }
        if EmbedType.normalized(rawValue: embed.type) == .healthAppointment {
            let model = HealthAppointmentModel(embed.rawData ?? [:])
            if let url = model.bookingURL {
                return EmbedHeaderCTA(title: AppStrings.openOnProvider(model.provider), accessibilityIdentifier: "external-provider-cta") { openExternalURL(url.absoluteString) }
            }
        }
        if EmbedType(rawValue: embed.type) == .codeCode,
           let payload = embed.codePayload,
           let chatId,
           !chatId.isEmpty,
           !codeRunViewModel.isPanelOpen {
            let hasSavedOutput = savedCodeRuns.output(chatId: chatId, embedId: embed.id) != nil
            guard isCodeRunnable || hasSavedOutput else { return nil }
            return EmbedHeaderCTA(
                title: hasSavedOutput && codeRunViewModel.status == .idle
                    ? AppStrings.codeRunShowOutput : codeRunViewModel.ctaTitle,
                accessibilityIdentifier: "embed-run-button"
            ) {
                runCode(embed, payload: payload)
            }
        }

        guard let type = EmbedType.normalized(rawValue: embed.type),
              let data = rawData(for: embed) else {
            return nil
        }

        switch type {
        case .wiki:
            guard let url = WikiArticleIdentity(data: data, fallbackLanguage: LocalizationManager.shared.currentLanguage.code).pageURL else { return nil }
            return EmbedHeaderCTA(title: AppStrings.localized("embeds.wiki.open_on_wikipedia"),
                                  accessibilityIdentifier: "wiki-open-wikipedia") { openExternalURL(url.absoluteString) }
        case .maps, .mapsPlace:
            guard let url = MapsEmbedModel(data).googleMapsURL(isPlace: type == .mapsPlace) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider("Google Maps"),
                                  accessibilityIdentifier: "maps-open-google-maps") { openExternalURL(url.absoluteString) }

        case .videosVideo:
            guard let url = firstString(["url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider("YouTube")) {
                openExternalURL(url)
            }

        case .codeGetDocs:
            guard let libraryID = CodeGetDocsEmbedRenderer.libraryID(from: data), !libraryID.isEmpty else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider("Context7")) {
                openExternalURL("https://context7.com\(libraryID)")
            }

        case .webWebsite:
            guard let url = firstString(["url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider(host(from: url))) {
                openExternalURL(url)
            }

        case .webRead:
            guard let url = firstString(["url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.openOnProvider(host(from: url))) {
                openExternalURL(url)
            }

        case .fitnessClass:
            guard let url = firstString(["detail_url"], in: data) else { return nil }
            return EmbedHeaderCTA(title: AppStrings.fitnessOpenProvider("Urban Sports"),
                                  accessibilityIdentifier: "fitness-open-urban-sports") {
                openExternalURL(url)
            }

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
            return EmbedHeaderCTA(title: AppStrings.openOnProvider("Google Hotels")) {
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
        guard let url = NativeEmbedActionURL.external(urlString) else { return }
        openURL(url)
    }

    private func closeWithAnimation() {
        presentationReady = false
        if isSidePanel { onClose(); return }
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
        guard let chatId, !chatId.isEmpty else {
            ToastManager.shared.show(AppStrings.error, type: .error)
            return
        }
        moreActionsOpen = false
        onOpenShareSettings(EmbedShareSettingsTarget(
            embed: embed, chatId: chatId, allEmbedRecords: allEmbedRecords
        ))
    }

    private func copyEmbedContent(_ embed: EmbedRecord) {
        do { try recipientMediaContext?.checkCurrent() } catch { return }
        if HostingEmbedKind.isDomain(embed) {
            let text = HostingDomainModel(embed).name
            copyToClipboard(EmbedPIIText.render(text, mappings: currentPIIMappings, revealed: isPIIRevealed))
            ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
            return
        }
        if currentEmbedType == .designIconResult, let bytes = designIconExport.svg, let text = String(data: bytes, encoding: .utf8) {
            copyToClipboard(text)
            ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
            return
        }
        if let text = NativeEmbedDownload.copyText(embed, renderText: {
            EmbedPIIText.render($0, mappings: currentPIIMappings, revealed: isPIIRevealed)
        }) {
            copyToClipboard(text)
            ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
            return
        }

        if EmbedType.normalized(rawValue: embed.type) == .travelConnection {
            let text = TravelConnectionActions(data: embed.rawData ?? [:]).copyText
            copyToClipboard(EmbedPIIText.render(text, mappings: currentPIIMappings, revealed: isPIIRevealed))
            ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
            return
        }
        if let type = EmbedType.normalized(rawValue: embed.type), type == .maps || type == .mapsPlace {
            guard let url = MapsEmbedModel(embed.rawData).osmURL else { return }
            copyToClipboard(url.absoluteString)
            ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
            return
        }
        if EmbedType.normalized(rawValue: embed.type) == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: currentPIIMappings, revealed: isPIIRevealed)
            copyToClipboard(mail.copyText)
            ToastManager.shared.show(AppStrings.localized("embeds.mail.copied"), type: .success)
            return
        }
        if EmbedType.normalized(rawValue: embed.type) == .videosVideo,
           let url = embed.rawData?["url"]?.value as? String {
            copyToClipboard(url)
            ToastManager.shared.show("Video URL copied to clipboard", type: .success)
            return
        }
        if let payload = embed.codePayload {
            copyToClipboard(EmbedPIIText.render(payload.code, mappings: currentPIIMappings, revealed: isPIIRevealed))
            ToastManager.shared.show("Code copied to clipboard", type: .success)
            return
        }
        if let table = sheetTable(for: embed), !table.tsv.isEmpty {
            copyToClipboard(table.tsv(rows: sheetDisplayedRows ?? table.rows))
            ToastManager.shared.show("Table copied to clipboard", type: .success)
            return
        }

    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }

    @ViewBuilder
    private var originalFileStatus: some View {
        if let actions = originalFileActions {
            VStack(alignment: .leading, spacing: .spacing4) {
                if let warning = actions.warning {
                    Text(warning).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("project-remote-preview-truncated")
                }
                if let progress = actions.progressLabel {
                    Text(progress).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .accessibilityValue(actions.progressValue ?? "")
                        .accessibilityIdentifier("project-remote-download-progress")
                }
                if actions.isDownloading { ProgressView() }
                if let error = actions.errorMessage {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityIdentifier("project-remote-download-error")
                }
                if let url = actions.downloadURL {
                    ShareLink(item: url) {
                        HStack(spacing: .spacing4) {
                            Icon("share", size: 18)
                            Text(actions.readyLabel).font(.omSmall)
                        }
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("project-remote-share-download")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
        }
    }

    private func downloadMindMapFile(_ embed: EmbedRecord) {
        let file = NativeMindMapDownloadFile.build(data: embed.rawData)
        nativeActionController.export(.init(filename: file.filename, bytes: Data(file.content.utf8), mimeType: "text/plain"))
    }

    private func downloadCodeFile(_ embed: EmbedRecord) {
        if let table = sheetTable(for: embed), currentEmbedType == .sheetsSheet {
            downloadSheet(table, from: embed); return
        }
        guard let payload = embed.codePayload else { return }
        let content = EmbedPIIText.render(payload.code, mappings: currentPIIMappings, revealed: isPIIRevealed)
        nativeActionController.export(.init(filename: payload.filename ?? defaultCodeFilename(language: payload.language),
            bytes: Data(content.utf8), mimeType: "text/plain"))
    }

    private func downloadOriginalFile(_ embed: EmbedRecord) {
        guard let source = NativeEmbedDownload.source(embed, records: allEmbedRecords, renderText: {
            EmbedPIIText.render($0, mappings: currentPIIMappings, revealed: isPIIRevealed)
        }) else { ToastManager.shared.show(AppStrings.error, type: .error); return }
        let recipient = recipientMediaContext
        let scope = recipient?.namespace ?? OfflineStore.shared.activeScopeId
        nativeActionController.download(load: { try await source.load(scope: scope, recipient: recipient) },
            validate: { try recipient?.checkCurrent() })
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

    private func calendarFile(for embed: EmbedRecord) -> EmbedCalendarFile? {
        if EmbedType.normalized(rawValue: embed.type) == .travelConnection {
            return TravelConnectionActions(data: embed.rawData ?? [:]).calendarFile(renderText: {
                EmbedPIIText.render($0, mappings: currentPIIMappings, revealed: isPIIRevealed)
            })
        }
        let render: (String) -> String = { EmbedPIIText.render($0, mappings: currentPIIMappings, revealed: isPIIRevealed) }
        if EmbedType.normalized(rawValue: embed.type) == .eventsEvent {
            return EventEmbedCalendarFile.make(embed.rawData ?? [:], renderText: render)
        }
        if EmbedType.normalized(rawValue: embed.type) == .fitnessClass {
            return FitnessEmbedCalendarFile.make(embed.rawData ?? [:], renderText: render)
        }
        guard EmbedType.normalized(rawValue: embed.type) == .healthAppointment else { return nil }
        return HealthAppointmentCalendarFile.make(embed.rawData ?? [:], renderText: {
            EmbedPIIText.render($0, mappings: currentPIIMappings, revealed: isPIIRevealed)
        })
    }

    private func healthMapHeaderUnderlap(for embed: EmbedRecord) -> CGFloat {
        if let type = EmbedType.normalized(rawValue: embed.type), type == .maps || type == .mapsPlace {
            let map = MapsEmbedModel(embed.rawData)
            return EmbedFullscreenHeaderLayout.healthMapUnderlap(
                hasHeaderCTA: headerCTA(for: embed) != nil,
                hasMap: map.hasCoordinates || map.mapImageURL != nil)
        }
        guard EmbedType.normalized(rawValue: embed.type) == .healthAppointment else { return 0 }
        // EntryWithMapTemplate starts the map at the panel edge while its absolute
        // CTA straddles that edge. Keep the header's full 44pt CTA hit bounds and
        // underlap only the map using the renderer's own map-availability decision.
        return EmbedFullscreenHeaderLayout.healthMapUnderlap(
            hasHeaderCTA: headerCTA(for: embed) != nil,
            hasMap: HealthAppointmentModel(embed.rawData ?? [:]).mapConfiguration != nil)
    }

    private func downloadCalendarFile(_ embed: EmbedRecord) {
        do { try recipientMediaContext?.checkCurrent() } catch { return }
        guard let file = calendarFile(for: embed) else { return }
        nativeActionController.calendar(file)
    }

    private func sheetTable(for embed: EmbedRecord) -> ParsedSheetTable? {
        guard EmbedType(rawValue: embed.type) == .sheetsSheet,
              let data = embed.data,
              case .raw(let dict) = data else { return nil }
        return ParsedSheetTable(data: dict).applyingPII(mappings: currentPIIMappings, revealed: isPIIRevealed)
    }

    private func downloadSheet(_ table: ParsedSheetTable, from embed: EmbedRecord) {
        let name = (table.title?.isEmpty == false ? table.title : "table") ?? "table"
        do {
            let bytes = try SheetXLSXExporter.makeData(table: table, rows: sheetDisplayedRows ?? table.rows)
            nativeActionController.export(.init(filename: name + ".xlsx", bytes: bytes,
                mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        } catch { ToastManager.shared.show(AppStrings.error, type: .error) }
    }

    private func reportIssue(_ embed: EmbedRecord) {
        if let onReportEmbedIssue { onReportEmbedIssue(embed) }
        else { reportIssueAction?.open(.init(title: "", category: "bug")) }
    }

    private var isCodeRunnable: Bool {
        guard originalFileActions == nil else { return false }
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
        if codeRunViewModel.status == .idle,
           savedCodeRuns.output(chatId: chatId, embedId: embed.id) != nil {
            codeRunViewModel.openSavedOutput()
            return
        }
        codeRunViewModel.toggleRun(
            chatId: chatId,
            embedId: embed.id,
            file: CodeRunClientFile(
                embedId: embed.id,
                code: EmbedPIIText.render(payload.code, mappings: currentPIIMappings, revealed: isPIIRevealed),
                language: payload.language,
                filename: payload.filename,
                isTarget: true
            )
        )
    }

    private func saveFinishedCodeRunIfNeeded(status: CodeRunExecutionStatus) {
        guard status.isTerminal, !isSavingRunOutput,
              let chatId, !chatId.isEmpty,
              let embed = currentEmbed, EmbedType.normalized(rawValue: embed.type) == .codeCode,
              let timestamp = codeRunViewModel.events.last?.timestamp,
              lastSavedRunEventTimestamp != timestamp else { return }
        let output = codeRunViewModel.programOutputText
        guard !output.isEmpty else { return }
        isSavingRunOutput = true
        Task {
            defer { isSavingRunOutput = false }
            do {
                try await CodeRunOutputStore.shared.saveCompletedRun(
                    chatId: chatId, embedId: embed.id, embed: embed, output: output,
                    status: status.rawValue, files: codeRunViewModel.files,
                    events: codeRunViewModel.events,
                    artifacts: codeRunViewModel.artifacts,
                    skippedArtifacts: codeRunViewModel.skippedArtifacts
                )
                lastSavedRunEventTimestamp = timestamp
            } catch {
                NativeDiagnostics.warning("Code run output save failed", category: "code-run")
            }
        }
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

private func traceFullscreenHeaderAction(_ event: String) {
    #if DEBUG
    if ProcessInfo.processInfo.arguments.contains("--ui-test-embed-presentation") {
        NativeDiagnostics.record(level: .info, category: "embed_header_action_fixture", message: event)
    }
    #endif
}

private struct EmbedFullscreenTopBar: View {
    let embed: EmbedRecord
    let showCopy: Bool
    let showShare: Bool
    let showDownload: Bool
    let showRun: Bool
    let runActive: Bool
    let showPreview: Bool
    let previewActive: Bool
    let showCalendar: Bool
    let viewportWidth: CGFloat
    let headerFrame: CGRect
    @Binding var moreOpen: Bool
    let onClose: () -> Void
    let onShare: () -> Void
    let onCopy: () -> Void
    let onDownload: () -> Void
    let onRun: () -> Void
    let onTogglePreview: () -> Void
    let onCalendar: () -> Void
    let onReportIssue: () -> Void
    var showReport = true
    var showChat = false
    var onShowChat: () -> Void = {}
    var downloadLabel = AppStrings.download
    var downloadDisabled = false
    var downloadIdentifier = "embed-download-button"
    var hostingActions: [HostingHeaderAction] = []
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
        if showDownload { values.append(.init(id: "download", icon: "download", label: downloadLabel, perform: onDownload)) }
        if showCalendar { values.append(.init(id: "calendar", icon: "calendar", label: "Add to calendar", perform: onCalendar)) }
        if showRun { values.append(.init(id: "run", icon: "play", label: AppStrings.codeRun, active: runActive, perform: onRun)) }
        if showPreview { values.append(.init(id: "preview", icon: "preview", label: AppStrings.preview, active: previewActive, perform: onTogglePreview)) }
        values += hostingActions.map { .init(id: $0.id, icon: "search", label: $0.label, active: $0.active, perform: $0.perform) }
        return values
    }
    private var usesMore: Bool { EmbedHeaderActionPolicy.usesMore(width: viewportWidth, actionCount: actions.count, hasShare: showShare) }
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if showReport {
                pill(.init(id: "report", icon: "bug", label: LocalizationManager.shared.text("header.report_issue"), perform: onReportIssue), label: EmbedHeaderActionPolicy.reportShowsLabel(width: viewportWidth))
            }
            if viewportWidth >= 460 && showShare { pill(share) }
            if showChat {
                pill(.init(id: "show-chat", icon: "chat", label: LocalizationManager.shared.text("chat.show_chat"), perform: onShowChat), label: true)
            }

            if usesMore {
                pill(.init(id: "more", icon: "more", label: LocalizationManager.shared.text("common.more_actions"), perform: {
                    moreOpen.toggle()
                    traceFullscreenHeaderAction("more-\(moreOpen ? "expanded" : "collapsed")")
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
                                    focusedActionID = viewportWidth < 460 && showShare ? "share" : actions.first?.id
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
                if viewportWidth < 460 && showShare { pill(share) }
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
        .onChange(of: embed.id) { _, _ in
            traceFullscreenHeaderAction("dismiss-embed-change")
            moreOpen = false; focusFirstMenuAction = false
        }
        .onChange(of: moreOpen) { _, open in if !open { focusFirstMenuAction = false } }
        .onKeyPress(.downArrow) {
            guard focusedActionID == "more", usesMore else { return .ignored }
            if moreOpen {
                focusedActionID = viewportWidth < 460 && showShare ? "share" : actions.first?.id
            } else {
                focusFirstMenuAction = true; moreOpen = true
            }
            return .handled
        }
        .onChange(of: usesMore) { _, value in
            if !value { traceFullscreenHeaderAction("dismiss-action-policy"); moreOpen = false }
        }
        .onKeyPress(.escape) {
            guard moreOpen else { return .ignored }; moreOpen = false; focusedActionID = "more"; return .handled
        }
    }
    private var menuWidth: CGFloat { EmbedHeaderActionPolicy.menuWidth(toolbar: toolbarFrame, anchor: moreFrame) }
    private var menuActions: some View {
        VStack(alignment: .leading, spacing: 8) {
            if viewportWidth < 460 && showShare { pill(share, label: true, inMenu: true) }
            ForEach(actions) { pill($0, label: true, inMenu: true) }
        }
    }
    private func pill(_ action: Action, label: Bool = false, inMenu: Bool = false) -> some View {
        EmbedHeaderActionPill(icon: action.icon, label: action.label, showsLabel: label,
                              headerFrame: inMenu ? .zero : headerFrame, active: action.active, inMenu: inMenu) {
            traceFullscreenHeaderAction("action-\(action.id)")
            if action.id != "more" { moreOpen = false }
            action.perform()
        }.focused($focusedActionID, equals: action.id)
            .disabled(action.id == "download" && downloadDisabled)
            .accessibilityIdentifier(action.id.hasPrefix("hosting-view-") ? action.id : action.id == "download" ? downloadIdentifier : "embed-\(action.id)-button")
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
        }.buttonStyle(EmbedHeaderPillInteractionStyle(anchor: inMenu ? .leading : .center, traceIcon: icon))
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
    let traceIcon: String
    @State private var hovered = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.95 : hovered ? 1.08 : 1, anchor: anchor)
            .shadow(color: .black.opacity(0.15), radius: configuration.isPressed ? 2 : hovered ? 12 : 8, x: 0, y: 2)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: configuration.isPressed)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: hovered)
            .onHover { hovered = $0 }
            #if DEBUG
            .onChange(of: configuration.isPressed) { _, pressed in
                traceFullscreenHeaderAction("press-\(traceIcon)-\(pressed)")
            }
            #endif
    }
}

// MARK: - Fullscreen header

struct EmbedHeaderCTA {
    let title: String
    var accessibilityIdentifier: String?
    let action: () -> Void
    var usesMailResponsiveSizing = false

    init(title: String, accessibilityIdentifier: String? = nil, usesMailResponsiveSizing: Bool = false, action: @escaping () -> Void) {
        self.title = title
        self.accessibilityIdentifier = accessibilityIdentifier
        self.usesMailResponsiveSizing = usesMailResponsiveSizing
        self.action = action
    }
}

enum EmbedFullscreenHeaderLayout {
    static func healthMapUnderlap(hasHeaderCTA: Bool, hasMap: Bool) -> CGFloat {
        hasHeaderCTA && hasMap ? 22 : 0
    }

    static func isNarrow(viewportWidth: CGFloat?, fallbackCompact: Bool) -> Bool {
        viewportWidth.map { $0 <= 730 } ?? fallbackCompact
    }

    static func height(viewportWidth: CGFloat?, fallbackCompact: Bool, topContentInset: CGFloat) -> CGFloat {
        (isNarrow(viewportWidth: viewportWidth, fallbackCompact: fallbackCompact) ? 190 : 240) + topContentInset
    }
}

/// Apps supplies catalog presentation; ordinary embeds retain their renderer-owned identity.
struct EmbedFullscreenHeaderPresentation: Equatable {
    let title: String
    let subtitle: String?
    let icon: String
    var eyebrow: String? = nil
    var providers: String? = nil
    var footer: String? = nil
}

struct EmbedFullscreenHeader: View {
    let embed: EmbedRecord
    var hasPreviousEmbed = false
    var hasNextEmbed = false
    var onNavigatePrevious: () -> Void = {}
    var onNavigateNext: () -> Void = {}
    var headerCTA: EmbedHeaderCTA?
    var secondaryHeaderCTA: AnyView? = nil
    var topContentInset: CGFloat = 0
    var viewportWidth: CGFloat? = nil
    var responsiveViewportWidth: CGFloat? = nil
    var presentation: EmbedFullscreenHeaderPresentation? = nil

    /// Map templates can flow behind the CTA without shrinking its hit-test bounds.
    var contentUnderlapsCTA = false
    var mailPIIMappings: [PIIMapping] = []
    var mailPIIRevealed = false

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var measuredCTAHeight: CGFloat = 44

    // Match the web's width breakpoint, including narrow macOS windows and
    // iPad split views whose platform size class may remain regular.
    private var isNarrow: Bool {
        EmbedFullscreenHeaderLayout.isNarrow(
            viewportWidth: responsiveViewportWidth ?? viewportWidth,
            fallbackCompact: horizontalSizeClass == .compact
        )
    }
    private var embedType: EmbedType? { EmbedType.normalized(rawValue: embed.type) }
    private var appId: String {
        if embedType == .fileFile { return "files" }
        return embed.appId ?? embedType?.appId ?? "web"
    }
    private var headerHeight: CGFloat {
        EmbedFullscreenHeaderLayout.height(
            viewportWidth: responsiveViewportWidth ?? viewportWidth,
            fallbackCompact: horizontalSizeClass == .compact,
            topContentInset: topContentInset
        )
    }
    private var headerFrameHeight: CGFloat {
        // The CTA begins 22pt above the panel edge and extends 22pt below it.
        // Keep its full button inside the header's hit-test layout bounds.
        hasHeaderCTA ? headerHeight + max(44, measuredCTAHeight) - 22 : headerHeight
    }
    private var hasHeaderCTA: Bool { headerCTA != nil || secondaryHeaderCTA != nil }
    private var ctaOffsetY: CGFloat {
        headerHeight - 22
    }
    var skillIconName: String {
        if let presentation { return presentation.icon }
        return EmbedVisualSkillIcon.name(for: embed, fullscreen: true)
    }

    var body: some View {
        ZStack(alignment: .top) {
            headerPanel
                .frame(height: headerHeight)
                .clipShape(.rect(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
                .shadow(color: .black.opacity(0.22), radius: 18, x: 0, y: 10)

            if hasHeaderCTA {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: .spacing4) { headerCTAControls }
                    VStack(spacing: .spacing4) { headerCTAControls }
                }
                    .frame(maxWidth: max(0, (viewportWidth ?? 600) - 32))
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { measuredCTAHeight = $0 }
                    .offset(y: ctaOffsetY)
            }
        }
        .frame(width: viewportWidth, height: headerFrameHeight,
               alignment: .top) // CTA reserves space below; never center the banner into that reserve.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embed-fullscreen-header")
        .accessibilityValue(embed.id)
    }

    @ViewBuilder
    private var headerCTAControls: some View {
        if let headerCTA { headerCTAButton(headerCTA) }
        if let secondaryHeaderCTA { secondaryHeaderCTA }
    }

    private var headerPanel: some View {
        ZStack {
            AppGradientBackground(appId: appId)
                .overlay { headerDecorations }
                .accessibilityHidden(true)

            VStack(spacing: .spacing2) {
                if let eyebrow = presentation?.eyebrow, !eyebrow.isEmpty {
                    Text(eyebrow).font(.omSmall).foregroundStyle(Color.fontButton.opacity(0.85))
                }
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
                        .accessibilityIdentifier("embed-header-subtitle")
                        .font(isNarrow ? .omXs : .omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(.white.opacity(0.85))
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                }
                if let providers = presentation?.providers, !providers.isEmpty {
                    Text(providers).font(.omXs).foregroundStyle(Color.fontButton.opacity(0.85)).lineLimit(1)
                }
                if let footer = presentation?.footer, !footer.isEmpty {
                    Text(footer).font(.omXs).foregroundStyle(Color.fontButton.opacity(0.85)).lineLimit(1)
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
        let mailNarrow = cta.usesMailResponsiveSizing && (responsiveViewportWidth ?? viewportWidth ?? 0) <= 600
        return Button(action: cta.action) {
            Text(cta.title)
                // The deployed Mail CTA names an unavailable web font family;
                // CDP confirms its rendered fallback is Helvetica regular 16px.
                .font(cta.usesMailResponsiveSizing ? .custom("Helvetica", size: 16) : .omP)
                .fontWeight(cta.usesMailResponsiveSizing ? .regular : .medium)
                .foregroundStyle(Color.fontButton)
                .lineLimit(1)
                .minimumScaleFactor(0.78)
                .padding(.horizontal, mailNarrow ? .spacing10 : .spacing12)
                .padding(.vertical, mailNarrow ? .spacing5 : .spacing6)
                .frame(minWidth: cta.usesMailResponsiveSizing ? (mailNarrow ? 160 : 200) : (isNarrow ? 160 : 200),
                       minHeight: cta.usesMailResponsiveSizing ? (mailNarrow ? 41 : 45) : nil,
                       maxHeight: cta.usesMailResponsiveSizing ? (mailNarrow ? 41 : 45) : nil)
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

    private func truncatedFilename(_ filename: String, maxLength: Int) -> String {
        guard filename.count > maxLength else { return filename }
        guard let dot = filename.lastIndex(of: ".") else {
            return String(filename.prefix(maxLength - 1)) + "…"
        }
        let suffix = String(filename[dot...])
        let stem = String(filename[..<dot])
        let allowedStem = maxLength - suffix.count - 1
        return allowedStem > 0
            ? String(stem.prefix(allowedStem)) + "…" + suffix
            : String(filename.prefix(maxLength - 1)) + "…"
    }

    var headerTitle: String {
        if let presentation { return presentation.title }
        if HostingEmbedKind.isDomain(embed) { return HostingDomainModel(embed).name }
        if HostingEmbedKind.isSearch(embed) {
            let query = embed.rawData?["query"]?.value as? String ?? ""
            return query.isEmpty ? AppStrings.hosting(.title) : query
        }
        if embedType == .wiki {
            return WikiArticleIdentity(data: embed.rawData ?? [:], fallbackLanguage: LocalizationManager.shared.currentLanguage.code).title
        }
        if embedType == .maps { return AppStrings.domainLocation }
        if embedType == .mapsPlace { return MapsEmbedModel(embed.rawData).name ?? AppStrings.domainLocation }
        if embedType == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: mailPIIMappings, revealed: mailPIIRevealed)
            return mail.subject.isEmpty ? AppStrings.localized("embeds.mail.email") : mail.subject
        }
        if embedType == .fileFile { return FileEmbedPayload(embed.rawData).filename }
        if embedType == .healthAppointment { return HealthAppointmentModel(embed.rawData ?? [:]).title }
        if embedType == .healthSearch || (embed.appId == "health" && embed.skillId == "search_appointments") {
            return AppStrings.domainHealthSearchAppointments
        }
        if embedType == .audioGenerate || embedType == .audioSpeak { return "Generate SFX" }
        if embedType == .image {
            return truncatedFilename(embed.rawData?["filename"]?.value as? String ?? "Image", maxLength: 30)
        }
        if embedType == .recording {
            let raw = embed.rawData ?? [:]
            return truncatedFilename((raw["title"]?.value as? String)
                ?? (raw["filename"]?.value as? String) ?? "Voice Note", maxLength: 40)
        }
        if embedType == .imagesGenerate || embedType == .imagesGenerateDraft {
            return embed.rawData?["prompt"]?.value as? String ?? "Generate"
        }
        if embedType == .videosTranscript { return "YouTube Video" }
        if embedType == .videosCreate {
            return embed.rawData?["filename"]?.value as? String ?? "ProductLaunch.tsx"
        }
        if embedType == .focusModeActivation { return AppStrings.focusModeActivated }
        if embedType == .designIconResult {
            return (embed.rawData?["display_name"]?.value as? String)
                ?? (embed.rawData?["name"]?.value as? String)
                ?? "Icon"
        }
        if embedType == .codeGetDocs {
            return CodeGetDocsEmbedRenderer.libraryID(from: embed.rawData)
                ?? LocalizationManager.shared.text("embeds.get_docs")
        }
        if embedType == .pdf {
            return embed.rawData?["filename"]?.value as? String ?? "PDF"
        }
        if embedType == .musicGenerate {
            let prompt = embed.rawData?["prompt"]?.value as? String ?? ""
            return prompt.isEmpty ? LocalizationManager.shared.text("app_skills.music.generate") : String(prompt.prefix(80))
        }
        if embedType == .electronicsPcbSchematic {
            return embed.rawData?["filename"]?.value as? String ?? "board.ato"
        }
        if embedType == .financeCheckAccounts { return LocalizationManager.shared.text("app_skills.finance.check_accounts") }
        if embedType == .weatherForecast { return LocalizationManager.shared.text("apps.weather.forecast") }
        if embedType == .travelFlight { return embed.rawData?["flight_number"]?.value as? String ?? "Flight Track" }
        if embedType == .reminderSet || embedType == .reminderList || embedType == .reminderCancel {
            return LocalizationManager.shared.text("apps.reminder.skills.set_reminder")
        }
        if embedType == .mathCalculate {
            return embed.rawData?["title"]?.value as? String ?? "Calculation"
        }
        if embedType == .codeNotebook {
            return embed.rawData?["filename"]?.value as? String ?? "notebook.ipynb"
        }
        if let payload = embed.codePayload {
            return payload.filename ?? (payload.language.isEmpty
                ? LocalizationManager.shared.text("embeds.code_snippet") : payload.languageDisplayName)
        }
        if let table = sheetTable {
            return table.title ?? LocalizationManager.shared.text("embeds.table")
        }
        if embedType == .travelStay {
            return AppStrings.localized("app_skills.travel.search_stays")
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

    var headerSubtitle: String? {
        if HostingEmbedKind.isDomain(embed) { return HostingDomainModel(embed).subtitle }
        if HostingEmbedKind.isSearch(embed) {
            let model = HostingSearchModel(embed: embed, allEmbedRecords: [:])
            return AppStrings.hosting(.providerVia, ["provider": model.provider]) + " · " + model.currency
                + (model.country.isEmpty ? "" : " · " + model.country)
        }
        if embedType == .wiki { return embed.rawData?["description"]?.value as? String }
        if let presentation { return presentation.subtitle }
        if embedType == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: mailPIIMappings, revealed: mailPIIRevealed)
            return mail.receiver.isEmpty ? nil : "\(AppStrings.localized("embeds.mail.to")): \(mail.receiver)"
        }
        if embedType == .fileFile { return FileEmbedPayload(embed.rawData).metadata }
        if embedType == .healthAppointment { return HealthAppointmentModel(embed.rawData ?? [:]).subtitle }
        if embedType == .healthSearch || (embed.appId == "health" && embed.skillId == "search_appointments") {
            return HealthAppointmentModel.searchSummary(embed.rawData ?? [:])
        }
        if embedType == .audioGenerate || embedType == .audioSpeak { return "ElevenLabs" }
        if embedType == .image {
            let raw = embed.rawData ?? [:]
            let mime = (raw["file_type"]?.value as? String)
                ?? (raw["fileType"]?.value as? String)
            let filename = raw["filename"]?.value as? String ?? ""
            let type = mime?.split(separator: "/").last.map(String.init)
                ?? filename.split(separator: ".").last.map(String.init)
            let typeLabel = type?.uppercased().replacingOccurrences(of: "SVG+XML", with: "SVG")
            let bytes = (raw["file_size"]?.value as? Int) ?? (raw["fileSize"]?.value as? Int)
            let sizeLabel: String? = bytes.map { count in
                if count < 1024 { return "\(count) B" }
                if count < 1_048_576 { return String(format: "%.1f KB", Double(count) / 1024) }
                return String(format: "%.1f MB", Double(count) / 1_048_576)
            }
            return [typeLabel, sizeLabel].compactMap { $0 }.joined(separator: " · ")
        }
        if embedType == .recording {
            let raw = embed.rawData ?? [:]
            let duration = raw["duration"]?.value as? String
            let modelID = raw["model"]?.value as? String ?? ""
            let catalog = try? NativeModelCatalog.load(bundle: .main)
            let modelName = catalog?.models.first(where: { $0.id == modelID })?.name
                ?? (modelID.isEmpty ? nil : modelID)
            return [duration, modelName].compactMap { $0 }.joined(separator: " · ")
        }
        if embedType == .imagesGenerate || embedType == .imagesGenerateDraft { return "Generate" }
        if embedType == .videosTranscript { return "Transcript" }
        if embedType == .videosCreate {
            let raw = embed.rawData ?? [:]
            let version = raw["active_render_version"]?.value as? Int ?? 1
            let status = raw["status"]?.value as? String ?? "finished"
            return "Remotion · v\(version) · \(status)"
        }
        if embedType == .webRead { return nil }
        if embedType == .mailSearch {
            let raw = embed.rawData ?? [:]
            let count = raw["result_count"]?.value as? Int ?? 0
            let range = raw["time_range"]?.value as? String ?? "All time"
            return "\(count) results · \(range)"
        }
        if embedType == .tasksCreate { return "Created tasks" }
        if embedType == .tasksSearch { return "Matching tasks" }
        if embedType == .workflowsCreateOrModify { return "Created or updated workflow" }
        if embedType == .workflowsSearch { return "Matching workflows" }
        if embedType == .codeGetDocs { return embed.rawData?["question"]?.value as? String }
        if embedType == .pdf {
            let count = embed.rawData?["page_count"]?.value as? Int ?? 0
            return count > 0 ? "\(count) \(count == 1 ? "page" : "pages")" : "PDF"
        }
        if embedType == .musicGenerate {
            let count = embed.rawData?["duration_seconds"]?.value as? Int ?? 0
            let duration = count > 0 ? String(format: "%d:%02d", count / 60, count % 60) : nil
            let modelID = embed.rawData?["model"]?.value as? String ?? ""
            let catalog = try? NativeModelCatalog.load(bundle: .main)
            let modelName = catalog?.models.first(where: { $0.id == modelID })?.name
                ?? (modelID.isEmpty ? "Lyria" : modelID)
            return [modelName, duration].compactMap { $0 }.joined(separator: " · ")
        }
        if embedType == .videosVideo { return nil }
        if embedType == .mindmapsMindmap {
            return MindMapEmbedRenderer.headerCounts(data: embed.rawData)
        }
        if embedType == .electronicsPcbSchematic { return "Atopile" }
        if embedType == .financeCheckAccounts {
            let raw = embed.rawData ?? [:]
            let provider = raw["provider"]?.value as? String ?? "Revolut Business"
            let period = (raw["period"]?.value as? String ?? "monthly").replacingOccurrences(of: "_", with: " ")
            let accounts = raw["account_count"]?.value as? Int ?? 0
            let transactions = raw["transaction_count"]?.value as? Int ?? 0
            return "\(provider) · \(period) · \(accounts) accounts · \(transactions) transactions"
        }
        if embedType == .weatherForecast {
            guard let location = embed.rawData?["location_name"]?.value as? String, !location.isEmpty else { return nil }
            return "(\(location))"
        }
        if embedType == .travelFlight {
            let raw = embed.rawData ?? [:]
            let origin = raw["origin_iata"]?.value as? String ?? ""
            let destination = raw["destination_iata"]?.value as? String ?? ""
            return origin.isEmpty || destination.isEmpty ? nil : "\(origin) → \(destination)"
        }
        if embedType == .mathCalculate {
            let raw = embed.rawData ?? [:]
            return (raw["subtitle"]?.value as? String) ?? (raw["query"]?.value as? String)
        }
        if embedType == .codeApplication {
            let raw = embed.rawData ?? [:]
            return [raw["framework"]?.value as? String, raw["runtime"]?.value as? String]
                .compactMap { $0 }.joined(separator: " · ")
        }
        if embedType == .socialMediaPost {
            let raw = embed.rawData ?? [:]
            let platform = (raw["platform"]?.value as? String ?? "").capitalized
            let page = raw["page"]?.value as? String ?? ""
            return [platform, page].filter { !$0.isEmpty }.joined(separator: " / ")
        }
        if embedType == .reminderSet || embedType == .reminderList || embedType == .reminderCancel {
            return embed.rawData?["trigger_at_formatted"]?.value as? String
        }
        if embedType == .codeNotebook {
            let notebook = embed.rawData?["notebook"]?.value as? [String: Any]
            let count = (notebook?["cells"] as? [Any])?.count ?? 0
            return "\(count) cells, Notebook"
        }
        if embedType == .focusModeActivation {
            return embed.rawData?["focus_mode_name"]?.value as? String
        }
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
        let parsed = AppleCodeEmbedContent(data: dict)
        return CodePayload(code: parsed.code, language: parsed.language,
                           filename: parsed.filename, lineCount: parsed.lineCount)
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
