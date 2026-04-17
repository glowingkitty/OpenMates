// Follow-up suggestion chips — AI-generated suggestions shown after responses.
// Tapping a chip fills the message input with the suggestion text.

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
                                .foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing4)
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
