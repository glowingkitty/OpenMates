// Notification banners — push notification, webhook pending, and offline banners.
// Mirrors the web app's PushNotificationBanner.svelte, WebhookPendingBanner.svelte,
// and OfflineBanner.svelte.

import SwiftUI

// MARK: - Push notification banner (in-app notification for new messages)

struct PushNotificationBanner: View {
    let chatTitle: String
    let messagePreview: String
    let appIcon: String?
    let onTap: () -> Void
    let onDismiss: () -> Void
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: .spacing3) {
                if let appIcon {
                    AppIconView(appId: appIcon, size: 32)
                        .accessibilityHidden(true)
                } else {
                    Image.iconOpenmates
                        .resizable()
                        .frame(width: 32, height: 32)
                        .accessibilityHidden(true)
                }

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(chatTitle)
                        .font(.omSmall).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                    Text(messagePreview)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                }

                Spacer()

                Button(action: onDismiss) {
                    Icon("close", size: 14)
                        .foregroundStyle(Color.fontTertiary)
                }
                .accessibleButton("Dismiss notification", hint: "Closes this notification banner")
            }
            .padding(.spacing4)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
            .shadow(color: .black.opacity(0.1), radius: 8, y: 4)
        }
        .buttonStyle(.plain)
        .padding(.horizontal)
        .accessibilityElement(children: .combine)
        .accessibleButton(
            "New message in \(chatTitle): \(messagePreview)",
            hint: "Opens the chat"
        )
    }
}

// MARK: - Webhook pending banner (shown when incoming webhook chats are queued)

struct WebhookPendingBanner: View {
    let pendingCount: Int
    let onTap: () -> Void

    var body: some View {
        if pendingCount > 0 {
            Button(action: onTap) {
                HStack(spacing: .spacing3) {
                    Icon("chat", size: 18)
                        .foregroundStyle(Color.buttonPrimary)
                        .accessibilityHidden(true)

                    Text("\(pendingCount) incoming webhook message\(pendingCount == 1 ? "" : "s")")
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)

                    Spacer()

                    Text(LocalizationManager.shared.text("common.view"))
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.buttonPrimary)
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing3)
                .background(Color.buttonPrimary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            .buttonStyle(.plain)
            .padding(.horizontal)
            .accessibilityElement(children: .combine)
            .accessibleButton(
                "\(pendingCount) incoming webhook message\(pendingCount == 1 ? "" : "s")",
                hint: "Opens the webhook messages view"
            )
        }
    }
}

// MARK: - Offline banner (shown when network is unavailable)

struct OfflineBanner: View {
    let isOffline: Bool
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        if isOffline {
            HStack(spacing: .spacing2) {
                Icon("offline", size: 14)
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text("common.offline"))
                    .font(.omXs).fontWeight(.medium)
                Text("— messages will sync when reconnected")
                    .font(.omXs)
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing2)
            .background(Color.warning)
            .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("You are offline. Messages will sync when reconnected.")
        }
    }
}
