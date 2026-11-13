// Send, edit, retry, stop and the chat/message menu actions through the Rust
// core (plan apple-client-core-migration A5). Created at app start with the
// core (`CoreChatActions.launch()` from `OpenMatesApp.init`, after
// `CoreChatWindow.launch()`).
//
// A turn (send, edit, retry) runs as one core call under a request id from the
// open window (`CoreChatWindow.nextActionRequest`), so the core's `ChatWindow`
// and `MessageUpdated` events for it (the user message with its send state,
// then the streaming reply, then the canonical window) reach the transcript
// through `CoreChatWindow`; nothing here assembles a stream. This type only
// tells the caller when the core accepted the turn (its `Stream` event
// `Submitted`, `Admitted` or `Completed`, or the call's success), when the
// turn ended and with which receipt (chat id, message ids, completed,
// waiting or queued, queue mode and revision), and remembers the message ids
// of core turns so the frozen Swift socket stream does not draw or persist
// them a second time. Several turns may run at once: the core streams sends
// of different chats in parallel and queues a second send of the same chat
// (the receipt then says `queued`); nothing here refuses or orders them.
// The task id of a reply arrives as the core's `taskAssigned` event (again
// when a continuation task replaces it) and is kept per chat, read-only
// through `taskId(for:)`. `stop(chatId:)` ends this device's own send with
// `cancelSend()` and a reply it did not start with `stopReply` by that task
// id. Delete message, delete chat and fork are single core calls.
// The app's signed-in send, edit, stop, consent answers, queued-message
// revisions (edit and steer of a queued follow-up, `reviseQueued`) and voice
// call turns (`CoreSendMapping.options(voiceCall:)`) all run through here.
// A rejected revision keeps the core's typed reason as `CoreQueuedRevisionRejection`.
// Every call goes through `CoreSession.perform` (the app's client) or an
// injected fake (tests), logs a `core.actions.*` timing line and keeps the
// core's typed `CoreError` in `lastError`; nothing is retried here.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.viewmodel.stream-updates, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order

import Combine
import Foundation

/// The core calls behind turns and the chat/message actions.
/// `CoreSessionChatActionsClient` is the app's implementation; tests inject a fake.
@MainActor
protocol ChatActionsCoreClient: AnyObject, Sendable {
    /// Sends `text` (`chatId` nil: a new chat) with `options`; the core queues a second send into a busy chat.
    func sendWithOptions(request: UInt64, chatId: String?, text: String,
                         options: SendOptionsRecord) async throws -> SendReceiptRecord
    /// Replaces user message `messageId` and everything after it; the core rejects incognito, slug and reserved chat id.
    func editMessageWithOptions(request: UInt64, chatId: String, messageId: String, text: String,
                                options: SendOptionsRecord) async throws -> SendReceiptRecord
    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord
    /// Cancels the running send, edit or retry; whether one was running.
    func cancelSend() -> Bool
    func stopReply(chatId: String, taskId: String) async throws
    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws
    func deleteChat(chatId: String) async throws
    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String
    /// Answers the consent request `requestId` of `chatId` with the approved item ids (empty: reject all).
    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws
}

/// The core call behind `CoreChatActions.reviseQueued`; kept apart from
/// `ChatActionsCoreClient` so a client without queue support stays valid.
@MainActor
protocol QueuedRevisionCoreClient: AnyObject, Sendable {
    /// Revises queued message `messageId` at `revision`: new `text` and/or a queue mode change.
    func reviseQueuedMessage(chatId: String, messageId: String, revision: UInt64, text: String?,
                             modeChange: SendQueueModeRecord?,
                             options: SendOptionsRecord) async throws -> QueuedRevisionReceiptRecord
}

/// The core call behind `CoreChatActions.undoCreatedProject`; separate so a
/// client without Project support stays valid.
@MainActor
protocol CreatedProjectUndoCoreClient: AnyObject, Sendable {
    /// Deletes the Project the assistant created for `chatId` and drops its focus.
    func undoCreatedProject(chatId: String) async throws -> CreatedProjectRecord
}

/// Why the core refused to undo an assistant-created Project.
enum CoreCreatedProjectUndoError: Error, Equatable {
    /// The chat has no assistant-created Project (the core's `Forbidden`).
    case forbidden
}

/// Why the core rejected a queued-message revision.
enum CoreQueuedRevisionRejection: Error, Equatable {
    /// The message left the queue or its revision moved on.
    case conflict
    case forbidden
    case invalid
    case unavailable
}

/// The app's core calls, each with a `CoreCancellation` tied to the calling task.
@MainActor
final class CoreSessionChatActionsClient: ChatActionsCoreClient, QueuedRevisionCoreClient, CreatedProjectUndoCoreClient {
    private let session: CoreSession

    init(session: CoreSession) {
        self.session = session
    }

    func sendWithOptions(request: UInt64, chatId: String?, text: String,
                         options: SendOptionsRecord) async throws -> SendReceiptRecord {
        try await session.perform { core, cancellation in
            try await core.sendWithOptions(request: request, chatId: chatId, text: text, options: options,
                                           cancellation: cancellation)
        }
    }

    func editMessageWithOptions(request: UInt64, chatId: String, messageId: String, text: String,
                                options: SendOptionsRecord) async throws -> SendReceiptRecord {
        try await session.perform { core, cancellation in
            try await core.editMessageWithOptions(request: request, chatId: chatId, messageId: messageId,
                                                  text: text, options: options, cancellation: cancellation)
        }
    }

    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord {
        try await session.perform { core, cancellation in
            try await core.retryLastTurn(request: request, chatId: chatId, cancellation: cancellation)
        }
    }

    func cancelSend() -> Bool {
        session.core.cancelSend()
    }

    func stopReply(chatId: String, taskId: String) async throws {
        try await session.perform { core, cancellation in
            try await core.stopReply(chatId: chatId, taskId: taskId, cancellation: cancellation)
        }
    }

    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws {
        try await session.perform { core, cancellation in
            try await core.deleteMessage(request: request, chatId: chatId, messageId: messageId, cancellation: cancellation)
        }
    }

    func deleteChat(chatId: String) async throws {
        try await session.perform { core, cancellation in
            try await core.deleteChat(chatId: chatId, cancellation: cancellation)
        }
    }

    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String {
        try await session.perform { core, cancellation in
            try await core.forkChat(chatId: chatId, messageId: messageId, title: title, cancellation: cancellation)
        }
    }

    func reviseQueuedMessage(chatId: String, messageId: String, revision: UInt64, text: String?,
                             modeChange: SendQueueModeRecord?,
                             options: SendOptionsRecord) async throws -> QueuedRevisionReceiptRecord {
        try await session.perform { core, cancellation in
            try await core.reviseQueuedMessage(chatId: chatId, messageId: messageId, revision: revision, text: text,
                                               modeChange: modeChange, options: options, cancellation: cancellation)
        }
    }

    func undoCreatedProject(chatId: String) async throws -> CreatedProjectRecord {
        try await session.perform { core, cancellation in
            try await core.undoCreatedProject(chatId: chatId, cancellation: cancellation)
        }
    }

    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws {
        let core = session.core
        try await Task.detached {
            try core.answerConsent(chatId: chatId, requestId: requestId, approvedItemIds: approvedItemIds)
        }.value
    }
}

/// A consent request of a running turn: the assistant asks permission to use `items`.
struct CoreConsentRequest: Equatable {
    let requestId: String
    let items: [EmbedRefRecord]
}

/// One turn the core sends.
enum CoreChatTurn: Equatable, Sendable {
    /// A new user message (`chatId` nil in `startTurn`: a new chat).
    case send(text: String, options: SendOptionsRecord = SendOptionsRecord())
    /// Replace user message `messageId` and everything after it with `text`.
    case edit(messageId: String, text: String, options: SendOptionsRecord = SendOptionsRecord())
    /// Send the newest unanswered user turn again.
    case retry
}

/// How the start of a turn ended for the caller (the composer).
enum CoreTurnAcceptance: Equatable {
    /// The core dispatched the turn; never send it again.
    case accepted
    /// The core refused or failed the turn before dispatch.
    case rejected(CoreError)
    case cancelled
    /// The app has no core (creation failed, unit-test host).
    case noCore
}

/// How a turn ended.
enum CoreTurnOutcome: Equatable {
    case completed
    case failed(CoreError)
    case cancelled
}

/// The end of a turn, whether it had been accepted before and the core's receipt.
struct CoreTurnEnd: Equatable {
    let outcome: CoreTurnOutcome
    let wasAccepted: Bool
    /// The core's receipt of a send or edit (`nil` for a retry, a refusal or a cancellation).
    var receipt: SendReceiptRecord?
    /// The final reply text from the turn's `Completed` stream event (`nil` when
    /// the turn ended without a reply, e.g. queued, refused or cancelled). Shells
    /// without a chat window (App Intents) read the answer from here.
    var replyText: String? = nil

    /// The core saved the message and queued it behind an active reply of its chat.
    var isQueued: Bool { receipt?.status == .queued }
}

/// What `stop(chatId:)` did.
enum CoreStopResult: Equatable {
    /// This device's own send in the chat was cancelled (`cancelSend`).
    case cancelledSend
    /// A reply this call did not start was stopped by its task id.
    case stoppedReply(taskId: String)
    /// No send runs and no task id is known for the chat.
    case nothingToStop
}

/// The app has no core for a chat action.
enum CoreChatActionsError: Error, Equatable {
    case noCore
}

@MainActor
final class CoreChatActions: ObservableObject {
    /// The app's actions; attached to the app's core by `launch()`. Unit tests
    /// create their own instance with a fake client.
    static let shared = CoreChatActions()

    /// A running turn. `chatId` is nil for a new-chat send until the core's
    /// `Started` event names the chat.
    struct ActiveTurn: Equatable {
        let request: UInt64
        var chatId: String?
    }

    private struct Runtime {
        var accepted = false
        var replyText: String?
        var waiter: CheckedContinuation<CoreTurnAcceptance, Never>?
        var onEnd: (@MainActor (CoreTurnEnd) -> Void)?
        var task: Task<Void, Never>?
    }

    /// The running turns, oldest first.
    private(set) var activeTurns: [ActiveTurn] = []
    /// User and reply message ids of core turns since sign-in.
    private(set) var turnMessageIDs = Set<String>()
    /// The last non-cancelled failure of a call; cleared at sign-out.
    private(set) var lastError: CoreError?
    /// The consent request each chat waits on, keyed by chat id; removed when
    /// answered, when its turn ends and at sign-out.
    @Published private(set) var pendingConsent: [String: CoreConsentRequest] = [:]
    private var consentRequests: [UInt64: String] = [:]

    var isAttached: Bool { client != nil }

    private var client: ChatActionsCoreClient?
    private var revisionClient: QueuedRevisionCoreClient?
    private var projectUndoClient: CreatedProjectUndoCoreClient?
    private let window: CoreChatWindow
    private var subscription: AnyCancellable?
    private var runtimes: [UInt64: Runtime] = [:]
    private var taskIDs: [String: String] = [:]

    init(window: CoreChatWindow = .shared) {
        self.window = window
    }

    /// Attaches the app's actions to the app's core. Without a core (creation
    /// failed, see `CoreSession.launchError`) every action reports no core.
    static func launch() {
        guard let session = CoreSession.shared else {
            NativeDiagnostics.error("core_chat_actions_unavailable reason=no_core", category: "core_bridge")
            return
        }
        shared.attach(client: CoreSessionChatActionsClient(session: session), events: session.events.eraseToAnyPublisher())
    }

    /// Runs actions through `client` and follows the core's `events`.
    func attach(client: ChatActionsCoreClient, events: AnyPublisher<ViewEventRecord, Never>) {
        self.client = client
        revisionClient = client as? QueuedRevisionCoreClient
        projectUndoClient = client as? CreatedProjectUndoCoreClient
        subscription = events.sink { [weak self] event in
            self?.apply(event)
        }
    }

    /// Whether a core turn of this device runs in `chatId`.
    func hasActiveTurn(in chatId: String) -> Bool {
        activeTurns.contains { $0.chatId == chatId }
    }

    /// The task id of the reply running in `chatId` (the core's latest
    /// `taskAssigned`; a continuation task replaces it); `nil` when none is known.
    func taskId(for chatId: String) -> String? {
        taskIDs[chatId]
    }

    /// Starts `turn` in saved chat `chatId` (`nil`: a new chat, send only) and
    /// returns once the core accepted or refused it; the reply keeps streaming
    /// through the window afterwards. Turns of other chats run in parallel and
    /// a second send into a chat with an active reply is queued by the core
    /// (`CoreTurnEnd.isQueued`). `onEnd` runs once when the turn ended (also
    /// after a refusal).
    func startTurn(_ turn: CoreChatTurn, chatId: String?,
                   onEnd: @escaping @MainActor (CoreTurnEnd) -> Void) async -> CoreTurnAcceptance {
        guard client != nil else {
            NativeSyncPerfLog.warning("phase=core.actions.turn outcome=no_core ms=0")
            return .noCore
        }
        let request = window.nextActionRequest()
        activeTurns.append(ActiveTurn(request: request, chatId: chatId ?? Self.reservedChatId(turn)))
        runtimes[request] = Runtime(onEnd: onEnd)
        let started = NativeSyncPerfLog.now()
        let phase = Self.phase(turn)
        let task = Task<Void, Never> { @MainActor [weak self] in
            guard let self else { return }
            let result = await self.run(turn, request: request, chatId: chatId)
            NativeSyncPerfLog.info(
                "phase=core.actions.\(phase) outcome=\(Self.outcomeName(result.outcome)) ms=\(NativeSyncPerfLog.ms(since: started))")
            self.finish(request: request, outcome: result.outcome, receipt: result.receipt)
        }
        runtimes[request]?.task = task
        // The turn task starts only after this suspends, so the waiter is in
        // place before any event or outcome of the turn.
        return await withCheckedContinuation { continuation in
            runtimes[request]?.waiter = continuation
        }
    }

    /// Stops the reply of `chatId`: `cancelSend` (and the call's cancellation)
    /// for this device's own running send, else `stopReply` by the task id the
    /// core assigned to a reply this call did not start.
    @discardableResult
    func stop(chatId: String) async throws -> CoreStopResult {
        let client = try attachedClient()
        let own = activeTurns.filter { $0.chatId == chatId }
        if !own.isEmpty {
            let wasSending = client.cancelSend()
            for turn in own { runtimes[turn.request]?.task?.cancel() }
            NativeSyncPerfLog.info("phase=core.actions.cancel sending=\(wasSending)")
            return .cancelledSend
        }
        guard let taskId = taskIDs[chatId] else { return .nothingToStop }
        try await stopReply(chatId: chatId, taskId: taskId)
        return .stoppedReply(taskId: taskId)
    }

    /// Stops reply task `taskId` of `chatId` that this core did not start.
    func stopReply(chatId: String, taskId: String) async throws {
        let client = try attachedClient()
        try await timed("stop_reply") { try await client.stopReply(chatId: chatId, taskId: taskId) }
    }

    /// Deletes one message of personal chat `chatId`; the open window is
    /// re-read by the core as a newer request.
    func deleteMessage(chatId: String, messageId: String) async throws {
        let client = try attachedClient()
        let request = window.nextActionRequest()
        try await timed("delete_message") {
            try await client.deleteMessage(request: request, chatId: chatId, messageId: messageId)
        }
    }

    /// Deletes `chatId` on every device; the core closes its window and emits the chat list.
    func deleteChat(chatId: String) async throws {
        let client = try attachedClient()
        try await timed("delete_chat") { try await client.deleteChat(chatId: chatId) }
    }

    /// Forks personal chat `chatId` up to and including `messageId`; returns the new chat id.
    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String {
        let client = try attachedClient()
        return try await timed("fork_chat") {
            try await client.forkChat(chatId: chatId, messageId: messageId, title: title)
        }
    }

    /// Answers the pending consent request `requestId` of `chatId` with the
    /// approved item ids (empty rejects all) and clears it; a failure keeps the
    /// request so the dialog can be answered again.
    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws {
        let client = try attachedClient()
        try await timed("answer_consent") {
            try await client.answerConsent(chatId: chatId, requestId: requestId, approvedItemIds: approvedItemIds)
        }
        if pendingConsent[chatId]?.requestId == requestId { pendingConsent[chatId] = nil }
    }

    /// Revises queued message `messageId` of `chatId` (expected `revision`):
    /// `text` replaces its content (`nil` keeps it), `mode` changes the queue
    /// mode (`nil` keeps it; `.steer` steers the active reply at its next safe
    /// boundary). Throws `CoreQueuedRevisionRejection` for the core's typed
    /// refusals; other core errors (offline, cancelled) pass through.
    func reviseQueued(chatId: String, messageId: String, revision: Int, text: String?,
                      mode: ChatQueuedSendMode?,
                      options: SendOptionsRecord = SendOptionsRecord()) async throws -> QueuedRevisionReceiptRecord {
        guard let revisionClient else {
            NativeSyncPerfLog.warning("phase=core.actions outcome=no_core ms=0")
            throw CoreChatActionsError.noCore
        }
        guard revision >= 1 else { throw CoreQueuedRevisionRejection.invalid }
        let modeChange: SendQueueModeRecord? = mode.map { $0 == .steer ? .steer : .followUp }
        do {
            return try await timed("revise_queued") {
                try await revisionClient.reviseQueuedMessage(
                    chatId: chatId, messageId: messageId, revision: UInt64(revision), text: text,
                    modeChange: modeChange, options: options)
            }
        } catch let failure as CoreError {
            guard let rejection = Self.rejection(failure) else { throw failure }
            throw rejection
        }
    }

    /// Undoes the Project the assistant created for `chatId` (the core decides
    /// whether it may). Throws `CoreCreatedProjectUndoError.forbidden` when the
    /// chat has no assistant-created Project; other core errors pass through.
    @discardableResult
    func undoCreatedProject(chatId: String) async throws -> CreatedProjectRecord {
        guard let projectUndoClient else {
            NativeSyncPerfLog.warning("phase=core.actions outcome=no_core ms=0")
            throw CoreChatActionsError.noCore
        }
        do {
            return try await timed("undo_created_project") {
                try await projectUndoClient.undoCreatedProject(chatId: chatId)
            }
        } catch CoreError.Forbidden {
            throw CoreCreatedProjectUndoError.forbidden
        }
    }

    /// The text the chat shows for a refused queued revision; `nil` for a cancellation.
    static func queuedRevisionMessage(for error: Error) -> String? {
        if let rejection = error as? CoreQueuedRevisionRejection {
            return rejection == .conflict ? AppStrings.queuedFollowupConflict : AppStrings.queuedFollowupUnavailable
        }
        if let coreError = error as? CoreError, coreError == .Cancelled { return nil }
        return AppStrings.queuedFollowupUnavailable
    }

    private static func rejection(_ error: CoreError) -> CoreQueuedRevisionRejection? {
        switch error {
        case .Conflict: return .conflict
        case .Forbidden: return .forbidden
        case .Invalid(_): return .invalid
        case .Unavailable(_, _): return .unavailable
        default: return nil
        }
    }

    /// The text the chat shows for a failed action; `nil` for a cancellation.
    static func userMessage(for error: Error) -> String? {
        guard let coreError = error as? CoreError else { return AppStrings.genericProcessingError }
        switch coreError {
        case .Cancelled: return nil
        case .Offline: return AppStrings.reconnecting
        default: return AppStrings.genericProcessingError
        }
    }

    private func attachedClient() throws -> ChatActionsCoreClient {
        guard let client else {
            NativeSyncPerfLog.warning("phase=core.actions outcome=no_core ms=0")
            throw CoreChatActionsError.noCore
        }
        return client
    }

    private func run(_ turn: CoreChatTurn, request: UInt64,
                     chatId: String?) async -> (outcome: CoreTurnOutcome, receipt: SendReceiptRecord?) {
        guard let client else { return (.failed(.Authentication), nil) }
        do {
            switch turn {
            case .send(let text, let options):
                let receipt = try await client.sendWithOptions(request: request, chatId: chatId, text: text, options: options)
                return (.completed, receipt)
            case .edit(let messageId, let text, let options):
                guard let chatId else {
                    return (.failed(.Invalid(message: "An edit needs the chat of the message.")), nil)
                }
                let receipt = try await client.editMessageWithOptions(
                    request: request, chatId: chatId, messageId: messageId, text: text, options: options)
                return (.completed, receipt)
            case .retry:
                guard let chatId else {
                    return (.failed(.Invalid(message: "A retry needs the chat of the turn.")), nil)
                }
                _ = try await client.retryLastTurn(request: request, chatId: chatId)
                return (.completed, nil)
            }
        } catch {
            let coreError = Self.coreError(error)
            return (coreError == .Cancelled ? .cancelled : .failed(coreError), nil)
        }
    }

    private func finish(request: UInt64, outcome: CoreTurnOutcome, receipt: SendReceiptRecord?) {
        guard let runtime = runtimes.removeValue(forKey: request) else { return }
        let chatId = activeTurns.first { $0.request == request }?.chatId
        activeTurns.removeAll { $0.request == request }
        if let receipt {
            turnMessageIDs.formUnion([receipt.userMessageId, receipt.assistantMessageId].compactMap { $0 })
        }
        if let chatId, !hasActiveTurn(in: chatId) { taskIDs[chatId] = nil }
        if let consentChat = consentRequests.removeValue(forKey: request) { pendingConsent[consentChat] = nil }
        if case .failed(let failure) = outcome { lastError = failure }
        if let waiter = runtime.waiter {
            switch outcome {
            case .completed: waiter.resume(returning: .accepted)
            case .failed(let failure): waiter.resume(returning: .rejected(failure))
            case .cancelled: waiter.resume(returning: .cancelled)
            }
        }
        runtime.onEnd?(CoreTurnEnd(outcome: outcome, wasAccepted: runtime.accepted || outcome == .completed,
                                   receipt: receipt, replyText: runtime.replyText))
    }

    private func accept(request: UInt64) {
        runtimes[request]?.accepted = true
        guard let waiter = runtimes[request]?.waiter else { return }
        runtimes[request]?.waiter = nil
        waiter.resume(returning: .accepted)
    }

    /// Follows the turns' `Stream` events and the reply task ids; sign-out
    /// forgets turn ids, task ids and the last error and cancels running turns.
    func apply(_ event: ViewEventRecord) {
        switch event {
        case .stream(let request, _, let progress):
            applyStream(request: request, progress: progress)
        case .session(let session):
            switch session {
            case .signedOut, .expired, .accessDenied:
                turnMessageIDs = []
                taskIDs = [:]
                lastError = nil
                pendingConsent = [:]
                consentRequests = [:]
                for runtime in runtimes.values { runtime.task?.cancel() }
            case .restored, .admitted, .verificationRequired:
                break
            }
        default:
            break
        }
    }

    private func applyStream(request: UInt64, progress: StreamEventRecord) {
        switch progress {
        case .taskAssigned(let chatId, _, let taskId):
            taskIDs[chatId] = taskId
        case .completed(let chatId, let messageId, let content):
            taskIDs[chatId] = nil
            guard runtimes[request] != nil else { return }
            runtimes[request]?.replyText = content
            turnMessageIDs.insert(messageId)
            accept(request: request)
        case .started(let chatId, let messageId, _):
            guard let index = activeTurns.firstIndex(where: { $0.request == request }) else { return }
            if activeTurns[index].chatId == nil { activeTurns[index].chatId = chatId }
            turnMessageIDs.insert(messageId)
        case .submitted(_, let messageId), .admitted(_, let messageId):
            guard runtimes[request] != nil else { return }
            turnMessageIDs.insert(messageId)
            accept(request: request)
        case .consent(let requestId, let items):
            guard let chatId = activeTurns.first(where: { $0.request == request })?.chatId else { return }
            pendingConsent[chatId] = CoreConsentRequest(requestId: requestId, items: items)
            consentRequests[request] = chatId
        case .content(_, _, _), .status(_):
            break
        }
    }

    private func timed<T: Sendable>(_ phase: String, _ operation: () async throws -> T) async throws -> T {
        let started = NativeSyncPerfLog.now()
        do {
            let value = try await operation()
            NativeSyncPerfLog.info(
                "phase=core.actions.\(phase) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            return value
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.actions.\(phase) outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            if let coreError = error as? CoreError, coreError != .Cancelled { lastError = coreError }
            throw error
        }
    }

    private static func coreError(_ error: Error) -> CoreError {
        (error as? CoreError) ?? CoreError.Internal(reason: String(describing: type(of: error)))
    }

    private static func reservedChatId(_ turn: CoreChatTurn) -> String? {
        if case .send(_, let options) = turn { return options.reservedChatId }
        return nil
    }

    private static func phase(_ turn: CoreChatTurn) -> String {
        switch turn {
        case .send(_, _): return "send"
        case .edit(_, _, _): return "edit"
        case .retry: return "retry"
        }
    }

    private static func outcomeName(_ outcome: CoreTurnOutcome) -> String {
        switch outcome {
        case .completed: return "ok"
        case .failed(let failure): return CoreSession.errorClass(failure)
        case .cancelled: return "cancelled"
        }
    }
}
