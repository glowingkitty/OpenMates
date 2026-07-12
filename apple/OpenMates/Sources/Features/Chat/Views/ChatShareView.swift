// Chat sharing entry point backed by the shared custom Apple share panel.
// Generates web-compatible encrypted links locally and syncs only permitted
// share metadata through the established share routes.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// CSS:     frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import SwiftUI

struct ChatShareView: View {
    let chatId: String
    var chat: Chat?

    @State private var chatKey: SymmetricKey?
    @State private var loadError = false

    var body: some View {
        Group {
            if let chatKey {
                AppleSharePanel(
                    context: AppleShareContext(
                        contentType: .chat,
                        id: chatId,
                        title: chat?.title ?? AppStrings.chat,
                        summary: chat?.chatSummary,
                        key: chatKey,
                        chatId: chatId
                    ),
                    onClose: {},
                    onGenerated: persistShare,
                    onStopSharing: stopSharing
                )
            } else if loadError {
                Text(AppStrings.error)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.spacing8)
                    .accessibilityIdentifier("share-error")
            } else {
                ProgressView()
                    .tint(Color.buttonPrimary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await loadKey() }
    }

    private func loadKey() async {
        if let key = ChatKeyManager.shared.key(for: chatId) {
            chatKey = key
            return
        }
        #if DEBUG
        if ProcessInfo.processInfo.environment["UI_TEST_CHAT_SHARE_URL"] != nil {
            chatKey = SymmetricKey(data: Data(repeating: 0, count: 32))
            return
        }
        #endif
        loadError = true
    }

    private func persistShare(_ url: URL, _ usedLongFallback: Bool, _ duration: ShareDuration) async {
        guard let chatKey else { return }
        do {
            let encryptedURL = try await CryptoManager.shared.encryptContent(url.absoluteString, key: chatKey)
            UserDefaults.standard.set(encryptedURL, forKey: storedShareURLKey)
            let body: [String: Any] = [
                "chat_id": chatId,
                "title": chat?.title ?? NSNull(),
                "summary": chat?.chatSummary ?? NSNull(),
                "category": chat?.category ?? NSNull(),
                "icon": chat?.icon ?? NSNull(),
                "is_shared": true,
                "share_pii": false,
                "share_highlights": false,
                "encrypted_shared_short_url": encryptedURL
            ]
            let _: Data = try await APIClient.shared.request(.post, path: "/v1/share/chat/metadata", body: body)
            NativeDiagnostics.info(
                "Chat share metadata synced kind=\(usedLongFallback ? "long" : "short") duration=\(duration.rawValue)",
                category: "sharing"
            )
        } catch {
            NativeDiagnostics.warning("Chat share metadata sync failed", category: "sharing")
        }
    }

    private func stopSharing() async {
        do {
            let _: Data = try await APIClient.shared.request(.post, path: "/v1/share/chat/unshare", body: ["chat_id": chatId])
            UserDefaults.standard.removeObject(forKey: storedShareURLKey)
        } catch {
            NativeDiagnostics.error("Chat unshare failed", category: "sharing")
        }
    }

    private var storedShareURLKey: String {
        "share.url.\(chatId)"
    }
}
