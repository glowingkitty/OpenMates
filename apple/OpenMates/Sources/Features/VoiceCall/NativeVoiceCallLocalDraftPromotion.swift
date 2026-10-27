// Web source: services/voiceCallMessages.ts (canonical new-chat preparation).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.launch-and-provider
#if !os(watchOS)
import Foundation

/// Local draft metadata is not canonical ownership. This only preserves the
/// originating draft while the factory performs exact durable wrapper/version
/// admission; it grants no provider, history-completeness or server authority.
@MainActor
enum NativeVoiceCallLocalDraftPromotion {
    static func eligible(_ chat: Chat, chatID: String) -> Bool {
        chat.id == chatID && UUID(uuidString: chatID) != nil && chat.encryptedChatKey == nil
            && chat.teamId == nil && chat.isSharedByOthers != true
            && (chat.messagesV ?? 0) == 0 && (chat.titleV ?? 0) == 0 && (chat.metadataV ?? 0) == 0
            && chat.lastMessageAt == nil && chat.parentId == nil && chat.isSubChat != true
            && !IncognitoChatSession.isIncognitoChatId(chatID)
    }
    static func prepare(_ chat: Chat, chatID: String, encryptedChatKey: String, mate: String) throws -> Chat {
        guard eligible(chat, chatID: chatID), !encryptedChatKey.isEmpty, !mate.isEmpty,
              chat.category == nil || chat.category == mate else { throw NativeVoiceCallError.contextUnavailable }
        return Chat(id: chat.id, title: chat.title, lastMessageAt: chat.lastMessageAt,
            createdAt: chat.createdAt, updatedAt: chat.updatedAt, lastEditedOverallTimestamp: chat.lastEditedOverallTimestamp,
            isArchived: chat.isArchived, isPinned: chat.isPinned, appId: chat.appId, category: mate,
            icon: chat.icon, chatSummary: chat.chatSummary, encryptedTitle: chat.encryptedTitle,
            encryptedCategory: chat.encryptedCategory, encryptedIcon: chat.encryptedIcon,
            encryptedChatSummary: chat.encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: chat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: chat.encryptedAutoSpeakResponse, encryptedChatKey: encryptedChatKey,
            messagesV: 0, titleV: 0, draftV: chat.draftV, metadataV: 0,
            lastVisibleMessageId: chat.lastVisibleMessageId, parentId: chat.parentId, isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings, budgetLimit: chat.budgetLimit, budgetSpent: chat.budgetSpent,
            encryptedFocusPhaseState: chat.encryptedFocusPhaseState, encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId, isPrivate: chat.isPrivate, isHidden: chat.isHidden,
            isHiddenCandidate: chat.isHiddenCandidate, teamId: chat.teamId, isSharedByOthers: chat.isSharedByOthers,
            hasNonEmptyDraft: chat.hasNonEmptyDraft, clearedDraftV: chat.clearedDraftV, unreadCount: chat.unreadCount)
    }
}
#endif
