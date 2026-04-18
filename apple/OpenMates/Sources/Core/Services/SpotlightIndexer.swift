// Spotlight indexer — indexes chats into Core Spotlight so users can find
// their conversations from the system search (Spotlight / Cmd-Space).
// Each chat becomes a searchable item with its title and last message date.
// Items are updated incrementally when chats are loaded and removed when deleted.

import CoreSpotlight
import UniformTypeIdentifiers
#if os(iOS)
import UIKit
#endif

@MainActor
final class SpotlightIndexer {
    static let shared = SpotlightIndexer()
    private let index = CSSearchableIndex.default()

    private init() {}

    /// Index a batch of chats. Called after initial load and on WebSocket updates.
    func indexChats(_ chats: [Chat]) {
        let items = chats.compactMap { chat -> CSSearchableItem? in
            guard let title = chat.title, !title.isEmpty else { return nil }

            let attributes = CSSearchableItemAttributeSet(contentType: .text)
            attributes.title = title
            attributes.contentDescription = "OpenMates chat"
            attributes.lastUsedDate = chat.lastMessageDate

            // Use the app icon as the thumbnail
            #if os(iOS)
            attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
            #endif

            return CSSearchableItem(
                uniqueIdentifier: "chat-\(chat.id)",
                domainIdentifier: "org.openmates.chats",
                attributeSet: attributes
            )
        }

        guard !items.isEmpty else { return }

        index.indexSearchableItems(items) { error in
            if let error {
                print("[Spotlight] Failed to index chats: \(error)")
            }
        }
    }

    /// Remove a single chat from the Spotlight index (called on delete).
    func removeChat(_ chatId: String) {
        index.deleteSearchableItems(withIdentifiers: ["chat-\(chatId)"]) { error in
            if let error {
                print("[Spotlight] Failed to remove chat: \(error)")
            }
        }
    }

    /// Clear all OpenMates items from Spotlight (called on logout).
    func removeAllItems() {
        index.deleteSearchableItems(withDomainIdentifiers: ["org.openmates.chats"]) { error in
            if let error {
                print("[Spotlight] Failed to clear index: \(error)")
            }
        }
    }
}
