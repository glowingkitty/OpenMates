// Production policy, card projection, carousel and fullscreen without account/network.
// Specification: specifications/features/continue-carousel/specification.yml
// Assertions: continue-carousel.saved-item.start-time-gated, continue-carousel.chat.reminder-gated
#if DEBUG && os(iOS)
import SwiftUI

struct DevWelcomeContinueFixture: View {
    @State private var selected: EmbedRecord?
    private let now = Date()
    private var cards: [WelcomeChatCardData] {
        let formatter = ISO8601DateFormatter()
        let memories = [("near", 1.0), ("later", 3.0), ("outside", 25.0)].map { id, hours in
            SettingsMemoryEntry(id: id, appId: "events", categoryId: "saved_events", key: "Public event", value: "",
                createdAt: 0, updatedAt: 0, version: 1, isExample: false,
                fields: ["embed_id": .string(id), "title": .string("Public \(id) event"),
                    "date_start": .string(formatter.string(from: now.addingTimeInterval(hours * 3600)))])
        }
        let items = WelcomeContinuePolicy.items(entries: memories, reminders: [], now: now)
        return WelcomeScreenState.priorityCards(items: items, chats: [], teamID: nil, now: now)
            + [.init(id: "recent", title: "Public recent chat", summary: "A recent chat", category: "general_knowledge", iconName: "message-circle", isPinned: false)]
    }
    var body: some View {
        VStack {
            WelcomeContinuationCarousel(cards: cards, containerSize: CGSize(width: 390, height: ProcessInfo.processInfo.arguments.contains("--dev-welcome-continue-large") ? 440 : 320),
                onOpenChat: { id in
                    if let memory = cards.first(where: { $0.id == id })?.savedMemory {
                        selected = WelcomeContinuePolicy.savedRecord(memory)
                    }
                }, onShowChatActions: { _ in })
            Text(cards.map(\.id).joined(separator: ",")).accessibilityIdentifier("continue-fixture-order")
        }
        .overlay {
            if let selected {
                EmbedFullscreenContainer(embeds: [selected], initialEmbedId: selected.id,
                    allEmbedRecords: [selected.id: selected], chatId: nil, onClose: { self.selected = nil })
            }
        }
    }
}
#endif
