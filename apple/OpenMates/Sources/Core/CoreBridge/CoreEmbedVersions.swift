// Embed version history, restore and image Enhance from the Rust core (the
// `embedVersionHistory`, `restoreEmbedVersion`, `startImageEnhance`,
// `imageEnhanceStatus`, `waitImageEnhance` and `saveImageEnhanceResult`
// calls of `ViewModelCore`, packages/openmates-apple-bindings
// view_embeds.rs and view_embed_enhance.rs).
//
// `CoreEmbedVersions` forwards each call through `CoreSession.perform` (a
// `CoreCancellation` tied to the calling task) and feeds the core's
// `unownedSocketFrame` events into the `ImageEnhanceWaker` of a running wait.
// It keeps the Enhance operation id per embed for the app's lifetime, so a
// timeout, cancel or lost answer resumes the same job and is never charged
// twice. `EmbedVersionEditModel` is the fullscreen's view state in front of
// the injectable `EmbedVersionsCoreClient`; it only picks the save scope from
// where the fullscreen was opened (the web `imageEnhance.svelte.ts` glue),
// waits in short slices and turns typed core errors into messages. The core
// decides versions, conflicts, billing and idempotency.
//
// Web source: frontend/packages/ui/src/components/embeds/images/imageEnhance.svelte.ts
//             frontend/packages/ui/src/services/rustCore/embeds/embedEditSession.ts
// Specification: specifications/features/embed-user-edits/specification.yml
// Assertions: embed-user-edits.enhance.button, embed-user-edits.restore.creates-version, embed-user-edits.edit.next-version, embed-user-edits.enhance.billed-once-refunded-on-failure
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities

import Combine
import Foundation

// MARK: - Core client

/// The core calls behind the embed version list, restore and Enhance.
/// `CoreEmbedVersions` is the app's implementation; tests inject a fake.
@MainActor
protocol EmbedVersionsCoreClient: AnyObject {
    func versionHistory(embedId: String, scope: EmbedScopeRecord?) async throws -> EmbedVersionHistoryRecord
    func restoreVersion(embedId: String, scope: EmbedScopeRecord, fromVersion: Int64) async throws -> EmbedRevisionOutcomeRecord
    func startEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceJobRecord
    func enhanceStatus(operationId: String) async throws -> ImageEnhanceJobRecord
    /// One wait slice of at most `deadlineMs`; `EnhanceTimeout` when the job is still running.
    func waitEnhance(operationId: String, deadlineMs: UInt64) async throws -> ImageEnhanceJobRecord
    func saveEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceSavedRecord
    /// The Enhance operation id of `embedId` that is not settled yet.
    func pendingEnhanceOperation(embedId: String) -> String?
    /// Keep (`operationId`) or forget (`nil`) the unsettled Enhance of `embedId`.
    func rememberEnhanceOperation(_ operationId: String?, embedId: String)
}

/// The core call that writes a chat's pending "embed updated" notices.
@MainActor
protocol EmbedNoticeCoreClient: AnyObject {
    func reconcileNotices(chatId: String) async throws -> EmbedNoticeReconcileRecord
}

/// Runs the notice reconcile once per chat open (web `ChatHistory.svelte`
/// reconciles once per chat); a failure is logged, never shown.
@MainActor
final class EmbedNoticeReconciler {
    private let client: EmbedNoticeCoreClient?
    private var reconciledOpen: UUID?

    init(client: EmbedNoticeCoreClient?) {
        self.client = client
    }

    /// Reconciles `chatId` for the open identified by `openToken`; a second
    /// call for the same open does nothing. `nil`: skipped or failed.
    func reconcileOnOpen(chatId: String, openToken: UUID) async -> EmbedNoticeReconcileRecord? {
        guard let client, reconciledOpen != openToken else { return nil }
        reconciledOpen = openToken
        do {
            let report = try await client.reconcileNotices(chatId: chatId)
            if let deferred = report.deferredCode {
                NativeDiagnostics.info("core_embed_notices_deferred code=\(deferred)", category: "core_bridge")
            }
            return report
        } catch {
            let failure = EmbedEditFailure.classify(error)
            if failure != .cancelled {
                NativeDiagnostics.error("core_embed_notices_failed class=\(failure.code)", category: "core_bridge")
            }
            return nil
        }
    }
}

@MainActor
final class CoreEmbedVersions: EmbedVersionsCoreClient, EmbedNoticeCoreClient {
    private static var instance: CoreEmbedVersions?

    /// The app's client over `CoreSession.shared`; `nil` when the core could
    /// not be created (`CoreSession.launchError`).
    static func live() -> CoreEmbedVersions? {
        if let instance { return instance }
        guard let session = CoreSession.shared else {
            NativeDiagnostics.error("core_embed_versions_unavailable reason=no_core", category: "core_bridge")
            return nil
        }
        let created = CoreEmbedVersions(session: session)
        instance = created
        return created
    }

    private let session: CoreSession
    private var wakers: [String: ImageEnhanceWaker] = [:]
    private var pending: [String: String] = [:]
    private var subscription: AnyCancellable?

    init(session: CoreSession) {
        self.session = session
        subscription = session.events.sink { [weak self] event in self?.apply(event) }
    }

    func versionHistory(embedId: String, scope: EmbedScopeRecord?) async throws -> EmbedVersionHistoryRecord {
        try await run("history") { core, cancellation in
            try await core.embedVersionHistory(embedId: embedId, scope: scope, cancellation: cancellation)
        }
    }

    func restoreVersion(embedId: String, scope: EmbedScopeRecord, fromVersion: Int64) async throws -> EmbedRevisionOutcomeRecord {
        try await run("restore") { core, cancellation in
            try await core.restoreEmbedVersion(embedId: embedId, scope: scope, fromVersion: fromVersion, cancellation: cancellation)
        }
    }

    func startEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceJobRecord {
        try await run("enhance_start") { core, cancellation in
            try await core.startImageEnhance(embedId: embedId, scope: scope, operationId: operationId, cancellation: cancellation)
        }
    }

    func enhanceStatus(operationId: String) async throws -> ImageEnhanceJobRecord {
        try await run("enhance_status") { core, cancellation in
            try await core.imageEnhanceStatus(operationId: operationId, cancellation: cancellation)
        }
    }

    func waitEnhance(operationId: String, deadlineMs: UInt64) async throws -> ImageEnhanceJobRecord {
        let waker = ImageEnhanceWaker()
        wakers[operationId] = waker
        defer { if wakers[operationId] === waker { wakers[operationId] = nil } }
        return try await run("enhance_wait") { core, cancellation in
            try await core.waitImageEnhance(operationId: operationId, deadlineMs: deadlineMs, waker: waker, cancellation: cancellation)
        }
    }

    func saveEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceSavedRecord {
        try await run("enhance_save") { core, cancellation in
            try await core.saveImageEnhanceResult(embedId: embedId, scope: scope, operationId: operationId, cancellation: cancellation)
        }
    }

    func pendingEnhanceOperation(embedId: String) -> String? { pending[embedId] }

    func rememberEnhanceOperation(_ operationId: String?, embedId: String) {
        pending[embedId] = operationId
    }

    /// Writes the `embed_updated` events the server lists as pending for
    /// `chatId` (offline and Team chats come back as `deferredCode`).
    func reconcileNotices(chatId: String) async throws -> EmbedNoticeReconcileRecord {
        try await run("reconcile_notices") { core, cancellation in
            try await core.reconcileEmbedUpdateNotices(chatId: chatId, cancellation: cancellation)
        }
    }

    /// Enhance frames wake a running wait; sign-out forgets unsettled jobs
    /// (their ids belong to the previous account).
    private func apply(_ event: ViewEventRecord) {
        switch event {
        case .unownedSocketFrame(let eventType, let payloadJson):
            guard !wakers.isEmpty, eventType.hasPrefix("image_enhance_") else { return }
            for waker in wakers.values {
                do {
                    _ = try waker.notifyFrame(eventType: eventType, payloadJson: payloadJson)
                } catch {
                    NativeDiagnostics.error(
                        "core_embed_enhance_frame_rejected class=\(CoreSession.errorClass(error))", category: "core_bridge")
                }
            }
        case .session(let change):
            switch change {
            case .signedOut, .expired, .accessDenied:
                pending = [:]
                wakers = [:]
            case .admitted, .restored, .verificationRequired:
                break
            }
        default:
            break
        }
    }

    /// One core call with a timing line and a fixed outcome class (never ids or content).
    private func run<T: Sendable>(_ phase: String,
                                  _ operation: (ViewModelCore, CoreCancellation) async throws -> T) async throws -> T {
        let started = NativeSyncPerfLog.now()
        do {
            let value = try await session.perform(operation)
            NativeSyncPerfLog.info("phase=core.embed_edit.\(phase) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            return value
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.embed_edit.\(phase) outcome=\(EmbedEditFailure.classify(error).code) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }
}

// MARK: - Failure classes

/// What a failed core call means for the fullscreen.
enum EmbedEditFailure: Equatable {
    /// The embed changed meanwhile: reload the version list and the embed.
    case versionConflict
    /// Not enough credits; nothing charged.
    case insufficientCredits
    /// Team images cannot be enhanced yet.
    case teamUnavailable
    /// The Enhance job failed on the server; nothing charged.
    case enhanceFailed
    /// The unsaved result is gone (after 24 hours).
    case enhanceExpired
    /// The call was cancelled (the user left the image).
    case cancelled
    /// The outcome is unknown or temporary: keep the operation id and resume it.
    case retryable(String)
    /// A final refusal: the operation id is dropped.
    case refused(String)

    /// Fixed, non-secret code for logs.
    var code: String {
        switch self {
        case .versionConflict: return "embed_version_conflict"
        case .insufficientCredits: return "insufficient_credits"
        case .teamUnavailable: return "team_enhance_unavailable"
        case .enhanceFailed: return "enhance_failed"
        case .enhanceExpired: return "enhance_result_expired"
        case .cancelled: return "cancelled"
        case .retryable(let code), .refused(let code): return code
        }
    }

    /// Whether the unsettled Enhance operation id must be kept for a resume.
    var keepsOperation: Bool {
        switch self {
        case .cancelled, .retryable: return true
        default: return false
        }
    }

    static func classify(_ error: Error) -> EmbedEditFailure {
        if error is CancellationError { return .cancelled }
        guard let edit = error as? EmbedEditError else {
            if let core = error as? CoreError {
                return core == .Cancelled ? .cancelled : .retryable("core_error")
            }
            return .retryable("unknown")
        }
        switch edit {
        case .VersionConflict(_): return .versionConflict
        case .InsufficientCredits: return .insufficientCredits
        case .TeamUnavailable: return .teamUnavailable
        case .EnhanceFailed(_, _): return .enhanceFailed
        case .EnhanceExpired(_): return .enhanceExpired
        case .Cancelled: return .cancelled
        case .EnhanceTimeout(_): return .retryable("enhance_timeout")
        case .EnhanceNotReady(_): return .retryable("enhance_result_not_ready")
        case .Offline: return .retryable("offline")
        case .RateLimited: return .retryable("rate_limited")
        case .Busy: return .retryable("enhance_job_busy")
        case .Unavailable(_): return .retryable("unavailable")
        case .Transport(let code): return .retryable("transport_\(code)")
        case .Internal(_): return .retryable("internal")
        case .SessionExpired: return .retryable("session_expired")
        case .Authentication: return .retryable("authentication")
        case .VerificationRequired: return .retryable("verification_required")
        case .ProjectContextRequired: return .refused("project_context_required")
        case .ScopeMismatch: return .refused("enhance_scope_mismatch")
        case .AccessDenied(let code): return .refused(code)
        case .Validation(let code): return .refused(code)
        case .Refused(let code): return .refused(code)
        case .KeyUnavailable: return .refused("embed_key_unavailable")
        case .NotFound(let code): return .refused(code)
        case .InvalidSource(let code): return .refused(code)
        case .OperationConflict: return .refused("operation_id_conflict")
        }
    }
}

// MARK: - Where the fullscreen was opened

enum EmbedEditUnavailableReason: Equatable {
    /// Shared, public, example or otherwise read-only view.
    case readOnly
    /// Team chat or Team Project (Enhance and restore are Personal only).
    case team
}

enum EmbedEditAvailability: Equatable {
    case available(EmbedScopeRecord)
    case unavailable(EmbedEditUnavailableReason)
}

/// Where the fullscreen was opened (web `ImageEditPlace`).
struct EmbedEditPlace: Equatable {
    var chatId: String?
    var chatTeamId: String?
    var projectId: String?
    var projectTeamId: String?
    var readOnly = false

    /// Project scope from the Projects workspace, chat scope from a chat;
    /// Teams and read-only viewers cannot save (web `imageEditAvailability`).
    var availability: EmbedEditAvailability {
        if let projectId, !projectId.isEmpty {
            if readOnly { return .unavailable(.readOnly) }
            if projectTeamId != nil { return .unavailable(.team) }
            return .available(.project(projectId: projectId, teamId: nil))
        }
        guard let chatId, !chatId.isEmpty, !readOnly else { return .unavailable(.readOnly) }
        if chatTeamId != nil { return .unavailable(.team) }
        return .available(.chat(chatId: chatId, teamId: nil))
    }

    /// The scope the version list is read in (Team embeds need theirs).
    var readScope: EmbedScopeRecord? {
        if let projectId, !projectId.isEmpty { return .project(projectId: projectId, teamId: projectTeamId) }
        if let chatId, !chatId.isEmpty { return .chat(chatId: chatId, teamId: chatTeamId) }
        return nil
    }
}

// MARK: - View model

/// State of the Enhance button of one opened image.
enum ImageEnhancePhase: Equatable {
    case idle
    case unavailable(EmbedEditUnavailableReason)
    case running
    case saved(version: Int64)
    case failed
    case expired
    case insufficientCredits

    /// The web `enhanceState` of the round button.
    var buttonState: String {
        switch self {
        case .running: return "running"
        case .unavailable: return "unavailable"
        case .failed, .expired, .insufficientCredits: return "failed"
        case .idle, .saved: return "idle"
        }
    }

    var canStart: Bool {
        switch self {
        case .running, .unavailable: return false
        default: return true
        }
    }
}

/// A message the fullscreen shows once (the web shows these as error notifications).
enum EmbedEditMessage: Equatable {
    case enhanceFailed
    case insufficientCredits
    case teamUnavailable
    case versionConflict
    case restoreFailed
    case enhanced(version: Int64)
    case restored(fromVersion: Int64)

    var isError: Bool {
        switch self {
        case .enhanced, .restored: return false
        default: return true
        }
    }
}

@MainActor
final class EmbedVersionEditModel: ObservableObject {
    /// About 15 s per wait: the wait holds the core, so other commands queue behind it.
    static let waitSliceMs: UInt64 = 15_000
    /// Slices before a still-running job is left for a later resume (about 3 minutes).
    static let maxWaitSlices = 12

    @Published private(set) var history: EmbedVersionHistoryRecord?
    @Published private(set) var historyLoading = false
    @Published private(set) var historyFailed = false
    @Published private(set) var phase: ImageEnhancePhase = .idle
    /// Quoted price of the current Enhance job, once the core reported it.
    @Published private(set) var credits: Int64?
    @Published private(set) var message: EmbedEditMessage?
    /// Version whose restore waits for the second tap.
    @Published private(set) var restoreConfirmVersion: Int64?
    @Published private(set) var restoringVersion: Int64?
    @Published private(set) var availability: EmbedEditAvailability = .unavailable(.readOnly)

    /// Called after a save or conflict with the new head (`nil`: unknown, reload it).
    var onHeadChanged: ((Int64?) -> Void)?

    private let client: EmbedVersionsCoreClient?
    private(set) var embedId: String?
    private var place = EmbedEditPlace()
    private var enhanceable = false
    private var enhanceTask: Task<Void, Never>?
    private var historyTask: Task<Void, Never>?
    private var restoreTask: Task<Void, Never>?
    /// Bumped by `close()`: results of an earlier open never touch the state.
    private var generation = 0

    init(client: EmbedVersionsCoreClient?) {
        self.client = client
    }

    /// More than one version: the fullscreen shows the list.
    var showsVersionList: Bool { (history?.versions.count ?? 0) > 1 }
    /// Restore is offered only where a save is allowed (Personal account).
    var canRestore: Bool {
        if case .available = availability { return client != nil }
        return false
    }
    /// The versions newest first, as the list shows them.
    var versionsNewestFirst: [EmbedVersionRecord] { (history?.versions ?? []).reversed() }

    /// Opens the model for `embedId`; reads its version list and, for an
    /// image, resumes an Enhance this app still has unsettled.
    @discardableResult
    func open(embedId: String, place: EmbedEditPlace, enhanceable: Bool) -> Task<Void, Never> {
        close()
        self.embedId = embedId
        self.place = place
        self.enhanceable = enhanceable
        availability = client == nil ? .unavailable(.readOnly) : place.availability
        if case .unavailable(let reason) = availability { phase = .unavailable(reason) } else { phase = .idle }
        let task = Task<Void, Never> { [weak self] in
            guard let self else { return }
            await self.loadHistory()
            guard !Task.isCancelled, self.embedId == embedId, self.enhanceable,
                  case .available(let scope) = self.availability,
                  let operationId = self.client?.pendingEnhanceOperation(embedId: embedId) else { return }
            self.launchEnhance(embedId: embedId, scope: scope, operationId: operationId, resume: true)
        }
        historyTask = task
        return task
    }

    /// The user left the image: running calls are cancelled; an unsettled
    /// Enhance keeps its operation id and resumes on the next open.
    func close() {
        enhanceTask?.cancel(); enhanceTask = nil
        historyTask?.cancel(); historyTask = nil
        restoreTask?.cancel(); restoreTask = nil
        generation += 1
        embedId = nil
        history = nil
        historyLoading = false
        historyFailed = false
        credits = nil
        message = nil
        restoreConfirmVersion = nil
        restoringVersion = nil
        phase = .idle
    }

    func clearMessage() { message = nil }

    /// Re-read the version list (after a save or a conflict).
    func loadHistory() async {
        guard let client, let embedId else { return }
        let opened = generation
        historyLoading = true
        defer { if opened == generation { historyLoading = false } }
        do {
            let record = try await client.versionHistory(embedId: embedId, scope: place.readScope)
            guard opened == generation else { return }
            history = record
            historyFailed = false
        } catch {
            guard opened == generation, EmbedEditFailure.classify(error) != .cancelled else { return }
            historyFailed = true
        }
    }

    // MARK: Enhance

    /// Press of the Enhance button; a no-op while a run is going or where
    /// Enhance is not offered. Reuses the unsettled operation id of this image.
    @discardableResult
    func startEnhance() -> Task<Void, Never>? {
        guard enhanceable, phase.canStart, let client, let embedId,
              case .available(let scope) = availability else { return nil }
        if let operationId = client.pendingEnhanceOperation(embedId: embedId) {
            return launchEnhance(embedId: embedId, scope: scope, operationId: operationId, resume: true)
        }
        let operationId = UUID().uuidString.lowercased()
        client.rememberEnhanceOperation(operationId, embedId: embedId)
        return launchEnhance(embedId: embedId, scope: scope, operationId: operationId, resume: false)
    }

    @discardableResult
    private func launchEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String, resume: Bool) -> Task<Void, Never> {
        enhanceTask?.cancel()
        phase = .running
        message = nil
        let opened = generation
        let task = Task<Void, Never> { [weak self] in
            guard let self else { return }
            await self.runEnhance(embedId: embedId, scope: scope, operationId: operationId, resume: resume, opened: opened)
        }
        enhanceTask = task
        return task
    }

    private func runEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String, resume: Bool, opened: Int) async {
        guard let client else { return }
        do {
            var job = try await firstRead(client, embedId: embedId, scope: scope, operationId: operationId, resume: resume)
            if opened == generation { credits = job.credits }
            var slices = 0
            while job.state == .pending {
                try Task.checkCancellation()
                do {
                    job = try await client.waitEnhance(operationId: operationId, deadlineMs: Self.waitSliceMs)
                } catch let error where EmbedEditFailure.classify(error) == .retryable("enhance_timeout") {
                    slices += 1
                    if slices >= Self.maxWaitSlices { throw error }
                }
            }
            switch job.state {
            case .failed: throw EmbedEditError.EnhanceFailed(operationId: operationId, code: job.errorCode ?? "enhance_failed")
            case .expired: throw EmbedEditError.EnhanceExpired(operationId: operationId)
            case .pending, .ready, .committed: break
            }
            let saved = try await client.saveEnhance(embedId: embedId, scope: scope, operationId: operationId)
            let version: Int64
            switch saved {
            case .committed(_, let outcome): version = outcome.version
            case .alreadyCommitted(_, let committed): version = committed
            }
            client.rememberEnhanceOperation(nil, embedId: embedId)
            guard opened == generation else { return }
            phase = .saved(version: version)
            message = .enhanced(version: version)
            onHeadChanged?(version)
            await loadHistory()
        } catch {
            await enhanceFailed(EmbedEditFailure.classify(error), embedId: embedId, opened: opened)
        }
    }

    /// A fresh start, or a resume that reads the job first (a job the server
    /// never received is started under the same operation id).
    private func firstRead(_ client: EmbedVersionsCoreClient, embedId: String, scope: EmbedScopeRecord,
                           operationId: String, resume: Bool) async throws -> ImageEnhanceJobRecord {
        guard resume else { return try await client.startEnhance(embedId: embedId, scope: scope, operationId: operationId) }
        do {
            return try await client.enhanceStatus(operationId: operationId)
        } catch EmbedEditError.NotFound(_) {
            return try await client.startEnhance(embedId: embedId, scope: scope, operationId: operationId)
        }
    }

    private func enhanceFailed(_ failure: EmbedEditFailure, embedId: String, opened: Int) async {
        if !failure.keepsOperation { client?.rememberEnhanceOperation(nil, embedId: embedId) }
        guard opened == generation else { return }
        switch failure {
        case .cancelled:
            phase = .idle
        case .insufficientCredits:
            phase = .insufficientCredits
            message = .insufficientCredits
        case .teamUnavailable:
            phase = .unavailable(.team)
            message = .teamUnavailable
        case .enhanceExpired:
            phase = .expired
            message = .enhanceFailed
        case .versionConflict:
            phase = .failed
            message = .versionConflict
            onHeadChanged?(nil)
            await loadHistory()
        case .enhanceFailed, .retryable, .refused:
            phase = .failed
            message = .enhanceFailed
        }
    }

    // MARK: Restore

    /// First tap asks for confirmation, the second restores `version` as the
    /// next version (web `restoreSelectedVersion`).
    @discardableResult
    func requestRestore(_ version: Int64) -> Task<Void, Never>? {
        guard canRestore, restoringVersion == nil, version != history?.currentVersion else { return nil }
        guard restoreConfirmVersion == version else {
            restoreConfirmVersion = version
            return nil
        }
        guard let client, let embedId, case .available(let scope) = availability else { return nil }
        restoringVersion = version
        message = nil
        let opened = generation
        let task = Task<Void, Never> { [weak self] in
            guard let self else { return }
            await self.runRestore(client, embedId: embedId, scope: scope, version: version, opened: opened)
        }
        restoreTask = task
        return task
    }

    func cancelRestore() { restoreConfirmVersion = nil }

    private func runRestore(_ client: EmbedVersionsCoreClient, embedId: String, scope: EmbedScopeRecord,
                            version: Int64, opened: Int) async {
        do {
            let outcome = try await client.restoreVersion(embedId: embedId, scope: scope, fromVersion: version)
            guard opened == generation else { return }
            restoringVersion = nil
            restoreConfirmVersion = nil
            message = .restored(fromVersion: version)
            onHeadChanged?(outcome.version)
            await loadHistory()
        } catch {
            guard opened == generation else { return }
            restoringVersion = nil
            switch EmbedEditFailure.classify(error) {
            case .cancelled:
                break
            case .versionConflict:
                restoreConfirmVersion = nil
                message = .versionConflict
                onHeadChanged?(nil)
                await loadHistory()
            default:
                message = .restoreFailed
            }
        }
    }
}
