// The app's one Rust view-model core (`ViewModelCore`, plan
// apple-client-core-migration A4 lane 1). Created once at app start
// (`CoreSession.launch()` from `OpenMatesApp.init`), never lazily on first
// use: it owns the core, its credential store (Keychain in the app, injected
// in tests) and the event relay, and publishes the core's session state on the
// main actor. Every call passes a `CoreCancellation` tied to the calling Swift
// task, so a cancelled or failed call settles its waiter with an error and
// never hangs. No protocol, session or cache logic: the core decides, this
// type only forwards calls and mirrors `Session` events.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.credentials.snapshot-boundary, client-core.apple.strangler-order
// Login (password, backup code, recovery key, passkey, pair), adoption of a
// Swift-finished passkey signup, device verification (code or passkey), the
// profile read, REST and uploads go through here too (`AuthManager` and
// `APIClient` are thin callers), logins and uploads each with a timing line.
// Memory documents (Settings > Memories) and the assistant Memory-write
// calls are thin forwards too (`listMemoryDocuments` ... `undoAssistantMemoryWrite`).

import Combine
import Foundation

/// A credential store the core can acknowledge stored revisions through.
/// `attach(core:)` is called once, right after the core is created.
protocol CoreAcknowledgingCredentialStore: CredentialStore {
    func attach(core: ViewModelCore)
}

extension KeychainCredentialStore: CoreAcknowledgingCredentialStore {}

/// The core's session as last reported by a `Session` event.
enum CoreSessionState: Equatable {
    /// `start` has not been called yet.
    case notStarted
    /// `start` is running and the core has not reported a session yet.
    case starting
    case signedOut
    /// A stored session was restored from the cache, not yet admitted.
    case restored(displayName: String?)
    /// The server admitted the session; `expiresAt` (unix ms) is the
    /// deadline of a paired session, `nil` for an ordinary one.
    case admitted(username: String, expiresAt: UInt64?)
    case expired
    case accessDenied(AccessDenialRecord)
    /// The server holds the session until the device is verified or the user signs in again.
    case verificationRequired(SessionVerificationRecord)
    /// `start` failed before the core reported any session.
    case failed(CoreError)

    init(_ event: SessionEventRecord) {
        switch event {
        case .signedOut: self = .signedOut
        case .restored(let displayName): self = .restored(displayName: displayName)
        case .admitted(let username, let expiresAt): self = .admitted(username: username, expiresAt: expiresAt)
        case .expired: self = .expired
        case .accessDenied(let denial): self = .accessDenied(denial)
        case .verificationRequired(let verification): self = .verificationRequired(verification)
        }
    }

    /// Non-identifying name for diagnostics (never the display or user name).
    var diagnosticName: String {
        switch self {
        case .notStarted: return "not_started"
        case .starting: return "starting"
        case .signedOut: return "signed_out"
        case .restored: return "restored"
        case .admitted: return "admitted"
        case .expired: return "expired"
        case .accessDenied: return "access_denied"
        case .verificationRequired: return "verification_required"
        case .failed: return "failed"
        }
    }
}

@MainActor
final class CoreSession: ObservableObject {
    /// The app's core, set by `launch()`; `nil` before launch, in unit-test
    /// hosts and when creation failed (see `launchError`).
    private(set) static var shared: CoreSession?
    /// Why `launch()` could not create the core.
    private(set) static var launchError: Error?

    /// Folder the core creates inside the Application Support container.
    static let cacheDirectoryName = "openmates-core"

    @Published private(set) var state: CoreSessionState = .notStarted {
        didSet {
            guard state != .starting, !startWaiters.isEmpty else { return }
            let waiters = startWaiters
            startWaiters = []
            waiters.forEach { $0.resume() }
        }
    }
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    /// The last error of a call made through this type.
    @Published private(set) var lastError: CoreError?
    /// Every core event in core order, on the main actor (session events
    /// are applied to `state` first). Later lanes subscribe here.
    let events = PassthroughSubject<ViewEventRecord, Never>()

    let core: ViewModelCore

    /// Creates the core over `config` with `credentials`. Throws the core's
    /// error (`Invalid` for a bad config, `Io` for an unusable cache folder).
    init(config: CoreConfig, credentials: CoreAcknowledgingCredentialStore) throws {
        let started = NativeSyncPerfLog.now()
        let sink = CoreSessionEventSink()
        let relay = CoreViewEventRelay { event in sink.target?.apply(event) }
        core = try ViewModelCore(config: config, credentials: credentials, listener: relay)
        credentials.attach(core: core)
        sink.target = self
        NativeSyncPerfLog.info("phase=core.create ms=\(NativeSyncPerfLog.ms(since: started))")
    }

    /// Creates the app's core once, at app start. A failure is logged and
    /// kept in `launchError`; it never falls back to another path.
    static func launch() {
        guard shared == nil else { return }
        do {
            shared = try CoreSession(config: appConfig(), credentials: KeychainCredentialStore())
        } catch {
            launchError = error
            NativeDiagnostics.error(
                "core_session_create_failed error=\(Self.errorClass(error))", category: "core_bridge")
        }
    }

    #if OPENMATES_CORE_TEST_SUPPORT
    /// UI-test fixtures only (`CoreUITestSeed`): creates the app's core over a
    /// seeded fixture cache instead of the product config and Keychain. Must
    /// run before `launch()`, which then keeps this core.
    static func launchSeededFixture(config: CoreConfig, credentials: CoreAcknowledgingCredentialStore) throws {
        guard shared == nil else { throw CoreError.Invalid(message: "The app core already exists.") }
        shared = try CoreSession(config: config, credentials: credentials)
    }
    #endif

    /// Config of the app's core: the selected server and a private folder in
    /// the app's Application Support container (created by the system call).
    static func appConfig(profile: ServerProfile = .current()) throws -> CoreConfig {
        let container = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true)
        return CoreConfig(
            apiUrl: profile.apiBaseURL.absoluteString,
            appUrl: profile.webBaseURL.absoluteString,
            cacheContainer: container.path,
            cacheDirectoryName: cacheDirectoryName)
    }

    /// Restore the stored session (`ViewModelCore.start`): the core reports
    /// `signedOut`, or `restored` then `admitted`, through `state`.
    func start() async throws {
        state = .starting
        let started = NativeSyncPerfLog.now()
        do {
            try await perform { core, cancellation in try await core.start(cancellation: cancellation) }
            NativeSyncPerfLog.info(
                "phase=core.start outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
        } catch {
            if state == .starting, let coreError = error as? CoreError { state = .failed(coreError) }
            NativeSyncPerfLog.warning(
                "phase=core.start outcome=\(Self.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }

    /// Re-run the core's session check (`ViewModelCore.start`) without
    /// leaving the current state first, so an admitted or restored session
    /// keeps its UI while the core admits it again and rotates the `ws_token`.
    func readmit() async throws {
        let started = NativeSyncPerfLog.now()
        do {
            try await perform { core, cancellation in try await core.start(cancellation: cancellation) }
            NativeSyncPerfLog.info(
                "phase=core.start mode=readmit outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.start mode=readmit outcome=\(Self.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }

    /// Returns once a running `start` has reported a session or failed.
    func settled() async {
        guard state == .starting else { return }
        await withCheckedContinuation { startWaiters.append($0) }
    }

    /// Sign in with email and password in the core (`ViewModelCore.loginPassword`).
    /// The core stores the session and admits it (`Session(Admitted)`); the
    /// record reports the core's legacy password migration.
    @discardableResult
    func loginPassword(email: String, password: String, tfaCode: String?,
                       stayLoggedIn: Bool) async throws -> LoginRecord {
        try await timedLogin(method: "password") { core, cancellation in
            try await core.loginPassword(email: email, password: password, tfaCode: tfaCode,
                stayLoggedIn: stayLoggedIn, cancellation: cancellation)
        }
    }

    /// Password plus a backup code (`ViewModelCore.loginBackupCode`); a
    /// refused code is `CoreError.Authentication`.
    @discardableResult
    func loginBackupCode(email: String, password: String, backupCode: String,
                         stayLoggedIn: Bool) async throws -> LoginRecord {
        try await timedLogin(method: "backup_code") { core, cancellation in
            try await core.loginBackupCode(email: email, password: password, backupCode: backupCode,
                stayLoggedIn: stayLoggedIn, cancellation: cancellation)
        }
    }

    /// Sign in with the recovery key (`ViewModelCore.loginRecoveryKey`).
    @discardableResult
    func loginRecoveryKey(email: String, recoveryKey: String, stayLoggedIn: Bool) async throws -> LoginRecord {
        try await timedLogin(method: "recovery_key") { core, cancellation in
            try await core.loginRecoveryKey(email: email, recoveryKey: recoveryKey,
                stayLoggedIn: stayLoggedIn, cancellation: cancellation)
        }
    }

    /// Begin a passkey sign-in: the options of the system ceremony. The core
    /// keeps the continuation until `finishPasskeyLogin` or `cancelPasskeyLogin`.
    func beginPasskeyLogin(email: String?) async throws -> PasskeyChallengeRecord {
        try await timedLogin(method: "passkey_begin") { core, cancellation in
            try await core.beginPasskeyLogin(email: email, cancellation: cancellation)
        }
    }

    /// Finish the begun passkey sign-in with the ceremony's assertion JSON and
    /// raw PRF output; the core verifies, unwraps, stores and admits.
    @discardableResult
    func finishPasskeyLogin(assertionJson: Data, prfOutput: Data, stayLoggedIn: Bool) async throws -> LoginRecord {
        try await timedLogin(method: "passkey") { core, cancellation in
            try await core.finishPasskeyLogin(assertionJson: assertionJson, prfOutput: prfOutput,
                stayLoggedIn: stayLoggedIn, cancellation: cancellation)
        }
    }

    /// Forget a begun passkey login or device verification (none: no-op).
    func cancelPasskeyLogin() async {
        await core.cancelPasskeyLogin()
    }

    /// One finish step of the core's pair login; `true` once the paired
    /// session is stored and started (see `ViewModelCore.finishPairLogin`).
    func finishPairLogin() async throws -> Bool {
        try await timedLogin(method: "pair") { core, cancellation in
            try await core.finishPairLogin(cancellation: cancellation)
        }
    }

    /// Hand a session that a Swift ceremony finished to the core
    /// (`ViewModelCore.adoptSession`); the core owns it afterwards.
    func adoptSession(_ session: AdoptedSessionRecord) async throws {
        try await timedLogin(method: "adopt") { core, cancellation in
            try await core.adoptSession(session: session, cancellation: cancellation)
        }
    }

    /// Answer a pending two-factor device verification in the core.
    func verifyDevice2fa(code: String) async throws {
        try await timedLogin(method: "device_2fa") { core, cancellation in
            try await core.verifyDevice2fa(code: code, cancellation: cancellation)
        }
    }

    /// Begin answering a pending passkey device verification: the options
    /// of the system ceremony for this account.
    func beginPasskeyDeviceVerification() async throws -> PasskeyChallengeRecord {
        try await timedLogin(method: "device_passkey_begin") { core, cancellation in
            try await core.beginPasskeyDeviceVerification(cancellation: cancellation)
        }
    }

    /// Answer the pending passkey device verification with the ceremony's
    /// assertion JSON (no PRF); success emits `Session(Admitted)`.
    func finishPasskeyDeviceVerification(assertionJson: Data) async throws {
        try await timedLogin(method: "device_passkey") { core, cancellation in
            try await core.finishPasskeyDeviceVerification(assertionJson: assertionJson, cancellation: cancellation)
        }
    }

    /// The account's profile (`ViewModelCore.userProfile`): `fresh` once the
    /// server admitted it in this run, else the copy cached at the last
    /// admission of a restored session. `Authentication` without either.
    func userProfile() async throws -> UserProfileRecord {
        try await perform { core, _ in try await core.userProfile() }
    }

    /// One REST request with the core's session and cookies.
    func httpRequest(_ request: HttpRequestRecord) async throws -> HttpResponseRecord {
        try await perform { core, cancellation in
            try await core.httpRequest(request: request, cancellation: cancellation)
        }
    }

    /// One file upload through the core (`ViewModelCore.uploadFile`); the
    /// core streams `request.filePath` and returns any status as a response.
    /// Logs only the outcome class and the duration.
    func uploadFile(_ request: UploadRequestRecord) async throws -> HttpResponseRecord {
        let started = NativeSyncPerfLog.now()
        do {
            let response = try await perform { core, cancellation in
                try await core.uploadFile(request: request, cancellation: cancellation)
            }
            NativeSyncPerfLog.info(
                "phase=core.upload outcome=ok status=\(response.status) ms=\(NativeSyncPerfLog.ms(since: started))")
            return response
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.upload outcome=\(Self.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }

    // MARK: - Memories (`ViewModelCore` memory documents)
    // The core decrypts, parses, validates, stamps and re-encrypts; these only
    // forward. Refusals arrive as `CoreError.Memory(code:)` with the web codes.

    /// The personal Memories in storage order, read fresh.
    func listMemoryDocuments() async throws -> [MemoryDocumentRecord] {
        try await perform { core, cancellation in try await core.listMemoryDocuments(cancellation: cancellation) }
    }

    /// One personal Memory by id; `Memory(rule_not_found)` for an unknown id.
    func memoryDocument(id: String) async throws -> MemoryDocumentRecord {
        try await perform { core, cancellation in try await core.memoryDocument(id: id, cancellation: cancellation) }
    }

    /// Create a Memory; the core assigns the id and save times.
    func createMemoryDocument(fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord {
        try await perform { core, cancellation in
            try await core.createMemoryDocument(fields: fields, cancellation: cancellation)
        }
    }

    /// Replace Memory `id` with `fields` (last write wins, like the web).
    func updateMemoryDocument(id: String, fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord {
        try await perform { core, cancellation in
            try await core.updateMemoryDocument(id: id, fields: fields, cancellation: cancellation)
        }
    }

    /// Delete Memory `id`.
    func deleteMemoryDocument(id: String) async throws {
        try await perform { core, cancellation in try await core.deleteMemoryDocument(id: id, cancellation: cancellation) }
    }

    /// The web expiry sweep; returns how many Memories were deleted.
    @discardableResult
    func deleteExpiredMemoryDocuments() async throws -> UInt32 {
        try await perform { core, cancellation in try await core.deleteExpiredMemoryDocuments(cancellation: cancellation) }
    }

    /// Opt this device's sends in or out of assistant Memory writes (off by
    /// default). Turn on only once the chat shows `context_entry` notices with Undo.
    func setAssistantMemoryWrites(enabled: Bool) {
        core.setAssistantMemoryWrites(enabled: enabled)
    }

    /// The assistant's undoable Memory writes in `chatId`, oldest first.
    func assistantMemoryWrites(chatId: String) async throws -> [ContextEntryNoticeRecord] {
        try await perform { core, cancellation in
            try await core.assistantMemoryWrites(chatId: chatId, cancellation: cancellation)
        }
    }

    /// Undo the assistant's Memory write `jobId` in `chatId`.
    func undoAssistantMemoryWrite(chatId: String, jobId: String) async throws -> MemoryUndoOutcomeRecord {
        try await perform { core, cancellation in
            try await core.undoAssistantMemoryWrite(chatId: chatId, jobId: jobId, cancellation: cancellation)
        }
    }

    /// Login timing next to core.create/core.start/core.logout. Logs only the
    /// method, the error class and the duration: never codes, names or tokens.
    private func timedLogin<T: Sendable>(
        method: String, _ operation: (ViewModelCore, CoreCancellation) async throws -> T
    ) async throws -> T {
        let started = NativeSyncPerfLog.now()
        do {
            let result = try await perform(operation)
            NativeSyncPerfLog.info(
                "phase=core.login method=\(method) outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
            return result
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.login method=\(method) outcome=\(Self.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }

    /// Sign out in the core: stored credentials and cache are wiped and the
    /// core reports `signedOut` even when the remote logout failed (thrown).
    func logout() async throws {
        let started = NativeSyncPerfLog.now()
        do {
            try await perform { core, _ in try await core.logout() }
            NativeSyncPerfLog.info(
                "phase=core.logout outcome=ok ms=\(NativeSyncPerfLog.ms(since: started))")
        } catch {
            NativeSyncPerfLog.warning(
                "phase=core.logout outcome=\(Self.errorClass(error)) ms=\(NativeSyncPerfLog.ms(since: started))")
            throw error
        }
    }

    /// Runs one core call with a `CoreCancellation` that fires when the
    /// calling task is cancelled. The core's error is recorded in
    /// `lastError` and rethrown; nothing is retried or replaced.
    func perform<T: Sendable>(
        _ operation: (ViewModelCore, CoreCancellation) async throws -> T
    ) async throws -> T {
        let cancellation = CoreCancellation()
        let core = self.core
        do {
            return try await withTaskCancellationHandler {
                try await operation(core, cancellation)
            } onCancel: {
                cancellation.cancel()
            }
        } catch let error as CoreError {
            lastError = error
            throw error
        }
    }

    private func apply(_ event: ViewEventRecord) {
        if case .session(let session) = event {
            CoreLegacyAccess.sessionDidChange(session)
            state = CoreSessionState(session)
        }
        events.send(event)
    }

    /// Fixed, non-secret error class for diagnostics.
    static func errorClass(_ error: Error) -> String {
        guard let coreError = error as? CoreError else { return String(describing: type(of: error)) }
        switch coreError {
        case .Invalid: return "invalid"
        case .Crypto: return "crypto"
        case .Authentication: return "authentication"
        case .TwoFactorRequired: return "two_factor_required"
        case .VerificationRequired: return "verification_required"
        case .SignupRequired: return "signup_required"
        case .Unavailable(let code, _): return "unavailable_\(code)"
        case .Locked: return "locked"
        case .Offline: return "offline"
        case .Forbidden: return "forbidden"
        case .Expired: return "expired"
        case .Cancelled: return "cancelled"
        case .Io: return "io"
        case .ProtocolError: return "protocol"
        case .Conflict: return "conflict"
        // Memory codes are fixed lowercase web codes (`rule_not_found`, ...), never user data.
        case .Memory(let code): return "memory_\(code)"
        case .Internal: return "internal"
        }
    }
}

/// Lets the relay, created before the session object exists, reach it
/// without keeping it alive.
@MainActor
private final class CoreSessionEventSink {
    weak var target: CoreSession?
}
