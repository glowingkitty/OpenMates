// Synthetic fullscreen actions open real platform dialogs and never save events.
// Web: embeds/UnifiedEmbedFullscreen.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
#if DEBUG
import SwiftUI
struct DevFullscreenActionFixture: View {
    let variant: String
    private var embed: EmbedRecord {
        let calendar = variant == "action-calendar"
        let raw: [String: Any] = calendar ? ["title": "Public calendar fixture", "date_start": "2026-10-04T09:30:00+02:00",
            "date_end": "2026-10-04T10:45:00+02:00", "venue": ["name": "Public venue", "city": "Berlin"],
            "url": "https://example.invalid/event"] : ["code": "print('Public export fixture')", "language": "python", "filename": "public-export.py"]
        return EmbedRecord(id: "fullscreen-action-fixture", type: calendar ? "events-event" : "code-code", status: .finished,
            data: .raw(raw.mapValues { AnyCodable($0) }), parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
    }
    var body: some View {
        EmbedFullscreenContainer(embeds: [embed], initialEmbedId: embed.id, allEmbedRecords: [embed.id: embed], chatId: nil,
            responsiveViewportWidth: 390)
            .background(Color.grey0)
            .accessibilityIdentifier("dev-fullscreen-action-fixture")
    }
}
#endif
