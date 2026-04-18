// Chat pagination — "Show more" button for loading additional chats.
// Loads 20 chats at a time from the backend when user scrolls to bottom.

import SwiftUI

struct ShowMoreChatsButton: View {
    let totalCount: Int
    let loadedCount: Int
    let isLoading: Bool
    let onLoadMore: () -> Void

    var remainingCount: Int { max(0, totalCount - loadedCount) }

    var body: some View {
        if remainingCount > 0 {
            Button(action: onLoadMore) {
                HStack {
                    if isLoading {
                        ProgressView()
                            .scaleEffect(0.8)
                            .accessibilityHidden(true)
                    }
                    Text("\(LocalizationManager.shared.text("chats.loadMore.button")) (\(min(remainingCount, 20)))")
                        .font(.omSmall)
                        .foregroundStyle(Color.buttonPrimary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing3)
            }
            .disabled(isLoading)
            .accessibleButton(
                isLoading ? "Loading more chats" : "Load \(min(remainingCount, 20)) more chats",
                hint: isLoading ? nil : "\(remainingCount) chats remaining"
            )
        }
    }
}

struct UnreadBadge: View {
    let count: Int

    var body: some View {
        if count > 0 {
            Text(count > 99 ? "99+" : "\(count)")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.white)
                .padding(.horizontal, count > 9 ? 5 : 4)
                .padding(.vertical, 2)
                .background(Color.buttonPrimary)
                .clipShape(Capsule())
                .accessibilityLabel("\(count > 99 ? "99 or more" : "\(count)") unread message\(count == 1 ? "" : "s")")
        }
    }
}
