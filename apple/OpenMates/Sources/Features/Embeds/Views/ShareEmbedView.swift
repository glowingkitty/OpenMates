// Embed sharing is a child of the common Settings Shared page.
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.shell.lifecycle-and-routing, settings-ui.navigation.parent-return
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import SwiftUI

@MainActor
struct EmbedShareSettingsAction {
    let open: (EmbedShareSettingsTarget) -> Void
}

private struct EmbedShareSettingsActionKey: EnvironmentKey {
    static let defaultValue: EmbedShareSettingsAction? = nil
}

extension EnvironmentValues {
    var embedShareSettingsAction: EmbedShareSettingsAction? {
        get { self[EmbedShareSettingsActionKey.self] }
        set { self[EmbedShareSettingsActionKey.self] = newValue }
    }
}

/// Capture the selected record and its owning chat at the action boundary.
/// A later fullscreen sibling selection must not change the shared identity.
struct EmbedShareSettingsTarget: Identifiable {
    let requestID = UUID()
    let embed: EmbedRecord
    let chatId: String
    let allEmbedRecords: [String: EmbedRecord]
    var id: String { embed.id }

    func context(key: SymmetricKey) -> AppleShareContext {
        AppleShareContext(contentType: .embed, id: embed.id,
            title: embed.rawData?["title"]?.value as? String ?? embed.type,
            summary: embed.rawData?["description"]?.value as? String,
            key: key, chatId: chatId)
    }
}

@MainActor
final class EmbedShareSettingsModel: ObservableObject {
    @Published private(set) var context: AppleShareContext?
    @Published private(set) var failed = false
    private var activeRequest: UUID?

    func load(_ target: EmbedShareSettingsTarget,
              resolveKey: (EmbedShareSettingsTarget) async -> SymmetricKey?) async {
        activeRequest = target.requestID
        context = nil
        failed = false
        let key = await resolveKey(target)
        guard activeRequest == target.requestID, !Task.isCancelled else { return }
        guard let key else { failed = true; return }
        context = target.context(key: key)
    }

    func clear() {
        activeRequest = nil
        context = nil
        failed = false
    }
}

struct ShareEmbedView: View {
    let target: EmbedShareSettingsTarget
    @StateObject private var model = EmbedShareSettingsModel()

    var body: some View {
        Group {
            if let context = model.context {
                AppleSharePanel(context: context, onClose: {},
                    onGenerated: persistShare, onStopSharing: nil)
                    .id(target.requestID)
            } else if model.failed {
                Text(AppStrings.error).font(.omSmall).foregroundStyle(Color.error)
                    .padding(.spacing8).accessibilityIdentifier("share-error")
            } else {
                ProgressView().tint(Color.buttonPrimary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .accessibilityIdentifier("settings-embed-share-content")
        .task(id: target.requestID) {
            await model.load(target) { request in
                await EmbedKeyManager.shared.key(for: request.embed,
                    chatId: request.chatId, allEmbeds: request.allEmbedRecords)
            }
        }
        .onDisappear { model.clear() }
    }

    private func persistShare(_ url: URL, _ fallback: Bool, _ duration: ShareDuration) async throws {
        guard let context = model.context, context.id == target.id,
              let accountID = await AuthManager.currentUserId() else { throw UserTasksError.accountChanged }
        let fence = UserTasksAccountFence(accountID: accountID)
        try await fence.check()
        let body: [String: Any] = ["embed_id": context.id, "title": context.title,
            "description": context.summary ?? NSNull(), "is_shared": true]
        do {
            let _: Data = try await APIClient.shared.request(.post, path: "/v1/share/embed/metadata",
                serverProfile: fence.serverProfile, body: JSONRawBody(data: JSONSerialization.data(withJSONObject: body)),
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
        } catch {
            // Preserve the existing offline long-link result while fencing a
            // changed account/server. The web queues this metadata separately.
            try await fence.check()
            NativeDiagnostics.warning("Embed share metadata sync failed", category: "sharing")
            return
        }
        try await fence.check()
        NativeDiagnostics.info("Embed share metadata synced kind=\(fallback ? "long" : "short") duration=\(duration.rawValue)", category: "sharing")
    }
}
