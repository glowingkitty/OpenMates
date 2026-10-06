// Specification: specifications/features/chats/specification.yml
// Assertions: chats.layout.responsive-history,
//             chats.rendering.inline-entity-interaction
//
// Unified embed preview card — compact card shown inline in chat messages.
// Mirrors UnifiedEmbedPreview.svelte with app gradient header, content area,
// and status bar footer. Dispatches to per-type renderers via EmbedContentView.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

private struct EmbedChatIDKey: EnvironmentKey {
    static let defaultValue: String? = nil
}

private struct EmbedPIIMappingsKey: EnvironmentKey {
    static let defaultValue: [PIIMapping] = []
}

private struct EmbedPIIRevealedKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var embedChatID: String? {
        get { self[EmbedChatIDKey.self] }
        set { self[EmbedChatIDKey.self] = newValue }
    }
    var embedPIIMappings: [PIIMapping] {
        get { self[EmbedPIIMappingsKey.self] }
        set { self[EmbedPIIMappingsKey.self] = newValue }
    }
    var embedPIIRevealed: Bool {
        get { self[EmbedPIIRevealedKey.self] }
        set { self[EmbedPIIRevealedKey.self] = newValue }
    }
}

// SearchResultsTemplate stretches compact cards within a result cell, capped at
// 320pt. Ordinary inline previews remain 300pt even on a phone.
private struct EmbedPreviewFillsGridCellKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var embedPreviewFillsGridCell: Bool {
        get { self[EmbedPreviewFillsGridCellKey.self] }
        set { self[EmbedPreviewFillsGridCellKey.self] = newValue }
    }
}

enum EmbedPreviewCardVariant {
    case compact
    case large
}

/// The web registry's preview/fullscreen components pass explicit
/// `skillIconName` values to BasicInfosBar and EmbedHeader. Resolve by the
/// canonical embed key so result cards do not inherit an unrelated app icon.
enum EmbedVisualSkillIcon {
    static func name(for embed: EmbedRecord, fullscreen: Bool = false) -> String {
        if (embed.appId ?? embed.rawData?["app_id"]?.value as? String) == "news",
           (embed.skillId ?? embed.rawData?["skill_id"]?.value as? String) == "search" {
            return "search"
        }
        if HostingEmbedKind.isSearch(embed) || HostingEmbedKind.isDomain(embed) { return "search" }
        // Stored tool calls use app-skill-use while preview fixtures use app:*.
        // Resolve both forms through the same canonical registry key.
        let appId = embed.appId ?? embed.rawData?["app_id"]?.value as? String
        let skillId = embed.skillId ?? embed.rawData?["skill_id"]?.value as? String
        let registryKey: String
        if embed.isAppSkillUse, let appId, let skillId {
            registryKey = "app:\(appId):\(skillId)"
        } else {
            registryKey = EmbedType.normalized(rawValue: embed.type)?.rawValue ?? embed.type
        }
        switch registryKey {
        case "recording": return "microphone"
        case "app:audio:generate", "app:audio:speak": return "audio"
        case "app:business:company_financials", "business-company-financial-result": return "business"
        case "app:calendar:list-calendars", "app:calendar:get-events", "app:calendar:create-event",
             "app:calendar:update-event", "app:calendar:delete-event",
             "app:code:search_repos", "app:design:search_icons",
             "app:electronics:search_components", "electronics-component",
             "app:events:search", "app:fitness:search_locations", "app:fitness:search_classes",
             "app:home:search", "app:images:search", "app:maps:search",
             "app:models3d:search", "app:news:search", "app:nutrition:search_recipes",
             "nutrition-recipe", "app:shopping:search_products", "shopping-product",
             "app:social_media:search", "app:tasks:search",
             "app:travel:search_connections", "app:travel:search_stays", "travel-stay",
             "app:videos:search", "app:web:search", "app:workflows:search": return "search"
        case "code-repo": return "github"
        case "app:code:get_docs", "docs-doc": return "docs"
        case "code-code", "code-notebook", "code-application": return "coding"
        case "design-icon-result": return fullscreen ? "design" : "search"
        case "electronics-pcb-schematic": return "pcbdesign"
        case "events-event": return "event"
        case "file-file": return "files"
        case "app:finance:check_accounts": return "finance"
        case "fitness-location", "fitness-class": return "fitness"
        case "app:health:search_appointments": return fullscreen ? "health" : "search"
        case "health-appointment": return "health"
        case "home-listing": return fullscreen ? "home" : "search"
        case "app:images:generate", "app:images:generate_draft", "app:music:generate": return "ai"
        case "image", "images-image-result": return "image"
        case "app:mail:search", "mail-email": return "mail"
        case "maps", "maps-place": return "pin"
        case "app:math:calculate", "math-plot": return "math"
        case "mindmaps-mindmap": return "workflow"
        case "app:models3d:generate", "models3d-model-result": return "3dmodels"
        case "web-website": return "website"
        case "pdf": return "pdf"
        case "app:reminder:set-reminder", "app:reminder:list-reminders", "app:reminder:cancel-reminder": return "reminder"
        case "app:social_media:get-posts": return fullscreen ? "socialmedia" : "search"
        case "social-media-post": return "socialmedia"
        case "app:tasks:create", "tasks-task": return "task"
        case "travel-connection": return fullscreen ? "travel" : "search"
        case "app:travel:price_calendar": return "calendar"
        case "app:travel:get_flight": return "travel"
        case "videos-video": return "video"
        case "app:videos:get_transcript": return "transcript"
        case "app:videos:create", "app:videos:generate": return "videos"
        case "app:weather:forecast": return fullscreen ? "search" : "weather"
        case "weather-day", "app:weather:rain_radar": return "weather"
        case "app:web:read": return "text"
        case "app:workflows:create-or-modify", "workflows-workflow": return "workflow"
        case "sheets-sheet": return "table"
        case "focus-mode-activation": return fullscreen ? "focus" : "insight"
        default:
            return AppIconView.iconName(forAppId: embed.appId ?? EmbedType.normalized(rawValue: embed.type)?.appId ?? "web")
        }
    }
}

struct EmbedPreviewCard: View {
    private enum Constants {
        static let compactWidth: CGFloat = 300
        static let compactHeight: CGFloat = 200
        static let expandedHeight: CGFloat = 400
        static let expandedInfoBarWidth: CGFloat = 300
        static let expandedInfoBarOffset: CGFloat = 15
        static let expandedBottomOutset: CGFloat = 30
        static let cornerRadius: CGFloat = 30
        static let minimumProcessingDuration: TimeInterval = 0.5
        static let storedEncryptedHintDuration: UInt64 = 2_000_000_000
        static let openDetailsHintDuration: UInt64 = 2_000_000_000
        static let recordingOpenAreaHeight: CGFloat = 64
        static let standardHoverScale: CGFloat = 0.985
        static let largeHoverScale: CGFloat = 0.995
    }

    private enum StatusHintPhase {
        case settled
        case storedEncrypted
        case openDetails
    }

    let embed: EmbedRecord
    let allEmbedRecords: [String: EmbedRecord]
    let variant: EmbedPreviewCardVariant
    let onTap: () -> Void
    @Environment(\.embedPreviewFillsGridCell) private var fillsGridCell
    @Environment(\.embedChatID) private var embedChatID
    @Environment(\.embedPIIMappings) private var embedPIIMappings
    @Environment(\.embedPIIRevealed) private var embedPIIRevealed
    @Environment(\.embedShareSettingsAction) private var shareSettingsAction
    @Environment(\.workspacePaneIsVisible) private var sharePaneVisible
    @State private var showsContextActions = false
    @State private var isHovering = false
    @State private var hoverX: CGFloat = 0
    @State private var hoverY: CGFloat = 0
    @State private var processingStartDate: Date?
    @State private var statusHintPhase: StatusHintPhase = .settled
    @State private var statusHintTask: Task<Void, Never>?
    @StateObject private var generatedAudioPreviewController = GeneratedAudioPreviewController()

    init(
        embed: EmbedRecord,
        allEmbedRecords: [String: EmbedRecord] = [:],
        variant: EmbedPreviewCardVariant = .compact,
        onTap: @escaping () -> Void
    ) {
        self.embed = embed
        self.allEmbedRecords = allEmbedRecords
        self.variant = variant
        self.onTap = onTap
    }

    private var embedType: EmbedType? {
        EmbedType.normalized(rawValue: embed.type)
    }

    var body: some View {
        Group {
            if embedType == .recording || embedType == .audioGenerate || embedType == .audioSpeak {
                ZStack(alignment: .top) {
                    cardSurface
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("embed-preview-card")
                        .contentShape(Rectangle())
                        .onTapGesture {
                            if embed.status != .processing { onTap() }
                        }

                    Button {
                        if embed.status != .processing { onTap() }
                    } label: {
                        Color.clear
                            .frame(maxWidth: .infinity)
                            .frame(height: Constants.recordingOpenAreaHeight)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(embed.status == .processing)
                    .accessibilityIdentifier("embed-preview")
                    .accessibilityLabel(embedType?.displayName ?? embed.type)
                    .accessibilityValue(statusAccessibilityValue)
                }
            } else {
                Button {
                    onTap()
                } label: {
                    cardSurface
                        .contentShape(Rectangle())
                }
                .buttonStyle(EmbedPreviewButtonStyle())
                .disabled(embed.status == .processing)
                .accessibilityIdentifier("embed-preview")
                .accessibleEmbed(
                    type: embedType?.displayName ?? embed.type,
                    title: statusTitle
                )
                // Code exposes its source/processing/empty renderer state in
                // every status, while retaining the outer actionable card.
                .accessibilityElement(children: exposesRuntimeSkillIcons || TravelSearchPresentation.isSearch(embed) || HostingEmbedKind.isSearch(embed) || HostingEmbedKind.isDomain(embed) || embedType == .codeCode || embedType == .mindmapsMindmap || (embed.status == .finished &&
                    (embedType == .maps || embedType == .mapsPlace || embedType == .webSearch || embedType == .newsSearch || (embedType == .webWebsite && appId == "news") || embedType == .imagesSearch || embedType == .sheetsSheet || (embed.isAppSkillUse && appId == "web"))) ? .contain : .combine)
                .accessibilityValue(statusAccessibilityValue)
            }
        }
        .highPriorityGesture(LongPressGesture().onEnded { _ in
            if sharePaneVisible, shareSettingsAction != nil, embed.status == .finished { showsContextActions = true }
        })
        #if os(macOS)
        .background(EmbedSecondaryClickSurface {
            if sharePaneVisible, shareSettingsAction != nil, embed.status == .finished { showsContextActions = true }
        })
        #endif
        .overlay(alignment: .topTrailing) {
            if showsContextActions, let chatId = embedChatID {
                EmbedContextMenuView(embed: embed, chatId: chatId,
                    onFullscreen: { showsContextActions = false; onTap() },
                    onShare: {
                        showsContextActions = false
                        shareSettingsAction?.open(EmbedShareSettingsTarget(
                            embed: embed, chatId: chatId, allEmbedRecords: allEmbedRecords))
                    }, onClose: { showsContextActions = false })
            }
        }
        .zIndex(showsContextActions ? 1 : 0)
        .onAppear {
            if embed.status == .processing && processingStartDate == nil {
                processingStartDate = Date()
            }
        }
        .onChange(of: embed.status) { oldStatus, newStatus in
            handleStatusChange(from: oldStatus, to: newStatus)
        }
        .onDisappear {
            showsContextActions = false
            statusHintTask?.cancel()
        }
    }

    private var cardSurface: some View {
        previewLayout
            .environment(\.generatedAudioPreviewController, generatedAudioPreviewController)
            .frame(width: cardWidth, height: cardHeight)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
            .background {
                // CSS box-shadow blur is twice the Gaussian radius. Draw each
                // layer separately so the second shadow does not blur the first.
                ZStack {
                    RoundedRectangle(cornerRadius: Constants.cornerRadius)
                        .fill(Color.grey25)
                        .shadow(color: .black.opacity(isHovering ? 0.12 : 0.16),
                                radius: isHovering ? 6 : 12, x: 0, y: isHovering ? 4 : 8)
                    RoundedRectangle(cornerRadius: Constants.cornerRadius)
                        .fill(Color.grey25)
                        .shadow(color: .black.opacity(isHovering ? 0.08 : 0.10),
                                radius: isHovering ? 1.5 : 3, x: 0, y: isHovering ? 1 : 2)
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            }
            .overlay(alignment: .bottom) {
                if variant == .large {
                    statusBar
                        .frame(width: Constants.expandedInfoBarWidth)
                        .fixedSize(horizontal: false, vertical: true)
                        .offset(y: Constants.expandedInfoBarOffset)
                        .shadow(color: .black.opacity(0.12), radius: 24, x: 0, y: 8)
                        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
                }
            }
            .padding(.top, variant == .large ? .spacing5 : 0)
            .padding(.bottom, variant == .large ? Constants.expandedBottomOutset : 0)
            #if DEBUG
            .background(EmbedPreviewGeometryProbe(name: "card"))
            #endif
            .rotation3DEffect(.degrees(isHovering ? -hoverY * tiltMaxAngle : 0), axis: (x: 1, y: 0, z: 0), perspective: 1 / tiltPerspective)
            .rotation3DEffect(.degrees(isHovering ? hoverX * tiltMaxAngle : 0), axis: (x: 0, y: 1, z: 0), perspective: 1 / tiltPerspective)
            .scaleEffect(isHovering ? hoverScale : 1)
            #if os(macOS)
            .background(hoverTracker)
            #endif
            .animation(.easeOut(duration: 0.15), value: isHovering)
    }

    private var statusAccessibilityValue: String {
        embed.status == .processing ? "Loading" : embed.status == .error ? "Failed to load" : embed.status == .cancelled ? "Cancelled" : "Ready"
    }

    private func handleStatusChange(from oldStatus: EmbedStatus, to newStatus: EmbedStatus) {
        statusHintTask?.cancel()

        if newStatus == .processing {
            processingStartDate = Date()
            statusHintPhase = .settled
            return
        }

        guard oldStatus == .processing, newStatus == .finished else {
            processingStartDate = nil
            statusHintPhase = .settled
            return
        }

        let duration = processingStartDate.map { Date().timeIntervalSince($0) } ?? 0
        processingStartDate = nil
        guard duration >= Constants.minimumProcessingDuration else {
            statusHintPhase = .settled
            return
        }

        statusHintPhase = .storedEncrypted
        statusHintTask = Task { @MainActor in
            do {
                try await Task.sleep(nanoseconds: Constants.storedEncryptedHintDuration)
                guard !Task.isCancelled else { return }
                statusHintPhase = .openDetails
                try await Task.sleep(nanoseconds: Constants.openDetailsHintDuration)
                guard !Task.isCancelled else { return }
                statusHintPhase = .settled
            } catch {
                // Cancellation is expected when the card unmounts or status changes again.
            }
        }
    }

    private var cardWidth: CGFloat? {
        variant == .large || fillsGridCell ? nil : Constants.compactWidth
    }

    private var cardHeight: CGFloat {
        variant == .large ? Constants.expandedHeight : Constants.compactHeight
    }

    private var tiltMaxAngle: CGFloat {
        variant == .large ? 1 : 3
    }

    private var tiltPerspective: CGFloat {
        variant == .large ? 1200 : 800
    }

    private var hoverScale: CGFloat {
        variant == .large ? Constants.largeHoverScale : Constants.standardHoverScale
    }

    private var hoverTracker: some View {
        GeometryReader { proxy in
            Color.clear
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
        }
    }

    @ViewBuilder
    private var previewLayout: some View {
        if embedType == .recording, embed.status == .finished {
            // RecordingRenderer owns the finished recording's web-parity
            // details + BasicInfosBar composition so playback state can drive
            // the footer play button without duplicating a second header.
            contentArea
        } else if hasFullWidthDetails {
            contentArea
                .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
                .overlay(alignment: .bottom) {
                    if variant == .compact {
                        if embedType == .videosVideo {
                            // A long video title must truncate within the card.
                            // Bind the overlay to the primary surface's width so
                            // its intrinsic footer cannot center beyond the clip
                            // and cut the app circle in half at the leading edge.
                            GeometryReader { viewport in
                                statusBar
                                    .frame(width: viewport.size.width, height: EmbedPreviewFooterLayout.height)
                                    .frame(maxHeight: .infinity, alignment: .bottom)
                            }
                        } else {
                            statusBar
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
        } else {
            GeometryReader { viewport in
                // Web .details-section has min-height:0 and flex:1, while
                // BasicInfosBar is a nonshrinking 61px sibling. Intrinsic text
                // or badge height must never move the footer outside the card.
                VStack(spacing: 0) {
                    contentArea
                        .frame(height: EmbedPreviewFooterLayout.detailsHeight(cardHeight: viewport.size.height))
                        .clipped()
                    if variant == .compact {
                        statusBar.fixedSize(horizontal: false, vertical: true)
                    } else {
                        // Large cards paint their footer in cardSurface's
                        // overlay and retain the web's15pt transformed offset.
                        Color.clear.frame(height: EmbedPreviewFooterLayout.height)
                    }
                }
                .frame(width: viewport.size.width, height: viewport.size.height, alignment: .top)
            }
        }
    }

    // MARK: - Content area

    private var contentArea: some View {
        ZStack(alignment: .topLeading) {
            Color.grey25

            // Hosting's web details retain the query/provider and explain each
            // terminal status. Generic loading/error placeholders hide that
            // information and must not replace its registered renderer.
            if HostingEmbedKind.isSearch(embed) || HostingEmbedKind.isDomain(embed)
                || (embed.status == .processing && embed.isAppSkillUse) {
                EmbedContentView(
                    embed: embed,
                    mode: .preview,
                    allEmbedRecords: allEmbedRecords,
                    chatId: embedChatID,
                    hasPIIMappings: !embedPIIMappings.isEmpty,
                    piiMappings: embedPIIMappings,
                    isPIIRevealed: embedPIIRevealed,
                    previewVariant: variant
                )
                .padding(.horizontal, .spacing10)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            } else if embed.status == .processing && embedType != .mindmapsMindmap && embedType != .codeCode {
                processingView
            } else if embed.status == .error && embedType != .codeCode {
                errorView
            } else if embed.status == .cancelled {
                cancelledView
            } else {
                EmbedContentView(
                    embed: embed,
                    mode: .preview,
                    allEmbedRecords: allEmbedRecords,
                    chatId: embedChatID,
                    hasPIIMappings: !embedPIIMappings.isEmpty,
                    piiMappings: embedPIIMappings,
                    isPIIRevealed: embedPIIRevealed,
                    previewVariant: variant
                )
                    .padding(
                        .horizontal,
                        hasFullWidthDetails || embedType == .recording
                            ? 0
                            : .spacing10
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var processingView: some View {
        VStack(spacing: .spacing4) {
            ProgressView()
                .scaleEffect(1.2)
            Text(LocalizationManager.shared.text("embeds.processing"))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        }
    }

    private var errorView: some View {
        VStack(spacing: .spacing3) {
            Icon("warning", size: 24)
                .foregroundStyle(Color.error)
            Text(LocalizationManager.shared.text("embed.failed_to_load"))
                .font(.omSmall)
                .foregroundStyle(Color.error)
        }
    }

    private var cancelledView: some View {
        VStack(spacing: .spacing3) {
            Icon("close", size: 24)
                .foregroundStyle(Color.fontTertiary)
            Text(LocalizationManager.shared.text("embed.cancelled"))
                .font(.omSmall)
                .foregroundStyle(Color.fontTertiary)
        }
        .opacity(0.6)
    }

    // MARK: - Status bar (mirrors BasicInfosBar.svelte)

    private var statusBar: some View {
        EmbedBasicInfoBar(
            appId: appId,
            appIconName: embedType == .mindmapsMindmap ? "workflow" : nil,
            skillIconName: skillIconName,
            title: statusTitle,
            subtitle: statusSubtitle,
            isProcessing: embed.status == .processing,
            faviconURL: faviconURL,
            faviconIsCircular: embedType == .codeRepo || embedType == .videosVideo,
            showSkillIcon: showsSkillIcon,
            trailingAction: processingOrAudioTrailingAction
        )
        #if DEBUG
        .background(EmbedPreviewGeometryProbe(name: "footer"))
        #endif
    }

    private var isGeneratedAudioSkill: Bool {
        embedType == .audioGenerate || embedType == .audioSpeak
    }

    private var processingOrAudioTrailingAction: AnyView? {
        if embed.status == .processing {
            return AnyView(
                EmbedProcessingStopGlyph()
                    .accessibilityLabel(AppStrings.stop)
            )
        }
        guard embed.status == .finished,
              isGeneratedAudioSkill,
              GeneratedAudioPreviewPlayButton.hasPlayableMedia(data: embed.rawData) else { return nil }
        return AnyView(
            GeneratedAudioPreviewPlayButton(
                controller: generatedAudioPreviewController,
                data: embed.rawData,
                skillId: embedType == .audioSpeak ? "speak" : "generate"
            )
        )
    }

    private var appId: String {
        embed.appId ?? embed.rawData?["app_id"]?.value as? String ?? embedType?.appId ?? "web"
    }

    private var exposesRuntimeSkillIcons: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("--dev-runtime-skill-icon-preview")
        #else
        false
        #endif
    }

    private var skillIconName: String {
        EmbedVisualSkillIcon.name(for: embed)
    }

    private var showsSkillIcon: Bool {
        if HostingEmbedKind.isDomain(embed) { return false }
        if embedType == .mailEmail || embedType == .mathPlot
            || embedType == .weatherForecast || embedType == .weatherRainRadar { return false }
        if embedType == .webSearch
            || embedType == .videosSearch
            || embedType == .image
            || embedType == .codeRepo
            || embedType == .codeCode
            || embedType == .docsDoc
            || embedType == .fileFile
            || embedType == .webWebsite
            || embedType == .videosVideo
            || embedType == .imagesImageResult
            || embedType == .eventsEvent
            || embedType == .healthAppointment
            || embedType == .travelConnection
            || embedType == .travelStay
            || embedType == .codeApplication
            || embedType == .designIconResult
            || embedType == .electronicsPcbSchematic
            || embedType == .mindmapsMindmap
            || embedType == .sheetsSheet
            || embedType == .pdf {
            return false
        }
        return true
    }

    private var hasFullWidthDetails: Bool {
        if embedType == .maps || embedType == .mapsPlace {
            return MapsEmbedModel(embed.rawData).mapImageURL != nil
        }
        if embedType == .webWebsite {
            return websiteUsesFullWidthImage
        }
        return embedType == .travelStay
            || embedType == .codeCode
            || embedType == .docsDoc
            || embedType == .image
            || embedType == .imagesImageResult
            || embedType == .imagesSearch
            || embedType == .videosVideo
            || (embed.isAppSkillUse && appId == "images")
    }

    private var statusTitle: String {
        if HostingEmbedKind.isDomain(embed) { return HostingDomainModel(embed).name }
        if HostingEmbedKind.isSearch(embed) { return AppStrings.hosting(.title) }
        if embedType == .mindmapsMindmap {
            return NativeMindMapPreviewTitle.resolve(embed.rawData)
        }
        if embedType == .travelStay {
            return firstString(in: embed.rawData ?? [:], keys: ["name"]) ?? "Stay"
        }
        if embedType == .maps || embedType == .mapsPlace { return AppStrings.domainLocation }
        if embedType == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: embedPIIMappings, revealed: embedPIIRevealed)
            return mail.subject.isEmpty ? AppStrings.localized("embeds.mail.email") : mail.subject
        }
        switch embedType {
        case .audioGenerate, .audioSpeak: return "Generate SFX"
        case .calendarListCalendars, .calendarGetEvents, .calendarCreateEvent,
             .calendarUpdateEvent, .calendarDeleteEvent: return AppStrings.search
        case .imagesGenerate, .imagesGenerateDraft, .videosGenerate, .musicGenerate: return "Generate"
        case .financeCheckAccounts: return AppStrings.financeCheckAccounts
        case .mathCalculate: return "Calculate"
        case .reminderSet, .reminderList, .reminderCancel: return AppStrings.setReminder
        case .weatherForecast: return AppStrings.weatherForecast
        case .travelFlight: return "Flight Track"
        default: break
        }
        if embedType == .docsDoc {
            return firstString(in: embed.rawData ?? [:], keys: ["filename", "title"])
                ?? EmbedType.docsDoc.displayName
        }
        if embedType == .sheetsSheet {
            return ParsedSheetTable(data: embed.rawData)
                .applyingPII(mappings: embedPIIMappings, revealed: embedPIIRevealed).title ?? AppStrings.localized("embeds.table")
        }
        if embedType == .image {
            return firstString(in: embed.rawData ?? [:], keys: ["filename"])
                ?? embedType?.displayName ?? embed.type
        }
        if embedType == .codeNotebook {
            return firstString(in: embed.rawData ?? [:], keys: ["filename"]) ?? "notebook.ipynb"
        }
        if embedType == .codeApplication {
            return firstString(in: embed.rawData ?? [:], keys: ["name"]) ?? "Application"
        }
        if embedType == .designIconResult {
            return firstString(in: embed.rawData ?? [:], keys: ["display_name", "name", "icon_id"]) ?? "Icon"
        }
        if embedType == .socialMediaPost {
            return firstString(in: embed.rawData ?? [:], keys: ["author_display_name", "author"])
                ?? EmbedType.socialMediaPost.displayName
        }
        if embedType == .electronicsPcbSchematic { return "Code snippet" }
        if embedType == .pdf {
            return firstString(in: embed.rawData ?? [:], keys: ["filename"]) ?? "PDF"
        }
        if embedType == .codeRepo {
            let raw = embed.rawData ?? [:]
            let fullName = firstString(in: raw, keys: ["name", "full_name"]) ?? ""
            return fullName.split(separator: "/").last.map(String.init) ?? EmbedType.codeRepo.displayName
        }
        if embedType == .videosVideo {
            let rawTitle = firstString(in: embed.rawData ?? [:], keys: ["title"]) ?? AppStrings.transcriptYouTubeVideo
            return rawTitle.count > 30 ? String(rawTitle.prefix(29)) + "…" : rawTitle
        }
        if embedType == .diagramsMermaid {
            return Self.mermaidStatusTitle(in: embed.rawData ?? [:])
        }
        if embedType == .webWebsite {
            return firstString(in: embed.rawData ?? [:], keys: ["title", "site_name"])
                ?? host(from: firstString(in: embed.rawData ?? [:], keys: ["url"]))
                ?? EmbedType.webWebsite.displayName
        }
        if embedType == .imagesImageResult {
            return sourceDomain ?? embedType?.displayName ?? embed.type
        }
        if embedType == .healthAppointment {
            return firstString(in: embed.rawData ?? [:], keys: ["name", "doctor_name", "speciality"])
                ?? AppStrings.domainHealthAppointment
        }
        if embedType == .eventsEvent {
            return firstString(in: embed.rawData ?? [:], keys: ["title", "name"])
                ?? embedType?.displayName
                ?? embed.type
        }
        if embedType == .travelConnection {
            let raw = embed.rawData ?? [:]
            let origin = firstString(in: raw, keys: ["origin_code", "departure_airport_code", "from_code", "origin"])
            let destination = firstString(in: raw, keys: ["destination_code", "arrival_airport_code", "to_code", "destination"])
            if let origin, let destination {
                // TravelConnectionEmbedPreview.svelte uses extractCode() in
                // BasicInfosBar, keeping long city names in the details area.
                let originCode = TravelValue.iataCode(from: origin) ?? String(origin.split(separator: " ").first ?? "")
                let destinationCode = TravelValue.iataCode(from: destination) ?? String(destination.split(separator: " ").first ?? "")
                return "\(originCode) → \(destinationCode)"
            }
            return firstString(in: raw, keys: ["title", "route"])
                ?? embedType?.displayName
                ?? embed.type
        }
        if embed.isAppSkillUse {
            return skillDisplayName
        }
        if embedType == .codeCode {
            let content = AppleCodeEmbedContent(data: embed.rawData)
            if let filename = content.previewFilename { return filename }
            if !content.language.isEmpty { return formatLanguageName(content.language) }
            return LocalizationManager.shared.text("embeds.code_snippet")
        }
        if let query = embed.rawData?["query"]?.value as? String, !query.isEmpty {
            return query
        }
        return embedType?.displayName ?? embed.type
    }

    static func mermaidStatusTitle(in raw: [String: AnyCodable]) -> String {
        let title = (raw["title"]?.value as? String ?? "")
            .unicodeScalars
            .filter { !CharacterSet.controlCharacters.contains($0) }
            .map(String.init)
            .joined()
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return title.isEmpty ? "Mermaid Diagram" : title
    }

    private var statusSubtitle: String? {
        if HostingEmbedKind.isDomain(embed) || (HostingEmbedKind.isSearch(embed) && embed.status != .processing) { return nil }
        if embedType == .travelStay { return nil }
        if embedType == .maps || embedType == .mapsPlace { return nil }
        if embedType == .mailEmail {
            let mail = MailEmbedModel(embed.rawData).applyingPII(mappings: embedPIIMappings, revealed: embedPIIRevealed)
            return mail.receiver.isEmpty ? nil : "\(AppStrings.localized("embeds.mail.to")) \(mail.receiver)"
        }
        if statusHintPhase == .storedEncrypted {
            return AppStrings.embedStoredEncrypted
        }
        if statusHintPhase == .openDetails {
            #if os(macOS)
            return AppStrings.embedClickToShowDetails
            #else
            return AppStrings.embedTapToShowDetails
            #endif
        }
        if embed.status == .processing {
            if isGeneratedAudioSkill { return nil }
            if embedType == .videosGenerate { return "Veo" }
            if embedType == .electronicsPcbSchematic { return "Atopile" }
            return AppStrings.localized("common.processing")
        }
        switch embedType {
        case .financeCheckAccounts:
            let accounts = embed.rawData?["account_count"]?.value as? Int ?? 0
            let transactions = embed.rawData?["transaction_count"]?.value as? Int ?? 0
            return "\(accounts) accounts · \(transactions) transactions"
        case .reminderSet, .reminderList, .reminderCancel:
            return embed.rawData?["trigger_at_formatted"]?.value as? String
        case .weatherForecast:
            if let provider = embed.rawData?["provider"]?.value as? String {
                return "\(AppStrings.via) \(provider)"
            }
            return nil
        case .musicGenerate:
            return "Lyria 3 Clip · 0:30"
        case .audioGenerate, .audioSpeak:
            return "ElevenLabs"
        case .videosGenerate:
            return "Veo"
        default: break
        }
        if embed.isAppSkillUse {
            return nil
        }
        if embedType == .docsDoc {
            let count = embed.rawData?["word_count"]?.value as? Int ?? 0
            return count > 0 ? "\(count) words" : nil
        }
        if embedType == .sheetsSheet {
            let table = ParsedSheetTable(data: embed.rawData)
            return table.displayRowCount == 0 && table.displayColCount == 0 ? nil : table.dimensionsText
        }
        if embedType == .pdf {
            let count = embed.rawData?["page_count"]?.value as? Int ?? 0
            return count > 0 ? "\(count) \(count == 1 ? "page" : "pages")" : nil
        }
        if embedType == .image,
           let filename = firstString(in: embed.rawData ?? [:], keys: ["filename"]),
           let ext = filename.split(separator: ".").last,
           filename.contains(".") {
            return ext.uppercased()
        }
        if embedType == .codeNotebook {
            let notebook = embed.rawData?["notebook"]?.value as? [String: Any]
            let count = (notebook?["cells"] as? [Any])?.count ?? 0
            return "\(count) cells, Notebook"
        }
        if embedType == .codeApplication {
            let raw = embed.rawData ?? [:]
            let framework = firstString(in: raw, keys: ["framework"])
            let runtime = firstString(in: raw, keys: ["runtime"])
            let count = (raw["file_refs"]?.value as? [Any])?.count ?? 0
            return [framework, runtime, count > 0 ? "\(count) files" : nil]
                .compactMap { $0 }.joined(separator: " · ")
        }
        if embedType == .codeRepo {
            let raw = embed.rawData ?? [:]
            let language = firstString(in: raw, keys: ["primary_language"])
            let license = firstString(in: raw, keys: ["license_spdx_id", "license_name"])
            let metadata = [language, license].compactMap { $0 }.joined(separator: " · ")
            return metadata.isEmpty ? EmbedType.codeRepo.displayName : metadata
        }
        if embedType == .videosVideo {
            let raw = embed.rawData ?? [:]
            var parts: [String] = []
            if let formatted = firstString(in: raw, keys: ["duration_formatted", "duration"]) {
                parts.append(formatted)
            } else if let seconds = raw["duration_seconds"]?.value as? Int {
                parts.append(String(format: "%d:%02d", seconds / 60, seconds % 60))
            }
            if let published = firstString(in: raw, keys: ["published_at", "publishedAt"]),
               let date = ISO8601DateFormatter().date(from: published) {
                let formatter = DateFormatter()
                formatter.locale = Locale(identifier: "en_US")
                formatter.dateFormat = "MMM d, yyyy"
                parts.append(formatter.string(from: date))
            }
            return parts.isEmpty ? nil : parts.joined(separator: ", ")
        }
        if embedType == .codeCode {
            let data = embed.rawData ?? [:]
            let code = data["code"]?.value as? String ?? ""
            let lineCount = (data["lineCount"]?.value as? Int)
                ?? (data["line_count"]?.value as? Int)
                ?? (code.isEmpty ? 0 : code.components(separatedBy: "\n").count)
            let language = (data["language"]?.value as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if lineCount > 0 {
                let lineText = lineCount == 1
                    ? LocalizationManager.shared.text("embeds.code_line_singular")
                    : LocalizationManager.shared.text("embeds.code_line_plural")
                return language.isEmpty ? "\(lineCount) \(lineText)" : "\(lineCount) \(lineText), \(formatLanguageName(language))"
            }
            return language.isEmpty ? nil : formatLanguageName(language)
        }
        if let provider = embed.rawData?["provider"]?.value as? String, !provider.isEmpty {
            return "\(AppStrings.via) \(provider)"
        }
        return nil
    }

    private var faviconURL: String? {
        let raw = embed.rawData ?? [:]
        if embedType == .imagesImageResult { return nil }
        if embedType == .codeRepo {
            return firstString(in: raw, keys: ["owner_avatar_url"])
                .flatMap { EmbedFieldReader.proxiedImageURL($0, maxWidth: 64) }
        }
        if embedType == .videosVideo {
            return firstString(in: raw, keys: ["channel_thumbnail", "channel_thumbnail_url"])
                .flatMap { EmbedFieldReader.proxiedImageURL($0, maxWidth: 64) }
        }
        return EmbedFieldReader.proxiedFaviconImageURL(
            directURL: firstString(in: raw, keys: ["favicon_url", "favicon", "meta_url_favicon", "meta_url.favicon"]),
            pageURL: firstString(in: raw, keys: ["source_page_url", "url"])
        )
    }

    private var websiteUsesFullWidthImage: Bool {
        guard embedType == .webWebsite else { return false }
        let raw = embed.rawData ?? [:]
        let description = firstString(in: raw, keys: ["description", "meta_description", "summary"])?
            .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let image = firstString(in: raw, keys: ["thumbnail_original", "thumbnail.original", "image", "image_url", "thumbnail_url", "meta_image", "og_image"])
        return (description?.isEmpty ?? true) && image != nil
    }

    private var sourceDomain: String? {
        firstString(in: embed.rawData ?? [:], keys: ["source", "source_domain"])
            ?? host(from: firstString(in: embed.rawData ?? [:], keys: ["source_page_url", "url"]))
    }

    private var skillDisplayName: String {
        let appId = embed.appId ?? embed.rawData?["app_id"]?.value as? String ?? "web"
        let skillId = embed.skillId ?? embed.rawData?["skill_id"]?.value as? String ?? "search"
        switch (appId, skillId) {
        case ("events", "search"), ("web", "search"), ("news", "search"), ("images", "search"), ("videos", "search"):
            return LocalizationManager.shared.text("common.search")
        case ("videos", "get_transcript"), ("videos", "get-transcript"):
            return AppStrings.videoGetTranscript
        case ("images", "view"):
            return LocalizationManager.shared.text("common.view")
        case ("travel", "search_connections"):
            return "Search connections"
        case ("weather", "forecast"):
            return AppStrings.weatherForecast
        case ("code", "get_docs"):
            return AppStrings.localized("app_skills.code.get_docs")
        default:
            let key = "app_skills.\(appId).\(skillId.replacingOccurrences(of: "-", with: "_"))"
            let localized = AppStrings.localized(key)
            return localized.hasPrefix("[T:")
                ? (EmbedType(rawValue: embed.type)?.displayName ?? skillId.replacingOccurrences(of: "_", with: " "))
                : localized
        }
    }

    private func formatLanguageName(_ language: String) -> String {
        switch language.lowercased() {
        case "js", "javascript": return "JavaScript"
        case "ts", "typescript": return "TypeScript"
        case "py", "python": return "Python"
        case "html": return "HTML"
        case "css": return "CSS"
        case "swift": return "Swift"
        case "md", "markdown": return "Markdown"
        default:
            return language.prefix(1).uppercased() + language.dropFirst()
        }
    }

    private func firstString(in raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = raw["meta_url"]?.value as? [String: Any],
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

private struct EmbedPreviewButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1.0)
            .animation(reduceMotion ? .none : .easeInOut(duration: 0.14), value: configuration.isPressed)
    }
}
