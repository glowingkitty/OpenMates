// Full-width gradient banner displayed at the top of the chat message list.
// Matches the web ChatHeader.svelte: living gradient orbs, floating decorative
// icons, shimmer loading state, category gradient loaded state, incognito state,
// and previous/next navigation arrows.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHeader.svelte
// CSS:     frontend/packages/ui/src/components/ChatHeader.svelte <style>
//          .chat-header-banner { height:35vh; min-height:240px; border-radius:0 0 14px 14px }
//          .banner-orbs .orb { radial-gradient, filter:blur(28px), opacity:0.55 }
//          .deco-icon { width:126px; opacity:0.4; decoEnter+decoFloat animation }
//          .processing-content (shimmer AI icon + text)
//          .loaded-content (icon + title + summary + time)
//          .nav-arrow (chevron left/right at edges)
// i18n:    chat.creating_new_chat, chat.header.just_now,
//          chat.header.minutes_ago, chat.header.started_today,
//          chat.header.started_yesterday, settings.incognito_mode_active
// Tokens:  GradientTokens.generated.swift, ColorTokens.generated.swift,
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import AVKit
import LucideIcons
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// MARK: - Banner State

enum ChatBannerState {
    case loading
    case loaded(title: String, appId: String, summary: String?)
    case incognito
}

// MARK: - Banner View

struct ChatBannerView: View {
    let state: ChatBannerState
    var createdAt: Date? = nil
    var isExampleChat = false
    var isIntroChat = false
    /// Silent looping teaser video URL (mp4) shown in the banner for intro/teaser chats.
    /// Web: ChatHeader.svelte videoTeaserMp4Url prop.
    var teaserVideoURL: URL? = nil
    /// Full video URL (streamed) — opened when user taps the play button on the teaser.
    var fullVideoURL: URL? = nil
    /// Explicit Lucide icon for public/example chats. Web passes `chat.icon`
    /// through `getValidIconName(icon, category)` before rendering ChatHeader.
    var iconName: String? = nil
    /// Web: `.menu-open .chat-header-banner` switches from responsive 35vh
    /// to fixed height while the settings panel is open.
    var isSettingsOpen = false
    /// Height of the active chat viewport, used to mirror CSS `height: 35vh`
    /// inside the rounded app shell instead of pinning the banner to its minimum.
    var viewportHeight: CGFloat = 0
    /// Callbacks for previous/next chat navigation arrows
    var onPrevious: (() -> Void)? = nil
    var onNext: (() -> Void)? = nil

    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shimmerPhase: CGFloat = 0
    @State private var decoAppeared = false
    /// Mobile crossfade: toggles between text (false) and video (true) every 6s.
    @State private var showVideoPhase = false
    /// Timer for the crossfade loop — must be invalidated on disappear.
    @State private var crossfadeTimer: Timer?
    /// Full video player presentation
    @State private var showFullVideo = false
    /// Actual banner width — used for responsive layout decisions instead of sizeClass alone.
    @State private var bannerWidth: CGFloat = 0

    private var isCompact: Bool { sizeClass == .compact }
    /// True when banner is narrow enough for mobile crossfade layout (matches web's max-width: 520px).
    private var useCompactTeaser: Bool { bannerWidth > 0 ? bannerWidth < 520 : isCompact }
    private let desktopMinimumBannerHeight: CGFloat = 240
    private let compactMinimumBannerHeight: CGFloat = 230
    private let responsiveBannerHeightRatio: CGFloat = 0.35

    private var minimumBannerHeight: CGFloat {
        isCompact ? compactMinimumBannerHeight : desktopMinimumBannerHeight
    }

    private var bannerHeight: CGFloat {
        if isSettingsOpen {
            return minimumBannerHeight
        }

        guard viewportHeight > 0 else {
            return minimumBannerHeight
        }

        return max(minimumBannerHeight, viewportHeight * responsiveBannerHeightRatio)
    }

    var body: some View {
        // TimelineView drives continuous animation for orbs + deco icons.
        // The .animation schedule updates every frame for smooth motion.
        TimelineView(.animation(minimumInterval: reduceMotion ? 60 : nil)) { timeline in
            let now = timeline.date.timeIntervalSinceReferenceDate
            GeometryReader { geo in
                let _ = updateBannerWidth(geo.size.width)
                ZStack {
                    // 1. Gradient background
                    gradientBackground
                        .frame(width: geo.size.width, height: bannerHeight)

                    // 2. Living gradient orbs
                    orbLayer(time: now)
                        .frame(width: geo.size.width, height: bannerHeight)
                        .clipped()

                    // 3. Decorative icons (loaded / incognito)
                    decoIcons(time: now)
                        .frame(width: geo.size.width, height: bannerHeight)
                        .clipped()

                    // 4. Center content
                    centerContent
                        .frame(width: geo.size.width, height: bannerHeight)

                    // 5. Navigation arrows
                    navArrows
                        .frame(width: geo.size.width, height: bannerHeight)
                }
                .clipShape(BottomRoundedRect(radius: 14))
                .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 4)
                // Swipe gesture: left swipe → next chat, right swipe → previous chat
                // Web: resolveHeaderSwipeNavigation — 50px threshold, abs(deltaX) > abs(deltaY) * 1.5
                .gesture(
                    DragGesture(minimumDistance: 50)
                        .onEnded { value in
                            let dx = value.translation.width
                            let dy = value.translation.height
                            guard abs(dx) > abs(dy) * 1.5 else { return }
                            if dx < 0 { onNext?() }   // swipe left → next
                            else { onPrevious?() }     // swipe right → previous
                        }
                )
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: bannerHeight)
    }

    // MARK: - Gradient Background

    @ViewBuilder
    private var gradientBackground: some View {
        switch state {
        case .incognito:
            LinearGradient.incognito
        case .loading:
            LinearGradient.primary
        case .loaded(_, let appId, _):
            CategoryMapping.isKnownCategory(appId)
                ? CategoryMapping.gradient(for: appId)
                : AppIconView.gradient(forAppId: appId)
        }
    }

    // MARK: - Living Gradient Orbs
    // Web: .banner-orbs — three radial-gradient blobs that drift and morph.
    // Uses prime-number durations so orbs never synchronize.

    private var orbColor: Color {
        switch state {
        case .incognito: return Color(hex: 0x6B6BAA)
        case .loading: return Color(hex: 0xA0BEFF)
        case .loaded(_, let appId, _):
            return CategoryMapping.isKnownCategory(appId)
                ? CategoryMapping.orbColor(for: appId)
                : orbColorForApp(appId)
        }
    }

    @ViewBuilder
    private func orbLayer(time: Double) -> some View {
        let color = orbColor
        GeometryReader { geo in
            ZStack {
                // Orb 1 — top-left, 11s morph + 19s drift
                OrbView(color: color, size: CGSize(width: min(480, geo.size.width * 0.8), height: 420),
                        opacity: 0.55, morphDuration: 11, driftDuration: 19, time: time)
                    .position(x: geo.size.width * 0.15, y: -20)

                // Orb 2 — bottom-right, 13s morph + 23s drift
                OrbView(color: color, size: CGSize(width: min(460, geo.size.width * 0.75), height: 400),
                        opacity: 0.55, morphDuration: 13, driftDuration: 23, time: time + 7)
                    .position(x: geo.size.width * 0.85, y: geo.size.height + 40)

                // Orb 3 — center, smaller, more transparent
                OrbView(color: color, size: CGSize(width: min(340, geo.size.width * 0.55), height: 300),
                        opacity: 0.38, morphDuration: 17, driftDuration: 29, time: time + 13)
                    .position(x: geo.size.width * 0.4, y: -10)
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: - Decorative Icons
    // Web: .deco-icon-left / .deco-icon-right — 126px icons at edges, 0.4 opacity,
    // with decoEnter (fade-up) + decoFloat (orbital) animation.

    @ViewBuilder
    private func decoIcons(time: Double) -> some View {
        switch state {
        case .loaded(_, let appId, _):
            GeometryReader { geo in
                let iconSize: CGFloat = isCompact ? 90 : 126
                let floatOffset = decoAppeared ? floatY(time: time, period: 16, radius: 10) : 30

                // Left icon — positioned at left edge, partially clipped
                // Web: left: calc(50% - 240px - 106px); bottom: -15px
                decoIcon(appId: appId, iconName: iconName, size: iconSize, rotation: -15)
                    .position(
                        x: geo.size.width * 0.08,
                        y: geo.size.height - 15 + floatOffset
                    )
                    .opacity(decoAppeared ? 0.4 : 0)

                // Right icon — positioned at right edge
                decoIcon(appId: appId, iconName: iconName, size: iconSize, rotation: 15)
                    .position(
                        x: geo.size.width * 0.92,
                        y: geo.size.height - 15 + floatY(time: time + 8, period: 16, radius: 10)
                    )
                    .opacity(decoAppeared ? 0.4 : 0)
            }
            .allowsHitTesting(false)
            .onAppear {
                withAnimation(.easeOut(duration: 0.6).delay(0.1)) {
                    decoAppeared = true
                }
            }

        case .incognito:
            GeometryReader { geo in
                let iconSize: CGFloat = isCompact ? 90 : 126

                incognitoDecoIcon(size: iconSize, rotation: -15)
                    .position(
                        x: geo.size.width * 0.08,
                        y: geo.size.height - 15 + (decoAppeared ? floatY(time: time, period: 16, radius: 10) : 30)
                    )
                    .opacity(decoAppeared ? 1 : 0)

                incognitoDecoIcon(size: iconSize, rotation: 15)
                    .position(
                        x: geo.size.width * 0.92,
                        y: geo.size.height - 15 + (decoAppeared ? floatY(time: time + 8, period: 16, radius: 10) : 30)
                    )
                    .opacity(decoAppeared ? 1 : 0)
            }
            .allowsHitTesting(false)
            .onAppear {
                withAnimation(.easeOut(duration: 0.6).delay(0.1)) {
                    decoAppeared = true
                }
            }

        case .loading:
            EmptyView()
        }
    }

    /// Decorative icon — raw SVG shape in white, NOT a gradient circle.
    /// Web: .deco-icon uses the Lucide/custom icon directly at 126px.
    /// Container layer controls opacity (0.4 for loaded, 1.0 for incognito).
    @ViewBuilder
    private func decoIcon(appId: String, iconName: String?, size: CGFloat, rotation: Double) -> some View {
        bannerIcon(appId: appId, iconName: iconName, size: size)
            .rotationEffect(.degrees(rotation))
    }

    @ViewBuilder
    private func incognitoDecoIcon(size: CGFloat, rotation: Double) -> some View {
        Image("anonym")
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .foregroundStyle(.white.opacity(0.15))
            .frame(width: size, height: size)
            .rotationEffect(.degrees(rotation))
    }

    /// Sinusoidal float offset driven by absolute time.
    /// `period` is full cycle in seconds, `radius` is max displacement in pt.
    private func floatY(time: Double, period: Double, radius: CGFloat) -> CGFloat {
        guard !reduceMotion else { return 0 }
        return sin(time * .pi * 2 / period) * radius
    }

    // MARK: - Center Content

    @ViewBuilder
    private var centerContent: some View {
        switch state {
        case .loading:
            loadingContent

        case .incognito:
            incognitoContent

        case .loaded(let title, let appId, let summary):
            loadedContent(title: title, appId: appId, iconName: iconName, summary: summary)
        }
    }

    // MARK: Loading (shimmer)
    // Web: .processing-content — AI icon (38px, white, shimmer) + "Creating new chat ..." text

    private var loadingContent: some View {
        VStack(spacing: .spacing6) {
            Image("ai")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: isCompact ? 32 : 38, height: isCompact ? 32 : 38)
                .foregroundStyle(.white)
                .modifier(ShimmerModifier(phase: shimmerPhase))

            Text(AppStrings.creatingNewChat)
                .font(isCompact ? .omLg : .omH3)
                .fontWeight(.semibold)
                .foregroundStyle(.white)
                .modifier(ShimmerModifier(phase: shimmerPhase))
        }
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.linear(duration: 1.8).repeatForever(autoreverses: false)) {
                shimmerPhase = 1
            }
        }
    }

    // MARK: Incognito

    private var incognitoContent: some View {
        VStack(spacing: .spacing4) {
            Image("anonym")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: isCompact ? 32 : 38, height: isCompact ? 32 : 38)
                .foregroundStyle(.white.opacity(0.9))

            Text(AppStrings.incognitoModeActive)
                .font(.omH3)
                .fontWeight(.bold)
                .foregroundStyle(.white)
        }
    }

    // MARK: Loaded

    private func loadedContent(title: String, appId: String, iconName: String?, summary: String?) -> some View {
        Group {
            if isIntroChat {
                introTeaserContent(appId: appId)
            } else {
                standardLoadedContent(title: title, appId: appId, iconName: iconName, summary: summary)
            }
        }
    }

    // MARK: Intro teaser
    // Web: ChatHeader.svelte .teaser-split-layout
    // Compact (iPhone): text and video crossfade in a loop (mobileTeaserTextCycle / mobileTeaserVideoCycle)
    // Regular (iPad/Mac): text left + video right side-by-side

    private func introTeaserContent(appId: String) -> some View {
        Group {
            if useCompactTeaser {
                mobileIntroTeaser(appId: appId)
            } else {
                desktopIntroTeaser(appId: appId)
            }
        }
        .modifier(FullVideoPresentation(url: fullVideoURL, isPresented: $showFullVideo))
    }

    // MARK: Mobile — crossfade loop between text and video
    // Web: mobileTeaserTextCycle 7s / mobileTeaserVideoCycle 7s
    // Text visible → crossfade → video visible → crossfade → text visible → ...

    private func mobileIntroTeaser(appId: String) -> some View {
        ZStack {
            // Text phase
            teaserTextColumn(appId: appId)
                .frame(maxWidth: 280, alignment: .leading)
                .opacity(showVideoPhase ? 0 : 1)
                .offset(y: showVideoPhase ? -8 : 0)

            // Video phase
            if teaserVideoURL != nil {
                teaserVideoWithPlayButton
                    .frame(maxWidth: 280)
                    .opacity(showVideoPhase ? 1 : 0)
                    .offset(y: showVideoPhase ? 0 : 8)
            }
        }
        .animation(.easeInOut(duration: 0.7), value: showVideoPhase)
        .padding(.horizontal, .spacing10)
        .padding(.vertical, .spacing6)
        .onAppear { startMobileCrossfade() }
        .onDisappear { stopMobileCrossfade() }
    }

    private func startMobileCrossfade() {
        guard teaserVideoURL != nil, !reduceMotion, crossfadeTimer == nil else { return }
        showVideoPhase = false
        crossfadeTimer = Timer.scheduledTimer(withTimeInterval: 6.0, repeats: true) { _ in
            Task { @MainActor in showVideoPhase.toggle() }
        }
    }

    private func stopMobileCrossfade() {
        crossfadeTimer?.invalidate()
        crossfadeTimer = nil
    }

    // MARK: Desktop/iPad — side-by-side split

    private func desktopIntroTeaser(appId: String) -> some View {
        HStack(alignment: .center, spacing: 36) {
            teaserTextColumn(appId: appId)
                .frame(maxWidth: .infinity, alignment: .leading)

            if teaserVideoURL != nil {
                teaserVideoWithPlayButton
                    .frame(maxWidth: 280)
            }
        }
        .frame(maxWidth: 960)
        .padding(.horizontal, .spacing12)
        .padding(.vertical, .spacing8)
    }

    /// AI icon + teaser copy lines
    private func teaserTextColumn(appId: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            bannerIcon(appId: appId, iconName: nil, size: isCompact ? 32 : 38)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(AppStrings.teaserLine1)
                    .font(isCompact ? .omLg : .omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                Text(AppStrings.teaserLine2)
                    .font(isCompact ? .omLg : .omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                Text(AppStrings.teaserLine3)
                    .font(isCompact ? .omLg : .omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
            }
        }
    }

    /// Teaser video with play button overlay.
    /// Web: .teaser-video-box + .video-play-btn (frosted glass circle with triangle)
    private var teaserVideoWithPlayButton: some View {
        ZStack {
            TeaserVideoPlayer(url: teaserVideoURL!)
                .aspectRatio(16/9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 14))
                .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 4)

            // Play button — frosted glass circle with triangle
            if fullVideoURL != nil {
                Button {
                    showFullVideo = true
                } label: {
                    ZStack {
                        Circle()
                            .fill(.ultraThinMaterial)
                            .overlay(Circle().stroke(.white.opacity(0.55), lineWidth: 2))
                            .frame(width: isCompact ? 56 : 72, height: isCompact ? 56 : 72)

                        // CSS triangle: border-left: 22px solid white
                        PlayTriangle()
                            .fill(.white.opacity(0.95))
                            .frame(width: isCompact ? 17 : 22, height: isCompact ? 20 : 26)
                            .offset(x: isCompact ? 2 : 3) // optical centering
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Standard loaded content — centered icon + title + summary

    private func standardLoadedContent(title: String, appId: String, iconName: String?, summary: String?) -> some View {
        VStack(spacing: .spacing2) {
            // Category icon (38px, white, raw shape — NOT a gradient circle)
            bannerIcon(appId: appId, iconName: iconName, size: isCompact ? 32 : 38)

            Text(title)
                .font(isCompact ? .omLg : .omH3)
                .fontWeight(.bold)
                .foregroundStyle(.white)
                .multilineTextAlignment(.center)
                .lineLimit(2)

            if isExampleChat {
                Text(AppStrings.exampleChatBadge)
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing2)
                    .background(Color.white.opacity(0.20))
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .padding(.top, .spacing1)
            }

            if let summary, !summary.isEmpty {
                Text(summary)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineSpacing(2)
                    .lineLimit(isCompact ? 2 : 3)
                    .padding(.top, .spacing1)
            }

            if let createdAt {
                Text(relativeTime(from: createdAt))
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(.white.opacity(0.85))
                    .padding(.top, .spacing1)
            }
        }
        .frame(maxWidth: isCompact ? 360 : 480)
        .padding(.horizontal, isCompact ? .spacing10 : .spacing12)
        .padding(.vertical, .spacing8)
    }

    @ViewBuilder
    private func bannerIcon(appId: String, iconName: String?, size: CGFloat) -> some View {
        if let iconName, !iconName.isEmpty {
            LucideNativeIcon(iconName, size: size)
                .foregroundStyle(.white)
        } else if CategoryMapping.isKnownCategory(appId) {
            LucideNativeIcon(CategoryMapping.lucideIconName(for: appId), size: size)
                .foregroundStyle(.white)
        } else {
            Image(AppIconView.iconName(forAppId: appId))
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .foregroundStyle(.white)
                .frame(width: size, height: size)
        }
    }

    // MARK: - Navigation Arrows
    // Web: .nav-arrow — full-height transparent hit targets at left/right edges

    @ViewBuilder
    private var navArrows: some View {
        HStack(spacing: 0) {
            if let onPrevious {
                Button(action: onPrevious) {
                    ZStack {
                        Color.clear
                        Image(systemName: SFSymbol.chevronLeft)
                            .font(.system(size: 18, weight: .medium))
                            .foregroundStyle(.white.opacity(0.85))
                    }
                }
                .buttonStyle(NavArrowButtonStyle())
                .frame(width: 40)
                .frame(maxHeight: .infinity)
            }

            Spacer()

            if let onNext {
                Button(action: onNext) {
                    ZStack {
                        Color.clear
                        Image(systemName: SFSymbol.chevronRight)
                            .font(.system(size: 18, weight: .medium))
                            .foregroundStyle(.white.opacity(0.85))
                    }
                }
                .buttonStyle(NavArrowButtonStyle())
                .frame(width: 40)
                .frame(maxHeight: .infinity)
            }
        }
    }

    // MARK: - Helpers

    /// Updates bannerWidth from GeometryReader without triggering re-render loops.
    private func updateBannerWidth(_ width: CGFloat) {
        DispatchQueue.main.async {
            if abs(bannerWidth - width) > 1 { bannerWidth = width }
        }
    }

    private func relativeTime(from date: Date) -> String {
        let diff = Date().timeIntervalSince(date)
        let minutes = Int(diff / 60)
        let timeFormatter = DateFormatter()
        timeFormatter.dateFormat = "HH:mm"
        let timeString = timeFormatter.string(from: date)

        if minutes < 1 { return AppStrings.chatHeaderJustNow }
        if minutes <= 10 { return AppStrings.chatHeaderMinutesAgo(count: minutes) }

        let calendar = Calendar.current
        if calendar.isDateInToday(date) {
            return AppStrings.chatHeaderStartedToday(time: timeString)
        }
        if calendar.isDateInYesterday(date) {
            return AppStrings.chatHeaderStartedYesterday(time: timeString)
        }

        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy/MM/dd"
        return AppStrings.chatHeaderStartedOn(date: dateFormatter.string(from: date), time: timeString)
    }

    /// Returns the orb highlight color for an app ID.
    /// Derived from GradientTokens end color (the brighter stop) for each app gradient.
    private func orbColorForApp(_ appId: String) -> Color {
        switch appId {
        case "openmates": return Color(hex: 0x9B6DFF)
        case "ai": return Color(hex: 0xE8956E)
        case "web": return Color(hex: 0xFF763B)
        case "code": return Color(hex: 0x42ABF4)
        case "travel": return Color(hex: 0x13DAF5)
        case "news": return Color(hex: 0xF95A6E)
        case "legal": return Color(hex: 0x005BA5)
        case "events": return Color(hex: 0xE61B3E)
        case "health": return Color(hex: 0xF42C2D)
        case "finance": return Color(hex: 0x2CB81E)
        case "music": return Color(hex: 0xC94458)
        case "maps": return Color(hex: 0x3EAB61)
        case "shopping": return Color(hex: 0xAE6301)
        case "photos", "images": return Color(hex: 0x1A5A8F)
        case "videos": return Color(hex: 0xF44A3C)
        default: return Color(hex: 0xA0BEFF)
        }
    }
}

// MARK: - Orb View
// Web: .orb — radial-gradient blob with blur, animated morph + drift.
// Driven by absolute time (via TimelineView) instead of SwiftUI withAnimation,
// ensuring continuous smooth motion of the computed sin/cos transforms.

private struct OrbView: View {
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

// MARK: - Shimmer Modifier
// Web: headerShimmer keyframes — left-to-right gradient sweep on AI icon + text.

private struct ShimmerModifier: ViewModifier {
    let phase: CGFloat

    func body(content: Content) -> some View {
        content
            .overlay(
                GeometryReader { geo in
                    let width = geo.size.width * 3
                    LinearGradient(
                        stops: [
                            .init(color: .clear, location: 0),
                            .init(color: .white.opacity(0.4), location: 0.35),
                            .init(color: .white.opacity(0.6), location: 0.5),
                            .init(color: .white.opacity(0.4), location: 0.65),
                            .init(color: .clear, location: 1),
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: width)
                    .offset(x: -width + (width * 2 * phase))
                }
                .clipped()
                .blendMode(.sourceAtop)
            )
    }
}

// MARK: - Nav Arrow Button Style
// Web: .nav-arrow:hover { background: rgba(255,255,255,0.1) }
// .nav-arrow:active { background: rgba(0,0,0,0.18) }

private struct NavArrowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(
                configuration.isPressed
                    ? Color.black.opacity(0.18)
                    : Color.white.opacity(0.001)
            )
            .contentShape(Rectangle())
    }
}

// MARK: - Bottom Rounded Rectangle
// Web: border-radius: 0 0 14px 14px — top flush, bottom corners rounded.

private struct BottomRoundedRect: Shape {
    let radius: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let r = min(radius, min(rect.width, rect.height) / 2)
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - r, y: rect.maxY),
            control: CGPoint(x: rect.maxX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX + r, y: rect.maxY))
        path.addQuadCurve(
            to: CGPoint(x: rect.minX, y: rect.maxY - r),
            control: CGPoint(x: rect.minX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
        path.closeSubpath()
        return path
    }
}

// MARK: - Teaser Video Player
// Silent looping AVPlayer for the bundled intro teaser clip.
// Web: .teaser-video-preview { autoplay, muted, loop, playsinline }

private struct TeaserVideoPlayer {
    let url: URL
}

#if os(iOS)
extension TeaserVideoPlayer: UIViewRepresentable {
    func makeUIView(context: Context) -> TeaserPlayerUIView {
        TeaserPlayerUIView(url: url)
    }

    func updateUIView(_ uiView: TeaserPlayerUIView, context: Context) {}
}

private class TeaserPlayerUIView: UIView {
    private var player: AVPlayer?
    private var playerLayer: AVPlayerLayer?
    private var loopObserver: Any?

    init(url: URL) {
        super.init(frame: .zero)
        backgroundColor = .clear

        let player = AVPlayer(url: url)
        player.isMuted = true
        player.preventsDisplaySleepDuringVideoPlayback = false

        let layer = AVPlayerLayer(player: player)
        layer.videoGravity = .resizeAspectFill
        self.layer.addSublayer(layer)

        self.player = player
        self.playerLayer = layer

        // Loop: restart when reaching end
        loopObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: player.currentItem,
            queue: .main
        ) { [weak player] _ in
            player?.seek(to: .zero)
            player?.play()
        }

        player.play()
    }

    required init?(coder: NSCoder) { fatalError() }

    override func layoutSubviews() {
        super.layoutSubviews()
        playerLayer?.frame = bounds
    }

    override func removeFromSuperview() {
        if let obs = loopObserver {
            NotificationCenter.default.removeObserver(obs)
            loopObserver = nil
        }
        player?.pause()
        player = nil
        super.removeFromSuperview()
    }
}
#elseif os(macOS)
extension TeaserVideoPlayer: NSViewRepresentable {
    func makeNSView(context: Context) -> TeaserPlayerNSView {
        TeaserPlayerNSView(url: url)
    }

    func updateNSView(_ nsView: TeaserPlayerNSView, context: Context) {}

    static func dismantleNSView(_ nsView: TeaserPlayerNSView, coordinator: ()) {
        nsView.cleanupPlayer()
    }
}

private class TeaserPlayerNSView: NSView {
    private var player: AVPlayer?
    private var playerLayer: AVPlayerLayer?
    private var loopObserver: Any?
    private var hasCleanedUp = false

    init(url: URL) {
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor

        let player = AVPlayer(url: url)
        player.isMuted = true
        player.preventsDisplaySleepDuringVideoPlayback = false

        let playerLayer = AVPlayerLayer(player: player)
        playerLayer.videoGravity = .resizeAspectFill
        layer?.addSublayer(playerLayer)

        self.player = player
        self.playerLayer = playerLayer

        loopObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: player.currentItem,
            queue: .main
        ) { [weak player] _ in
            player?.seek(to: .zero)
            player?.play()
        }

        player.play()
    }

    required init?(coder: NSCoder) { fatalError() }

    override func layout() {
        super.layout()
        playerLayer?.frame = bounds
    }

    func cleanupPlayer() {
        guard !hasCleanedUp else { return }
        hasCleanedUp = true

        if let loopObserver {
            NotificationCenter.default.removeObserver(loopObserver)
            self.loopObserver = nil
        }

        player?.pause()
        playerLayer?.player = nil
        playerLayer?.removeFromSuperlayer()
        player?.replaceCurrentItem(with: nil)
        playerLayer = nil
        player = nil
    }
}
#endif

// MARK: - Play Triangle
// Web: .video-play-icon { border-left: 22px solid white } — CSS border triangle

private struct PlayTriangle: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

// MARK: - Full Video Player
// Streams the full video from api.video when the user taps the play button.
// Web: mounts a <video> element and calls requestFullscreen().

private struct FullVideoPresentation: ViewModifier {
    let url: URL?
    @Binding var isPresented: Bool

    func body(content: Content) -> some View {
        #if os(iOS)
        content
            .fullScreenCover(isPresented: $isPresented) {
                if let url {
                    FullVideoPlayerView(url: url, isPresented: $isPresented)
                }
            }
        #elseif os(macOS)
        content
            .background {
                if let url {
                    FullVideoWindowPresenter(url: url, isPresented: $isPresented)
                        .frame(width: 0, height: 0)
                }
            }
        #endif
    }
}

#if os(macOS)
private struct FullVideoWindowPresenter: NSViewRepresentable {
    let url: URL
    @Binding var isPresented: Bool

    func makeNSView(context: Context) -> NSView {
        NSView(frame: .zero)
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        if isPresented {
            FullVideoWindowController.shared.present(url: url, isPresented: $isPresented)
        } else {
            FullVideoWindowController.shared.dismiss()
        }
    }
}

@MainActor
private final class FullVideoWindowController: NSObject, NSWindowDelegate {
    static let shared = FullVideoWindowController()

    private var window: NSWindow?
    private var playerView: MacFullVideoPlayerView?
    private var isPresented: Binding<Bool>?
    private var isDismissing = false

    func present(url: URL, isPresented: Binding<Bool>) {
        self.isPresented = isPresented

        let window = window ?? makeWindow()
        self.window = window

        if playerView?.url != url || playerView?.isStopped == true {
            playerView?.stop()
            let playerView = MacFullVideoPlayerView(url: url) { [weak self] in
                self?.dismiss()
            }
            window.contentView = playerView
            window.makeFirstResponder(playerView)
            self.playerView = playerView
        }

        isDismissing = false
        window.makeKeyAndOrderFront(nil)
        playerView?.play()

        if !window.styleMask.contains(.fullScreen) {
            window.toggleFullScreen(nil)
        }
    }

    func dismiss() {
        guard let window, !isDismissing else { return }
        isDismissing = true
        playerView?.stop()

        if window.styleMask.contains(.fullScreen) {
            window.toggleFullScreen(nil)
        } else {
            finishDismiss()
        }
    }

    func windowDidExitFullScreen(_ notification: Notification) {
        finishDismiss()
    }

    func windowWillClose(_ notification: Notification) {
        playerView?.stop()
        isPresented?.wrappedValue = false
    }

    private func makeWindow() -> NSWindow {
        let screenFrame = NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 1280, height: 720)
        let window = NSWindow(
            contentRect: screenFrame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.backgroundColor = .black
        window.collectionBehavior = [.fullScreenPrimary]
        window.isReleasedWhenClosed = false
        window.isRestorable = false
        window.delegate = self
        return window
    }

    private func finishDismiss() {
        guard isDismissing else { return }
        window?.orderOut(nil)
        isDismissing = false
        isPresented?.wrappedValue = false
    }
}

private final class MacFullVideoPlayerView: NSView {
    let url: URL

    private let player: AVPlayer
    private let playerView = AVPlayerView()
    private let closeButton = NSButton()
    private let onClose: () -> Void
    private var hasStopped = false
    var isStopped: Bool { hasStopped }

    init(url: URL, onClose: @escaping () -> Void) {
        self.url = url
        self.player = AVPlayer(url: url)
        self.onClose = onClose

        super.init(frame: .zero)
        setupView()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var acceptsFirstResponder: Bool { true }

    func play() {
        guard !hasStopped else { return }
        player.play()
    }

    func stop() {
        guard !hasStopped else { return }
        hasStopped = true
        player.pause()
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 {
            close()
        } else {
            super.keyDown(with: event)
        }
    }

    private func setupView() {
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor

        playerView.player = player
        playerView.controlsStyle = .floating
        playerView.videoGravity = .resizeAspect
        playerView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(playerView)

        closeButton.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: AppStrings.close)
        closeButton.imagePosition = .imageOnly
        closeButton.isBordered = false
        closeButton.wantsLayer = true
        closeButton.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.45).cgColor
        closeButton.layer?.cornerRadius = 18
        closeButton.contentTintColor = .white
        closeButton.target = self
        closeButton.action = #selector(closeButtonPressed)
        closeButton.translatesAutoresizingMaskIntoConstraints = false
        closeButton.setAccessibilityLabel(AppStrings.close)
        addSubview(closeButton)

        NSLayoutConstraint.activate([
            playerView.leadingAnchor.constraint(equalTo: leadingAnchor),
            playerView.trailingAnchor.constraint(equalTo: trailingAnchor),
            playerView.topAnchor.constraint(equalTo: topAnchor),
            playerView.bottomAnchor.constraint(equalTo: bottomAnchor),

            closeButton.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            closeButton.topAnchor.constraint(equalTo: topAnchor, constant: 54),
            closeButton.widthAnchor.constraint(equalToConstant: 36),
            closeButton.heightAnchor.constraint(equalToConstant: 36)
        ])
    }

    @objc private func closeButtonPressed() {
        close()
    }

    private func close() {
        onClose()
    }
}
#endif

private struct FullVideoPlayerView: View {
    let url: URL
    @Binding var isPresented: Bool
    @StateObject private var playerHolder = FullVideoPlayerHolder()

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black.ignoresSafeArea()

            VideoPlayer(player: playerHolder.player)
                .ignoresSafeArea()

            Button {
                playerHolder.player?.pause()
                isPresented = false
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(.ultraThinMaterial)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .padding(.top, 54)
            .padding(.leading, 16)
        }
        .onAppear {
            playerHolder.play(url: url)
        }
        .onDisappear {
            playerHolder.player?.pause()
        }
    }
}

@MainActor
private class FullVideoPlayerHolder: ObservableObject {
    @Published var player: AVPlayer?

    func play(url: URL) {
        guard player == nil else { return }
        let p = AVPlayer(url: url)
        player = p
        p.play()
    }
}
