// Daily inspiration banner — gradient card shown on the new chat welcome screen.
// Displays a category-specific gradient background with living orbs, mate profile
// circle, inspiration phrase, and "Click to start chat" CTA.
// Matches the web DailyInspirationBanner.svelte layout and visual treatment.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/DailyInspirationBanner.svelte
// CSS:     DailyInspirationBanner.svelte <style>
//          Banner height: 240px desktop, 190px mobile (≤730px)
//          Background: getCategoryGradientColors per inspiration category
//          Layout: label top-left, mate profile + phrase row, CTA bottom-left
//          Decorative category icons at edges, living gradient orbs
// JS:      frontend/packages/ui/src/utils/categoryUtils.ts
//          getCategoryGradientColors, CATEGORY_GRADIENTS, CATEGORY_FALLBACK_ICONS
// i18n:    daily_inspiration.label, daily_inspiration.click_to_start_chat
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
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

    init(
        inspirationId: String? = nil,
        text: String,
        title: String? = nil,
        category: String? = nil,
        iconName: String? = nil,
        video: DailyInspirationVideo? = nil,
        startedChatId: String? = nil
    ) {
        self.inspirationId = inspirationId
        self.text = text
        self.title = title
        self.category = category
        self.iconName = iconName
        self.video = video
        self.startedChatId = startedChatId
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
    let onTap: () -> Void

    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var decoAppeared = false
    @State private var showMobileVideo = false

    private var isCompact: Bool { sizeClass == .compact }
    /// Web mobile screenshot parity: fixed minimum card height.
    private let bannerHeight: CGFloat = 240

    private var category: String { inspiration.category ?? "general_knowledge" }
    private var hasVideo: Bool { inspiration.video?.thumbnailUrl != nil || inspiration.video?.youtubeId != nil }

    var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 60 : nil)) { timeline in
            let now = timeline.date.timeIntervalSinceReferenceDate
            ZStack(alignment: .topLeading) {
                // 1. Category gradient background
                CategoryMapping.gradient(for: category)
                    .frame(maxWidth: .infinity)
                    .frame(height: bannerHeight)

                // 2. Living gradient orbs
                orbLayer(time: now)
                    .frame(maxWidth: .infinity)
                    .frame(height: bannerHeight)
                    .clipped()

                // 3. Decorative category icons at edges
                decoIcons(time: now)
                    .frame(maxWidth: .infinity)
                    .frame(height: bannerHeight)
                    .clipped()

                // 4. Content: label, phrase row with mate profile, CTA, and optional video
                contentLayer
            }
            .task(id: inspiration.inspirationId ?? inspiration.text) {
                guard isCompact, hasVideo, !reduceMotion else { return }
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(5))
                    if !Task.isCancelled {
                        await MainActor.run {
                            withAnimation(.easeInOut(duration: 0.42)) {
                                showMobileVideo.toggle()
                            }
                        }
                    }
                }
            }
            .onChange(of: inspiration.inspirationId ?? inspiration.text) { _, _ in
                showMobileVideo = false
            }
            .frame(maxWidth: .infinity)
            .frame(height: bannerHeight)
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
            .shadow(color: .black.opacity(0.15), radius: .spacing4, x: 0, y: .spacing2)
            .contentShape(Rectangle())
            .onTapGesture(perform: onTap)
        }
        .accessibilityElement(children: .combine)
        .accessibleButton(
            "Daily inspiration: \(inspiration.text)",
            hint: "Starts a new chat with this inspiration"
        )
    }

    // MARK: - Content

    private var contentLayer: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            // Top label — "Daily inspiration" with book icon
            // Web: .banner-label { font-size: xxs, uppercase, white 0.85 }
            HStack(spacing: .spacing2) {
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        // Sit above orbs and deco icons
        .zIndex(2)
    }

    private var bannerContent: some View {
        ZStack {
            HStack(alignment: .center, spacing: 14) {
                leftContent
                    .opacity(isCompact && hasVideo && showMobileVideo ? 0 : 1)
                    .offset(y: isCompact && hasVideo && showMobileVideo ? -6 : 0)

                if !isCompact, hasVideo {
                    videoPreviewLayer
                        .frame(maxWidth: 220, maxHeight: .infinity)
                }
            }
            .animation(.easeInOut(duration: 0.42), value: showMobileVideo)

            if isCompact, hasVideo {
                videoPreviewLayer
                    .frame(maxWidth: 220, maxHeight: .infinity)
                    .opacity(showMobileVideo ? 1 : 0)
                    .offset(y: showMobileVideo ? 0 : 6)
                    .animation(.easeInOut(duration: 0.42), value: showMobileVideo)
            }
        }
    }

    private var leftContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            phraseBlock
                .frame(maxHeight: .infinity, alignment: .center)

            // CTA: create icon + "Click to start chat"
            // Web: .banner-cta { font-size: xxs, white 0.85 }
            HStack(spacing: .spacing2) {
                Icon("create", size: 13)
                    .foregroundStyle(.white.opacity(0.85))
                Text(AppStrings.dailyInspirationCTA)
                    .font(.custom("Lexend Deca", size: 12).weight(.medium))
                    .fontWeight(.medium)
                    .foregroundStyle(.white.opacity(0.85))
            }
            .padding(.bottom, 10)
        }
    }

    private var phraseBlock: some View {
        HStack(alignment: .center, spacing: .spacing6) {
            // Mate profile circle — gradient + category icon + AI badge
            // Web: .mate-profile.banner-mate-profile { 44px desktop, 36px mobile }
            mateProfileCircle

            // Inspiration phrase
            // Web: .banner-phrase { font-size: p, font-weight: 600, line-clamp: 4 }
            Text(inspiration.text)
                .font(.custom("Lexend Deca", size: 16).weight(.semibold))
                .fontWeight(.semibold)
                .foregroundStyle(.white)
                .lineLimit(4)
                .multilineTextAlignment(.leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var videoPreviewLayer: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: .radius6)
                .fill(.black.opacity(0.28))

            if let thumbnailUrl = inspiration.video?.thumbnailUrl,
               let url = URL(string: thumbnailUrl) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                    default:
                        AppIconView(appId: "videos", size: 54)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipped()
            } else {
                AppIconView(appId: "videos", size: 54)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

            LinearGradient(
                colors: [.black.opacity(0), .black.opacity(0.72)],
                startPoint: .top,
                endPoint: .bottom
            )

            HStack(spacing: .spacing3) {
                ZStack {
                    Circle()
                        .fill(Color(hex: 0xEF2F2A))
                        .frame(width: 46, height: 46)
                    Icon("play", size: 20)
                        .foregroundStyle(.white)
                }

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(inspiration.video?.title ?? inspiration.title ?? inspiration.text)
                        .font(.omSmall)
                        .fontWeight(.bold)
                        .foregroundStyle(.white)
                        .lineLimit(2)
                    if let channel = inspiration.video?.channelName {
                        Text(channel)
                            .font(.omXs)
                            .fontWeight(.medium)
                            .foregroundStyle(.white.opacity(0.72))
                            .lineLimit(1)
                    }
                }
            }
            .padding(.spacing4)
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .frame(maxHeight: .infinity)
        .accessibilityLabel(inspiration.video?.title ?? inspiration.text)
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

                Image("ai")
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFit()
                    .frame(width: sparkleSize, height: sparkleSize)
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
                InspirationOrbView(color: color, size: CGSize(width: min(480, geo.size.width * 0.8), height: 420),
                        opacity: 0.55, morphDuration: 11, driftDuration: 19, time: time)
                    .position(x: geo.size.width * 0.15, y: -20)

                InspirationOrbView(color: color, size: CGSize(width: min(460, geo.size.width * 0.75), height: 400),
                        opacity: 0.55, morphDuration: 13, driftDuration: 23, time: time + 7)
                    .position(x: geo.size.width * 0.85, y: geo.size.height + 40)

                InspirationOrbView(color: color, size: CGSize(width: min(340, geo.size.width * 0.55), height: 300),
                        opacity: 0.38, morphDuration: 17, driftDuration: 29, time: time + 13)
                    .position(x: geo.size.width * 0.4, y: -10)
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: - Decorative icons
    // Web: .deco-icon-left / .deco-icon-right — 126px, 0.4 opacity, floating.

    private func decoIcons(time: Double) -> some View {
        let iconName = CategoryMapping.iconName(for: category)
        let iconSize: CGFloat = isCompact ? 90 : 126

        return GeometryReader { geo in
            let floatOffset = decoAppeared ? floatY(time: time, period: 16, radius: 10) : 30

            // Left icon
            decoIcon(name: iconName, size: iconSize, rotation: -15)
                .position(
                    x: geo.size.width * 0.08,
                    y: geo.size.height - 15 + floatOffset
                )
                .opacity(decoAppeared ? 0.4 : 0)

            // Right icon — half-cycle offset
            decoIcon(name: iconName, size: iconSize, rotation: 15)
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
    }

    private func decoIcon(name: String, size: CGFloat, rotation: Double) -> some View {
        Image(name)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .foregroundStyle(.white)
            .frame(width: size, height: size)
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
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
        } else {
            Circle()
                .fill(CategoryMapping.gradient(for: category))
                .overlay {
                    Icon(fallbackIconName, size: 20)
                        .foregroundStyle(.white)
                }
        }
    }

    private var bundledMateImage: UIImage? {
        guard let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates") else {
            return nil
        }
        return UIImage(contentsOfFile: path)
    }
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
