// Unified embed preview card — compact card shown inline in chat messages.
// Mirrors UnifiedEmbedPreview.svelte with app gradient header, content area,
// and status bar footer. Dispatches to per-type renderers via EmbedContentView.

import SwiftUI

enum EmbedPreviewCardVariant {
    case compact
    case large
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
    @State private var isHovering = false
    @State private var hoverX: CGFloat = 0
    @State private var hoverY: CGFloat = 0
    @State private var processingStartDate: Date?
    @State private var statusHintPhase: StatusHintPhase = .settled
    @State private var statusHintTask: Task<Void, Never>?

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
        EmbedType(rawValue: embed.type)
    }

    var body: some View {
        Button(action: onTap) {
            previewLayout
            .frame(width: cardWidth, height: cardHeight)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
            .shadow(color: .black.opacity(0.16), radius: 24, x: 0, y: 8)
            .shadow(color: .black.opacity(0.10), radius: 6, x: 0, y: 2)
            .overlay(alignment: .bottom) {
                if variant == .large {
                    statusBar
                        .frame(width: Constants.expandedInfoBarWidth)
                        .offset(y: Constants.expandedInfoBarOffset)
                        .shadow(color: .black.opacity(0.12), radius: 24, x: 0, y: 8)
                        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
                }
            }
            .padding(.top, variant == .large ? .spacing5 : 0)
            .padding(.bottom, variant == .large ? Constants.expandedBottomOutset : 0)
            .rotation3DEffect(.degrees(isHovering ? -hoverY * tiltMaxAngle : 0), axis: (x: 1, y: 0, z: 0), perspective: 1 / tiltPerspective)
            .rotation3DEffect(.degrees(isHovering ? hoverX * tiltMaxAngle : 0), axis: (x: 0, y: 1, z: 0), perspective: 1 / tiltPerspective)
            .scaleEffect(isHovering ? 1.02 : 1)
            #if os(macOS)
            .background(hoverTracker)
            #endif
            .animation(.easeOut(duration: 0.15), value: isHovering)
        }
        .buttonStyle(EmbedPreviewButtonStyle())
        .disabled(embed.status == .processing)
        .accessibilityIdentifier("embed-preview")
        .accessibleEmbed(
            type: embedType?.displayName ?? embed.type,
            title: embedType?.displayName
        )
        .accessibilityValue(embed.status == .processing ? "Loading" : embed.status == .error ? "Failed to load" : embed.status == .cancelled ? "Cancelled" : "Ready")
        .onAppear {
            if embed.status == .processing && processingStartDate == nil {
                processingStartDate = Date()
            }
        }
        .onChange(of: embed.status) { oldStatus, newStatus in
            handleStatusChange(from: oldStatus, to: newStatus)
        }
        .onDisappear {
            statusHintTask?.cancel()
        }
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
        variant == .large ? nil : Constants.compactWidth
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
        if hasFullWidthDetails {
            contentArea
                .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
                .overlay(alignment: .bottom) {
                    if variant == .compact {
                        statusBar
                    }
                }
        } else {
            VStack(spacing: 0) {
                contentArea
                if variant == .compact {
                    statusBar
                }
            }
        }
    }

    // MARK: - Content area

    private var contentArea: some View {
        ZStack(alignment: .topLeading) {
            Color.grey25

            if embed.status == .processing {
                processingView
            } else if embed.status == .error {
                errorView
            } else if embed.status == .cancelled {
                cancelledView
            } else {
                EmbedContentView(
                    embed: embed,
                    mode: .preview,
                    allEmbedRecords: allEmbedRecords,
                    previewVariant: variant
                )
                    .padding(.horizontal, hasFullWidthDetails ? 0 : .spacing20)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var processingView: some View {
        VStack(spacing: .spacing4) {
            ProgressView()
                .scaleEffect(1.2)
            Text(LocalizationManager.shared.text("embed.processing"))
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
            skillIconName: skillIconName,
            title: statusTitle,
            subtitle: statusSubtitle,
            faviconURL: faviconURL,
            showSkillIcon: showsSkillIcon
        )
    }

    private var appId: String {
        embed.appId ?? embedType?.appId ?? "web"
    }

    private var skillIconName: String {
        switch embed.skillId ?? embedType?.displayName.lowercased() {
        case "search", "search_products", "search_connections", "search_stays", "search_appointments", "search_recipes":
            return "search"
        case "read":
            return "visible"
        case "get_docs":
            return "docs"
        case "get_transcript":
            return "videos"
        case "generate", "generate_draft", "image_result":
            return "image"
        case "calculate":
            return "math"
        case "set-reminder":
            return "reminder"
        default:
            return AppIconView.iconName(forAppId: appId)
        }
    }

    private var showsSkillIcon: Bool {
        if embedType == .codeCode
            || embedType == .webWebsite
            || embedType == .videosVideo
            || embedType == .imagesImageResult
            || embedType == .eventsEvent
            || embedType == .travelConnection {
            return false
        }
        return true
    }

    private var hasFullWidthDetails: Bool {
        if embedType == .webWebsite {
            return websiteUsesFullWidthImage
        }
        return embedType == .codeCode
            || embedType == .image
            || embedType == .imagesImageResult
            || embedType == .imagesSearch
            || (embed.isAppSkillUse && appId == "images")
    }

    private var statusTitle: String {
        if embedType == .webWebsite {
            return firstString(in: embed.rawData ?? [:], keys: ["title", "site_name"])
                ?? host(from: firstString(in: embed.rawData ?? [:], keys: ["url"]))
                ?? EmbedType.webWebsite.displayName
        }
        if embedType == .imagesImageResult {
            return sourceDomain ?? embedType?.displayName ?? embed.type
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
                return "\(origin) → \(destination)"
            }
            return firstString(in: raw, keys: ["title", "route"])
                ?? embedType?.displayName
                ?? embed.type
        }
        if embed.isAppSkillUse {
            return skillDisplayName
        }
        if embedType == .codeCode {
            if let filename = embed.rawData?["filename"]?.value as? String, !filename.isEmpty {
                return filename.split(separator: "/").last.map(String.init) ?? filename
            }
            return LocalizationManager.shared.text("embeds.code_snippet")
        }
        if let query = embed.rawData?["query"]?.value as? String, !query.isEmpty {
            return query
        }
        return embedType?.displayName ?? embed.type
    }

    private var statusSubtitle: String? {
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
        if embed.isAppSkillUse {
            return nil
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
        return EmbedFieldReader.proxiedImageURL(
            firstString(in: raw, keys: ["favicon_url", "favicon", "meta_url_favicon"]),
            maxWidth: 64
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: firstString(in: raw, keys: ["source_page_url", "url"]))
    }

    private var websiteUsesFullWidthImage: Bool {
        guard embedType == .webWebsite else { return false }
        let raw = embed.rawData ?? [:]
        let description = firstString(in: raw, keys: ["description", "meta_description", "summary"])?
            .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let image = firstString(in: raw, keys: ["image", "image_url", "thumbnail_url", "meta_image", "og_image"])
        return (description?.isEmpty ?? true) && image != nil && variant == .large
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
        case ("travel", "search_connections"):
            return "Search connections"
        case ("code", "get_docs"):
            return LocalizationManager.shared.text("common.docs")
        default:
            return EmbedType(rawValue: embed.type)?.displayName ?? skillId.replacingOccurrences(of: "_", with: " ")
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
