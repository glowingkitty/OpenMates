// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.delivery.confirmed-action-haptics, apple-notifications.registration.lifecycle, apple-notifications.action.direct-reply
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation, auth.lookup.anti-enumeration, auth.login.method-convergence
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.credentials.snapshot-boundary, client-core.apple.strangler-order
//
// The app's auth state, a thin holder over the Rust core's session
// (`CoreSession`, plan apple-client-core-migration A4 lane 1). The core owns
// the session: start, every login (password, backup code, recovery key,
// passkey, pair), device verification, the legacy password migration, logout,
// cookies, `ws_token`, master key and the profile. This type mirrors its
// `Session` events into SwiftUI state (`state`, `currentUser`, network
// authority) and runs the app-local side effects of a sign-in or sign-out
// (offline scope, drafts, Spotlight, profile cache). Backup-code, recovery-key
// and passkey logins live in `AuthManager+CoreLogin.swift`.

import Combine
import CryptoKit
import Foundation
import SwiftUI

/// Captured before network execution; a late rejection cannot challenge a newer
/// account, server, logical native session, or admission generation.
struct AuthSessionRecoveryContext: Equatable, Sendable {
    let accountID: String
    let profile: ServerProfile
    let sessionID: String
    let generation: UUID
}

/// Reads of the core's session that `AuthManager` makes on admission.
/// Injected in tests, which run without a server session.
struct AuthCoreReads {
    /// The account's server user payload (`userProfile`): `fresh` when the
    /// server admitted it in this run, else cached for a restored session.
    var profile: @MainActor () async throws -> UserProfileRecord
    /// The core's session id and `ws_token` (`CoreLegacyAccess.socketGrant`).
    var socketGrant: @MainActor () async throws -> LegacySocketGrantRecord

    static func live(_ core: CoreSession) -> AuthCoreReads {
        AuthCoreReads(
            profile: { try await core.userProfile() },
            socketGrant: { try await CoreLegacyAccess.socketGrant() })
    }
}

@MainActor
final class AuthManager: ObservableObject {
    @Published var state: AuthState = .initializing {
        didSet {
            if state != .authenticated {
                NotificationReplyStore().revoke()
                networkAuthority = nil
            }
        }
    }
    @Published var currentUser: UserProfile? {
        didSet {
            let ownerChanged = oldValue?.id != nil && currentUser?.id != oldValue?.id
            let preferenceChanged = oldValue?.id != nil && currentUser?.pushNotificationEnabled != oldValue?.pushNotificationEnabled
            let persistedOwner = try? NotificationReplyStore().registration()?.accountID
            if ownerChanged || preferenceChanged || (currentUser?.id != nil && persistedOwner != nil && persistedOwner != currentUser?.id) {
                NotificationReplyStore().revoke()
            }
            if currentUser?.id != oldValue?.id { networkAuthority = nil }
        }
    }
    @Published var error: String?
    @Published private(set) var sessionValidationState: SessionValidationState = .initializing {
        didSet {
            guard sessionValidationState != .onlineAuthenticated, sessionValidationState != .validating else { return }
            if networkAuthority != nil { NotificationReplyStore().revoke() }
            networkAuthority = nil
        }
    }
    /// Cached identity unlocks local history; only this grant permits protected IO.
    /// Granted on every `Session(Admitted)`, dropped on any other state.
    @Published private(set) var networkAuthority: AuthSessionRecoveryContext?

    var hasNetworkAuthority: Bool {
        guard state == .authenticated, let authority = networkAuthority else { return false }
        return currentUser?.id == authority.accountID && ServerProfile.current() == authority.profile &&
            Self.nativeSessionId == authority.sessionID
    }

    static func hasNetworkAuthority(for profile: ServerProfile, sessionID: String? = nil) -> Bool {
        guard let manager = _shared, manager.hasNetworkAuthority,
              manager.networkAuthority?.profile == profile else { return false }
        return sessionID == nil || manager.networkAuthority?.sessionID == sessionID
    }

    static func captureNetworkAuthority() -> AuthSessionRecoveryContext? {
        guard let manager = _shared, manager.hasNetworkAuthority else { return nil }
        return manager.networkAuthority
    }

    static func requireNetworkAuthority(profile: ServerProfile, sessionID: String? = nil) throws {
        guard hasNetworkAuthority(for: profile, sessionID: sessionID) else { throw CancellationError() }
    }

    /// Public/auth bootstrap remains available without an unlocked account.
    /// Once a cached account exists it must not lend the session to protected work.
    static func requireProtectedRequestAuthority(profile: ServerProfile) throws {
        guard let manager = _shared else { return }
        guard manager.currentUser != nil || manager.state != .unauthenticated else { return }
        try requireNetworkAuthority(profile: profile)
    }

    let api: APIClient
    let crypto = CryptoManager.shared
    private let injectedCore: CoreSession?
    private let injectedReads: AuthCoreReads?
    private let profileCacheWriter: ((UserProfile) -> Void)?
    private let sessionScopeActivator: ((UserProfile) throws -> Void)?
    private(set) var lastOpenedSelectionRevision = 0
    /// Changes on every admission and sign-out; fences late async work.
    private(set) var admissionGeneration = UUID()
    private var stateSubscription: AnyCancellable?
    private weak var boundCore: CoreSession?
    private var applyTask: Task<Void, Never>?
    private var checkTask: Task<Void, Never>?
    private var pairDeadlineTask: Task<Void, Never>?

    /// Static accessor for the current user ID (used by ChatViewModel for key loading).
    private static weak var _shared: AuthManager?

    static func currentUserId() async -> String? {
        await MainActor.run { _shared?.currentUser?.id }
    }

    /// Bind a cold-launch notification action before asynchronous session restore.
    static var notificationSession: AuthManager { _shared ?? AuthManager() }

    static var notificationAccountId: String? {
        _shared?.currentUser?.id ?? cachedUser()?.id
    }

    static func isRecoveryEligibleDevice() async -> Bool {
        await MainActor.run {
            _shared?.state == .authenticated && _shared?.sessionValidationState == .onlineAuthenticated
        }
    }

    enum AuthState: Equatable {
        case initializing
        case unauthenticated
        case needsDeviceVerification(type: String)
        case authenticated
    }

    enum SessionValidationState: Equatable {
        case initializing
        /// A cached profile of the core's restored session; not admitted yet.
        case offlineAuthenticated
        /// The core is admitting the session again.
        case validating
        case onlineAuthenticated
        case requiresReauthentication(reason: String)
        case unauthenticated
    }

    /// - Parameters:
    ///   - core: the core to follow; `nil` uses `CoreSession.shared`.
    ///   - reads: test seam for the core's session reads.
    init(api: APIClient = .shared, core: CoreSession? = nil, reads: AuthCoreReads? = nil,
         profileCacheWriter: ((UserProfile) -> Void)? = nil,
         sessionScopeActivator: ((UserProfile) throws -> Void)? = nil) {
        self.api = api
        self.injectedCore = core
        self.injectedReads = reads
        self.profileCacheWriter = profileCacheWriter
        self.sessionScopeActivator = sessionScopeActivator
        Self._shared = self
    }

    /// The core this manager follows (`nil` in hosts without a core).
    var core: CoreSession? { injectedCore ?? CoreSession.shared }

    private var reads: AuthCoreReads? {
        if let injectedReads { return injectedReads }
        return core.map(AuthCoreReads.live)
    }

    // MARK: - Local profile edits

    /// The resume card follows the viewed chat; it does not change chat recency.
    func updateLastOpened(_ chatId: String, accountId: String) {
        guard state == .authenticated, var user = currentUser, user.id == accountId,
              !chatId.isEmpty, !chatId.hasPrefix("/"),
              ChatStore.isServerSyncChatId(chatId), user.lastOpened != chatId else { return }
        lastOpenedSelectionRevision += 1
        user.lastOpened = chatId
        currentUser = user
        cacheAuthenticatedUser(user)
    }

    func publishPasswordWrapper(for accountId: String, encryptedKey: String,
                                keyIv: String, salt: String, version: Int) {
        guard var user = currentUser, user.id == accountId, version == 2 else { return }
        user.encryptedKey = encryptedKey
        user.keyIv = keyIv
        user.salt = salt
        user.credentialVersion = version
        currentUser = user
        cacheAuthenticatedUser(user)
    }

    func profilePreservingNewerSelection(_ received: UserProfile, since revision: Int) -> UserProfile {
        var result = received
        if lastOpenedSelectionRevision != revision, currentUser?.id == received.id {
            result.lastOpened = currentUser?.lastOpened
        }
        return result
    }

    /// Only the acknowledged /session preference is copied. Other profile fields
    /// may have changed locally while registration's authoritative read awaited.
    func applyAuthoritativePushNotificationPreference(_ received: UserProfile,
                                                      accountID: String, profile: ServerProfile, scope: UUID) {
        guard state == .authenticated, received.id == accountID,
              currentUser?.id == accountID, ServerProfile.current() == profile,
              OfflineStore.shared.scopeGeneration == scope,
              let enabled = received.pushNotificationEnabled, let currentUser,
              currentUser.pushNotificationEnabled != enabled,
              let data = try? JSONEncoder().encode(currentUser),
              var fields = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return }
        fields["pushNotificationEnabled"] = enabled
        guard let updated = try? JSONSerialization.data(withJSONObject: fields),
              let user = try? JSONDecoder().decode(UserProfile.self, from: updated) else { return }
        self.currentUser = user
        cacheAuthenticatedUser(user)
    }

    // MARK: - Session check (app launch) and re-admission

    /// Start the core once (`ViewModelCore.start`) and follow its session
    /// events; later calls let the core admit the session again.
    func checkSession() async {
        if let checkTask { await checkTask.value; return }
        let task = Task { @MainActor in await self.performCheckSession() }
        checkTask = task
        await task.value
        checkTask = nil
    }

    private func performCheckSession() async {
        Self._shared = self
        if applyUITestFixtureIfRequested() { return }
        guard let core else {
            NativeDiagnostics.error("phase=auth.check core_unavailable", category: "auth")
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return
        }
        bind(core)
        switch core.state {
        case .notStarted:
            do { try await core.start() } catch { logCoreFailure("start", error) }
        case .starting:
            await core.settled()
        case .signedOut:
            break
        case .restored, .admitted, .expired, .accessDenied, .verificationRequired, .failed:
            do { try await core.readmit() } catch { logCoreFailure("readmit", error) }
        }
        await drainCoreEvents()
        if state == .initializing {
            // A restored session without a cached profile that the core
            // could not admit (offline): nothing to unlock locally.
            NativeDiagnostics.warning("phase=auth.check outcome=not_admitted core_state=\(core.state.diagnosticName)", category: "auth")
            sessionValidationState = .unauthenticated
            state = .unauthenticated
        }
    }

    /// Ask the core to admit a restored session (foreground, reconnect,
    /// protected work). `forceReadmit` also re-admits an admitted session,
    /// which rotates the `ws_token`.
    func ensureAdmitted(forceReadmit: Bool = false) async {
        #if DEBUG
        if Self.isSyntheticOfflineFixture { return }
        #endif
        guard let core else { return }
        switch core.state {
        case .notStarted, .starting:
            await checkSession()
            return
        case .admitted:
            guard forceReadmit else { return }
        case .restored, .failed:
            break
        case .signedOut, .expired, .accessDenied, .verificationRequired:
            return
        }
        sessionValidationState = .validating
        do { try await core.readmit() } catch { logCoreFailure("readmit", error) }
        await drainCoreEvents()
        if sessionValidationState == .validating { sessionValidationState = .offlineAuthenticated }
    }

    /// The core's socket grant (session id, `ws_token`) for the admitted
    /// session. Re-admits once in the core, which rotates the token, when
    /// `force` or when `needsRefresh` says the token lapses too soon.
    /// Throws the core's error (`Authentication` while signed out).
    func socketGrant(force: Bool = false,
                     needsRefresh: (String?) -> Bool = { $0 == nil }) async throws -> LegacySocketGrantRecord {
        if force || sessionValidationState != .onlineAuthenticated { await ensureAdmitted(forceReadmit: force) }
        let grant = try await CoreLegacyAccess.socketGrant()
        guard needsRefresh(grant.wsToken) else { return grant }
        await ensureAdmitted(forceReadmit: true)
        return try await CoreLegacyAccess.socketGrant()
    }

    /// Identity of the admitted session for fencing late async work.
    var sessionRecoveryContext: AuthSessionRecoveryContext? {
        guard state == .authenticated, let accountID = currentUser?.id else { return nil }
        return AuthSessionRecoveryContext(accountID: accountID, profile: ServerProfile.current(),
            sessionID: Self.nativeSessionId, generation: admissionGeneration)
    }

    func bind(_ core: CoreSession) {
        guard boundCore !== core else { return }
        boundCore = core
        stateSubscription = core.$state.sink { [weak self] coreState in
            self?.enqueue(coreState)
        }
    }

    private func enqueue(_ coreState: CoreSessionState) {
        let previous = applyTask
        applyTask = Task { @MainActor [weak self] in
            await previous?.value
            await self?.apply(coreState)
        }
    }

    /// Returns once every session event the core delivered so far is applied.
    /// The relay posts events to the main queue before the core call that
    /// produced them returns, so one main-queue hop orders after them.
    func drainCoreEvents() async {
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        while let task = applyTask {
            await task.value
            if applyTask == task { return }
        }
    }

    /// Mirror one core session state into the app's auth state.
    func apply(_ coreState: CoreSessionState) async {
        switch coreState {
        case .notStarted, .starting, .accessDenied(.chatUnavailable):
            return
        case .restored:
            await applyRestored()
        case .admitted(_, let expiresAt):
            await applyAdmitted(expiresAt: expiresAt)
        case .signedOut, .expired, .accessDenied(.expired), .accessDenied(.scopeRevoked):
            await clearLocalAccount(reason: coreState.diagnosticName, onlyWhenSignedIn: true)
        case .verificationRequired(.device(.twoFactor, _, _)):
            admissionGeneration = UUID()
            sessionValidationState = .requiresReauthentication(reason: "device_verification_required")
            state = .needsDeviceVerification(type: "2fa")
        case .verificationRequired(.device(.passkey, _, _)):
            admissionGeneration = UUID()
            sessionValidationState = .requiresReauthentication(reason: "device_verification_required")
            state = .needsDeviceVerification(type: "passkey")
        case .verificationRequired(.reAuth):
            // A re-auth requirement means signing in again: sign out in the core.
            await signOut(reason: "verification_\(coreState.diagnosticName)")
        case .failed(let error):
            NativeDiagnostics.warning("phase=auth.start_failed error=\(CoreSession.errorClass(error))", category: "auth")
            if currentUser == nil {
                sessionValidationState = .unauthenticated
                state = .unauthenticated
            }
        }
    }

    /// A stored session restored from the cache: unlock the profile the core
    /// cached at this account's last admission, offline, until the core
    /// admits it again (`fresh == false` grants no network authority).
    private func applyRestored() async {
        guard let reads else { return }
        let generation = admissionGeneration
        do {
            let record = try await reads.profile()
            let cached = try await Self.decodeProfile(record.json)
            guard generation == admissionGeneration, state != .authenticated else { return }
            try activateScope(for: cached)
            currentUser = cached
            sessionValidationState = .offlineAuthenticated
            state = .authenticated
        } catch {
            logCoreFailure("restore_profile", error)
        }
    }

    private func applyAdmitted(expiresAt: UInt64?) async {
        guard let reads else { return }
        let generation = UUID()
        admissionGeneration = generation
        let selectionRevision = lastOpenedSelectionRevision
        do {
            let record = try await reads.profile()
            let received = try await Self.decodeProfile(record.json)
            let grant = try await reads.socketGrant()
            guard generation == admissionGeneration else { return }
            let user = profilePreservingNewerSelection(received, since: selectionRevision)
            try activateScope(for: user)
            currentUser = user
            cacheAuthenticatedUser(user)
            if record.fresh {
                networkAuthority = AuthSessionRecoveryContext(accountID: user.id, profile: ServerProfile.current(),
                    sessionID: grant.sessionId, generation: generation)
                sessionValidationState = .onlineAuthenticated
            } else {
                // A cached copy is shown, never treated as server-confirmed.
                sessionValidationState = .offlineAuthenticated
            }
            state = .authenticated
            schedulePairDeadline(expiresAt, generation: generation)
        } catch {
            guard generation == admissionGeneration else { return }
            logCoreFailure("admitted_profile", error)
            sessionValidationState = currentUser == nil ? .unauthenticated : .offlineAuthenticated
            if currentUser == nil { state = .unauthenticated }
        }
    }

    /// The admitted account's server profile as the core holds it (replaces
    /// Swift reads of `/v1/auth/session`, a core-owned route). Throws the
    /// core's error (`Authentication` while signed out), and `Offline` while
    /// the core holds only the cached copy of a restored session.
    static func admittedProfile() async throws -> UserProfile {
        guard let core = CoreSession.shared else { throw CoreError.Authentication }
        let record = try await core.userProfile()
        guard record.fresh else { throw CoreError.Offline }
        return try await decodeProfile(record.json)
    }

    /// Decodes the core's snake_case user payload off the main actor.
    nonisolated static func decodeProfile(_ data: Data) async throws -> UserProfile {
        try await Task.detached(priority: .userInitiated) {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(UserProfile.self, from: data)
        }.value
    }

    /// A paired session ends at its deadline: let the core decide then.
    private func schedulePairDeadline(_ expiresAt: UInt64?, generation: UUID) {
        pairDeadlineTask?.cancel()
        guard let expiresAt else { return }
        let remainingMs = Int64(expiresAt) - Int64(Date().timeIntervalSince1970 * 1000)
        pairDeadlineTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(max(0, remainingMs)))
            guard !Task.isCancelled, let self, self.admissionGeneration == generation else { return }
            await self.ensureAdmitted(forceReadmit: true)
        }
    }

    // MARK: - Email lookup

    func lookup(email: String, stayLoggedIn: Bool = false) async throws -> LookupResponse {
        let hashedEmail = await crypto.hashEmail(email)
        return try await api.request(
            .post,
            path: "/v1/auth/lookup",
            body: LookupRequest(hashedEmail: hashedEmail, stayLoggedIn: stayLoggedIn)
        )
    }

    // MARK: - Password login (core)

    /// Password login in the core. `codeType == "backup"` sends `tfaCode` as
    /// a backup code (`loginWithBackupCode`).
    ///
    /// Throws `AuthError.tfaRequired` (ask for a code), `.invalidCredentials`,
    /// `.invalidTwoFactorCode`, `NativeSignupError` for a stale or mismatched
    /// signup, else the core's `CoreError`. Device verification is no error:
    /// `state` becomes `.needsDeviceVerification`.
    func loginWithPassword(
        email: String,
        password: String,
        userEmailSalt: String?,
        tfaCode: String? = nil,
        codeType: String? = nil,
        stayLoggedIn: Bool = false,
        signupProof: NativeSignupLoginProof? = nil
    ) async throws {
        if codeType == "backup", let tfaCode {
            try await loginWithBackupCode(email: email, password: password, backupCode: tfaCode,
                stayLoggedIn: stayLoggedIn)
            return
        }
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        if let signupProof { try validateSignupContext(signupProof) }
        bind(core)
        let record: LoginRecord
        do {
            record = try await core.loginPassword(email: email, password: password, tfaCode: tfaCode,
                stayLoggedIn: stayLoggedIn)
        } catch CoreError.TwoFactorRequired {
            throw AuthError.tfaRequired
        } catch CoreError.Authentication {
            throw tfaCode == nil ? AuthError.invalidCredentials : AuthError.invalidTwoFactorCode
        } catch CoreError.VerificationRequired {
            await drainCoreEvents()
            return
        }
        CoreCeremonySession.reset()
        await drainCoreEvents()
        guard let user = currentUser, state == .authenticated else { return }
        if let signupProof {
            let coreMasterKey = try await CoreLegacyAccess.masterKey(for: user.id)
            guard ServerProfile.current() == signupProof.serverProfile, signupProof.validates(user: user),
                  let masterKey = coreMasterKey, signupProof.validatesMasterKey(masterKey) else {
                await signOut(reason: "signup_proof_mismatch")
                throw NativeSignupError.sessionProofMismatch
            }
        }
        confirmAuthenticated(for: user.id)
        logPasswordMigration(record.passwordMigration)
    }

    /// Haptic confirmation of a finished sign-in of `accountID`.
    func confirmAuthenticated(for accountID: String) {
        guard state == .authenticated, currentUser?.id == accountID else { return }
        NativeHaptics.shared.confirmed(.authenticated, id: admissionGeneration.uuidString,
            scope: OfflineStore.shared.scopeGeneration.uuidString)
    }

    // MARK: - Device verification (core)

    /// Answer the core's pending two-factor device verification. A refused
    /// code throws `AuthError.invalidTwoFactorCode` and stays pending.
    func verifyDeviceWith2FA(code: String) async throws {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        do {
            try await core.verifyDevice2fa(code: code)
        } catch CoreError.Authentication {
            throw AuthError.invalidTwoFactorCode
        }
        await drainCoreEvents()
    }

    // MARK: - Pair login (core)

    /// Begin a pair login of this device: the code and link to show.
    func beginPairLogin() async throws -> PairChallengeRecord {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        bind(core)
        return try await core.perform { core, _ in try await core.beginPairLogin() }
    }

    /// One poll; `"approved"` means ask for the PIN. `CoreError.Expired` when
    /// the code failed, was cancelled or lapsed.
    func pollPairLogin() async throws -> String {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        return try await core.perform { core, _ in try await core.pollPairLogin() }
    }

    /// Send the PIN, then finish until the core stored and started the paired
    /// session. A wrong PIN is `CoreError.Authentication` or `.Crypto`.
    func completePairLogin(pin: String) async throws {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        try await core.perform { core, _ in try await core.submitPairPin(pin: pin) }
        while !(try await core.finishPairLogin()) {
            try await Task.sleep(for: .seconds(1))
        }
        await drainCoreEvents()
        if let user = currentUser { confirmAuthenticated(for: user.id) }
    }

    /// Abandon the running pair login (nothing running: no-op).
    func cancelPairLogin() async {
        guard let core else { return }
        do {
            try await core.perform { core, _ in try await core.cancelPairLogin() }
        } catch {
            logCoreFailure("pair_cancel", error)
        }
    }

    // MARK: - Logout

    /// User sign-out: unregister push while the session still works, then
    /// sign out in the core and clear the local account.
    func logout() async {
        NotificationReplyStore().revoke()
        await PushNotificationManager.shared.unregisterCurrentDevice()
        await signOut(reason: "user")
    }

    /// Sign out without the push round trip (forced by the server, a lapsed
    /// pairing or a refused verification).
    func signOut(reason: String) async {
        NotificationReplyStore().revoke()
        PushNotificationManager.shared.invalidateRegistration()
        admissionGeneration = UUID()
        if let core {
            do { try await core.logout() } catch { logCoreFailure("logout_\(reason)", error) }
        }
        await clearLocalAccount(reason: reason, onlyWhenSignedIn: false)
    }

    /// App-local cleanup of a signed-out account. The core already wiped its
    /// credentials and cache; this clears the app's own stores.
    private func clearLocalAccount(reason: String, onlyWhenSignedIn: Bool) async {
        admissionGeneration = UUID()
        pairDeadlineTask?.cancel()
        if onlyWhenSignedIn, currentUser == nil {
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return
        }
        NativeDiagnostics.info("phase=auth.signed_out reason=\(reason)", category: "auth")
        AppSessionCoordinator.shared.resetTransientRuntime()
        await clearComposerDraftsForLogout()
        OfflineStore.shared.deactivate()
        NotificationPreviewCrypto.clearPrivateKey()
        ChatKeyManager.shared.clearAll()
        EmbedKeyManager.shared.clearAll()
        SpotlightIndexer.shared.removeAllItems()
        CoreCeremonySession.reset()
        Self.clearCachedUser()
        PairSessionDeadlineStore.clear()
        PairPendingAckStore.clear()
        PairVerifiedAccountStore.clear()
        currentUser = nil
        sessionValidationState = .unauthenticated
        state = .unauthenticated
    }

    // MARK: - App-local side effects

    func validateSignupContext(_ proof: NativeSignupLoginProof) throws {
        guard !Task.isCancelled, ServerProfile.current() == proof.serverProfile,
              Self.nativeSessionId == proof.sessionId, currentUser == nil else {
            throw NativeSignupError.staleContext
        }
    }

    func activateScope(for user: UserProfile) throws {
        if let sessionScopeActivator { try sessionScopeActivator(user); return }
        let apiBaseURL = ServerConfiguration.current.apiBaseURL
        let store = OfflineStore.shared
        let scope = OfflineStore.scopeId(userId: user.id, apiBaseURL: apiBaseURL)
        if store.activeScopeId != scope {
            PushNotificationManager.shared.invalidateRegistration()
            AppSessionCoordinator.shared.resetTransientRuntime()
            ChatKeyManager.shared.clearAll()
            EmbedKeyManager.shared.clearAll()
            try store.activate(userId: user.id, apiBaseURL: apiBaseURL)
        }
    }

    private func clearComposerDraftsForLogout() async {
        do {
            try await DraftService.shared.clearAll()
        } catch {
            NativeDiagnostics.error("phase=logoutDraftClear.failed errorType=\(type(of: error))", category: "composer_drafts")
        }
    }

    func cacheAuthenticatedUser(_ user: UserProfile) {
        if let profileCacheWriter { profileCacheWriter(user); return }
        guard let data = try? JSONEncoder().encode(user) else { return }
        UserDefaults.standard.set(data, forKey: Self.cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.set(data, forKey: Self.cachedUserDefaultsKey)
    }

    private func logCoreFailure(_ operation: String, _ error: Error) {
        NativeDiagnostics.warning(
            "phase=auth.\(operation) error=\(CoreSession.errorClass(error))", category: "auth")
    }

    // MARK: - Identity helpers

    /// Session id of the core's session; while signed out, the id of the
    /// running sign-in ceremony (`CoreCeremonySession`).
    static var nativeSessionId: String {
        CoreLegacyAccess.sessionID ?? CoreCeremonySession.sessionID
    }

    static func makeNativeDeviceInfo() -> DeviceInfo {
        #if os(iOS)
        let os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #elseif os(macOS)
        let os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #else
        let os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #endif
        return DeviceInfo(
            os: os,
            deviceModel: getNativeDeviceModel(),
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        )
    }

    private static func getNativeDeviceModel() -> String {
        #if os(iOS)
        return UIDevice.current.model
        #else
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        var model = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &model, &size, nil, 0)
        return String(cString: model)
        #endif
    }

    private static let cachedUserDefaultsKey = "openmates.apple.auth.cached_user"

    static func cachedUser() -> UserProfile? {
        guard let data = OpenMatesSharedEnvironment.defaults.data(forKey: cachedUserDefaultsKey)
            ?? UserDefaults.standard.data(forKey: cachedUserDefaultsKey) else { return nil }
        return try? JSONDecoder().decode(UserProfile.self, from: data)
    }

    private static func clearCachedUser() {
        UserDefaults.standard.removeObject(forKey: cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: cachedUserDefaultsKey)
    }

    // MARK: - UI-test fixtures

    #if DEBUG
    static var isSyntheticOfflineFixture: Bool {
        let arguments = ProcessInfo.processInfo.arguments
        return arguments.contains("--ui-test-authenticated-chat-navigation") || arguments.contains("--ui-test-window-drafts")
    }
    #endif

    /// Synthetic offline identities of UI tests; they run without a server
    /// session. Returns `true` when a fixture decided the state.
    private func applyUITestFixtureIfRequested() -> Bool {
        #if DEBUG
        let isWindowDraftFixture = ProcessInfo.processInfo.arguments.contains("--ui-test-window-drafts")
        if isWindowDraftFixture, state == .authenticated, currentUser?.id == "ui-test-window-drafts-user" { return true }
        if Self.isSyntheticOfflineFixture {
            let user = UserProfile(
                id: isWindowDraftFixture ? "ui-test-window-drafts-user" : "ui-test-chat-navigation-user",
                username: isWindowDraftFixture ? "ui-test-window-drafts" : "ui-test-chat-navigation",
                email: nil, credits: 0, language: "en", darkmode: nil, timezone: "UTC",
                lastOpened: "ui-test-regular-chat", profileImageUrl: nil, isAdmin: false,
                encryptedKey: nil, keyIv: nil, salt: nil, userEmailSalt: nil, encryptedSettings: nil,
                autoDeleteChatsAfterDays: nil, pushNotificationEnabled: nil, emailNotificationsEnabled: nil,
                emailNotificationPreferences: nil, backupReminderIntervalDays: nil,
                defaultAiModelSimple: nil, defaultAiModelComplex: nil,
                followUpSuggestionsEnabled: nil, recommendationsEnabled: nil)
            currentUser = user
            if isWindowDraftFixture {
                CoreLegacyAccess.installFixtureMasterKey(SymmetricKey(data: Data(repeating: 0x42, count: 32)), for: user.id)
                do {
                    try activateScope(for: user)
                    OfflineStore.shared.clearAll()
                } catch {
                    NativeDiagnostics.error("Window draft UI fixture setup failed: \(type(of: error))", category: "apple_composer")
                    state = .unauthenticated
                    return true
                }
            }
            sessionValidationState = .offlineAuthenticated
            state = .authenticated
            return true
        }
        #endif
        if ProcessInfo.processInfo.arguments.contains("--ui-test-disable-auth-cache") {
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return true
        }
        return false
    }
}
