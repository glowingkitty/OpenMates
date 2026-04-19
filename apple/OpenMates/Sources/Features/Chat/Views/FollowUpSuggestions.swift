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

    var body: some View {
        if !suggestions.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(suggestions, id: \.self) { suggestion in
                        Button {
                            onSelect(suggestion)
                        } label: {
                            Text(suggestion)
                                .font(.omSmall)
                                .fontWeight(.medium)
                                .foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing6)
                                .padding(.vertical, .spacing3)
                                .background(Color.grey10)
                                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                                .overlay(
                                    RoundedRectangle(cornerRadius: .radiusFull)
                                        .stroke(Color.grey30, lineWidth: 1)
                                )
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, .spacing4)
            }
            .padding(.vertical, .spacing2)
        }
    }
}
