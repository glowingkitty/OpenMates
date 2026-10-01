// Scoped embed navigation uses only the recipient's hydrated graph.
// Web: frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open

import Foundation

struct SharedChatRecipientEmbedRenderIdentity: Hashable {
    let scopeID: String
    let embedID: String
}

enum SharedChatRecipientEmbedNavigation {
    static func renderIdentity(scopeID: String, embedID: String) -> SharedChatRecipientEmbedRenderIdentity {
        .init(scopeID: scopeID, embedID: embedID)
    }

    static func siblings(of selected: EmbedRecord, in records: [String: EmbedRecord]) -> [EmbedRecord] {
        let ordered = records.values.sorted { $0.id < $1.id }
        let parentID = selected.parentEmbedId ?? ordered.first { $0.childEmbedIds.contains(selected.id) }?.id
        let candidates: [EmbedRecord]
        if let parentID {
            let declared = records[parentID]?.childEmbedIds.compactMap { records[$0] } ?? []
            candidates = declared + ordered.filter { $0.parentEmbedId == parentID }
        } else {
            candidates = ordered.filter { $0.parentEmbedId == nil && $0.type == selected.type }
        }
        var seen = Set<String>()
        return (candidates + [selected]).filter { seen.insert($0.id).inserted }
    }

    static func moved(from id: String, by offset: Int, in siblings: [EmbedRecord]) -> EmbedRecord? {
        guard let index = siblings.firstIndex(where: { $0.id == id }) else { return nil }
        let destination = index + offset
        return siblings.indices.contains(destination) ? siblings[destination] : nil
    }

    @MainActor static func title(of embed: EmbedRecord) -> String {
        for field in ["title", "filename", "name"] {
            if let text = embed.rawData?[field]?.value as? String,
               !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return text }
        }
        return AppStrings.shareEmbed
    }
}
