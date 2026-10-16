// Isolated production embed/context actions and Settings shared/share routing.
// Seeds real AES-GCM wrappers in detached in-memory key managers. The fixture
// never generates a link, authenticates an account, or writes to a server.
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.shell.lifecycle-and-routing, settings-ui.navigation.parent-return
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte
//         frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import CryptoKit
import SwiftUI

struct DevEmbedShareSettingsFixture: View {
    @StateObject private var store = ChatStore()
    @StateObject private var theme = ThemeManager()
    @State private var openedEmbed: EmbedRecord?
    @State private var shareTarget: EmbedShareSettingsTarget?
    @State private var settingsOpen = false
    @State private var ready = false
    @State private var preparationFailed = false
    private let chatId = "embed-share-settings-fixture-chat"

    private var records: [EmbedRecord] {
        ["first", "second"].map { suffix in
            EmbedRecord(id: "embed-share-settings-\(suffix)", type: "web-website", status: .finished,
                data: .raw(["title": AnyCodable("Share fixture \(suffix)"),
                    "url": AnyCodable("https://example.invalid/\(suffix)"),
                    "description": AnyCodable("Captured embed identity \(suffix)")]),
                parentEmbedId: nil, appId: "web", skillId: "search", embedIds: nil, createdAt: nil)
        }
    }
    private var byId: [String: EmbedRecord] { Dictionary(uniqueKeysWithValues: records.map { ($0.id, $0) }) }

    var body: some View {
        GeometryReader { geometry in
            WorkspaceSettingsLayout(windowWidth: geometry.size.width,
                windowFrame: geometry.frame(in: .global), isOpen: $settingsOpen) {
                ZStack {
                    ScrollView {
                        VStack(spacing: .spacing6) {
                            if preparationFailed { Text(AppStrings.error).accessibilityIdentifier("embed-share-fixture-error") }
                            ForEach(records) { embed in
                                EmbedPreviewCard(embed: embed, allEmbedRecords: byId) { openedEmbed = embed }
                                    .accessibilityIdentifier("embed-share-fixture-\(embed.id)")
                            }
                        }.padding(.spacing6)
                    }
                    .disabled(!ready || openedEmbed != nil)
                    .accessibilityHidden(openedEmbed != nil)
                    if let openedEmbed {
                        EmbedFullscreenContainer(embeds: records, initialEmbedId: openedEmbed.id,
                            allEmbedRecords: byId, chatId: chatId,
                            onClose: { self.openedEmbed = nil }, onOpenShareSettings: openShare,
                            isSidePanel: true, responsiveViewportWidth: geometry.size.width)
                            .accessibilityIdentifier("embed-share-fixture-fullscreen")
                    }
                }
                .environment(\.embedChatID, chatId)
                .environment(\.embedShareSettingsAction, EmbedShareSettingsAction(open: openShare))
            } settings: {
                if let shareTarget {
                    SettingsView(isolatedNavigation: true, embedShareTarget: shareTarget,
                        viewportWidth: geometry.size.width, onClose: { settingsOpen = false })
                        .id(shareTarget.requestID)
                }
            }
        }
        // Exercise the production overlay close control on either platform.
        .frame(maxWidth: 730)
        .onChange(of: settingsOpen) { _, open in if !open { shareTarget = nil } }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embed-share-settings-fixture")
        .accessibilityValue(ready ? "ready" : "preparing")
        .environmentObject(store)
        .environmentObject(theme)
        .task {
            do {
                let chatKey = SymmetricKey(size: .bits256)
                ChatKeyManager.shared.setKey(chatKey, for: chatId)
                var entries: [EmbedKeyRecord] = []
                for embed in records {
                    let key = SymmetricKey(size: .bits256)
                    let wrapper = try await CryptoManager.shared.wrapChatKey(key, masterKey: chatKey)
                    entries.append(EmbedKeyRecord(hashedEmbedId: digest(embed.id), keyType: "chat",
                        hashedChatId: digest(chatId), encryptedEmbedKey: wrapper))
                }
                EmbedKeyManager.shared.store(entries, source: "isolated-share-settings")
                ready = true
            } catch { preparationFailed = true }
        }
        .onDisappear {
            ChatKeyManager.shared.removeKey(for: chatId)
            EmbedKeyManager.shared.removeKeys(for: chatId)
        }
    }

    private func openShare(_ target: EmbedShareSettingsTarget) {
        shareTarget = target
        settingsOpen = true
    }
    private func digest(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
}
#endif
