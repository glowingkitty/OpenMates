// Follow-up suggestion chips — AI-generated suggestions shown after responses.
// Tapping a chip fills the message input with the suggestion text.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/FollowUpSuggestions.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
//          .follow-up-suggestions-wrapper (padding, alignment with assistant messages)
// Note:    Web renders a full gradient banner card with animated orbs and
//          pagination. The Swift version is simplified to horizontal pill chips
//          appropriate for compact mobile layout.
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct FollowUpSuggestions: View {
    let suggestions: [String]
    var category: String?
    var icon: String?
    let onSelect: (String) -> Void
    @State private var page = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var parsedSuggestions: [ParsedSuggestion] {
        suggestions.map(ParsedSuggestion.init(raw:))
    }

    private var currentSuggestions: [ParsedSuggestion] {
        let start = min(page * 3, max(parsedSuggestions.count - 1, 0))
        return Array(parsedSuggestions.dropFirst(start).prefix(3))
    }

    private var hasMultiplePages: Bool {
        parsedSuggestions.count > 3
    }

    var body: some View {
        if !suggestions.isEmpty {
            GeometryReader { geo in
                let isMobile = geo.size.width <= 730
                let cardHeight: CGFloat = isMobile ? 195 : 170

                VStack(spacing: .spacing4) {
                    VStack(spacing: 2) {
                        Text(AppStrings.suggestionsExploreNext)
                            .font(.custom("Lexend Deca", size: 16).weight(.bold))
                            .foregroundStyle(Color.grey70)
                            .multilineTextAlignment(.center)

                        Text(AppStrings.suggestionsHeader)
                            .font(.custom("Lexend Deca", size: 14).weight(.medium))
                            .foregroundStyle(Color.grey70)
                            .multilineTextAlignment(.center)
                    }
                    .padding(.horizontal, isMobile ? 15 : 18)

                    ZStack {
                        FollowUpGradientBackground(
                            category: category,
                            icon: icon,
                            height: cardHeight,
                            reduceMotion: reduceMotion
                        )
                        .clipShape(RoundedRectangle(cornerRadius: .radius6))
                        .shadow(color: .black.opacity(0.18), radius: 16, x: 0, y: 4)

                        HStack(spacing: 0) {
                            if hasMultiplePages {
                                pageButton(icon: "chevron-left", height: cardHeight) {
                                    withAnimation(.easeInOut(duration: 0.2)) {
                                        page = max(page - 1, 0)
                                    }
                                }
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(currentSuggestions) { suggestion in
                                    Button {
                                        onSelect(suggestion.body)
                                    } label: {
                                        HStack(alignment: .center, spacing: 8) {
                                            suggestionIcon(suggestion)

                                            Text(suggestion.body)
                                                .font(.custom("Lexend Deca", size: isMobile ? 15 : 16).weight(.semibold))
                                                .foregroundStyle(Color.fontButton)
                                                .lineLimit(2)
                                                .multilineTextAlignment(.leading)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                        }
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding(.vertical, isMobile ? 4 : 6)
                                        .padding(.horizontal, isMobile ? 6 : 8)
                                        .contentShape(RoundedRectangle(cornerRadius: .radius3))
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                            .frame(maxWidth: 700)
                            .padding(.vertical, isMobile ? 12 : 16)
                            .padding(.horizontal, .spacing4)

                            if hasMultiplePages {
                                pageButton(icon: "chevron-right", height: cardHeight) {
                                    withAnimation(.easeInOut(duration: 0.2)) {
                                        let maxPage = max(Int(ceil(Double(parsedSuggestions.count) / 3.0)) - 1, 0)
                                        page = min(page + 1, maxPage)
                                    }
                                }
                            }
                        }
                    }
                    .frame(height: cardHeight)
                    .clipShape(RoundedRectangle(cornerRadius: .radius6))
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing4)
                .frame(maxWidth: 700)
                .frame(maxWidth: .infinity)
            }
            .frame(height: 255)
        }
    }

    private func pageButton(icon: String, height: CGFloat, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            LucideNativeIcon(icon, size: 26)
                .foregroundStyle(Color.fontButton)
                .frame(width: 36, height: height)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(0.9)
    }

    @ViewBuilder
    private func suggestionIcon(_ suggestion: ParsedSuggestion) -> some View {
        if suggestion.iconName == "back" {
            Icon("back", size: 18)
                .foregroundStyle(Color.fontButton.opacity(0.9))
                .scaleEffect(x: -1, y: 1)
                .frame(width: 18, height: 18)
        } else {
            Icon(suggestion.iconName, size: 18)
                .foregroundStyle(Color.fontButton.opacity(0.9))
                .frame(width: 18, height: 18)
        }
    }
}

private struct FollowUpGradientBackground: View {
    let category: String?
    let icon: String?
    let height: CGFloat
    let reduceMotion: Bool

    private var resolvedCategory: String {
        category ?? "openmates_official"
    }

    private var resolvedIcon: String {
        if let icon, !icon.isEmpty {
            return icon
        }
        return CategoryMapping.lucideIconName(for: resolvedCategory)
    }

    var body: some View {
        TimelineView(.animation) { timeline in
            let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate

            GeometryReader { geo in
                ZStack {
                    CategoryMapping.gradient(for: resolvedCategory)

                    orb(size: CGSize(width: 320, height: 280), opacity: 0.55, time: time, morph: 11, drift: 19)
                        .position(x: -20, y: 20)
                    orb(size: CGSize(width: 300, height: 260), opacity: 0.55, time: time + 8, morph: 13, drift: 23)
                        .position(x: geo.size.width + 20, y: geo.size.height + 10)
                    orb(size: CGSize(width: 240, height: 200), opacity: 0.38, time: time + 15, morph: 17, drift: 29)
                        .position(x: geo.size.width * 0.42, y: 40)

                    decoIcon(size: height > 170 ? 64 : 90, rotation: -15, time: time)
                        .position(x: height > 170 ? 18 : 25, y: geo.size.height / 2)
                    decoIcon(size: height > 170 ? 64 : 90, rotation: 15, time: time + 8)
                        .position(x: geo.size.width - (height > 170 ? 18 : 25), y: geo.size.height / 2)
                }
            }
        }
    }

    private func orb(size: CGSize, opacity: Double, time: Double, morph: Double, drift: Double) -> some View {
        let color = CategoryMapping.orbColor(for: resolvedCategory)
        let morphX = 1.0 + 0.15 * sin(time * .pi * 2 / morph)
        let morphY = 1.0 + 0.15 * cos(time * .pi * 2 / morph + 0.7)
        let driftX = 18 * sin(time * .pi * 2 / drift)
        let driftY = 15 * cos(time * .pi * 2 / drift + 1.2)

        return Ellipse()
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
    }

    private func decoIcon(size: CGFloat, rotation: Double, time: Double) -> some View {
        LucideNativeIcon(resolvedIcon, size: size)
            .foregroundStyle(Color.fontButton.opacity(0.3))
            .rotationEffect(.degrees(rotation))
            .offset(
                x: reduceMotion ? 0 : 6 * cos(time * .pi * 2 / 16),
                y: reduceMotion ? 0 : 8 * sin(time * .pi * 2 / 16)
            )
    }
}

private struct ParsedSuggestion: Identifiable {
    let id: String
    let raw: String
    let appId: String?
    let body: String

    init(raw: String) {
        self.raw = raw
        self.id = raw

        let pattern = #"^\[([a-zA-Z0-9_-]+)(?:-[a-zA-Z0-9_-]+)?\]\s*(.+)$"#
        if let regex = try? NSRegularExpression(pattern: pattern),
           let match = regex.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)),
           let appRange = Range(match.range(at: 1), in: raw),
           let bodyRange = Range(match.range(at: 2), in: raw) {
            appId = String(raw[appRange])
            body = String(raw[bodyRange])
        } else {
            appId = nil
            body = raw
        }
    }

    var iconName: String {
        switch appId {
        case nil:
            return "back"
        case "audio", "recording":
            return "mic"
        case "code":
            return "code"
        case "events", "event":
            return "calendar"
        case "images", "image":
            return "image"
        case "maps", "map":
            return "map"
        case "videos", "video":
            return "video"
        case "web", "search":
            return "search"
        default:
            return AppIconView.iconName(forAppId: appId ?? "ai")
        }
    }
}
