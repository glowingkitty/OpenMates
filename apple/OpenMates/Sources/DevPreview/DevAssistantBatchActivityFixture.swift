// Local, manual production activity/batch fixture; no auth/API/provider/persistence.
// Web: frontend/packages/ui/src/components/AssistantActivityGroup.preview.ts
#if DEBUG
import SwiftUI

struct DevAssistantBatchActivityFixture: View {
    @StateObject private var store = ChatStore()
    @State private var progress: SubChatProgress?
    @State private var narrow = false
    @State private var hydrated = false
    private let parentID = "batch-fixture-parent"
    private let responseID = "batch-fixture-response"
    private var skill: DevEmbedPreviewSkill { DevEmbedPreviewFixtures.skills(for: .web)[0] }
    private var records: [String: EmbedRecord] {
        let parent = skill.primaryEmbed
        var records = skill.allRecords
        records[parent.id] = EmbedRecord(id: parent.id, type: "app-skill-use", status: .processing,
            data: parent.data, parentEmbedId: parent.parentEmbedId, appId: parent.appId,
            skillId: parent.skillId, embedIds: parent.embedIds, createdAt: parent.createdAt)
        records["batch-fixture-focus"] = EmbedRecord(id: "batch-fixture-focus", type: "focus-mode-activation", status: .finished,
            data: .raw(["focus_id": AnyCodable("web-research"), "focus_mode_name": AnyCodable("Research")]),
            parentEmbedId: nil, appId: "web", skillId: nil, embedIds: nil, createdAt: nil)
        return records
    }
    private var content: String {
        """
        The parent keeps two batches separate.

        ```json
        {"type":"focus-mode-activation","embed_id":"batch-fixture-focus"}
        ```

        ```json
        {"type":"sub_chat_batch","batch_id":"batch-a","chat_id":"batch-fixture-parent","task_id":"task-a","parent_message_id":"batch-fixture-response","status":"processing","sub_chat_ids":["batch-child-a"]}
        ```

        ```json
        {"type":"sub_chat_batch","batch_id":"batch-b","chat_id":"batch-fixture-parent","task_id":"task-b","parent_message_id":"batch-fixture-response","status":"processing","sub_chat_ids":["batch-child-b"]}
        ```

        ```json
        {"type":"app_skill_use","embed_id":"\(skill.primaryEmbed.id)"}
        ```

        The authored conclusion stays mounted.
        """
    }
    private var message: Message {
        .init(id: responseID, chatId: parentID, role: .assistant, content: nil, encryptedContent: nil,
            createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, appId: "code", isStreaming: true, embedRefs: nil)
    }
    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: .spacing4) {
                ScrollView {
                    MessageBubble(message: message, chatId: parentID, appId: "code", embeds: [],
                        allEmbedRecords: records, streamingContent: content, thinkingContent: nil, isThinkingStreaming: false,
                        piiMappings: [], isPIIRevealed: false, containerWidth: narrow ? 280 : geometry.size.width,
                        isSearchTarget: false, searchHighlightQuery: nil, onEmbedTap: { _ in }, onOpenPublicChat: nil,
                        subChatStore: store, subChatProgress: progress, onOpenSubChat: { _ in },
                        onInteractiveQuestionSubmit: nil, onShowActions: nil, responseActive: true)
                        .frame(maxWidth: narrow ? 280 : .infinity).padding(.spacing8)
                }.accessibilityIdentifier("dev-batch-scroll")
                HStack(spacing: .spacing4) {
                    Button("Foreign event") { progress = event(task: "foreign-task", status: "completed") }
                        .accessibilityIdentifier("dev-batch-foreign")
                    Button("Complete first batch") { progress = event(task: "task-a", status: "completed") }
                        .accessibilityIdentifier("dev-batch-complete-first")
                    Button("Hydrate second history") {
                        store.performWithoutPersistence { store.setMessages(for: "batch-child-b", messages: [childMessage("batch-child-b", role: .assistant)]) }
                        hydrated = true
                    }.accessibilityIdentifier("dev-batch-hydrate-second").disabled(hydrated)
                }
                HStack {
                    Button("Run second batch") { progress = event(task: "task-b", status: "running") }
                        .accessibilityIdentifier("dev-batch-run-second")
                    Button("Change width") { narrow.toggle() }.accessibilityIdentifier("dev-batch-reflow")
                    Text(hydrated ? "history settled" : "history pending").accessibilityIdentifier("dev-batch-state")
                }
            }
            .font(.omSmall).buttonStyle(.plain)
            .onAppear {
                store.performWithoutPersistence {
                    store.chats = [child("batch-child-a", title: "First batch child"), child("batch-child-b", title: "Second batch child")]
                    for id in ["batch-child-a", "batch-child-b"] { store.setMessages(for: id, messages: [childMessage(id, role: .user)]) }
                }
            }
        }
    }
    private func event(task: String, status: String) -> SubChatProgress {
        .init(chatId: parentID, taskId: task, executionMode: "parallel", status: status, total: 1, completed: 1,
            activeSubChatId: nil, messageId: responseID)
    }
    private func child(_ id: String, title: String) -> Chat {
        .init(id: id, title: title, lastMessageAt: nil, createdAt: "2026-10-19T00:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai", encryptedTitle: nil, encryptedChatKey: nil,
            parentId: parentID, isSubChat: true)
    }
    private func childMessage(_ id: String, role: MessageRole) -> Message {
        .init(id: id + "-response", chatId: id, role: role, content: role == .assistant ? "A completed synthetic child summary." : "Synthetic child prompt.",
            encryptedContent: nil, createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, appId: "ai", isStreaming: false, embedRefs: nil)
    }
}
#endif
