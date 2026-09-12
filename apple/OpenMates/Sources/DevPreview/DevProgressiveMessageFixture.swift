// Manual, deterministic fixture for the real message renderer and embed route.
// Compare ChatMessage plus StreamingMessageRenderHarness in web /dev/preview/.
// State is synthetic and local; public fixture image GETs may use the normal cache.
// No auth, draft, sync, API, WebSocket, provider, or account persistence is started.
#if DEBUG
import SwiftUI

struct DevProgressiveMessageFixture: View {
    let variant: String
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var step = 0
    @State private var hydrated = false
    @State private var finalized = false
    @State private var narrow = false
    @State private var generation = 0
    @State private var route: [EmbedRecord] = []

    private var skill: DevEmbedPreviewSkill { DevEmbedPreviewFixtures.skills(for: .web)[0] }
    private var sourceRecord: EmbedRecord {
        let record = skill.childEmbeds[0]
        var raw = record.rawData ?? [:]
        raw["embed_ref"] = AnyCodable(record.id)
        return EmbedRecord(id: record.id, type: record.type, status: record.status, data: .raw(raw),
            parentEmbedId: record.parentEmbedId, appId: record.appId, skillId: record.skillId,
            embedIds: record.embedIds, createdAt: record.createdAt)
    }
    private var records: [String: EmbedRecord] {
        guard hydrated else { return [:] }
        var records = skill.allRecords
        records[sourceRecord.id] = sourceRecord
        return records
    }
    private var content: String {
        if variant == "streaming-long" {
            return "A long streaming paragraph starts with [First Berlin guide](embed:\(sourceRecord.id)). "
                + String(repeating: "This ordinary sentence keeps the source in the same paragraph. ", count: 70)
                + "Its final source is [Last Berlin guide](embed:\(sourceRecord.id))."
        }
        var text = "The first paragraph is available while the response is still streaming."
        if step >= 1 { text += "\n\nThe second paragraph has a source: [Berlin guide](embed:\(sourceRecord.id)" }
        if step >= 2 { text += ")." }
        if step >= 3 { text += "\n\nA third paragraph arrives after the citation can already be opened." }
        if step >= 4 { text += "\n\n- The first result stays visible.\n- The second result arrives progressively." }
        return text
    }
    private var message: Message {
        Message(id: "progressive-fixture-\(generation)", chatId: "progressive-fixture-chat",
            role: .assistant, content: finalized ? content : nil, encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, appId: "code",
            isStreaming: !finalized, embedRefs: nil, modelName: nil)
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                VStack(spacing: 12) {
                    ScrollView {
                        MessageBubble(message: message, chatId: message.chatId, appId: "code",
                            embeds: [], allEmbedRecords: records,
                            streamingContent: finalized ? nil : content,
                            thinkingContent: nil, isThinkingStreaming: false,
                            piiMappings: [], isPIIRevealed: false,
                            containerWidth: narrow ? min(280, geometry.size.width) : geometry.size.width,
                            isSearchTarget: false, searchHighlightQuery: nil,
                            onEmbedTap: { route.append($0) }, onOpenPublicChat: nil,
                            onInteractiveQuestionSubmit: nil, onShowActions: nil)
                            .frame(maxWidth: narrow ? 280 : .infinity)
                            .padding(16)
                    }
                    .accessibilityIdentifier("dev-stream-scroll")
                    VStack(spacing: 8) {
                        HStack {
                            Button("Next chunk") { step = min(4, step + 1) }
                                .accessibilityIdentifier("dev-stream-next")
                                .disabled(finalized || step == 4)
                            Button("Hydrate source") { hydrated = true }
                                .accessibilityIdentifier("dev-stream-hydrate")
                                .disabled(hydrated)
                            Button("Finalize") { finalized = true }
                                .accessibilityIdentifier("dev-stream-finalize")
                                .disabled(finalized)
                        }
                        HStack {
                            Button("Change width") { narrow.toggle() }
                                .accessibilityIdentifier("dev-stream-reflow")
                            Button("Reset") {
                                step = 0; hydrated = false; finalized = false; narrow = false
                                generation += 1
                            }
                            .accessibilityIdentifier("dev-stream-reset")
                            Text("Chunk \(step) · \(finalized ? "complete" : "streaming")")
                                .accessibilityIdentifier("dev-stream-phase")
                        }
                    }
                    .font(.omXs)
                    .buttonStyle(.bordered)
                    .padding(8)
                }
                .allowsHitTesting(route.isEmpty)
                .accessibilityHidden(!route.isEmpty)
                if let active = route.last {
                    EmbedFullscreenContainer(embeds: [active], initialEmbedId: active.id,
                        allEmbedRecords: records, chatId: nil,
                        onOpenEmbed: { child, _ in route.append(child) },
                        onClose: { _ = route.popLast() })
                        .background(Color.grey0)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("dev-stream-fullscreen")
                }
            }
        }
        .environment(\.progressiveMarkdownReducedMotion, variant == "streaming-reduced-motion" || reduceMotion)
    }
}
#endif
