// The app's chat list from the Rust core (plan apple-client-core-migration
// A4 lane 2). Created at app start with the core (`CoreChatList.launch()`
// from `OpenMatesApp.init`, right after `CoreSession.launch()`), so the
// core's cached list (`ChatList(Cached)`, emitted by `start` before any
// network request) is held before the sidebar first appears.
//
// It keeps the core's last `ChatList` snapshot exactly as the core gives it
// (rows in display order, completeness Cached/Partial/Complete) and publishes
// it on the main actor. Each `ChatList` event replaces the whole snapshot
// once; nothing else rebuilds it (no per-stream-update work). After admission,
// the core restores the selected workspace and resumes its last opened chat
// before boot sync. Pull-to-refresh, explicit paging or later Team switches
// use their dedicated core commands, each through `CoreSession` with
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
    @Published private(set) var isLoadingMoreMetadata = false
    /// Team the core list was last switched to (`nil`: personal, the scope after start).
    private(set) var coreTeamID: String?

    private var session: CoreSession?
    private var subscriptions: Set<AnyCancellable> = []
    private var chatsByID: [String: Chat] = [:]
    private var syncTask: Task<Void, Never>?
    private var startupResume: Task<[String], Never>?
    private var startupBootList: Task<Void, Never>?
    private var startupBootListGeneration = UUID()
    private var startupBootListPending = false
    private var foregroundOpenWaiting = false
    private var startupHydration: Task<Void, Never>?
    private var startupHydrationIDs: [String] = []
    private var startupInterrupted = false
    private var startupScopeReady = true
    private var scheduledInitialSync = false
    private var metadataPageTask: Task<Bool, Never>?
    private var metadataPageRequest = UUID()
    private var reconnectRefresh: Task<Void, Never>?
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
        let workspace = TeamWorkspaceContext.shared
        shared.attach(session, teams: workspace.$teamID.eraseToAnyPublisher(),
                      initialScopeReady: workspace.$hasRestoredInitialSelection.eraseToAnyPublisher())
    }

    /// Follows `session`'s events and, when given, the selected team.
    func attach(_ session: CoreSession, teams: AnyPublisher<String?, Never>? = nil,
                initialScopeReady: AnyPublisher<Bool, Never>? = nil) {
        guard self.session !== session else { return }
        self.session = session
        subscriptions = []
        startupScopeReady = initialScopeReady == nil
        measuredFrom = NativeSyncPerfLog.now()
        session.events.sink { [weak self] event in
            self?.apply(event)
        }.store(in: &subscriptions)
        teams?.removeDuplicates().sink { [weak self] teamID in
            self?.selectedTeamDidChange(teamID)
        }.store(in: &subscriptions)
        let window = CoreChatWindow.shared
        window.deliberateOpenSettled.sink { [weak self] in
            self?.continueStartupHydrationAfterOpen()
        }.store(in: &subscriptions)
        window.deliberateOpenStarted.sink { [weak self] in
            guard let self else { return }
            self.interruptStartupNavigation()
            self.startupHydration?.cancel()
            self.preemptStartupBootList()
        }.store(in: &subscriptions)
        window.changes.sink { [weak self] change in
            if case .window = change { self?.resumeStartupBootListAfterForeground() }
        }.store(in: &subscriptions)
        window.deliberateOpenFinished.sink { [weak self] in
            self?.resumeStartupBootListAfterForeground()
        }.store(in: &subscriptions)
        initialScopeReady?.removeDuplicates().sink { [weak self] ready in
            guard let self else { return }
            self.startupScopeReady = ready
            if ready { self.sessionAdmitted() }
        }.store(in: &subscriptions)
    }

    /// The mapped row of `id` in the current snapshot (read-only accessor
    /// for callers that still hold a chat id).
    func chat(for id: String) -> Chat? { chatsByID[id] }

    /// Re-read the list in the core (`refreshChats`); the result arrives as a `ChatList` event.
    func refresh() async {
        await run("refresh") { core, cancellation in try await core.refreshChats(cancellation: cancellation) }
    }

    /// The core owns the offset and requests exactly one metadata page.
    func loadMoreMetadata() async -> Bool {
        guard admitted, !switchInFlight, requestedTeamID == coreTeamID, metadataPageTask == nil else { return false }
        deferStartupHydration()
        let request = UUID()
        metadataPageRequest = request
        isLoadingMoreMetadata = true
        let page = Task { @MainActor [weak self] in
            guard let self else { return false }
            return await self.run("load_more_metadata") { core, cancellation in
                try await core.loadMoreChatMetadata(cancellation: cancellation)
            }
        }
        metadataPageTask = page
        let loaded = await page.value
        guard metadataPageRequest == request else { return false }
        metadataPageTask = nil
        isLoadingMoreMetadata = false
        return loaded
    }

    private func cancelMetadataPage() {
        metadataPageRequest = UUID()
        metadataPageTask?.cancel()
        metadataPageTask = nil
        isLoadingMoreMetadata = false
    }

    /// Catch up the sidebar, then refresh the opened cohort against the replacement
    /// socket's admitted account. The selected window stays independent.
    func resumeAfterReconnect() {
        pauseReconnectRefresh()
        guard admitted, !switchInFlight, requestedTeamID == coreTeamID, let session else { return }
        startupHydration?.cancel()
        let scope = coreTeamID
        reconnectRefresh = Task(priority: .utility) { @MainActor [weak self] in
            guard let self else { return }
            let refreshed = await self.run("reconnect_refresh") { core, cancellation in
                try await core.refreshChats(cancellation: cancellation)
            }
            guard refreshed, !Task.isCancelled, self.admitted,
                  self.coreTeamID == scope, self.requestedTeamID == scope else { return }
            do {
                // Request zero refreshes selectors without accepting a window event.
                let ids = try await session.perform { core, cancellation in
                    try await core.resumeStartupChat(request: 0, cancellation: cancellation)
                }
                guard !Task.isCancelled, self.admitted,
                      self.coreTeamID == scope, self.requestedTeamID == scope else { return }
                self.startupHydrationIDs = ids
                self.deferStartupHydration()
            } catch {
                NativeSyncPerfLog.warning("phase=core.list.reconnect_cohort outcome=\(CoreSession.errorClass(error))")
            }
        }
    }

    func pauseReconnectRefresh() {
        reconnectRefresh?.cancel()
        reconnectRefresh = nil
    }

    /// Switch the core to `teamID` (`nil`: personal); the core admits the
    /// session there and emits that scope's list, which replaces this one.
    @discardableResult
    func switchTeam(_ teamID: String?) async -> Bool {
        pauseReconnectRefresh()
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
                let needsBootList = !admitted
                admitted = true
                if needsBootList { sessionAdmitted() }
            case .signedOut, .expired, .accessDenied:
                admitted = false
                clear()
            case .restored:
                // A new Rust actor produces a restored event before its list.
                // The same actor's re-admission only sends Admitted.
                admitted = false
                scheduledInitialSync = false
                pauseReconnectRefresh()
                startupResume?.cancel()
                discardStartupHydration()
                resetStartupBootList()
                syncTask?.cancel()
            case .verificationRequired:
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

    /// Foreground navigation supersedes the startup choice and its optional
    /// hydration without removing the local sidebar snapshot.
    func interruptStartupNavigation() {
        startupInterrupted = true
        pauseReconnectRefresh()
        startupResume?.cancel()
        CoreChatWindow.shared.stopStartupSelection()
        deferStartupHydration()
    }

    private func discardStartupHydration() {
        startupHydration?.cancel()
        startupHydration = nil
        startupHydrationIDs = []
    }

    private func deferStartupHydration() {
        startupHydration?.cancel()
        startupHydration = startStartupHydration(after: .seconds(1))
    }

    /// A deliberate open that preempted startup can recover the remaining
    /// cohort. The core has already recorded the navigation, so this read
    /// cannot select a chat or publish a replacement window.
    private func continueStartupHydrationAfterOpen() {
        guard startupInterrupted, startupHydrationIDs.isEmpty, admitted,
              !switchInFlight, requestedTeamID == coreTeamID, let session else { return }
        let scope = coreTeamID
        startupHydration?.cancel()
        startupHydration = Task(priority: .utility) { @MainActor [weak self] in
            do {
                try await Task.sleep(for: .seconds(1))
                guard let self, self.admitted, self.coreTeamID == scope,
                      self.requestedTeamID == scope, !Task.isCancelled else { return }
                let ids = try await session.perform { core, cancellation in
                    try await core.resumeStartupChat(request: 0, cancellation: cancellation)
                }
                guard !Task.isCancelled, self.admitted, self.coreTeamID == scope,
                      self.requestedTeamID == scope else { return }
                self.startupHydrationIDs = ids
                guard !ids.isEmpty else { return }
                await self.run("hydrate_startup") { core, cancellation in
                    try await core.hydrateStartupChats(ids: ids, cancellation: cancellation)
                }
            } catch {
                NativeSyncPerfLog.warning("phase=core.list.resume_hydration outcome=\(CoreSession.errorClass(error))")
            }
        }
    }

    private func startStartupHydration(after delay: Duration? = nil) -> Task<Void, Never>? {
        guard admitted, !startupHydrationIDs.isEmpty, !switchInFlight, requestedTeamID == coreTeamID else { return nil }
        let ids = startupHydrationIDs
        let team = coreTeamID
        return Task(priority: .utility) { @MainActor [weak self] in
            if let delay {
                do { try await Task.sleep(for: delay) } catch { return }
            }
            guard let self, self.admitted, !Task.isCancelled,
                  self.coreTeamID == team, self.requestedTeamID == team else { return }
            await self.run("hydrate_startup") { core, cancellation in
                try await core.hydrateStartupChats(ids: ids, cancellation: cancellation)
            }
        }
    }

    private func bootAfterStartupSelection() async {
        #if DEBUG
        let fixtureStartsAtComposer = ProcessInfo.processInfo.arguments.contains("--ui-test-start-new-chat")
        #else
        let fixtureStartsAtComposer = false
        #endif
        if !startupInterrupted, !fixtureStartsAtComposer {
            let resume = Task { @MainActor in await CoreChatWindow.shared.resumeStartup() }
            startupResume = resume
            let ids = await resume.value
            guard !Task.isCancelled else { return }
            startupResume = nil
            startupHydrationIDs = ids
        }
        guard !Task.isCancelled else { return }
        startupBootListPending = true
        startStartupBootList()
    }

    private func preemptStartupBootList() {
        foregroundOpenWaiting = true
        startupBootListGeneration = UUID()
        startupBootList?.cancel()
        startupBootList = nil
    }

    private func resumeStartupBootListAfterForeground() {
        guard foregroundOpenWaiting else { return }
        foregroundOpenWaiting = false
        if startupBootListPending {
            startStartupBootList()
        } else {
            deferStartupHydration()
        }
    }

    private func resetStartupBootList() {
        preemptStartupBootList()
        startupBootListPending = false
        foregroundOpenWaiting = false
    }

    private func startStartupBootList() {
        guard startupBootListPending, startupBootList == nil, !foregroundOpenWaiting,
              admitted, !switchInFlight, requestedTeamID == coreTeamID else { return }
        let generation = startupBootListGeneration
        startupBootList = Task(priority: .utility) { @MainActor [weak self] in
            guard let self, !Task.isCancelled else { return }
            // Complete sidebar metadata ahead of full background history.
            await self.run("boot_sync") { core, cancellation in
                try await core.bootSync(cancellation: cancellation)
            }
            guard !Task.isCancelled, self.startupBootListGeneration == generation else { return }
            self.startupBootList = nil
            self.startupBootListPending = false
            if self.startupInterrupted {
                self.deferStartupHydration()
            } else {
                self.startupHydration = self.startStartupHydration()
            }
        }
    }

    private func sessionAdmitted() {
        guard admitted, startupScopeReady, !switchInFlight, !scheduledInitialSync else { return }
        scheduledInitialSync = true
        syncTask?.cancel()
        let teamID = requestedTeamID
        syncTask = Task { [weak self] in
            guard let self else { return }
            if teamID != self.coreTeamID {
                self.switchInFlight = true
                let switched = await self.run("startup_team") { core, cancellation in
                    try await core.switchTeamForStartup(teamId: teamID, cancellation: cancellation)
                }
                self.switchInFlight = false
                guard switched, !Task.isCancelled, teamID == self.requestedTeamID else { return }
                self.coreTeamID = teamID
            }
            await self.bootAfterStartupSelection()
        }
    }

    private func selectedTeamDidChange(_ teamID: String?) {
        let changed = requestedTeamID != teamID
        requestedTeamID = teamID
        guard scheduledInitialSync else {
            sessionAdmitted()
            return
        }
        if changed {
            resetStartupBootList()
            discardStartupHydration()
            interruptStartupNavigation()
            cancelMetadataPage()
        }
        guard admitted, teamID != coreTeamID || switchInFlight else { return }
        pauseReconnectRefresh()
        syncTask?.cancel()
        syncTask = Task { [weak self] in _ = await self?.switchTeam(teamID) }
    }

    private func clear() {
        cancelMetadataPage()
        discardStartupHydration()
        interruptStartupNavigation()
        startupInterrupted = false
        scheduledInitialSync = false
        resetStartupBootList()
        pauseReconnectRefresh()
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
