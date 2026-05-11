// New chat suggestions — contextual conversation starters shown on empty chat state.
// Mirrors the web app's NewChatSuggestions.svelte + ChatSearchSuggestions.svelte.
// Shows app-aware suggestions and search-based quick actions.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/NewChatSuggestions.svelte
//          frontend/packages/ui/src/components/ChatSearchSuggestions.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct NewChatSuggestionsView: View {
    let onSelect: (String, String?) -> Void

    @State private var suggestions: [ChatSuggestion] = []
    @State private var isLoading = true

    struct ChatSuggestion: Identifiable, Decodable {
        let id: String
        let text: String
        let appId: String?
        let category: String?
        let icon: String?

        var parsedBody: String {
            Self.parse(text).body
        }

        var resolvedAppId: String {
            if let appId, !appId.isEmpty { return appId }
            return Self.parse(text).appId ?? "ai"
        }

        @MainActor var resolvedIconName: String {
            if let icon, !icon.isEmpty { return icon }
            return AppIconView.iconName(forAppId: resolvedAppId)
        }

        private static func parse(_ raw: String) -> (appId: String?, body: String) {
            let pattern = #"^\[([a-zA-Z0-9_-]+)(?:-[a-zA-Z0-9_-]+)?\]\s*(.+)$"#
            guard let regex = try? NSRegularExpression(pattern: pattern),
                  let match = regex.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)),
                  let appRange = Range(match.range(at: 1), in: raw),
                  let bodyRange = Range(match.range(at: 2), in: raw) else {
                return (nil, raw)
            }
            return (String(raw[appRange]), String(raw[bodyRange]).trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    var body: some View {
        if isLoading {
            ProgressView().padding()
        } else if !suggestions.isEmpty {
            GeometryReader { proxy in
                let cardWidth: CGFloat = proxy.size.width <= 730 ? 210 : 300
                let sideInset = max((proxy.size.width - cardWidth) / 2, proxy.size.width <= 730 ? 15 : 48)

                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(AppStrings.suggestionsHeader)
                        .font(.omP)
                        .foregroundStyle(Color.grey60)
                        .tracking(0.5)
                        .opacity(0.9)
                        .padding(.leading, sideInset)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: proxy.size.width <= 730 ? .spacing5 : .spacing6) {
                            ForEach(suggestions) { suggestion in
                                SuggestionChip(suggestion: suggestion, width: cardWidth) {
                                    onSelect(suggestion.parsedBody, suggestion.appId)
                                }
                            }
                        }
                        .padding(.leading, sideInset)
                        .padding(.trailing, proxy.size.width <= 730 ? 15 : 48)
                        .padding(.top, 4)
                        .padding(.bottom, proxy.size.width <= 730 ? 8 : 14)
                    }
                }
                .mask(
                    LinearGradient(
                        stops: [
                            .init(color: .clear, location: 0),
                            .init(color: .black, location: proxy.size.width <= 730 ? 0.05 : 0.035),
                            .init(color: .black, location: proxy.size.width <= 730 ? 0.95 : 0.965),
                            .init(color: .clear, location: 1)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
            }
            .frame(height: 106)
        }
    }

    func load() async {
        do {
            suggestions = try await APIClient.shared.request(
                .get, path: "/v1/chat/suggestions"
            )
        } catch {
            print("[Suggestions] Load error: \(error)")
        }
        isLoading = false
    }
}

struct SuggestionChip: View {
    let suggestion: NewChatSuggestionsView.ChatSuggestion
    var width: CGFloat = 300
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: .spacing2) {
                Icon(suggestion.resolvedIconName, size: 27)
                    .foregroundStyle(Color.fontButton)
                    .frame(width: 27, height: 27)

                Text(suggestion.parsedBody)
                    .font(.custom("Lexend Deca", size: width <= 210 ? 12 : 14).weight(.bold))
                    .foregroundStyle(Color.fontButton)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(width: width)
            .frame(minHeight: 56)
            .padding(.horizontal, width <= 210 ? .spacing6 : .spacing8)
            .padding(.vertical, width <= 210 ? .spacing5 : .spacing6)
            .background(AppIconView.gradient(forAppId: suggestion.resolvedAppId))
            .clipShape(RoundedRectangle(cornerRadius: 15))
            .shadow(color: .black.opacity(0.3), radius: 4, x: 0, y: 4)
            .contentShape(RoundedRectangle(cornerRadius: 15))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Chat search suggestions (shown while typing in search)

struct ChatSearchSuggestionsView: View {
    let query: String
    let onSelect: (String) -> Void

    @State private var results: [SearchSuggestion] = []

    struct SearchSuggestion: Identifiable {
        let id = UUID()
        let text: String
        let type: SuggestionType

        enum SuggestionType { case chat, web, app }
    }

    var body: some View {
        if !results.isEmpty {
            VStack(spacing: 0) {
                ForEach(results) { result in
                    Button {
                        onSelect(result.text)
                    } label: {
                        HStack(spacing: .spacing3) {
                            Icon(iconForType(result.type), size: 20)
                                .foregroundStyle(Color.fontTertiary)
                            Text(result.text)
                                .font(.omSmall).foregroundStyle(Color.fontPrimary)
                                .lineLimit(1)
                            Spacer()
                        }
                        .padding(.horizontal, .spacing4)
                        .padding(.vertical, .spacing3)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func iconForType(_ type: SearchSuggestion.SuggestionType) -> String {
        switch type {
        case .chat: return "chat"
        case .web: return "web"
        case .app: return "app"
        }
    }
}
