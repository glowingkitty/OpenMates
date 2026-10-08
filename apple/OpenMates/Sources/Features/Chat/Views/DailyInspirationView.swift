// Daily inspiration banner — gradient card shown on the new chat welcome screen.
// Displays a category-specific gradient background with living orbs, mate profile
// circle, inspiration phrase, and "Click to start chat" CTA.
// Matches the web DailyInspirationBanner.svelte layout and visual treatment.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/DailyInspirationBanner.svelte
// CSS:     DailyInspirationBanner.svelte <style>
//          Regular layout uses measured container width (mobile ≤730px).
//          Rendered wide preview: equal 333px columns, 14px gap, 300×200 video.
//          Inner max outer width 760px, including 40px horizontal padding.
//          Background: getCategoryGradientColors per inspiration category
//          Layout: label top-left, mate profile + phrase row, CTA bottom-left
//          Decorative category icons at edges, living gradient orbs
// JS:      frontend/packages/ui/src/utils/categoryUtils.ts
//          getCategoryGradientColors, CATEGORY_GRADIENTS, CATEGORY_FALLBACK_ICONS
// i18n:    daily_inspiration.label, daily_inspiration.click_to_start_chat
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// Slow ornamental motion keeps its wall-clock periods without display-rate
/// SwiftUI layout work. Foreground/viewport visibility belongs to this leaf.
enum WelcomeDecorativeMotionPolicy {
    static let minimumInterval: TimeInterval = 1.0 / 20.0
    static func runs(paneVisible: Bool, scrollVisible: Bool, sceneActive: Bool, windowVisible: Bool, reduced: Bool) -> Bool {
        windowVisible && WorkspaceMotionPolicy.shouldAnimate(paneVisible: paneVisible, scrollVisible: scrollVisible,
            sceneActive: sceneActive, reduced: reduced)
    }
}

struct WelcomeDecorativeClock<Content: View>: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.workspacePaneIsVisible) private var paneVisible
    @State private var scrollVisible = true
    @State private var windowVisible = false
    @ViewBuilder let content: (Double) -> Content
    private var runs: Bool {
        WelcomeDecorativeMotionPolicy.runs(paneVisible: paneVisible, scrollVisible: scrollVisible,
            sceneActive: scenePhase == .active, windowVisible: windowVisible, reduced: reduceMotion)
    }
    private var clock: some View {
        TimelineView(.animation(minimumInterval: WelcomeDecorativeMotionPolicy.minimumInterval, paused: !runs)) { timeline in
            content(reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate)
        }
        .background(WelcomeDecorativeVisibilityReader { visible in
            if windowVisible != visible { windowVisible = visible }
        })
    }
    var body: some View {
        if #available(iOS 18, macOS 15, *) {
            clock.onScrollVisibilityChange(threshold: 0.01) { scrollVisible = $0 }
        } else {
            // Native visible-rect observation also covers older deployment targets.
            clock
        }
    }
}

#if os(macOS)
private struct WelcomeDecorativeVisibilityReader: NSViewRepresentable {
    let changed: (Bool) -> Void
    func makeNSView(context: Context) -> Reader { Reader() }
    func updateNSView(_ view: Reader, context: Context) { view.changed = changed; view.publish() }
    static func dismantleNSView(_ view: Reader, coordinator: ()) { view.detach() }
    final class Reader: NSView {
        var changed: (Bool) -> Void = { _ in }
        private var observers: [NSObjectProtocol] = []
        private var lastValue: Bool?
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); attach() }
        override func viewDidMoveToSuperview() { super.viewDidMoveToSuperview(); attach() }
        override func layout() { super.layout(); publish() }
        func detach() { observers.forEach(NotificationCenter.default.removeObserver); observers = [] }
        private func attach() {
            detach()
            guard let window else { publish(); return }
            for name in [NSWindow.didBecomeKeyNotification, NSWindow.didResignKeyNotification,
                         NSWindow.didMiniaturizeNotification, NSWindow.didDeminiaturizeNotification,
                         NSWindow.didChangeOcclusionStateNotification] { observe(name, object: window) }
            for name in [NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification] { observe(name, object: nil) }
            var ancestor = superview
            while let view = ancestor {
                if let clip = view as? NSClipView {
                    clip.postsBoundsChangedNotifications = true
                    observe(NSView.boundsDidChangeNotification, object: clip)
                }
                ancestor = view.superview
            }
            publish()
        }
        private func observe(_ name: Notification.Name, object: Any?) {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: object, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.publish() }
            })
        }
        func publish() {
            let visible = window.map { NSApp.isActive && $0.isKeyWindow && $0.isVisible && !$0.isMiniaturized
                && $0.occlusionState.contains(.visible) } == true && !isHiddenOrHasHiddenAncestor && !visibleRect.isEmpty
            guard lastValue != visible else { return }; lastValue = visible
            DispatchQueue.main.async { [weak self] in self?.changed(visible) }
        }
    }
}
#elseif os(iOS)
private struct WelcomeDecorativeVisibilityReader: UIViewRepresentable {
    let changed: (Bool) -> Void
    func makeUIView(context: Context) -> Reader { Reader() }
    func updateUIView(_ view: Reader, context: Context) { view.changed = changed; view.publish() }
    static func dismantleUIView(_ view: Reader, coordinator: ()) { view.observations = [] }
    final class Reader: UIView {
        var changed: (Bool) -> Void = { _ in }
        var observations: [NSKeyValueObservation] = []
        private var lastValue: Bool?
        override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? { nil }
        override func didMoveToWindow() { super.didMoveToWindow(); attach() }
        override func didMoveToSuperview() { super.didMoveToSuperview(); attach() }
        override func layoutSubviews() { super.layoutSubviews(); publish() }
        private func attach() {
            observations = []
            var ancestor = superview
            while let view = ancestor {
                if let scroll = view as? UIScrollView {
                    observations.append(scroll.observe(\.contentOffset) { [weak self] _, _ in self?.publish() })
                }
                ancestor = view.superview
            }
            publish()
        }
        func publish() {
            var rect = bounds
            var current: UIView? = self
            while let view = current, !rect.isEmpty {
                if view.isHidden || view.alpha == 0 { rect = .zero; break }
                if view.clipsToBounds || view is UIScrollView || view is UIWindow { rect = rect.intersection(view.bounds) }
                guard let parent = view.superview else { break }
                rect = view.convert(rect, to: parent); current = parent
            }
            let visible = window != nil && !rect.isEmpty && !rect.isNull
            guard lastValue != visible else { return }; lastValue = visible
            DispatchQueue.main.async { [weak self] in self?.changed(visible) }
        }
    }
}
#endif

// MARK: - Data model

/// Matches the web's DailyInspiration type from dailyInspirationStore.ts.
struct DailyInspirationData: Decodable {
    let inspirationId: String?
    let text: String
    let title: String?
    let category: String?
    let iconName: String?
    let video: DailyInspirationVideo?
    let startedChatId: String?
    let feature: DailyInspirationFeature?
    let contentType: String?
    let wiki: DailyInspirationWiki?

    init(
        inspirationId: String? = nil,
        text: String,
        title: String? = nil,
        category: String? = nil,
        iconName: String? = nil,
        video: DailyInspirationVideo? = nil,
        startedChatId: String? = nil,
        feature: DailyInspirationFeature? = nil,
        contentType: String? = nil,
        wiki: DailyInspirationWiki? = nil
    ) {
        self.inspirationId = inspirationId
        self.text = text
        self.title = title
        self.category = category
        self.iconName = iconName
        self.video = video
        self.startedChatId = startedChatId
        self.feature = feature
        self.contentType = contentType
        self.wiki = wiki
    }
}

struct DailyInspirationWiki: Decodable {
    let title: String
    let wikiTitle: String?
    let description: String?
    let thumbnailUrl: String?
    let wikidataId: String?
    let extract: String?
    var language: String? = nil

    var previewEmbed: EmbedRecord {
        var data: [String: AnyCodable] = ["title": AnyCodable(title),
            "wiki_title": AnyCodable(wikiTitle ?? title)]
        if let language { data["language"] = AnyCodable(language) }
        for (key, value) in [("description", description), ("thumbnail_url", thumbnailUrl),
                             ("wikidata_id", wikidataId), ("extract", extract)] {
            if let value { data[key] = AnyCodable(value) }
        }
        return EmbedRecord(id: "inspiration-wiki-" + (wikiTitle ?? title), type: EmbedType.wiki.rawValue,
            status: .finished, data: .raw(data), parentEmbedId: nil, appId: EmbedType.wiki.appId,
            skillId: nil, embedIds: nil, createdAt: nil)
    }
}

/// Shared public API mapping keeps the banner and its widget on one payload.
struct DailyInspirationAPIResponse: Decodable {
    let inspirations: [Item]
    struct Item: Decodable {
        let inspirationId: String
        let phrase: String
        let title: String
        let category: String
        let contentType: String?
        let video: DailyInspirationVideo?
        let wiki: DailyInspirationWiki?

        func bannerData(sourceLanguage: String) -> DailyInspirationData {
            var article = wiki
            if article?.language?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false {
                article?.language = sourceLanguage
            }
            return DailyInspirationData(inspirationId: inspirationId, text: phrase, title: title,
                category: category, video: video, contentType: contentType, wiki: article)
        }
    }

    static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: data)
    }
}

struct DailyInspirationFeature: Decodable {
    let iconName: String?
    let title: String?
    let description: String?

    enum CodingKeys: String, CodingKey {
        case iconName = "icon"
        case title
        case description
    }

    init(iconName: String, title: String, description: String) {
        self.iconName = iconName
        self.title = title
        self.description = description
    }
}

struct DailyInspirationVideo: Decodable {
    let youtubeId: String?
    let title: String?
    let channelName: String?
    let thumbnailUrl: String?
    let durationSeconds: Int?
    let viewCount: Int?
    let publishedAt: String?
}

// MARK: - Sidebar chip (compact)
// Shown in the chat list sidebar — a small row that opens the welcome screen.
// This is iOS-specific; the web only shows the full banner in the main content area.

struct DailyInspirationBanner: View {
    let inspiration: DailyInspirationData?
    let onTap: (String) -> Void

    // Keep the old nested type as an alias so MainAppView references still compile.
    typealias DailyInspiration = DailyInspirationData

    var body: some View {
        if let inspiration {
            Button {
                onTap(inspiration.text)
            } label: {
                HStack(spacing: .spacing3) {
                    Icon("insight", size: 16)
                        .foregroundStyle(Color.buttonPrimary)
                        .accessibilityHidden(true)

                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(AppStrings.dailyInspiration)
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(Color.fontTertiary)
                        Text(inspiration.text)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }

                    Spacer()

                    Icon("back", size: 12)
                        .foregroundStyle(Color.fontTertiary)
                        .scaleEffect(x: -1, y: 1)
                        .accessibilityHidden(true)
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, .spacing4)
            .padding(.top, .spacing2)
            .accessibilityElement(children: .combine)
            .accessibleButton("Daily inspiration: \(inspiration.text)", hint: "Starts a new chat with this inspiration as the opening message")
        }
    }
}

// MARK: - Full inspiration card (welcome screen)
// Matches DailyInspirationBanner.svelte — gradient banner with orbs, mate profile,
// phrase, and CTA. Used in NewChatWelcomeView.

struct InspirationCard: View {
    let inspiration: DailyInspirationData
    let containerSize: CGSize
    var heightOverride: CGFloat? = nil
    var ctaTitle: String? = nil
    var tapHint: String? = nil
    var isInteractive = true
    var onOpenWiki: ((EmbedRecord) -> Void)? = nil
    let onTap: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var decoAppeared = false
    @State private var showMobileCard = false

    private var isCompact: Bool { containerSize.width <= 730 }

    /// Production shell supplies its measured height; standalone welcome cards
    /// retain the desktop 240pt minimum and mobile 190pt fallback.
    private var bannerHeight: CGFloat {
        if let heightOverride { return heightOverride }
        guard !isCompact else { return 190 }
        let responsiveHeight = containerSize.height * 0.35
        return max(240, responsiveHeight)
    }

    private var shouldShowSideBySideVideo: Bool {
        hasVideo && !isCompact && containerSize.width >= 520
    }

    // DailyInspirationBanner normalizes unsupported categories before looking
    // up its gradient, icon, and orb color. Task prompts use "productivity".
    private var category: String {
        let requested = inspiration.category ?? "general_knowledge"
        return CategoryMapping.isKnownCategory(requested) ? requested : "general_knowledge"
    }
    private var hasVideo: Bool { inspiration.video?.thumbnailUrl != nil || inspiration.video?.youtubeId != nil }
    private var hasWiki: Bool { inspiration.wiki != nil && (inspiration.contentType == nil || inspiration.contentType == "wiki") }
    private var hasMobileCard: Bool { hasVideo || hasWiki || inspiration.feature != nil }
    private var mobileCardTaskIdentity: String {
        [inspiration.inspirationId ?? inspiration.text,
         isCompact ? "compact" : "wide",
         hasVideo ? "video" : hasWiki ? "wiki" : inspiration.feature == nil ? "none" : "feature",
         reduceMotion ? "reduced" : "animated"].joined(separator: "\u{1F}")
    }
    private var accessibilitySummary: String {
        let prefix = "Daily inspiration: \(inspiration.text)"
        guard let feature = inspiration.feature else { return prefix }
        return [prefix, feature.title, feature.description].compactMap { $0 }.joined(separator: ", ")
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // 1. Category gradient background
            GeometryReader { geometry in
                bannerGradient(in: geometry.size)
            }
            .frame(height: bannerHeight)
            .allowsHitTesting(false)
            .accessibilityHidden(true)

            // Only decorative layers depend on the animation clock. Keep
            // the content, actions and phase task outside frame updates.
            WelcomeDecorativeClock { now in
                ZStack {
                    orbLayer(time: now)
                    decoIcons(time: now)
                }
                .frame(maxWidth: .infinity)
                .frame(height: bannerHeight)
                .clipped()
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)

            // 4. Content: label, phrase row with mate profile, CTA, and optional video
            contentLayer
                .frame(height: bannerHeight)
        }
        .task(id: mobileCardTaskIdentity) {
            // Web alternates the phrase and preview at 55% of its 20-second
            // inspiration interval, including feature-only cards. Ordinary
            // cards still switch with Reduce Motion enabled, without motion.
            guard isCompact, hasMobileCard else { return }
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(11)) }
                catch { return }
                await MainActor.run {
                    if reduceMotion {
                        showMobileCard.toggle()
                    } else {
                        withAnimation(.easeInOut(duration: 0.42)) {
                            showMobileCard.toggle()
                        }
                    }
                }
            }
        }
        .onChange(of: mobileCardTaskIdentity) { _, _ in
            showMobileCard = false
        }
        .frame(maxWidth: .infinity)
        .frame(height: bannerHeight)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .shadow(color: .black.opacity(0.15), radius: .spacing4, x: 0, y: .spacing2)
        .contentShape(Rectangle())
        .onTapGesture { if isInteractive { onTap() } }
        .disabled(!isInteractive)
        .allowsHitTesting(isInteractive)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("daily-inspiration-card")
        .accessibilityLabel(accessibilitySummary)
        .accessibilityAddTraits(isInteractive ? .isButton : [])
        .accessibilityRemoveTraits(isInteractive ? [] : .isButton)
        .accessibilityHint(isInteractive ? (tapHint ?? "Starts a new chat with this inspiration") : "")
        .accessibilityValue(showMobileCard && isCompact
            ? (inspiration.feature?.title ?? inspiration.video?.title ?? inspiration.wiki?.title ?? inspiration.text)
            : inspiration.text)
    }

    // MARK: - Content

    private var contentLayer: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            // Top label — "Daily inspiration" with book icon
            // Web: .banner-label { font-size: xxs, uppercase, white 0.85 }
            HStack(spacing: .spacing3) {
                Icon("book", size: 14)
                    .foregroundStyle(.white.opacity(0.85))
                Text(AppStrings.dailyInspiration)
                    .font(.custom("Lexend Deca", size: 12).weight(.medium))
                    .fontWeight(.medium)
                    .foregroundStyle(.white.opacity(0.85))
                    .textCase(.uppercase)
            }

            bannerContent
                .frame(maxHeight: .infinity)
        }
        // Web: .banner-inner { mobile padding: 12px 38px 10px, desktop: 14px 40px 12px }
        .padding(.horizontal, isCompact ? 38 : 40)
        .padding(.top, isCompact ? 12 : 14)
        .padding(.bottom, isCompact ? 10 : 12)
        // The web's 680px max-width is content-box; its 40px side padding
        // makes the centered outer banner-inner 760px wide.
        .frame(maxWidth: isCompact ? .infinity : 760, maxHeight: .infinity, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // Sit above orbs and deco icons
        .zIndex(2)
    }

    // CSS `linear-gradient(135deg, start, end)` crosses the actual banner
    // rectangle at 45 degrees. The shared omGradient uses 9.04/90.06% stops
    // for product tokens, so this banner builds its exact 0/100% CSS field.
    private func bannerGradient(in size: CGSize) -> LinearGradient {
        let width = max(1, size.width)
        let height = max(1, size.height)
        let startX = (width - height) / (4 * width)
        let startY = (height - width) / (4 * height)
        return LinearGradient(
            colors: [bannerStartColor, CategoryMapping.orbColor(for: category)],
            startPoint: UnitPoint(x: startX, y: startY),
            endPoint: UnitPoint(x: 1 - startX, y: 1 - startY)
        )
    }

    private var bannerStartColor: Color {
        switch category {
        case "software_development": return Color(hex: 0x155D91)
        case "business_development": return Color(hex: 0x004040)
        case "medical_health": return Color(hex: 0xFD50A0)
        case "legal_law": return Color(hex: 0x239CFF)
        case "openmates_official": return Color(hex: 0x6366F1)
        case "maker_prototyping": return Color(hex: 0xEA7600)
        case "marketing_sales": return Color(hex: 0xFF8C00)
        case "finance": return Color(hex: 0x119106)
        case "design": return Color(hex: 0x101010)
        case "electrical_engineering": return Color(hex: 0x233888)
        case "movies_tv": return Color(hex: 0x00C2C5)
        case "history": return Color(hex: 0x4989F2)
        case "science": return Color(hex: 0xCE5B06)
        case "life_coach_psychology": return Color(hex: 0xFDB250)
        case "cooking_food": return Color(hex: 0xFD8450)
        case "activism": return Color(hex: 0xF53D00)
        case "general_knowledge": return Color(hex: 0xDE1E66)
        case "onboarding_support": return Color(hex: 0x6364FF)
        default: return Color(hex: 0xDE1E66)
        }
    }

    private var bannerContent: some View {
        GeometryReader { viewport in
            // Web .banner-left and .banner-embed-wrapper each use flex:1 and
            // min-width:0. Explicit columns prevent a thumbnail's intrinsic
            // size from expanding across the phrase's layout allocation.
            let hasSideCard = !isCompact && (shouldShowSideBySideVideo || hasWiki || inspiration.feature != nil)
            let columnWidth = hasSideCard ? max(0, (viewport.size.width - 14) / 2) : viewport.size.width
            ZStack {
                HStack(alignment: .center, spacing: 14) {
                    if !isCompact || !hasMobileCard || !showMobileCard {
                        leftContent
                            .frame(width: columnWidth, height: viewport.size.height, alignment: .leading)
                            .clipped()
                            .accessibilityElement(children: .contain)
                            .transition(.opacity.combined(with: .offset(y: -6)))
                    } else {
                        // Preserve the measured row allocation during crossfade.
                        // The inactive phrase has no retained accessibility tree.
                        Color.clear
                            .frame(width: columnWidth, height: viewport.size.height)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }

                    if shouldShowSideBySideVideo {
                        videoPreviewLayer(size: CGSize(width: columnWidth, height: viewport.size.height + 27))
                            .offset(y: -1.5) // web wrapper margins: -15px top, -12px bottom
                            .frame(width: columnWidth, height: viewport.size.height, alignment: .trailing)
                    } else if !isCompact, hasWiki, let wiki = inspiration.wiki {
                        wikiPreviewLayer(wiki, size: CGSize(width: columnWidth, height: viewport.size.height + 27))
                            .offset(y: -1.5)
                            .frame(width: columnWidth, height: viewport.size.height, alignment: .trailing)
                    } else if !isCompact, let feature = inspiration.feature {
                        featurePreviewLayer(feature)
                            .frame(width: columnWidth, height: viewport.size.height)
                            .clipped()
                    }
                }
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.42), value: showMobileCard)

                if isCompact, hasMobileCard, showMobileCard {
                    ZStack {
                        if hasVideo {
                            videoPreviewLayer(size: viewport.size)
                        } else if hasWiki, let wiki = inspiration.wiki {
                            wikiPreviewLayer(wiki, size: viewport.size)
                        } else if let feature = inspiration.feature {
                            featurePreviewLayer(feature, mobile: true)
                                .frame(width: viewport.size.width, height: viewport.size.height)
                        }
                    }
                    .accessibilityElement(children: .contain)
                    .transition(.opacity.combined(with: .offset(y: 6)))
                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.42), value: showMobileCard)
                }
            }
        }
    }

    private var leftContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            phraseBlock
                .frame(maxHeight: .infinity, alignment: .center)

            // CTA: create icon + "Click to start chat"
            // Web: .banner-cta { font-size: xxs, white 0.85 }
            Button(action: onTap) {
                HStack(spacing: .spacing3) {
                    Icon(inspiration.feature == nil ? "create" : "lucide-link", size: 13)
                        .foregroundStyle(.white.opacity(0.85))
                        .accessibilityHidden(true)
                    Text(ctaTitle ?? AppStrings.dailyInspirationCTA)
                        .font(.custom("Lexend Deca", size: 12).weight(.medium))
                        .fontWeight(.medium)
                        .foregroundStyle(.white.opacity(0.85))
                }
                .fixedSize(horizontal: false, vertical: true)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("daily-inspiration-cta-text")
            .padding(.bottom, 10)
        }
    }

    private func featurePreviewLayer(_ feature: DailyInspirationFeature, mobile: Bool = false) -> some View {
        VStack(spacing: .spacing4) {
            Icon("lucide-\(feature.iconName ?? "help-circle")", size: 42)
                .foregroundStyle(.white)
                .frame(width: mobile ? 46 : 64, height: mobile ? 46 : 64)
                .accessibilityHidden(true)
            VStack(spacing: .spacing2) {
                if let title = feature.title {
                    Text(title)
                        .font(.omSmall.weight(.bold))
                        .foregroundStyle(.white.opacity(0.96))
                        .multilineTextAlignment(.center)
                }
                if !mobile, let description = feature.description {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(.white.opacity(0.81))
                        .multilineTextAlignment(.center)
                }
            }
        }
        .frame(width: mobile ? nil : 220)
        .accessibilityIdentifier("daily-inspiration-info-card")
    }

    private var phraseBlock: some View {
        HStack(alignment: .center, spacing: .spacing6) {
            // Mate profile circle — gradient + category icon + AI badge
            // Web: .mate-profile.banner-mate-profile { 44px desktop, 36px mobile }
            mateProfileCircle

            // Inspiration phrase
            // Web: .banner-phrase { font-size: p, font-weight: 600, line-clamp: 4 }
            Text(inspiration.text)
                .font((isCompact ? Font.omSmall : .omP).weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(4)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("daily-inspiration-phrase")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func wikiPreviewLayer(_ wiki: DailyInspirationWiki, size: CGSize) -> some View {
        let scale = min(1, max(0, size.width) / 300, max(0, size.height) / 200)
        return EmbedPreviewCard(embed: wiki.previewEmbed, onTap: { onOpenWiki?(wiki.previewEmbed) })
            .frame(width: 300, height: 200)
            .scaleEffect(scale)
            .frame(width: 300 * scale, height: 200 * scale)
            .accessibilityIdentifier("daily-inspiration-wiki-preview")
    }

    private func videoPreviewLayer(size: CGSize) -> some View {
        // Render the same production 300×200 preview and 61px footer as web.
        // Short banners fit the entire card, including its footer, together.
        let scale = min(1, max(0, size.width) / 300, max(0, size.height) / 200)
        return EmbedPreviewCard(embed: videoEmbed, onTap: onTap)
            .frame(width: 300, height: 200)
            .scaleEffect(scale)
            .frame(width: 300 * scale, height: 200 * scale)
            // This banner owns the preview action. Keep its hit region in the
            // final visible coordinates instead of inside the transformed
            // shared card's button and context-menu gesture hierarchy.
            .allowsHitTesting(false)
            .overlay {
                Button(action: onTap) {
                    Color.clear
                        .frame(width: 300 * scale, height: 200 * scale)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(inspiration.video?.title ?? inspiration.title ?? inspiration.text)
                .accessibilityIdentifier("daily-inspiration-video-preview")
            }
    }

    private var videoEmbed: EmbedRecord {
        var data: [String: AnyCodable] = [
            "title": AnyCodable(inspiration.video?.title ?? inspiration.title ?? inspiration.text)
        ]
        if let id = inspiration.video?.youtubeId, !id.isEmpty {
            data["url"] = AnyCodable("https://www.youtube.com/watch?v=\(id)")
        }
        if let thumbnail = inspiration.video?.thumbnailUrl, !thumbnail.isEmpty {
            data["thumbnail_url"] = AnyCodable(thumbnail)
        }
        if let channel = inspiration.video?.channelName { data["channel_name"] = AnyCodable(channel) }
        if let duration = inspiration.video?.durationSeconds { data["duration_seconds"] = AnyCodable(duration) }
        if let views = inspiration.video?.viewCount { data["view_count"] = AnyCodable(views) }
        if let published = inspiration.video?.publishedAt { data["published_at"] = AnyCodable(published) }
        return EmbedRecord(id: "inspiration-video-\(inspiration.inspirationId ?? "current")",
            type: "videos-video", status: .finished, data: .raw(data), parentEmbedId: nil,
            appId: "videos", skillId: nil, embedIds: nil, createdAt: nil)
    }

    // MARK: - Mate profile circle

    /// Gradient circle with category icon overlay + AI badge.
    /// Web: .mate-profile.{category} — 44px desktop, 36px mobile circle with
    /// category background, AI badge (white circle + sparkle).
    private var mateProfileCircle: some View {
        let size: CGFloat = isCompact ? 36 : 44
        let badgeSize: CGFloat = isCompact ? 15 : 18
        let sparkleSize: CGFloat = isCompact ? 10 : 12
        let iconName = CategoryMapping.iconName(for: category)

        return ZStack(alignment: .bottomTrailing) {
            MateProfileImage(category: category, fallbackIconName: iconName)
                .frame(width: size, height: size)
                .clipShape(Circle())
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)

            // AI badge: white circle + ai sparkle icon
            // Web: .mate-profile::after (white circle), ::before (sparkle gradient)
            ZStack {
                Circle()
                    .fill(.white)
                    .frame(width: badgeSize, height: badgeSize)

                Icon("ai", size: sparkleSize)
                    .foregroundStyle(Color(hex: 0x4867CD))
            }
            .offset(x: isCompact ? .spacing2 : .spacing2, y: isCompact ? .spacing2 : .spacing2)
        }
    }

    // MARK: - Living gradient orbs
    // Same technique as ChatBannerView.swift — three radial-gradient blobs.

    private func orbLayer(time: Double) -> some View {
        let color = CategoryMapping.orbColor(for: category)
        return GeometryReader { geo in
            ZStack {
                InspirationOrbView(color: color, size: CGSize(width: 480, height: 420),
                        opacity: 0.55, morphDuration: 11, driftDuration: 19, time: time)
                    .position(x: 140, y: 130)

                InspirationOrbView(color: color, size: CGSize(width: 460, height: 400),
                        opacity: 0.55, morphDuration: 13, driftDuration: 23, time: time + 7)
                    .position(x: geo.size.width - 110, y: geo.size.height - 80)

                InspirationOrbView(color: color, size: CGSize(width: 340, height: 300),
                        opacity: 0.38, morphDuration: 17, driftDuration: 29, time: time + 13)
                    .position(x: geo.size.width * 0.25 + 170, y: 130)
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: - Decorative icons
    // Web: .deco-icon-left / .deco-icon-right — 126px, 0.4 opacity, floating.

    private func decoIcons(time: Double) -> some View {
        let iconName = "lucide-\(CategoryMapping.lucideIconName(for: category))"
        let iconSize: CGFloat = 126

        return GeometryReader { geo in
            let floatOffset = decoAppeared ? floatY(time: time, period: 16, radius: 10) : 30

            // Left icon
            decoIcon(name: iconName, size: iconSize, rotation: -15)
                .position(
                    x: geo.size.width / 2 - 383,
                    y: geo.size.height - 48 + floatOffset
                )
                .opacity(decoAppeared ? 0.4 : 0)

            // Right icon — half-cycle offset
            decoIcon(name: iconName, size: iconSize, rotation: 15)
                .position(
                    x: geo.size.width / 2 + 383,
                    y: geo.size.height - 48 + floatY(time: time + 8, period: 16, radius: 10)
                )
                .opacity(decoAppeared ? 0.4 : 0)
        }
        .allowsHitTesting(false)
        .onAppear {
            withAnimation(.easeOut(duration: 0.6).delay(0.1)) {
                decoAppeared = true
            }
        }
    }

    private func decoIcon(name: String, size: CGFloat, rotation: Double) -> some View {
        Icon(name, size: size)
        .foregroundStyle(.white)
        .rotationEffect(.degrees(rotation))
    }

    private func floatY(time: Double, period: Double, radius: CGFloat) -> CGFloat {
        guard !reduceMotion else { return 0 }
        return sin(time * .pi * 2 / period) * radius
    }
}

private struct MateProfileImage: View {
    let category: String
    let fallbackIconName: String

    var body: some View {
        if category == "openmates_official" {
            AppIconView(appId: "openmates", size: 44)
        } else if let image = bundledMateImage {
            #if os(iOS)
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
            #elseif os(macOS)
            Image(nsImage: image)
                .resizable()
                .scaledToFill()
            #endif
        } else {
            Circle()
                .fill(CategoryMapping.gradient(for: category))
                .overlay {
                    Icon(fallbackIconName, size: 20)
                        .foregroundStyle(.white)
                }
        }
    }

    #if os(iOS)
    private var bundledMateImage: UIImage? {
        if category == "general_knowledge" {
            return UIImage(named: "mate-general-knowledge")
        }
        guard let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates") else {
            return nil
        }
        return UIImage(contentsOfFile: path)
    }
    #elseif os(macOS)
    private var bundledMateImage: NSImage? {
        if category == "general_knowledge" {
            return NSImage(named: NSImage.Name("mate-general-knowledge"))
        }
        guard let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates") else {
            return nil
        }
        return NSImage(contentsOfFile: path)
    }
    #endif
}

// MARK: - Orb View (same as ChatBannerView — duplicated because that one is private)

private struct InspirationOrbView: View {
    let color: Color
    let size: CGSize
    let opacity: Double
    let morphDuration: Double
    let driftDuration: Double
    let time: Double

    var body: some View {
        let morphX = 1.0 + 0.15 * sin(time * .pi * 2 / morphDuration)
        let morphY = 1.0 + 0.15 * cos(time * .pi * 2 / morphDuration + 0.7)
        let driftX = 30 * sin(time * .pi * 2 / driftDuration)
        let driftY = 25 * cos(time * .pi * 2 / driftDuration + 1.2)

        Ellipse()
            .fill(
                RadialGradient(
                    colors: [color, color, color.opacity(0)],
                    center: .center,
                    startRadius: 0,
                    endRadius: max(size.width, size.height) * 0.45
                )
            )
            .frame(width: size.width, height: size.height)
            .scaleEffect(x: morphX, y: morphY)
            .offset(x: driftX, y: driftY)
            .blur(radius: 28)
            .opacity(opacity)
            .allowsHitTesting(false)
    }
}
