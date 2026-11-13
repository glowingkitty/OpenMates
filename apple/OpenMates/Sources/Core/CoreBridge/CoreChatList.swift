// The app's chat list from the Rust core (plan apple-client-core-migration
// A4 lane 2). Created at app start with the core (`CoreChatList.launch()`
// from `OpenMatesApp.init`, right after `CoreSession.launch()`), so the
// core's cached list (`ChatList(Cached)`, emitted by `start` before any
// network request) is held before the sidebar first appears.
//
// It keeps the core's last `ChatList` snapshot exactly as the core gives it
// (rows in display order, completeness Cached/Partial/Complete) and publishes
// it on the main actor. Each `ChatList` event replaces the whole snapshot
// once; nothing else rebuilds it (no per-stream-update work). It runs
// `bootSync` after each admission, `refreshChats` on pull-to-refresh and
// `switchTeam` when the selected team changes, each through `CoreSession` with
// a `CoreCancellation`, an error branch and a `core.list.*` timing line.
// Sign-out, expiry and access denial empty it. No ordering, grouping, dedup,
// unread or draft rule is computed here; the mapper copies fields.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order
// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.client.shared-rust-policy

import Combine
import Foundation

@MainActor
final class CoreChatList: ObservableObject {
    /// The app's list; attached to the app's core by `launch()`. Unit tests
    /// create their own instance and attach it to a test core.
    static let shared = CoreChatList()

    /// Mapped rows in the core's display order.
    @Published private(set) var chats: [Chat] = []
    /// What the core decided for each row (unread, draft-only, draft preview), by chat id.
    @Published private(set) var presentations: [String: ChatSidebarRowPresentation] = [:]
    /// Completeness of the last `ChatList` event; `nil` before the first one.
    @Published private(set) var completeness: ListCompletenessRecord?
    /// The last failed list call (`bootSync`, `refreshChats`, `switchTeam`); cancellations are not errors.
    @Published private(set) var lastError: CoreError?
    /// Rows of the last event the sidebar cannot show (saved-item home entries,
    /// flagged by the core's `isSavedItem`).
    private(set) var refusedRowCount = 0
    /// Saved-item home entries of the last event, in core order. Like the web
    /// sidebar, they are not chat rows; they are kept for the home cards.
    @Published private(set) var savedItemIDs: [String] = []
    /// Chats the account has in this scope as the core last reported it
    /// (`nil` until reported). Counts chat rows only, not saved items.
    @Published private(set) var totalCount: Int?
    /// Team the core list was last switched to (`nil`: personal, the scope after start).
    private(set) var coreTeamID: String?

    private var session: CoreSession?
    private var subscriptions: Set<AnyCancellable> = []
    private var chatsByID: [String: Chat] = [:]
    private var syncTask: Task<Void, Never>?
    private var requestedTeamID: String?
    private var admitted = false
    private var switchInFlight = false
    private var measuredFrom = NativeSyncPerfLog.now()
    private var loggedCompleteness: Set<String> = []

    init() {}

    /// Attaches the app's list to the app's core and follows the selected
    /// team. Without a core (creation failed, see `CoreSession.launchError`)
    /// the list stays empty and the failure is logged once.
    static func launch() {
        guard let session = CoreSession.shared else {
            NativeDiagnostics.error("core_chat_list_unavailable reason=no_core", category: "core_bridge")
            return
        }
        shared.attach(session, teams: TeamWorkspaceContext.shared.$teamID.eraseToAnyPublisher())
    }

    /// Follows `session`'s events and, when given, the selected team.
    func attach(_ session: CoreSession, teams: AnyPublisher<String?, Never>? = nil) {
        guard self.session !== session else { return }
        self.session = session
        subscriptions = []
        measuredFrom = NativeSyncPerfLog.now()
        session.events.sink { [weak self] event in
            self?.apply(event)
        }.store(in: &subscriptions)
        teams?.removeDuplicates().sink { [weak self] teamID in
            self?.selectedTeamDidChange(teamID)
        }.store(in: &subscriptions)
    }

    /// The mapped row of `id` in the current snapshot (read-only accessor
    /// for callers that still hold a chat id).
    func chat(for id: String) -> Chat? { chatsByID[id] }

    /// Re-read the list in the core (`refreshChats`); the result arrives as a `ChatList` event.
    func refresh() async {
        await run("refresh") { core, cancellation in try await core.refreshChats(cancellation: cancellation) }
    }

    /// Switch the core to `teamID` (`nil`: personal); the core admits the
    /// session there and emits that scope's list, which replaces this one.
    @discardableResult
    func switchTeam(_ teamID: String?) async -> Bool {
        requestedTeamID = teamID
        switchInFlight = true
        defer { switchInFlight = false }
        let switched = await run("switch_team") { core, cancellation in
            try await core.switchTeam(teamId: teamID, cancellation: cancellation)
        }
        if switched { coreTeamID = teamID }
        return switched
    }

    /// Applies one core event; only `ChatList` and `Session` events matter here.
    func apply(_ event: ViewEventRecord) {
        switch event {
        case .chatList(let rows, let completeness, let totalCount):
            replace(rows: rows, completeness: completeness, totalCount: totalCount)
        case .session(let session):
            switch session {
            case .admitted:
                admitted = true
                sessionAdmitted()
            case .signedOut, .expired, .accessDenied:
                admitted = false
                clear()
            case .restored, .verificationRequired:
                break
            }
        default:
            break
        }
    }

    /// Chats known to the account but not in the list yet; the web sidebar's
    /// "Load more (N)" count. Zero until the core reports a total.
    var remainingChatCount: Int { max(0, (totalCount ?? chats.count) - chats.count) }

    private func replace(rows: [ChatListRowRecord], completeness: ListCompletenessRecord, totalCount: UInt64?) {
        var mapped: [Chat] = []
        mapped.reserveCapacity(rows.count)
        var presentations: [String: ChatSidebarRowPresentation] = [:]
        var refused = 0
        var savedItems: [String] = []
        for row in rows {
            if row.isSavedItem {
                savedItems.append(row.id)
                refused += 1
                continue
            }
            guard let result = CoreChatRowMapper.map(row) else {
                refused += 1
                continue
            }
            mapped.append(result.chat)
            presentations[result.chat.id] = result.presentation
        }
        chatsByID = Dictionary(mapped.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        refusedRowCount = refused
        savedItemIDs = savedItems
        self.totalCount = totalCount.map { Int(clamping: $0) }
        self.presentations = presentations
        self.completeness = completeness
        chats = mapped
        logFirst(completeness, rows: mapped.count, refused: refused)
    }

    /// One timing line per completeness level and sign-in: the first cached
    /// list shown, the first network page, the complete list. Counts only.
    private func logFirst(_ completeness: ListCompletenessRecord, rows: Int, refused: Int) {
        let name: String
        switch completeness {
        case .cached: name = "cached"
        case .partial: name = "partial"
        case .complete: name = "complete"
        }
        guard loggedCompleteness.insert(name).inserted else { return }
        NativeSyncPerfLog.info(
            "phase=core.list.\(name) rows=\(rows) refused=\(refused) ms=\(NativeSyncPerfLog.ms(since: measuredFrom))")
    }

    private func sessionAdmitted() {
        // A running team switch admits the session itself and emits its list.
        guard !switchInFlight else { return }
        syncTask?.cancel()
        if requestedTeamID != coreTeamID {
            let teamID = requestedTeamID
            syncTask = Task { [weak self] in _ = await self?.switchTeam(teamID) }
        } else {
            syncTask = Task { [weak self] in
                _ = await self?.run("boot_sync") { core, cancellation in try await core.bootSync(cancellation: cancellation) }
            }
        }
    }

    private func selectedTeamDidChange(_ teamID: String?) {
        requestedTeamID = teamID
        guard admitted, teamID != coreTeamID else { return }
        syncTask?.cancel()
        syncTask = Task { [weak self] in _ = await self?.switchTeam(teamID) }
    }

    private func clear() {
        syncTask?.cancel()
        syncTask = nil
        chatsByID = [:]
        refusedRowCount = 0
        savedItemIDs = []
        totalCount = nil
        coreTeamID = nil
        presentations = [:]
        completeness = nil
        chats = []
        loggedCompleteness = []
        measuredFrom = NativeSyncPerfLog.now()
    }

    /// Runs one list call through `CoreSession.perform` (cancelled with the
    /// calling task). Logs the call, its outcome class and duration; a
    /// failure other than cancellation is kept in `lastError`.
    @discardableResult
    private func run(_ phase: String,
                     _ operation: (ViewModelCore, CoreCancellation) async throws -> Void) async -> Bool {
        guard let session else {
            NativeSyncPerfLog.warning("phase=core.list.\(phase) outcome=no_core ms=0")
            return false
        }
        let started = NativeSyncPerfLog.now()
        do {
            try await session.perform(operation)
            lastError = nil
            NativeSyncPerfLog.info(
                "phase=core.list.\(phase) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            return true
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.list.\(phase) outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            if let coreError = error as? CoreError, coreError != .Cancelled { lastError = coreError }
            return false
        }
    }
}
