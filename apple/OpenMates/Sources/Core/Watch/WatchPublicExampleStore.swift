// Public Watch data only. No authenticated runtime, disk cache, outbox or handoff.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.guest.compact-workspace, apple-watch.guest.account-isolation
import Foundation
import Combine

@MainActor
final class WatchPublicExampleStore: ObservableObject {
    struct Conversation {
        let summary: WatchChatSummary
        let messages: [WatchChatMessage]
        let records: [EmbedRecord]
    }
    let chats: [WatchChatSummary]
    private let text: @MainActor (String) -> String

    init(text: @escaping @MainActor (String) -> String) {
        self.text = text
        chats = BundledPublicExampleCatalog.orderedIDs.compactMap { id in
            guard let example = BundledPublicExampleCatalog.examples[id] else { return nil }
            var chat = WatchChatSummary(id: id, title: text(example.titleKey), lastMessageAt: nil,
                preview: nil, isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)
            chat.category = example.appId
            return chat
        }
    }
    func search(_ query: String) -> [WatchChatSummary] {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return chats }
        return chats.filter { ($0.title ?? "").localizedStandardContains(query) }
    }
    func conversation(id: String) -> Conversation? {
        guard let example = BundledPublicExampleCatalog.examples[id],
              let summary = chats.first(where: { $0.id == id }) else { return nil }
        var records = BundledPublicExampleCatalog.demoEmbedRecords(for: id)
        var messages = example.messages.map { spec in
            let parsed = BundledPublicExampleCatalog.extractEmbeds(from: text(spec.key), fallbackAppId: example.appId)
            for record in parsed.records where records[record.id] == nil { records[record.id] = record }
            return WatchChatMessage(id: spec.id, chatId: id,
                role: WatchChatMessage.Role(rawValue: spec.role) ?? .assistant,
                content: parsed.content, encryptedContent: nil,
                embedRefs: parsed.refs.map { ref in
                    guard let record = records[ref.id] else {
                        return WatchEmbedRef(id: ref.id, type: ref.type, status: ref.status, data: ref.data)
                    }
                    return WatchEmbedRef(id: record.id, type: record.type, status: record.status.rawValue, data: record.rawData)
                },
                createdAt: "2026-04-20T12:00:00Z", isPending: false)
        }
        // Preserve the main-app static result-parent projection, including groups
        // supplied solely by the bundled source rather than explicit text markers.
        let uniqueRecords = Dictionary(records.values.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first }).values
        let parents = uniqueRecords.filter(\.isAppSkillUse).sorted { $0.id < $1.id }
        var assigned = Set<String>()
        for index in messages.indices where messages[index].role == .assistant {
            let refs = messages[index].embedRefs ?? []
            let ids = Set(refs.map(\.id))
            let matching = parents.filter { !ids.contains($0.id) && !Set($0.childEmbedIds).isDisjoint(with: ids) }
            assigned.formUnion(matching.map(\.id))
            messages[index].embedRefs = matching.map { WatchEmbedRef(id: $0.id, type: $0.type, status: $0.status.rawValue, data: nil) } + refs
        }
        if let last = messages.lastIndex(where: { $0.role == .assistant }) {
            let refs = messages[last].embedRefs ?? []
            let ids = Set(refs.map(\.id))
            messages[last].embedRefs = parents.filter { !assigned.contains($0.id) && !ids.contains($0.id) }
                .map { WatchEmbedRef(id: $0.id, type: $0.type, status: $0.status.rawValue, data: nil) } + refs
        }
        return Conversation(summary: summary, messages: messages, records: Array(records.values))
    }
}
