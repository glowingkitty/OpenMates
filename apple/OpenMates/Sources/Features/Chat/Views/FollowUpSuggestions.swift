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
    let onSelect: (String) -> Void
    @State private var page = 0

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
            VStack(spacing: .spacing4) {
                VStack(spacing: .spacing1) {
                    Text(AppStrings.suggestionsExploreNext)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey70)
                        .multilineTextAlignment(.center)

                    Text(AppStrings.suggestionsHeader)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                        .multilineTextAlignment(.center)
                }
                .padding(.horizontal, .spacing6)

                ZStack {
                    RoundedRectangle(cornerRadius: .radius6)
                        .fill(LinearGradient.appCode)
                        .shadow(color: .black.opacity(0.18), radius: 16, x: 0, y: 4)

                    HStack(spacing: 0) {
                        if hasMultiplePages {
                            pageButton(icon: "chevron-left") {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    page = max(page - 1, 0)
                                }
                            }
                        }

                        VStack(alignment: .leading, spacing: .spacing3) {
                            ForEach(currentSuggestions) { suggestion in
                                Button {
                                    onSelect(suggestion.body)
                                } label: {
                                    HStack(alignment: .top, spacing: .spacing4) {
                                        Icon(suggestion.iconName, size: 20)
                                            .foregroundStyle(Color.fontButton)
                                            .frame(width: 22, height: 22)

                                        Text(suggestion.body)
                                            .font(.omP)
                                            .fontWeight(.bold)
                                            .foregroundStyle(Color.fontButton)
                                            .lineLimit(2)
                                            .multilineTextAlignment(.leading)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.vertical, .spacing2)
                                    .padding(.horizontal, .spacing3)
                                    .contentShape(RoundedRectangle(cornerRadius: .radius3))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, .spacing6)
                        .padding(.horizontal, .spacing4)

                        if hasMultiplePages {
                            pageButton(icon: "chevron-right") {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    let maxPage = max(Int(ceil(Double(parsedSuggestions.count) / 3.0)) - 1, 0)
                                    page = min(page + 1, maxPage)
                                }
                            }
                        }
                    }
                }
                .frame(height: 170)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing4)
            .frame(maxWidth: 700)
            .frame(maxWidth: .infinity)
        }
    }

    private func pageButton(icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            LucideNativeIcon(icon, size: 26)
                .foregroundStyle(Color.fontButton)
                .frame(width: 36, height: 170)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(0.9)
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
        switch appId ?? "web" {
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
            return appId ?? "search"
        }
    }
}
