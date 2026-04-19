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
    }

    var body: some View {
        if isLoading {
            ProgressView().padding()
        } else if !suggestions.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(suggestions) { suggestion in
                        SuggestionChip(suggestion: suggestion) {
                            onSelect(suggestion.text, suggestion.appId)
                        }
                    }
                }
                .padding(.horizontal, .spacing4)
            }
            .padding(.vertical, .spacing3)
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
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: .spacing2) {
                if let appId = suggestion.appId {
                    AppIconView(appId: appId, size: 16)
                }
                Text(suggestion.text)
                    .font(.omXs)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
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
                            Image(systemName: iconForType(result.type))
                                .foregroundStyle(Color.fontTertiary)
                                .frame(width: 20)
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
        case .chat: return "message"
        case .web: return "globe"
        case .app: return "square.grid.2x2"
        }
    }
}
