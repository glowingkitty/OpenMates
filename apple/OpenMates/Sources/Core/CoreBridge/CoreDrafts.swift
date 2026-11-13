// Composer drafts through the Rust core (plan apple-client-core-migration A6).
// Created at app start with the core (`CoreDrafts.launch()` from
// `OpenMatesApp.init`, after `CoreChatActions.launch()`).
//
// The core encrypts a draft, sends it to the server, keeps its versioned
// tombstone on clear and emits the chat list with the row's draft preview
// (`saveDraft` / `clearDraft` on `ViewModelCore`); no draft protocol, version
// or tombstone rule lives here. This type only orders the calls of one chat:
// one core call per chat runs at a time and only the latest request waiting
// behind it is sent next (an older save that never started is dropped, a
// clear after a save runs after it), so debounced composer saves never race
// each other on the core. Timing (the composer's debounce) stays in the view.
// Sign-out, expiry and access denial drop the waiting requests and cancel the
// running one. Every call goes through `CoreSession.perform` (the app's
// client) or an injected fake (tests), logs a `core.drafts.*` timing line and
// keeps the core's typed `CoreError` in `lastError`; nothing is retried here.
// `read` returns the core's draft of a chat (server read online, the core's
// last synced copy offline). A draft saved or cleared on another device
// arrives as the core's `draftChanged` event and is passed on unchanged through
// `remoteChanges`; `hasUnsyncedChanges` says whether this device asked for a
// save or clear the core has not completed yet (waiting, running or failed
// since its last success), which is the composer's "local wins" signal.
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.sync.version-authoritative, drafts.draft-only.lifecycle
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order

import Combine
import Foundation

/// The core calls behind composer drafts.
/// `CoreSessionDraftsClient` is the app's implementation; tests inject a fake.
@MainActor
protocol DraftsCoreClient: AnyObject, Sendable {
    /// Saves `markdown` as the encrypted draft of `chatId` (`nil`: a new chat); returns the chat id.
    func saveDraft(chatId: String?, markdown: String) async throws -> String
    /// Clears the draft of `chatId` with its versioned tombstone.
    func clearDraft(chatId: String) async throws
    /// The core's draft of `chatId` (`nil`: none or cleared).
    func readDraft(chatId: String) async throws -> DraftViewRecord?
}

/// The app's draft calls, each with a `CoreCancellation` tied to the calling task.
@MainActor
final class CoreSessionDraftsClient: DraftsCoreClient {
    private let session: CoreSession

    init(session: CoreSession) {
        self.session = session
    }

    func saveDraft(chatId: String?, markdown: String) async throws -> String {
        try await session.perform { core, cancellation in
            try await core.saveDraft(chatId: chatId, markdown: markdown, cancellation: cancellation)
        }
    }

    func clearDraft(chatId: String) async throws {
        try await session.perform { core, cancellation in
            try await core.clearDraft(chatId: chatId, cancellation: cancellation)
        }
    }

    func readDraft(chatId: String) async throws -> DraftViewRecord? {
        try await session.perform { core, cancellation in
            try await core.draft(chatId: chatId, cancellation: cancellation)
        }
    }
}

/// One draft request for a chat.
enum CoreDraftRequest: Equatable, Sendable {
    case save(markdown: String)
    case clear
}

/// A draft saved (`draft`) or cleared (`nil`) on another device, as the core reported it.
struct CoreDraftChange: Equatable, Sendable {
    let chatId: String
    let draft: DraftViewRecord?
}

@MainActor
final class CoreDrafts {
    /// The app's drafts; attached to the app's core by `launch()`. Unit tests
    /// create their own instance with a fake client.
    static let shared = CoreDrafts()

    /// The last failed core call (cancellations are not failures).
    private(set) var lastError: CoreError?

    var isAttached: Bool { client != nil }

    /// Drafts changed on another device (this device's own saves never echo).
    let remoteChanges = PassthroughSubject<CoreDraftChange, Never>()

    private var client: DraftsCoreClient?
    private var subscription: AnyCancellable?
    /// The newest request of each chat that waits for that chat's running call.
    private var waiting: [String: CoreDraftRequest] = [:]
    private var running: [String: (id: UUID, task: Task<Void, Never>)] = [:]
    /// Chats with a request the core has not completed (waiting, running or failed).
    private var unsynced: Set<String> = []

    init() {}

    /// Attaches the app's drafts to the app's core. Without a core (creation
    /// failed, see `CoreSession.launchError`) every request is logged and dropped.
    static func launch() {
        guard let session = CoreSession.shared else {
            NativeDiagnostics.error("core_drafts_unavailable reason=no_core", category: "core_bridge")
            return
        }
        shared.attach(client: CoreSessionDraftsClient(session: session), events: session.events.eraseToAnyPublisher())
    }

    /// Runs requests through `client`; `events` ends them on sign-out.
    func attach(client: DraftsCoreClient, events: AnyPublisher<ViewEventRecord, Never>) {
        self.client = client
        subscription = events.sink { [weak self] event in
            self?.apply(event)
        }
    }

    /// Saves `markdown` as the draft of `chatId` after that chat's running call.
    func save(chatId: String, markdown: String) {
        enqueue(.save(markdown: markdown), chatId: chatId)
    }

    /// Clears the draft of `chatId` after that chat's running call.
    func clear(chatId: String) {
        enqueue(.clear, chatId: chatId)
    }

    /// Whether a call for `chatId` runs or waits.
    func isBusy(chatId: String) -> Bool {
        running[chatId] != nil
    }

    /// Whether this device asked for a save or clear of `chatId` that the
    /// core has not completed yet (waiting, running or failed since).
    func hasUnsyncedChanges(chatId: String) -> Bool {
        unsynced.contains(chatId)
    }

    /// The core's draft of `chatId` (`nil`: none or cleared). Throws the
    /// core's typed error (invalid id, team scope, offline without a cached copy).
    func read(chatId: String) async throws -> DraftViewRecord? {
        guard let client else {
            NativeSyncPerfLog.warning("phase=core.drafts.read outcome=no_core ms=0")
            throw CoreError.Unavailable(code: "no_core", reason: "The client core is not running")
        }
        let started = NativeSyncPerfLog.now()
        do {
            let draft = try await client.readDraft(chatId: chatId)
            NativeSyncPerfLog.info(
                "phase=core.drafts.read outcome=\(draft == nil ? "none" : "ok") ms=\(NativeSyncPerfLog.ms(since: started))")
            return draft
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.drafts.read outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            let coreError = (error as? CoreError) ?? CoreError.Internal(reason: String(describing: type(of: error)))
            if coreError != .Cancelled { lastError = coreError }
            throw coreError
        }
    }

    /// Returns once every request of `chatId` made so far has run.
    func settle(chatId: String) async {
        while let entry = running[chatId] {
            await entry.task.value
        }
    }

    private func enqueue(_ request: CoreDraftRequest, chatId: String) {
        guard client != nil else {
            NativeSyncPerfLog.warning("phase=core.drafts.\(Self.phase(request)) outcome=no_core ms=0")
            return
        }
        waiting[chatId] = request
        unsynced.insert(chatId)
        guard running[chatId] == nil else { return }
        let id = UUID()
        let task = Task<Void, Never> { @MainActor [weak self] in
            guard let self else { return }
            await self.drain(chatId: chatId, id: id)
        }
        running[chatId] = (id: id, task: task)
    }

    private func drain(chatId: String, id: UUID) async {
        while !Task.isCancelled, let request = waiting.removeValue(forKey: chatId) {
            await run(request, chatId: chatId)
        }
        // No suspension between the empty check and this: a request queued
        // while the last call ran was taken by the loop above. A drain ended
        // by sign-out leaves a newer session's entry alone.
        if running[chatId]?.id == id { running[chatId] = nil }
    }

    private func run(_ request: CoreDraftRequest, chatId: String) async {
        guard let client else { return }
        let started = NativeSyncPerfLog.now()
        let phase = Self.phase(request)
        do {
            switch request {
            case .save(let markdown):
                _ = try await client.saveDraft(chatId: chatId, markdown: markdown)
            case .clear:
                try await client.clearDraft(chatId: chatId)
            }
            NativeSyncPerfLog.info("phase=core.drafts.\(phase) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            // A newer request still waiting keeps the chat unsynced.
            if waiting[chatId] == nil { unsynced.remove(chatId) }
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.drafts.\(phase) outcome=\(CoreSession.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            let coreError = (error as? CoreError) ?? CoreError.Internal(reason: String(describing: type(of: error)))
            if coreError != .Cancelled { lastError = coreError }
        }
    }

    /// Passes remote draft changes on; sign-out, expiry and access denial end
    /// every request of the old session.
    func apply(_ event: ViewEventRecord) {
        switch event {
        case .draftChanged(let chatId, let draft):
            remoteChanges.send(CoreDraftChange(chatId: chatId, draft: draft))
        case .session(let session):
            switch session {
            case .signedOut, .expired, .accessDenied:
                waiting = [:]
                for entry in running.values { entry.task.cancel() }
                running = [:]
                unsynced = []
                lastError = nil
            case .restored, .admitted, .verificationRequired:
                break
            }
        default:
            break
        }
    }

    private static func phase(_ request: CoreDraftRequest) -> String {
        switch request {
        case .save(_): return "save"
        case .clear: return "clear"
        }
    }
}
