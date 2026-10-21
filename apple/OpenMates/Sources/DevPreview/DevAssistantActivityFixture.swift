// Production response/activity renderer with local manual actions only.
// Web: frontend/packages/ui/src/components/ChatMessage.preview.ts
// No account, transport, provider invocation or persistence is started.
#if DEBUG
import SwiftUI
struct DevAssistantActivityFixture: View {
    let variant: String
    @State private var stage = 0
    @State private var narrow = false
    @State private var route: [EmbedRecord] = []
    private let chatID = "activity-fixture-chat"
    private var web: DevEmbedPreviewSkill { DevEmbedPreviewFixtures.skills(for: .web)[0] }
    private var news: DevEmbedPreviewSkill { DevEmbedPreviewFixtures.skills(for: .news)[0] }
    private var memory: ChatAppliedMemory {
        .init(id: "app:web:research", title: "Web: Research preferences", source: "app", appId: "web", projectId: nil,
              revision: String(repeating: "a", count: 64), body: "Prefer primary sources and keep the original research goal visible.")
    }
    private var records: [String: EmbedRecord] {
        var values = web.allRecords.merging(news.allRecords, uniquingKeysWith: { first, _ in first })
        for (skill, processing) in [(web, stage == 1), (news, stage == 2)] {
            let parent = skill.primaryEmbed
            values[parent.id] = EmbedRecord(id: parent.id, type: parent.type, status: processing ? .processing : .finished,
                data: parent.data, parentEmbedId: parent.parentEmbedId, appId: parent.appId, skillId: parent.skillId,
                embedIds: parent.embedIds, createdAt: parent.createdAt)
        }
        return values
    }
    private var content: String {
        var text = "I will compare two sources.\n\n```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"\(web.primaryEmbed.id)\"}\n```"
        if stage >= 2 { text += "\n\nThe first comparison is ready.\n\n```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"\(news.primaryEmbed.id)\"}\n```" }
        if stage >= 3 { text += "\n\nThe answer keeps both results in source order." }
        return text
    }
    private var message: Message {
        Message(id: "activity-response", chatId: chatID, role: .assistant, content: stage == 3 ? content : nil,
            encryptedContent: nil, createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, appId: "code", isStreaming: stage < 3, embedRefs: nil)
    }
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                VStack(spacing: .spacing4) {
                    ScrollView {
                        Group {
                            if stage == 0 {
                                TransientAssistantResponseView(response: .init(id: "activity-response", chatId: chatID,
                                    userMessageId: "activity-user", mateCategory: "code", mateName: nil),
                                    memories: [memory], viewportWidth: narrow ? 280 : geometry.size.width,
                                    onOpenMateSettings: nil, onOpenModelSettings: nil)
                            } else {
                                MessageBubble(message: message, chatId: chatID, appId: "code", embeds: [],
                                    allEmbedRecords: records, streamingContent: stage == 3 ? nil : content,
                                    thinkingContent: "I will inspect the two sources before comparing the results.", isThinkingStreaming: false,
                                    piiMappings: [], isPIIRevealed: false, containerWidth: narrow ? 280 : geometry.size.width,
                                    isSearchTarget: false, searchHighlightQuery: nil, onEmbedTap: { route.append($0) }, onOpenPublicChat: nil,
                                    onInteractiveQuestionSubmit: nil, onShowActions: nil, responseActive: stage < 3, loadedMemories: [memory])
                            }
                        }.frame(maxWidth: narrow ? 280 : .infinity).padding(.spacing8)
                    }.accessibilityIdentifier("dev-activity-scroll")
                    HStack(spacing: .spacing4) {
                        Button(stage == 0 ? "Begin response" : stage == 2 ? "Finish response" : "Next activity") { stage = min(3, stage + 1) }
                            .accessibilityIdentifier("dev-activity-next").disabled(stage == 3)
                        Button("Change width") { narrow.toggle() }.accessibilityIdentifier("dev-activity-reflow")
                        Text("Stage \(stage)").accessibilityIdentifier("dev-activity-phase")
                    }.buttonStyle(.plain).font(.omSmall).padding(.spacing4).background(Color.grey10)
                }.allowsHitTesting(route.isEmpty).accessibilityHidden(!route.isEmpty)
                if let active = route.last {
                    EmbedFullscreenContainer(embeds: [active], initialEmbedId: active.id, allEmbedRecords: records, chatId: nil,
                        onOpenEmbed: { child, _ in route.append(child) }, onClose: { _ = route.popLast() })
                        .background(Color.grey0).accessibilityElement(children: .contain).accessibilityIdentifier("dev-activity-fullscreen")
                }
            }
        }.environment(\.progressiveMarkdownReducedMotion, variant == "response-activity-reduced-motion")
    }
}
#endif
