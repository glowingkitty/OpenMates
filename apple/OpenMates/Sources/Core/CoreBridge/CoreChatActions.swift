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
// `Submitted`, `Admitted` or `Completed`, or the call's success) and when the
// turn ended, and remembers the message ids of core turns so the frozen Swift
// socket stream does not draw or persist them a second time. A running turn
// is stopped with `cancelSend()`; a reply this core did not start with
// `stopReply`. Delete message, delete chat and fork are single core calls.
// The app uses delete chat, delete message and fork (personal chats); its
// send, edit and stop stay on the Swift pipeline until the core send takes
// attachments, PII mappings, queued follow-ups, temporary chat ids and
// new-chat sends, so turns, cancel and stopReply here are not called yet.
// Every call goes through `CoreSession.perform` (the app's client) or an
// injected fake (tests), logs a `core.actions.*` timing line and throws the
// core's typed `CoreError`; nothing is retried or replaced here.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.viewmodel.stream-updates, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order

import Combine
import Foundation

/// The core calls behind turns and the chat/message actions.
/// `CoreSessionChatActionsClient` is the app's implementation; tests inject a fake.
@MainActor
protocol ChatActionsCoreClient: AnyObject, Sendable {
    func send(request: UInt64, chatId: String?, text: String) async throws -> ChatWindowViewRecord
    func editMessage(request: UInt64, chatId: String, messageId: String, text: String) async throws -> ChatWindowViewRecord
    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord
    /// Cancels the running send, edit or retry; whether one was running.
    func cancelSend() -> Bool
    func stopReply(chatId: String, taskId: String) async throws
    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws
    func deleteChat(chatId: String) async throws
    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String
}

/// The app's core calls, each with a `CoreCancellation` tied to the calling task.
@MainActor
final class CoreSessionChatActionsClient: ChatActionsCoreClient {
    private let session: CoreSession

    init(session: CoreSession) {
        self.session = session
    }

    func send(request: UInt64, chatId: String?, text: String) async throws -> ChatWindowViewRecord {
        try await session.perform { core, cancellation in
            try await core.send(request: request, chatId: chatId, text: text, cancellation: cancellation)
        }
    }

    func editMessage(request: UInt64, chatId: String, messageId: String, text: String) async throws -> ChatWindowViewRecord {
        try await session.perform { core, cancellation in
            try await core.editMessage(request: request, chatId: chatId, messageId: messageId, text: text,
                                       cancellation: cancellation)
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
}

/// One turn the core sends.
enum CoreChatTurn: Equatable, Sendable {
    /// A new user message.
    case send(text: String)
    /// Replace user message `messageId` and everything after it with `text`.
    case edit(messageId: String, text: String)
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
    /// Another core turn is still running.
    case busy
    /// The app has no core (creation failed, unit-test host).
    case noCore
}

/// How a turn ended.
enum CoreTurnOutcome: Equatable {
    case completed
    case failed(CoreError)
    case cancelled
}

/// The end of a turn and whether it had been accepted before.
struct CoreTurnEnd: Equatable {
    let outcome: CoreTurnOutcome
    let wasAccepted: Bool
}

/// The app has no core for a chat action.
enum CoreChatActionsError: Error, Equatable {
    case noCore
}

@MainActor
final class CoreChatActions {
    /// The app's actions; attached to the app's core by `launch()`. Unit tests
    /// create their own instance with a fake client.
    static let shared = CoreChatActions()

    /// The running turn.
    struct ActiveTurn: Equatable {
        let request: UInt64
        let chatId: String
    }

    private(set) var activeTurn: ActiveTurn?
    /// User and reply message ids of core turns since sign-in.
    private(set) var turnMessageIDs = Set<String>()

    var isAttached: Bool { client != nil }

    private var client: ChatActionsCoreClient?
    private let window: CoreChatWindow
    private var subscription: AnyCancellable?
    private var turnTask: Task<Void, Never>?
    private var acceptanceWaiter: CheckedContinuation<CoreTurnAcceptance, Never>?
    private var accepted = false
    private var onEnd: (@MainActor (CoreTurnEnd) -> Void)?

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
        subscription = events.sink { [weak self] event in
            self?.apply(event)
        }
    }

    /// Whether a core turn runs in `chatId`.
    func hasActiveTurn(in chatId: String) -> Bool {
        activeTurn?.chatId == chatId
    }

    /// Not used by the app yet: it adopts this once the core send takes attachments, PII mappings, queued follow-ups, temporary chat ids and new-chat sends.
    /// Starts `turn` in saved chat `chatId` and returns once the core accepted
    /// or refused it; the reply keeps streaming through the window afterwards.
    /// `onEnd` runs once when the turn ended (also after a refusal).
    func startTurn(_ turn: CoreChatTurn, chatId: String,
                   onEnd: @escaping @MainActor (CoreTurnEnd) -> Void) async -> CoreTurnAcceptance {
        guard client != nil else {
            NativeSyncPerfLog.warning("phase=core.actions.turn outcome=no_core ms=0")
            return .noCore
        }
        guard activeTurn == nil else { return .busy }
        let request = window.nextActionRequest()
        activeTurn = ActiveTurn(request: request, chatId: chatId)
        accepted = false
        self.onEnd = onEnd
        let started = NativeSyncPerfLog.now()
        let phase = Self.phase(turn)
        turnTask = Task<Void, Never> { @MainActor [weak self] in
            guard let self else { return }
            let outcome = await self.run(turn, request: request, chatId: chatId)
            NativeSyncPerfLog.info(
                "phase=core.actions.\(phase) outcome=\(Self.outcomeName(outcome)) ms=\(NativeSyncPerfLog.ms(since: started))")
            self.finish(request: request, outcome: outcome)
        }
        // The turn task starts only after this suspends, so the waiter is in
        // place before any event or outcome of the turn.
        return await withCheckedContinuation { continuation in
            acceptanceWaiter = continuation
        }
    }

    /// Not used by the app yet: it adopts this once the core send takes attachments, PII mappings, queued follow-ups, temporary chat ids and new-chat sends.
    /// Stops the running turn: `cancelSend` for a send on the core's actor,
    /// and the call's cancellation for a turn still before its send (an
    /// edit's truncation). Returns whether a turn was running.
    @discardableResult
    func cancel() -> Bool {
        guard activeTurn != nil else { return false }
        let wasSending = client?.cancelSend() ?? false
        turnTask?.cancel()
        NativeSyncPerfLog.info("phase=core.actions.cancel sending=\(wasSending)")
        return true
    }

    /// Not used by the app yet: it adopts this once the core send takes attachments, PII mappings, queued follow-ups, temporary chat ids and new-chat sends.
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

    private func run(_ turn: CoreChatTurn, request: UInt64, chatId: String) async -> CoreTurnOutcome {
        guard let client else { return .failed(.Authentication) }
        do {
            switch turn {
            case .send(let text):
                _ = try await client.send(request: request, chatId: chatId, text: text)
            case .edit(let messageId, let text):
                _ = try await client.editMessage(request: request, chatId: chatId, messageId: messageId, text: text)
            case .retry:
                _ = try await client.retryLastTurn(request: request, chatId: chatId)
            }
            return .completed
        } catch {
            let coreError = Self.coreError(error)
            return coreError == .Cancelled ? .cancelled : .failed(coreError)
        }
    }

    private func finish(request: UInt64, outcome: CoreTurnOutcome) {
        guard activeTurn?.request == request else { return }
        let wasAccepted = accepted
        activeTurn = nil
        turnTask = nil
        accepted = false
        if let waiter = acceptanceWaiter {
            acceptanceWaiter = nil
            switch outcome {
            case .completed: waiter.resume(returning: .accepted)
            case .failed(let failure): waiter.resume(returning: .rejected(failure))
            case .cancelled: waiter.resume(returning: .cancelled)
            }
        }
        let end = onEnd
        onEnd = nil
        end?(CoreTurnEnd(outcome: outcome, wasAccepted: wasAccepted || outcome == .completed))
    }

    private func accept() {
        accepted = true
        guard let waiter = acceptanceWaiter else { return }
        acceptanceWaiter = nil
        waiter.resume(returning: .accepted)
    }

    /// Follows the running turn's `Stream` events; sign-out forgets turn ids.
    func apply(_ event: ViewEventRecord) {
        switch event {
        case .stream(let request, _, let progress):
            guard activeTurn?.request == request else { return }
            switch progress {
            case .started(_, let messageId, _):
                turnMessageIDs.insert(messageId)
            case .submitted(_, let messageId), .admitted(_, let messageId):
                turnMessageIDs.insert(messageId)
                accept()
            case .completed(_, let messageId, _):
                turnMessageIDs.insert(messageId)
                accept()
            case .consent(_, _), .content(_, _, _), .status(_):
                break
            }
        case .session(let session):
            switch session {
            case .signedOut, .expired, .accessDenied:
                turnMessageIDs = []
            case .restored, .admitted, .verificationRequired:
                break
            }
        default:
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
            throw error
        }
    }

    private static func coreError(_ error: Error) -> CoreError {
        (error as? CoreError) ?? CoreError.Internal(reason: String(describing: type(of: error)))
    }

    private static func phase(_ turn: CoreChatTurn) -> String {
        switch turn {
        case .send(_): return "send"
        case .edit(_, _): return "edit"
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
