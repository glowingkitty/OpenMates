// Container of the Recommendations card for one chat: hydrates the chat's
// recommendations from the core and runs the Accept action (billed Memory
// draft, then the Memory editor opens with the draft; saving the entry resolves
// the recommendation). Clicking Accept never removes an item; only saving does.
// Workflow suggestions are not offered: Apple has no workflow draft surface
// that can be opened from a chat yet, so the card must not show a dead button.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatRecommendations.svelte
//          frontend/packages/ui/src/services/recommendationDrafts.ts
// Tokens:  none (no own visuals; RecommendationsCardView renders the card)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor, app-memories.suggestions.billing
// Container of the Recommendations card for one chat: hydrates the chat's open
// recommendations through the Rust core (decryption stays in the core) and
// owns the card's busy/status state.
// Web source: frontend/packages/ui/src/components/ChatRecommendations.svelte
//   (mounted by ChatHistory.svelte above the follow-up suggestions, only after a
//   completed turn; no dismiss control, an action never removes a recommendation).
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor
// Tokens: none (layout comes from RecommendationsCardView).

import Foundation
import SwiftUI

/// Source of a chat's open recommendations; `CoreSession` is the production one.
@MainActor
protocol ChatRecommendationsSource: AnyObject {
    func chatRecommendations(chatId: String) async throws -> [ChatRecommendationRecord]
    func recommendationMemoryDraft(chatId: String, recommendation: ChatRecommendationRecord) async throws -> RecommendationDraftRecord
    func resolveChatRecommendation(chatId: String, recommendationId: String) async throws
}

extension CoreSession: ChatRecommendationsSource {
    func chatRecommendations(chatId: String) async throws -> [ChatRecommendationRecord] {
        try await perform { core, cancellation in
            try await core.chatRecommendations(chatId: chatId, cancellation: cancellation)
        }
    }
}

extension CoreSession {
    func recommendationMemoryDraft(chatId: String, recommendation: ChatRecommendationRecord) async throws -> RecommendationDraftRecord {
        try await perform { core, cancellation in
            try await core.recommendationMemoryDraft(chatId: chatId, recommendation: recommendation, cancellation: cancellation)
        }
    }

    func resolveChatRecommendation(chatId: String, recommendationId: String) async throws {
        try await perform { core, cancellation in
            try await core.resolveChatRecommendation(chatId: chatId, recommendationId: recommendationId, cancellation: cancellation)
        }
    }
}

extension AppStrings {
    static var recommendationsInsufficientCredits: String { localized("memories.suggestion_insufficient_credits") }
    static var recommendationsMemoryNotFound: String { localized("memories.suggestion_not_found") }
    static var recommendationsConnectionProblem: String { localized("memories.suggestion_connection_problem") }
}

/// The unsaved Memory draft a recommendation produced, handed to Settings >
/// Memories (web `memoryDraftSuggestion` store). The editor reads it through
/// `draft(forExisting:)`; a successful save calls `didSave()`, which resolves
/// the recommendation (removes it from the card, encrypted state written back).
@MainActor
final class MemoryDraftSuggestionStore {
    static let shared = MemoryDraftSuggestionStore()

    struct Pending {
        let draft: SettingsMemoryDraft
        /// Id of the Memory an update edits; `nil` for a new Memory.
        let existingID: String?
        let chatId: String
        let recommendationId: String
    }

    private(set) var pending: Pending?
    var resolve: ((String, String) async -> Void)?

    func offer(_ pending: Pending, resolve: @escaping (String, String) async -> Void) {
        self.pending = pending
        self.resolve = resolve
    }

    /// The draft for the editor of `existingID` (`nil` = Create memory page).
    func draft(forExisting existingID: String?) -> SettingsMemoryDraft? {
        guard let pending, pending.existingID == existingID else { return nil }
        return pending.draft
    }

    func discard() { pending = nil; resolve = nil }

    func didSave() {
        guard let pending, let resolve else { return }
        discard()
        Task { await resolve(pending.chatId, pending.recommendationId) }
    }
}

extension ChatRecommendation {
    /// Maps a core record to the card's item (kinds/actions are 1:1).
    init(record: ChatRecommendationRecord) {
        self.init(
            id: record.id,
            kind: record.kind == .workflow ? .workflow : .memory,
            action: record.action == .update ? .update : .create,
            targetID: record.targetId,
            title: record.title,
            summary: record.summary
        )
    }
}

@MainActor
final class ChatRecommendationsModel: ObservableObject {
    @Published private(set) var items: [ChatRecommendation] = []
    @Published private(set) var busyID: String?
    @Published private(set) var statusText: String?

    private let source: ChatRecommendationsSource?
    private let openMemoryEditor: @MainActor (String?) -> Void
    private var generation = 0
    private var chatId: String?
    private var records: [String: ChatRecommendationRecord] = [:]

    /// `source` is `nil` when the app's core could not be created.
    /// `openMemoryEditor` opens Settings > Memories on the draft (`nil` = the
    /// create page, else the Memory an update edits).
    init(source: ChatRecommendationsSource?,
         openMemoryEditor: @escaping @MainActor (String?) -> Void = ChatRecommendationsModel.openSettingsMemoryEditor) {
        self.source = source
        self.openMemoryEditor = openMemoryEditor
    }

    /// Opens the Memory editor through the app's settings deep link
    /// (`settings_memories/create` or `settings_memories/<id>`).
    static func openSettingsMemoryEditor(_ existingID: String?) {
        let page = existingID.map { "settings_memories/\($0)" } ?? "settings_memories/create"
        guard let url = URL(string: "openmates://settings/\(page)") else { return }
        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
    }

    /// Loads the open recommendations of `chatId`; a failed read hides the card
    /// (the web hides it for unreadable state too) and is logged.
    func hydrate(chatId: String) async {
        generation += 1
        let token = generation
        busyID = nil
        statusText = nil
        self.chatId = chatId
        guard let source else { items = []; records = [:]; return }
        do {
            let records = try await source.chatRecommendations(chatId: chatId)
            guard token == generation else { return }
            // Workflow drafts have no Apple surface yet: no dead Accept button.
            let memories = records.filter { $0.kind == .memory }
            self.records = Dictionary(memories.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            items = memories.map { ChatRecommendation(record: $0) }
        } catch is CancellationError {
            return
        } catch {
            guard token == generation else { return }
            items = []
            NativeDiagnostics.info("chat_recommendations_failed", category: "chat_recommendations")
        }
    }

    /// An action on a card. Drafts (billed create-draft/update-preview request,
    /// Memory editor, workflow panel) are not in the Apple core yet, so the
    /// failure text is shown and the recommendation stays (web keeps it too).
    func perform(_ item: ChatRecommendation) {
        Task { await run(item) }
    }

    /// Accept: billed draft, then the Memory editor. The item stays on the card.
    func run(_ item: ChatRecommendation) async {
        guard busyID == nil, let source, let chatId, let record = records[item.id] else { return }
        busyID = item.id
        statusText = nil
        defer { if busyID == item.id { busyID = nil } }
        do {
            let result = try await source.recommendationMemoryDraft(chatId: chatId, recommendation: record)
            guard self.chatId == chatId, items.contains(where: { $0.id == item.id }) else { return }
            switch result.status {
            case .draft:
                guard let fields = result.fields else { statusText = AppStrings.recommendationsDraftFailed; return }
                MemoryDraftSuggestionStore.shared.offer(
                    .init(draft: SettingsMemoryDraft(fields), existingID: result.existingId,
                          chatId: chatId, recommendationId: item.id)
                ) { [weak source] chatId, recommendationId in
                    do { try await source?.resolveChatRecommendation(chatId: chatId, recommendationId: recommendationId) }
                    catch { NativeDiagnostics.info("chat_recommendation_resolve_failed", category: "chat_recommendations") }
                }
                openMemoryEditor(result.existingId)
            case .upToDate: statusText = AppStrings.recommendationsMemoryUpToDate
            case .insufficientCredits: statusText = AppStrings.recommendationsInsufficientCredits
            case .memoryNotFound: statusText = AppStrings.recommendationsMemoryNotFound
            case .networkUnavailable: statusText = AppStrings.recommendationsConnectionProblem
            case .requestFailed: statusText = AppStrings.recommendationsDraftFailed
            }
        } catch is CancellationError {
            return
        } catch {
            statusText = AppStrings.recommendationsDraftFailed
        }
    }
}

struct ChatRecommendationsContainer: View {
    let chatId: String
    let category: String?
    /// Changes whenever the turn state changes so the card re-reads after a reply.
    let refreshKey: String

    @StateObject private var model = ChatRecommendationsModel(source: CoreSession.shared)

    var body: some View {
        RecommendationsCardView(items: model.items, category: category,
                                busyID: model.busyID, statusText: model.statusText) { item in
            model.perform(item)
        }
        .task(id: "\(chatId)|\(refreshKey)") { await model.hydrate(chatId: chatId) }
    }
}
