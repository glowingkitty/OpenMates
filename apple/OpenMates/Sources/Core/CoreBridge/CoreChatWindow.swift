// The open chat's messages from the Rust core (plan apple-client-core-migration
// A4 lane 3). Created at app start with the core (`CoreChatWindow.launch()`
// from `OpenMatesApp.init`, right after `CoreChatList.launch()`), so its event
// subscription exists before the first chat opens.
//
// It opens a chat through the core view model (`openChat` with a Swift
// request id), keeps the core's open window as mapped `Message` values in core
// order and tells its reader what changed through `changes`:
// - a `ChatWindow` event (cached, first page, strict, live, older page)
//   replaces the window once; a message whose record did not change keeps its
//   mapped value, so the render form is rebuilt only for changed messages;
// - a `MessageUpdated` event (one reply-text update while a reply streams)
//   patches that one message; the window is never re-mapped per update.
// Events of another chat or of a superseded open are ignored. `loadOlder`
// merges the next older page in the core, `close` closes the window in the
// core, and sign-out, expiry and access denial empty it. Every core call goes
// through `CoreSession.perform` with a `CoreCancellation` tied to the calling
// task, has an error branch and a `core.window.*` timing line. No ordering,
// merge, decrypt or cache rule is computed here; the mapper copies fields.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.viewmodel.stream-updates, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order
// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.client.shared-rust-policy

import Combine
import Foundation

/// One change of the open window, for the chat view model.
enum CoreChatWindowChange: Equatable {
    enum Reason: Equatable {
        /// The first window of a newly opened chat.
        case opened
        /// The window after `loadOlder` merged an older page.
        case olderPage
        /// Any later window of the same chat (strict read, live update, re-open).
        case updated
    }

    /// The whole window was replaced.
    case window(chatId: String, reason: Reason)
    /// One message changed while its reply streams (`CoreChatWindow.message(id:)`).
    case message(chatId: String, messageId: String)
    /// The open chat is gone or unreadable; the window is empty.
    case unavailable(chatId: String)
    /// The window was closed or the session ended.
    case cleared
}

#if DEBUG
/// A viewport probe reads only these monotonic timestamps from the accepted window.
struct CoreChatWindowStartupTimings: Equatable {
    private(set) var cached: Int?
    private(set) var firstServerPage: Int?
    private(set) var canonical: Int?
    private(set) var refreshed: Int?
    var deliberateOpenStarted: Int?
    var deliberateOpenSettled: Int?

    mutating func recordWindow(source: ChatWindowSourceRecord, uptimeMS: Int) {
        switch source {
        case .cached, .cachedOffline:
            if cached == nil { cached = uptimeMS }
        case .firstPage:
            if firstServerPage == nil { firstServerPage = uptimeMS }
        case .canonical:
            // A one-page canonical read emits no separate first-page event.
            if firstServerPage == nil { firstServerPage = uptimeMS }
            if canonical == nil { canonical = uptimeMS }
            if refreshed == nil { refreshed = uptimeMS }
        case .cacheSettled:
            // A validated local window can settle an open without server rows.
            if refreshed == nil { refreshed = uptimeMS }
        default:
            break
        }
    }
}
#endif

/// How an `open` call ended.
enum CoreChatOpenOutcome: Equatable {
    case opened
    /// The core does not own this chat shape: not a saved chat id, a volatile
    /// chat, or no account in the core. The caller's local shape applies.
    case refused
    case failed(CoreError)
    /// Cancelled by the caller or superseded by a newer open.
    case cancelled
    /// The app has no core (creation failed, unit-test host).
    case noCore
}

struct CoreStartupChatSelection: Equatable {
    let chatID: String
    let request: UInt64
}

@MainActor
final class CoreChatWindow {
    /// The app's window; attached to the app's core by `launch()`. Unit tests
    /// create their own instance and attach it to a test core.
    static let shared = CoreChatWindow()

    /// The open chat (`nil`: none).
    private(set) var chatId: String?
    /// Mapped messages of the open window, oldest first (core order).
    private(set) var messages: [Message] = []
    /// Origin of the last window; `nil` before the first one.
    private(set) var source: ChatWindowSourceRecord?
    #if DEBUG
    let benchmarkChanges = CurrentValueSubject<CoreChatWindowStartupTimings, Never>(.init())
    private let measureStartupWindow: Bool
    private var pendingDeliberateOpenStartedUptimeMS: Int?
    #endif
    /// The core's title and category of the open chat (empty until a window arrives).
    private(set) var title = ""
    private(set) var category = ""
    /// Older messages exist in the core (`hasMoreBefore`, else not `historyComplete`).
    private(set) var hasOlderMessages = false
    /// A network refresh of the open window is still running in the core.
    private(set) var refreshing = false
    /// The request id of the current open; live windows reuse it.
    private(set) var openRequest: UInt64 = 0
    /// The failure the core reported for the current open (`ChatOpenFailed`).
    private(set) var openFailure: ViewErrorKindRecord?
    /// The last failed window call; cancellations and refusals are not errors.
    private(set) var lastError: CoreError?
    /// Messages mapped since creation (diagnostics and tests: proves unchanged
    /// messages are not re-mapped).
    private(set) var mappedMessageCount = 0
    /// What changed, in event order; the chat view model applies it.
    let changes = PassthroughSubject<CoreChatWindowChange, Never>()
    let startupSelections = PassthroughSubject<CoreStartupChatSelection, Never>()
    let unavailableStartupChats = PassthroughSubject<String, Never>()
    let deliberateOpenSettled = PassthroughSubject<Void, Never>()
    let deliberateOpenStarted = PassthroughSubject<Void, Never>()
    let deliberateOpenFinished = PassthroughSubject<Void, Never>()
    private(set) var startupSelection: CoreStartupChatSelection?
    private var startupRequest: UInt64?

    var isAttached: Bool { session != nil }

    private var session: CoreSession?
    private var subscriptions: Set<AnyCancellable> = []
    private var nextRequest: UInt64 = 0
    private var records: [MessageViewRecord] = []
    private var indexByID: [String: Int] = [:]
    private var windowsSinceOpen = 0
    private var olderPagePending = false
    private var openedAt = NativeSyncPerfLog.now()

    #if DEBUG
    init(measureStartupWindow: Bool = ProcessInfo.processInfo.arguments.contains("--ui-test-startup-chat-readiness")) {
        self.measureStartupWindow = measureStartupWindow
    }
    #else
    init() {}
    #endif

    /// Attaches the app's window to the app's core. Without a core (creation
    /// failed, see `CoreSession.launchError`) opens report `.noCore`.
    static func launch() {
        guard let session = CoreSession.shared else {
            NativeDiagnostics.error("core_chat_window_unavailable reason=no_core", category: "core_bridge")
            return
        }
        shared.attach(session)
    }

    /// Follows `session`'s events.
    func attach(_ session: CoreSession) {
        guard self.session !== session else { return }
        self.session = session
        subscriptions = []
        session.events.sink { [weak self] event in
            self?.apply(event)
        }.store(in: &subscriptions)
    }

    /// The mapped message `id` of the open window.
    func message(id: String) -> Message? {
        indexByID[id].map { messages[$0] }
    }

    /// Makes `chatId` the chat this window follows under a new request id and
    /// returns it; events of any older open are ignored from now on. Opening
    /// another chat empties the window first; re-opening the same chat keeps
    /// it until the core's next window replaces it. `open(request:chatId:)`
    /// then asks the core.
    @discardableResult
    func begin(chatId: String) -> UInt64 {
        stopStartupSelection()
        #if DEBUG
        pendingDeliberateOpenStartedUptimeMS = nil
        updateStartupTimings { $0 = .init() }
        #endif
        nextRequest &+= 1
        if self.chatId != chatId {
            resetWindow()
            self.chatId = chatId
            windowsSinceOpen = 0
        }
        openRequest = nextRequest
        openFailure = nil
        olderPagePending = false
        openedAt = NativeSyncPerfLog.now()
        return openRequest
    }

    /// Reserves a request that can accept a scoped choice made by the core.
    func beginStartupSelection() -> UInt64? {
        guard chatId == nil, startupRequest == nil else { return nil }
        nextRequest &+= 1
        openRequest = nextRequest
        startupRequest = openRequest
        openedAt = NativeSyncPerfLog.now()
        return openRequest
    }

    /// The initial local paint and the authoritative network read share a request.
    func resumeStartup() async -> [String] {
        guard let session, let request = beginStartupSelection() else { return [] }
        do {
            try await session.perform { core, cancellation in
                try await core.paintStartupChat(request: request, cancellation: cancellation)
            }
            guard !Task.isCancelled, startupRequest == request else { return [] }
            return try await session.perform { core, cancellation in
                try await core.resumeStartupChat(request: request, cancellation: cancellation)
            }
        } catch {
            NativeSyncPerfLog.warning("phase=core.window.startup outcome=\(CoreSession.errorClass(error))")
            return []
        }
    }

    func stopStartupSelection() {
        startupRequest = nil
        startupSelection = nil
    }

    func adoptedStartupRequest(for id: String) -> UInt64? {
        guard startupSelection?.chatID == id, chatId == id else { return nil }
        return startupSelection?.request
    }

    /// A request id for a core action on the open window (send, edit, retry,
    /// delete message), newer than the current open, so the windows it emits
    /// are accepted; the open itself is unchanged. A later `begin` supersedes it.
    func nextActionRequest() -> UInt64 {
        nextRequest &+= 1
        return nextRequest
    }

    /// `begin` plus `open(request:chatId:)`.
    func open(chatId: String) async -> CoreChatOpenOutcome {
        await open(request: begin(chatId: chatId), chatId: chatId)
    }

    /// Opens `chatId` in the core as the window of `request` (from `begin`).
    /// Windows arrive as events before and while this runs: the cached window
    /// first, then the strict one. Returns once the core's strict read ended.
    func open(request: UInt64, chatId: String) async -> CoreChatOpenOutcome {
        guard let session else {
            NativeSyncPerfLog.warning("phase=core.window.open outcome=no_core ms=0")
            return .noCore
        }
        guard request == openRequest, self.chatId == chatId else { return .cancelled }
        #if DEBUG
        if measureStartupWindow {
            // Publish the start on the next existing window/settle update.
            pendingDeliberateOpenStartedUptimeMS = Int(ProcessInfo.processInfo.systemUptime * 1_000)
        }
        #endif
        // A restore still running holds no account yet; wait for its outcome
        // instead of reading it as signed out.
        await session.settled()
        guard request == openRequest, self.chatId == chatId, !Task.isCancelled else { return .cancelled }
        deliberateOpenStarted.send(())
        defer {
            if request == openRequest { deliberateOpenFinished.send(()) }
        }
        let started = NativeSyncPerfLog.now()
        do {
            try await session.perform { core, cancellation in
                try await core.openChat(request: request, chatId: chatId, cancellation: cancellation)
            }
            NativeSyncPerfLog.info(
                "phase=core.window.open outcome=ok windows=\(windowsSinceOpen) ms=\(NativeSyncPerfLog.ms(since: started))")
            if request == openRequest {
                lastError = nil
                deliberateOpenSettled.send(())
                #if DEBUG
                if measureStartupWindow {
                    updateStartupTimings {
                        $0.deliberateOpenStarted = pendingDeliberateOpenStartedUptimeMS
                        $0.deliberateOpenSettled = Int(ProcessInfo.processInfo.systemUptime * 1_000)
                    }
                }
                #endif
            }
            return .opened
        } catch let error as CoreError {
            NativeSyncPerfLog.warning(
                "phase=core.window.open outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            return settleFailedOpen(error, request: request, chatId: chatId, session: session)
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.window.open outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            let wrapped = CoreError.Internal(reason: String(describing: type(of: error)))
            return settleFailedOpen(wrapped, request: request, chatId: chatId, session: session)
        }
    }

    /// Refresh the current window for an external notification.
    func refreshOpenChat(chatId: String) async -> Bool {
        guard self.chatId == chatId else { return false }
        let request = nextActionRequest()
        return await run("refresh_open") { core, cancellation in
            try await core.refreshOpenChat(request: request, chatId: chatId, cancellation: cancellation)
        }
    }

    /// Merge the next older page into the open window in the core; the merged
    /// window arrives as a `ChatWindow` event (reason `.olderPage`). Returns
    /// whether the core call succeeded.
    func loadOlder() async -> Bool {
        guard let chatId else { return false }
        let request = openRequest
        olderPagePending = true
        let succeeded = await run("load_older") { core, cancellation in
            try await core.loadOlder(request: request, chatId: chatId, cancellation: cancellation)
        }
        if !succeeded { olderPagePending = false }
        return succeeded
    }

    /// Closes the window of `request` in the core and empties it here; a
    /// newer open (another request) is left alone. The core's `closeChat`
    /// takes no cancellation; it emits nothing and never reads the network.
    func close(request: UInt64, expectedChatId: String? = nil) async {
        guard request == openRequest, let chatId,
              expectedChatId == nil || expectedChatId == chatId else { return }
        stopStartupSelection()
        resetWindow()
        self.chatId = nil
        changes.send(.cleared)
        await run("close") { core, _ in try await core.closeChat(chatId: chatId) }
    }

    /// Applies one core event; only window, message, chat and session events matter here.
    func apply(_ event: ViewEventRecord) {
        switch event {
        case .chatWindow(let request, let window):
            if startupRequest == request {
                if chatId != window.chatId {
                    resetWindow()
                    chatId = window.chatId
                    windowsSinceOpen = 0
                }
                replace(request: request, window: window)
                let selection = CoreStartupChatSelection(chatID: window.chatId, request: request)
                if startupSelection != selection {
                    startupSelection = selection
                    startupSelections.send(selection)
                }
            } else {
                replace(request: request, window: window)
            }
        case .messageUpdated(let request, let chatId, let message):
            update(request: request, chatId: chatId, record: message)
        case .chatUnavailable(let chatId):
            guard chatId == self.chatId else { return }
            let removesStartupSelection = startupSelection?.chatID == chatId
            resetWindow()
            changes.send(.unavailable(chatId: chatId))
            if removesStartupSelection {
                startupSelection = nil
                self.chatId = nil
                unavailableStartupChats.send(chatId)
            }
        case .chatOpenFailed(let request, let chatId, let error):
            guard request == openRequest, chatId == self.chatId else { return }
            openFailure = error
        case .session(let session):
            switch session {
            case .signedOut, .expired, .accessDenied:
                stopStartupSelection()
                guard chatId != nil else { return }
                resetWindow()
                chatId = nil
                changes.send(.cleared)
            case .restored, .admitted, .verificationRequired:
                break
            }
        default:
            break
        }
    }

    /// A window of the open chat from this open or a later request (a live
    /// update reuses the open's request; a send uses its own, newer one from
    /// `nextActionRequest`).
    private func replace(request: UInt64, window: ChatWindowViewRecord) {
        guard window.chatId == chatId, request >= openRequest else { return }
        var mapped: [Message] = []
        mapped.reserveCapacity(window.messages.count)
        var index: [String: Int] = [:]
        index.reserveCapacity(window.messages.count)
        var previousCreatedAt = ""
        for record in window.messages {
            let message: Message
            if let old = indexByID[record.id], records[old] == record,
               record.metadata.createdAt != nil || messages[old].createdAt == previousCreatedAt {
                message = messages[old]
            } else {
                message = CoreMessageMapper.map(record, chatId: window.chatId, fallbackCreatedAt: previousCreatedAt)
                mappedMessageCount += 1
            }
            index[record.id] = mapped.count
            mapped.append(message)
            previousCreatedAt = message.createdAt
        }
        records = window.messages
        indexByID = index
        messages = mapped
        source = window.source
        #if DEBUG
        if measureStartupWindow, !mapped.isEmpty {
            let uptime = Int(ProcessInfo.processInfo.systemUptime * 1_000)
            updateStartupTimings {
                $0.deliberateOpenStarted = pendingDeliberateOpenStartedUptimeMS
                $0.recordWindow(source: window.source, uptimeMS: uptime)
            }
        }
        #endif
        title = window.title
        category = window.category
        hasOlderMessages = window.hasMoreBefore ?? !window.historyComplete
        refreshing = window.refreshing
        windowsSinceOpen += 1
        let reason: CoreChatWindowChange.Reason
        if olderPagePending {
            olderPagePending = false
            reason = .olderPage
        } else {
            reason = windowsSinceOpen == 1 ? .opened : .updated
        }
        if windowsSinceOpen == 1 {
            NativeSyncPerfLog.info(
                "phase=core.window.first source=\(Self.sourceName(window.source)) messages=\(mapped.count) ms=\(NativeSyncPerfLog.ms(since: openedAt))")
        }
        changes.send(.window(chatId: window.chatId, reason: reason))
    }

    /// One message of the open window as it is now; an id not shown yet is
    /// appended (the core's `MessageUpdated` contract).
    private func update(request: UInt64, chatId: String, record: MessageViewRecord) {
        guard chatId == self.chatId, request >= openRequest else { return }
        if let index = indexByID[record.id] {
            guard records[index] != record else { return }
            messages[index] = CoreMessageMapper.map(record, chatId: chatId, fallbackCreatedAt: messages[index].createdAt)
            records[index] = record
        } else {
            let message = CoreMessageMapper.map(record, chatId: chatId, fallbackCreatedAt: messages.last?.createdAt ?? "")
            indexByID[record.id] = messages.count
            messages.append(message)
            records.append(record)
        }
        mappedMessageCount += 1
        changes.send(.message(chatId: chatId, messageId: record.id))
    }

    private func settleFailedOpen(_ error: CoreError, request: UInt64, chatId: String,
                                  session: CoreSession) -> CoreChatOpenOutcome {
        let current = request == openRequest && self.chatId == chatId
        switch error {
        case .Cancelled:
            return .cancelled
        case .Invalid:
            // The core refuses chat shapes it does not own (id that is not a
            // saved chat id, volatile chat): typed, not a failure.
            if current { forgetRefusedOpen() }
            return .refused
        case .Authentication where !Self.holdsAccount(session.state):
            if current { forgetRefusedOpen() }
            return .refused
        default:
            guard current else { return .cancelled }
            lastError = error
            // The core keeps a window that was already shown; without one it closed it.
            if windowsSinceOpen == 0 { self.chatId = nil }
            return .failed(error)
        }
    }

    private func forgetRefusedOpen() {
        guard windowsSinceOpen == 0 else { return }
        resetWindow()
        chatId = nil
    }

    private static func holdsAccount(_ state: CoreSessionState) -> Bool {
        switch state {
        case .restored, .admitted, .verificationRequired: return true
        case .notStarted, .starting, .signedOut, .expired, .accessDenied, .failed: return false
        }
    }

    #if DEBUG
    private func updateStartupTimings(_ update: (inout CoreChatWindowStartupTimings) -> Void) {
        var timings = benchmarkChanges.value
        update(&timings)
        if timings != benchmarkChanges.value { benchmarkChanges.send(timings) }
    }
    #endif

    private func resetWindow() {
        #if DEBUG
        pendingDeliberateOpenStartedUptimeMS = nil
        updateStartupTimings { $0 = .init() }
        #endif
        records = []
        indexByID = [:]
        messages = []
        source = nil
        title = ""
        category = ""
        hasOlderMessages = false
        refreshing = false
        openFailure = nil
        olderPagePending = false
        windowsSinceOpen = 0
    }

    private static func sourceName(_ source: ChatWindowSourceRecord) -> String {
        switch source {
        case .cached: return "cached"
        case .cachedOffline: return "cached_offline"
        case .cacheSettled: return "cache_settled"
        case .firstPage: return "first_page"
        case .canonical: return "canonical"
        case .live: return "live"
        case .liveSettled: return "live_settled"
        }
    }

    /// Runs one window call through `CoreSession.perform` (cancelled with the
    /// calling task); logs its outcome class and duration and keeps a failure
    /// other than cancellation in `lastError`.
    @discardableResult
    private func run(_ phase: String,
                     _ operation: (ViewModelCore, CoreCancellation) async throws -> Void) async -> Bool {
        guard let session else {
            NativeSyncPerfLog.warning("phase=core.window.\(phase) outcome=no_core ms=0")
            return false
        }
        let started = NativeSyncPerfLog.now()
        do {
            try await session.perform(operation)
            NativeSyncPerfLog.info(
                "phase=core.window.\(phase) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            return true
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.window.\(phase) outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            if let coreError = error as? CoreError, coreError != .Cancelled { lastError = coreError }
            return false
        }
    }
}
