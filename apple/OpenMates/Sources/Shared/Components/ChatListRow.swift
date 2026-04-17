// Chat list row — single row in the chat sidebar.
// Shows app gradient icon, title, relative timestamp, and pin indicator.

import SwiftUI

struct ChatListRow: View {
    let chat: Chat

    var body: some View {
        HStack(spacing: .spacing4) {
            if let appId = chat.appId {
                AppIconView(appId: appId, size: 36)
            } else {
                Circle()
                    .fill(LinearGradient.primary)
                    .frame(width: 36, height: 36)
                    .overlay {
                        Image.iconChat
                            .resizable()
                            .frame(width: 18, height: 18)
                            .foregroundStyle(.white)
                    }
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(chat.displayTitle)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                if let date = chat.lastMessageDate {
                    Text(date, style: .relative)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()

            if chat.isPinned == true {
                Image(systemName: SFSymbol.pin)
                    .font(.caption)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.vertical, .spacing1)
    }
}
