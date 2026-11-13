// Maps one core chat-list row (`ChatListRowRecord` with its
// `ChatRowMetadataRecord`) to the `Chat` value and the row presentation that
// `ChatListRow` renders, so the sidebar view stays unchanged (plan
// apple-client-core-migration A4 lane 2). A pure field copy: no ordering,
// grouping, dedup, unread or draft rule is derived here; the core decided
// them. Rows the sidebar cannot represent (the core's saved-item home
// entries, ids `embed:<id>`) are refused with `nil`, never guessed.
// Timestamps: every row time (`createdAt`, `updatedAt` and the metadata's
// `lastMessageAt`/`lastEditedAt`) is unix seconds, the server's chat-row unit
// (backend/core/directus/schemas/chats.yml), passed through by the core.
// Draft preview: the core marks a draft-only row by `status == .draft` and
// sets `hasDraft` only for a draft of an established chat; both carry it.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.draft-only.presentation

import Foundation

@MainActor
enum CoreChatRowMapper {
    /// Id prefix of the core's saved-item home entries (`place_home_entries`).
    static let savedItemPrefix = "embed:"

    /// One mapped row: the chat value and what the core decided for its row.
    struct Mapped {
        let chat: Chat
        let presentation: ChatSidebarRowPresentation
    }

    private static let iso = ISO8601DateFormatter()

    /// The row as the sidebar renders it, or `nil` for a row shape the
    /// sidebar does not show (a saved-item home entry).
    static func map(_ row: ChatListRowRecord) -> Mapped? {
        guard !row.id.hasPrefix(savedItemPrefix) else { return nil }
        let meta = row.metadata
        let settings: SubChatSettings? = meta.subChatWaitForCompletion == nil && meta.subChatReportTrigger == nil
            ? nil
            : SubChatSettings(waitForCompletion: meta.subChatWaitForCompletion, reportTrigger: meta.subChatReportTrigger)
        let chat = Chat(
            id: row.id,
            title: row.title,
            lastMessageAt: seconds(meta.lastMessageAt),
            createdAt: seconds(row.createdAt) ?? "",
            updatedAt: seconds(row.updatedAt),
            lastEditedOverallTimestamp: seconds(meta.lastEditedAt),
            isArchived: row.archived,
            isPinned: row.pinned,
            appId: meta.appId,
            category: row.category.isEmpty ? nil : row.category,
            icon: meta.icon,
            chatSummary: row.summary.isEmpty ? nil : row.summary,
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: row.messagesV.map { Int(clamping: $0) },
            draftV: meta.draftV.map { Int(clamping: $0) },
            lastVisibleMessageId: meta.lastVisibleMessageId,
            parentId: meta.parentId,
            isSubChat: meta.isSubChat,
            subChatSettings: settings,
            budgetLimit: meta.budgetLimit.map { Double($0) },
            budgetSpent: meta.budgetSpent.map { Double($0) },
            activeFocusId: meta.activeFocusId,
            isPrivate: meta.isPrivate,
            isHidden: meta.isHidden,
            teamId: meta.teamId,
            isSharedByOthers: meta.isSharedByOthers,
            hasNonEmptyDraft: row.hasDraft,
            unreadCount: Int(clamping: row.unreadCount))
        let preview = row.hasDraft || row.status == .draft ? ChatDraftPreviewFormatter.format(meta.draftPreview) : ""
        let presentation = ChatSidebarRowPresentation(
            unreadCount: Int(clamping: row.unreadCount),
            isDraftOnly: row.status == .draft,
            draftPreview: preview.isEmpty ? nil : preview)
        return Mapped(chat: chat, presentation: presentation)
    }

    private static func seconds(_ value: Int64?) -> String? {
        value.map { iso.string(from: Date(timeIntervalSince1970: TimeInterval($0))) }
    }
}
