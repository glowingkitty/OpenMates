// Shared pair-login runtime for Apple auth surfaces.
// Owns the backend request sequence and cryptographic bundle decode for the
// QR/PIN Magic Pair Login flow while keeping each platform's SwiftUI view small.
// Used by the regular iOS/macOS login surface and by the standalone Watch app.
// Does not store sessions; callers decide how to persist the authenticated user.

import CryptoKit
import Foundation
import Security

#if os(iOS) || os(watchOS)
import WatchConnectivity
#endif

#if os(iOS)
import UserNotifications
#endif

#if os(iOS)
import UIKit
#endif

enum PairLoginStatus: Equatable {
    case generating
    case waiting
    case ready
    case expired
    case failed
}

enum PairLoginCompleteFailureKind: Equatable {
    case tooManyAttempts
    case invalidPIN(attemptsRemaining: String)
    case expired
    case generic
}

struct PairLoginInitiation: Equatable {
    let token: String
    let pairURLString: String
}

struct PairLoginResult {
    let loginResponse: LoginResponse
    let masterKey: SymmetricKey
    let serverProfile: ServerProfile
}

struct WatchPairLoginRequest: Equatable {
    let token: String
    let pairURLString: String
    let deviceName: String
    let serverProfile: ServerProfile
    let createdAt: Int
}

struct WatchPairLoginApproval: Equatable {
    let token: String
    let pin: String
}

struct WatchPairAttemptState: Equatable {
    private(set) var generation = 0
    private(set) var serverProfile = ServerProfile.production
    private(set) var token: String?
    private(set) var pairURLString: String?

    mutating func begin(serverProfile: ServerProfile) -> Int {
        generation += 1
        self.serverProfile = serverProfile
        token = nil
        pairURLString = nil
        return generation
    }

    mutating func ensureCurrentAttempt(serverProfile: ServerProfile) -> Int {
        guard generation > 0, self.serverProfile == serverProfile else {
            return begin(serverProfile: serverProfile)
        }
        return generation
    }

    mutating func accept(
        _ initiation: PairLoginInitiation,
        generation: Int,
        serverProfile: ServerProfile
    ) -> Bool {
        guard accepts(generation: generation, serverProfile: serverProfile) else { return false }
        token = initiation.token.uppercased()
        pairURLString = initiation.pairURLString
        return true
    }

    func accepts(generation: Int, serverProfile: ServerProfile) -> Bool {
        self.generation == generation && self.serverProfile == serverProfile
    }
}

enum PairLoginRuntime {
    private static let diagnosticsCategory = "pair_login"

    static func normalizedPIN(_ rawValue: String) -> String {
        String(
            rawValue
                .uppercased()
                .filter { $0.isLetter || $0.isNumber }
                .prefix(6)
        )
    }

    static func buildPairURL(webAppURL: URL, token: String) -> String {
        let upperToken = token.uppercased()
        if let scheme = webAppURL.scheme, let host = webAppURL.host {
            return "\(scheme)://\(host)/#pair=\(upperToken)"
        }
        return "\(webAppURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/#pair=\(upperToken)"
    }

    static func failureKind(for message: String?) -> PairLoginCompleteFailureKind {
        if message == "too_many_attempts" {
            return .tooManyAttempts
        }
        if let message, message.hasPrefix("invalid_pin:") {
            return .invalidPIN(attemptsRemaining: message.split(separator: ":").last.map(String.init) ?? "0")
        }
        if message == "expired" {
            return .expired
        }
        return .generic
    }

    static var officialAppDeviceHint: String {
        #if os(watchOS)
        return "OpenMates Apple Watch app"
        #elseif os(iOS)
        if UIDevice.current.userInterfaceIdiom == .pad {
            return "OpenMates iPadOS app"
        }
        return "OpenMates iOS app"
        #elseif os(macOS)
        return "OpenMates macOS app"
        #else
        return "OpenMates Apple app"
        #endif
    }

    static func initiate(
        deviceHint: String = officialAppDeviceHint,
        serverProfile: ServerProfile = ServerProfile.current()
    ) async throws -> PairLoginInitiation {
        logInfo("phase=initiate.start \(serverDiagnostics(serverProfile)) deviceHint=\(deviceHint)")
        do {
            let response: PairInitiateResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/auth/pair/initiate",
                serverProfile: serverProfile,
                body: PairInitiateRequest(deviceHint: deviceHint)
            )
            let token = response.token.uppercased()
            let pairURLString = buildPairURL(webAppURL: serverProfile.webBaseURL, token: token)
            let pairHost = serverProfile.webBaseURL.host() ?? "unknown"
            logInfo("phase=initiate.success \(serverDiagnostics(serverProfile)) expiresIn=\(response.expiresIn) pairHost=\(pairHost)")
            return PairLoginInitiation(
                token: token,
                pairURLString: pairURLString
            )
        } catch {
            logError("phase=initiate.failed \(serverDiagnostics(serverProfile)) errorType=\(type(of: error))")
            throw error
        }
    }

    static func poll(token: String, serverProfile: ServerProfile = ServerProfile.current()) async throws -> PairPollResponse {
        do {
            let response: PairPollResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/auth/pair/poll/\(token)",
                serverProfile: serverProfile
            )
            if response.status != "waiting" {
                logInfo("phase=poll.status \(serverDiagnostics(serverProfile)) status=\(response.status)")
            }
            return response
        } catch {
            logError("phase=poll.failed \(serverDiagnostics(serverProfile)) errorType=\(type(of: error))")
            throw error
        }
    }

    static func complete(
        token: String,
        pin: String,
        stayLoggedIn: Bool,
        serverProfile: ServerProfile = ServerProfile.current()
    ) async throws -> PairLoginResult {
        logInfo("phase=complete.start \(serverDiagnostics(serverProfile)) stayLoggedIn=\(stayLoggedIn)")
        let completeResponse: PairCompleteResponse
        do {
            completeResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/auth/pair/complete/\(token)",
                serverProfile: serverProfile,
                body: PairCompleteRequest(pin: pin)
            )
        } catch {
            logError("phase=complete.failed \(serverDiagnostics(serverProfile)) step=completeRequest errorType=\(type(of: error))")
            throw error
        }

        guard completeResponse.success else {
            logWarning("phase=complete.rejected \(serverDiagnostics(serverProfile)) kind=\(failureKind(for: completeResponse.message))")
            throw PairLoginRuntimeError.completeFailed(failureKind(for: completeResponse.message))
        }

        let (bundle, masterKey) = try await decryptLoginBundle(from: completeResponse, token: token, pin: pin)
        let loginResponse: LoginResponse
        do {
            loginResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/auth/login",
                serverProfile: serverProfile,
                body: LoginRequest(
                    hashedEmail: bundle.hashedEmail,
                    lookupHash: bundle.lookupHash,
                    loginMethod: "pair",
                    tfaCode: nil,
                    codeType: nil,
                    emailEncryptionKey: nil,
                    stayLoggedIn: stayLoggedIn,
                    sessionId: WatchCompatibleSession.nativeSessionId,
                    deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()
                )
            )
        } catch {
            logError("phase=complete.failed \(serverDiagnostics(serverProfile)) step=loginRequest errorType=\(type(of: error))")
            throw error
        }
        logInfo("phase=complete.success \(serverDiagnostics(serverProfile)) loginSuccess=\(loginResponse.success) needsDeviceVerification=\(loginResponse.needsDeviceVerification ?? false)")
        return PairLoginResult(loginResponse: loginResponse, masterKey: masterKey, serverProfile: serverProfile)
    }

    static func authorize(
        token: String,
        currentUser: UserProfile,
        authorizerDeviceName: String,
        serverProfile: ServerProfile = ServerProfile.current()
    ) async throws -> String {
        let pin = generatePairPIN()
        let credentials: PairCredentialsResponse = try await APIClient.shared.request(
            .get,
            path: "/v1/auth/pair/credentials",
            serverProfile: serverProfile
        )
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUser.id) else {
            throw AuthError.missingAuthData
        }
        let masterKeyExported = masterKey.withUnsafeBytes { Data($0).base64EncodedString() }
        let bundleJSON = try JSONSerialization.data(withJSONObject: [
            "lookup_hash": credentials.lookupHash,
            "hashed_email": credentials.hashedEmail,
            "user_email_salt": credentials.userEmailSalt,
            "master_key_exported": masterKeyExported,
        ])
        let pairKey = await CryptoManager.shared.derivePairLoginKey(pin: pin, token: token)
        let encrypted = try await CryptoManager.shared.encrypt(bundleJSON, using: pairKey)
        let response: PairAuthorizeResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/pair/authorize/\(token.uppercased())",
            serverProfile: serverProfile,
            body: PairAuthorizeRequest(
                encryptedBundle: encrypted.ciphertext.base64EncodedString(),
                iv: encrypted.nonce.base64EncodedString(),
                pin: pin,
                authorizerDeviceName: authorizerDeviceName
            )
        )
        guard response.success else { throw AuthError.invalidCredentials }
        return pin
    }

    static func decryptLoginBundle(
        from response: PairCompleteResponse,
        token: String,
        pin: String
    ) async throws -> (PairLoginBundle, SymmetricKey) {
        guard let encryptedBundle = response.encryptedBundle,
              let iv = response.iv,
              let encryptedData = Data(base64Encoded: encryptedBundle),
              let ivData = Data(base64Encoded: iv) else {
            throw AuthError.missingAuthData
        }

        let pairKey = await CryptoManager.shared.derivePairLoginKey(pin: pin, token: token)
        let plaintext = try await CryptoManager.shared.decryptAESGCM(
            ciphertext: encryptedData,
            iv: ivData,
            key: pairKey
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let bundle = try decoder.decode(PairLoginBundle.self, from: plaintext)
        guard let masterKeyData = Data(base64Encoded: bundle.masterKeyExported) else {
            throw AuthError.missingAuthData
        }
        return (bundle, SymmetricKey(data: masterKeyData))
    }

    static func generatePairPIN() -> String {
        let alphabet = Array("ABCDEFGHJKLMNPQRTUVWXY3468")
        var bytes = [UInt8](repeating: 0, count: 6)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return String(bytes.map { alphabet[Int($0) % alphabet.count] })
    }

    private static func serverDiagnostics(_ profile: ServerProfile) -> String {
        "serverKind=\(profile.diagnosticsKind)"
    }

    private static func logInfo(_ message: String) {
        NativeDiagnostics.info(message, category: diagnosticsCategory)
    }

    private static func logWarning(_ message: String) {
        NativeDiagnostics.warning(message, category: diagnosticsCategory)
    }

    private static func logError(_ message: String) {
        NativeDiagnostics.error(message, category: diagnosticsCategory)
    }
}

enum WatchPairLoginConnectivityPayload {
    private static let requestValiditySeconds = 300
    static let kindKey = "kind"
    static let tokenKey = "token"
    static let pairURLKey = "pair_url"
    static let deviceNameKey = "device_name"
    static let serverProfileIdKey = "server_profile_id"
    static let serverWebBaseURLKey = "server_web_base_url"
    static let serverAPIBaseURLKey = "server_api_base_url"
    static let serverUploadBaseURLKey = "server_upload_base_url"
    static let createdAtKey = "created_at"
    static let pinKey = "pin"
    static let watchLoginRequestKind = "openmates.watch.pair_login.request"
    static let watchLoginApprovalKind = "openmates.watch.pair_login.approval"
    static let forbiddenSecretKeys = [
        "master_key",
        "master_key_exported",
        "session_token",
        "ws_token",
        "cookie",
        "auth_cookie",
        "encrypted_bundle",
    ]

    static func requestMessage(_ request: WatchPairLoginRequest) -> [String: Any] {
        var message = serverProfileFields(request.serverProfile)
        message.merge([
            kindKey: watchLoginRequestKind,
            tokenKey: request.token.uppercased(),
            pairURLKey: request.pairURLString,
            deviceNameKey: request.deviceName,
            createdAtKey: request.createdAt,
        ]) { _, new in new }
        return message
    }

    static func parseRequest(_ message: [String: Any]) -> WatchPairLoginRequest? {
        guard message[kindKey] as? String == watchLoginRequestKind,
              let token = message[tokenKey] as? String,
              let pairURLString = message[pairURLKey] as? String,
              let serverProfile = serverProfile(from: message) else { return nil }
        return WatchPairLoginRequest(
            token: token.uppercased(),
            pairURLString: pairURLString,
            deviceName: message[deviceNameKey] as? String ?? "Apple Watch",
            serverProfile: serverProfile,
            createdAt: message[createdAtKey] as? Int ?? Int(Date().timeIntervalSince1970)
        )
    }

    static func requestMatchesCurrentServer(_ request: WatchPairLoginRequest, currentProfile: ServerProfile) -> Bool {
        request.serverProfile.webBaseURL == currentProfile.webBaseURL
            && request.serverProfile.apiBaseURL == currentProfile.apiBaseURL
    }

    static func shouldOfferApproval(
        for request: WatchPairLoginRequest,
        currentProfile: ServerProfile,
        isAuthenticated: Bool,
        now: Int = Int(Date().timeIntervalSince1970)
    ) -> Bool {
        let requestAge = now - request.createdAt
        return isAuthenticated
            && requestAge >= 0
            && requestAge <= requestValiditySeconds
            && requestMatchesCurrentServer(request, currentProfile: currentProfile)
    }

    private static func serverProfileFields(_ profile: ServerProfile) -> [String: Any] {
        [
            serverProfileIdKey: profile.id,
            serverWebBaseURLKey: profile.webBaseURL.absoluteString,
            serverAPIBaseURLKey: profile.apiBaseURL.absoluteString,
            serverUploadBaseURLKey: profile.uploadBaseURL.absoluteString,
        ]
    }

    private static func serverProfile(from message: [String: Any]) -> ServerProfile? {
        guard let serverProfileId = message[serverProfileIdKey] as? String,
              let serverWebBaseURL = message[serverWebBaseURLKey] as? String,
              let serverAPIBaseURL = message[serverAPIBaseURLKey] as? String else { return nil }
        return ServerProfile.fromPayload(
            id: serverProfileId,
            webBaseURLString: serverWebBaseURL,
            apiBaseURLString: serverAPIBaseURL,
            uploadBaseURLString: message[serverUploadBaseURLKey] as? String
        )
    }

    static func approvalMessage(_ approval: WatchPairLoginApproval) -> [String: Any] {
        [
            kindKey: watchLoginApprovalKind,
            tokenKey: approval.token.uppercased(),
            pinKey: approval.pin,
        ]
    }

    static func parseApproval(_ message: [String: Any]) -> WatchPairLoginApproval? {
        guard message[kindKey] as? String == watchLoginApprovalKind,
              let token = message[tokenKey] as? String,
              let pin = message[pinKey] as? String else { return nil }
        return WatchPairLoginApproval(token: token.uppercased(), pin: pin)
    }

    static func containsForbiddenSecretKeys(_ message: [String: Any]) -> Bool {
        let keys = Set(message.keys.map { $0.lowercased() })
        return forbiddenSecretKeys.contains { keys.contains($0) }
    }
}

#if os(watchOS)
@MainActor
final class WatchPhoneLoginBridge: NSObject, ObservableObject, WCSessionDelegate {
    @Published private(set) var isPhoneReachable = false
    @Published private(set) var didSendRequest = false

    private let diagnosticsCategory = "watch_pair_login"

    private var approvalHandler: (@MainActor (WatchPairLoginApproval) -> Void)?
    func start(onApproval: @escaping @MainActor (WatchPairLoginApproval) -> Void) {
        approvalHandler = onApproval
        guard WCSession.isSupported() else {
            NativeDiagnostics.warning("phase=bridge.start unsupported=watchConnectivity", category: diagnosticsCategory)
            return
        }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        isPhoneReachable = session.isReachable
        NativeDiagnostics.info(
            "phase=bridge.start activationState=\(session.activationState.rawValue) reachable=\(session.isReachable)",
            category: diagnosticsCategory
        )
    }

    @discardableResult
    func sendLoginRequest(_ request: WatchPairLoginRequest) -> Bool {
        guard WCSession.isSupported(), WCSession.default.isReachable else {
            isPhoneReachable = false
            didSendRequest = false
            NativeDiagnostics.warning(
                "phase=bridge.send.skipped reason=notReachable supported=\(WCSession.isSupported()) serverKind=\(request.serverProfile.diagnosticsKind)",
                category: diagnosticsCategory
            )
            return false
        }
        isPhoneReachable = true
        didSendRequest = true
        NativeDiagnostics.info(
            "phase=bridge.send.start serverKind=\(request.serverProfile.diagnosticsKind) reachable=\(WCSession.default.isReachable)",
            category: diagnosticsCategory
        )
        WCSession.default.sendMessage(
            WatchPairLoginConnectivityPayload.requestMessage(request),
            replyHandler: { message in
                guard let approval = WatchPairLoginConnectivityPayload.parseApproval(message) else { return }
                self.dispatchToMain { bridge in
                    NativeDiagnostics.info("phase=bridge.send.replyApproval", category: bridge.diagnosticsCategory)
                    bridge.approvalHandler?(approval)
                }
            },
            errorHandler: { _ in
                self.dispatchToMain { bridge in
                    bridge.didSendRequest = false
                    NativeDiagnostics.warning("phase=bridge.send.failed reason=sendMessageError", category: bridge.diagnosticsCategory)
                }
            }
        )
        return true
    }

    private nonisolated func dispatchToMain(_ work: @MainActor @escaping (WatchPhoneLoginBridge) -> Void) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            work(self)
        }
    }

    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        let isReachable = session.isReachable
        dispatchToMain { bridge in
            let errorLabel = error.map { " errorType=\(type(of: $0))" } ?? ""
            NativeDiagnostics.info(
                "phase=bridge.activationComplete state=\(activationState.rawValue) reachable=\(isReachable)\(errorLabel)",
                category: bridge.diagnosticsCategory
            )
            bridge.isPhoneReachable = isReachable
        }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        let isReachable = session.isReachable
        dispatchToMain { bridge in
            NativeDiagnostics.info(
                "phase=bridge.reachabilityChanged reachable=\(isReachable)",
                category: bridge.diagnosticsCategory
            )
            bridge.isPhoneReachable = isReachable
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let approval = WatchPairLoginConnectivityPayload.parseApproval(message) else { return }
        dispatchToMain { bridge in
            NativeDiagnostics.info("phase=bridge.receivedApproval", category: bridge.diagnosticsCategory)
            bridge.approvalHandler?(approval)
        }
    }

}
#endif

#if os(iOS)
@MainActor
final class PhoneWatchLoginBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneWatchLoginBridge()

    @Published private(set) var pendingRequest: WatchPairLoginRequest?
    @Published private(set) var lastError: String?

    private let diagnosticsCategory = "watch_pair_login"

    private var isAuthenticatedProvider: (@MainActor () -> Bool)?

    private override init() {
        super.init()
    }

    func start(isAuthenticated: @escaping @MainActor () -> Bool) {
        isAuthenticatedProvider = isAuthenticated
        guard WCSession.isSupported() else {
            NativeDiagnostics.warning("phase=phoneBridge.start unsupported=watchConnectivity", category: diagnosticsCategory)
            return
        }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        NativeDiagnostics.info(
            "phase=phoneBridge.start activationState=\(session.activationState.rawValue) reachable=\(session.isReachable) paired=\(session.isPaired) watchAppInstalled=\(session.isWatchAppInstalled)",
            category: diagnosticsCategory
        )
    }

    func denyPendingRequest() {
        pendingRequest = nil
        lastError = nil
    }

    func approvePendingRequest(authManager: AuthManager) async throws {
        guard let request = pendingRequest else { return }
        let currentProfile = ServerProfile.current()
        NativeDiagnostics.info(
            "phase=phoneBridge.approve.start requestServerKind=\(request.serverProfile.diagnosticsKind) currentServerKind=\(currentProfile.diagnosticsKind)",
            category: diagnosticsCategory
        )
        guard WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(request, currentProfile: currentProfile) else {
            let mismatch = PairLoginRuntimeError.serverMismatch(
                message: AppStrings.pairWatchLoginServerMismatch(
                    watchServer: request.serverProfile.displayDomain,
                    phoneServer: currentProfile.displayDomain
                )
            )
            lastError = mismatch.localizedDescription
            NativeDiagnostics.warning(
                "phase=phoneBridge.approve.failed reason=serverMismatch requestServerKind=\(request.serverProfile.diagnosticsKind) currentServerKind=\(currentProfile.diagnosticsKind)",
                category: diagnosticsCategory
            )
            throw mismatch
        }
        guard let currentUser = authManager.currentUser else {
            lastError = AppStrings.loginFailed
            NativeDiagnostics.warning("phase=phoneBridge.approve.failed reason=missingCurrentUser", category: diagnosticsCategory)
            throw AuthError.invalidCredentials
        }
        let pin = try await PairLoginRuntime.authorize(
            token: request.token,
            currentUser: currentUser,
            authorizerDeviceName: UIDevice.current.name,
            serverProfile: request.serverProfile
        )
        let approval = WatchPairLoginApproval(token: request.token, pin: pin)
        if WCSession.isSupported(), WCSession.default.isReachable {
            WCSession.default.sendMessage(
                WatchPairLoginConnectivityPayload.approvalMessage(approval),
                replyHandler: nil,
                errorHandler: { _ in }
            )
        }
        pendingRequest = nil
        lastError = nil
        NativeDiagnostics.info(
            "phase=phoneBridge.approve.success requestServerKind=\(request.serverProfile.diagnosticsKind) sentViaReachableSession=\(WCSession.isSupported() && WCSession.default.isReachable)",
            category: diagnosticsCategory
        )
    }

    private func receive(_ request: WatchPairLoginRequest) {
        let currentProfile = ServerProfile.current()
        guard WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: currentProfile,
            isAuthenticated: isAuthenticatedProvider?() ?? false
        ) else {
            NativeDiagnostics.info(
                "phase=phoneBridge.request.ignored reason=ineligible requestServerKind=\(request.serverProfile.diagnosticsKind) currentServerKind=\(currentProfile.diagnosticsKind)",
                category: diagnosticsCategory
            )
            return
        }
        if let pendingRequest {
            guard pendingRequest.token != request.token else { return }
            guard pendingRequest.createdAt <= request.createdAt else {
                NativeDiagnostics.info(
                    "phase=phoneBridge.request.ignored reason=olderThanPending",
                    category: diagnosticsCategory
                )
                return
            }
        }
        pendingRequest = request
        NativeDiagnostics.info(
            "phase=phoneBridge.request.received serverKind=\(request.serverProfile.diagnosticsKind)",
            category: diagnosticsCategory
        )
        requestNotification(for: request)
    }

    private func requestNotification(for request: WatchPairLoginRequest) {
        let center = UNUserNotificationCenter.current()
        let title = AppStrings.pairConnectAppleWatchTitle
        let body = AppStrings.pairConnectAppleWatchDescription
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
            let notification = UNNotificationRequest(
                identifier: "openmates-watch-login-\(request.token)",
                content: content,
                trigger: trigger
            )
            center.add(notification)
        }
    }

    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        let errorLabel = error.map { " errorType=\(type(of: $0))" } ?? ""
        let isReachable = session.isReachable
        let isPaired = session.isPaired
        let isWatchAppInstalled = session.isWatchAppInstalled
        Task { @MainActor in
            NativeDiagnostics.info(
                "phase=phoneBridge.activationComplete state=\(activationState.rawValue) reachable=\(isReachable) paired=\(isPaired) watchAppInstalled=\(isWatchAppInstalled)\(errorLabel)",
                category: self.diagnosticsCategory
            )
        }
    }

    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}

    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let request = WatchPairLoginConnectivityPayload.parseRequest(message) else { return }
        Task { @MainActor in self.receive(request) }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        guard let request = WatchPairLoginConnectivityPayload.parseRequest(message) else {
            replyHandler(["status": "ignored"])
            return
        }
        Task { @MainActor in self.receive(request) }
        replyHandler(["status": "pending"])
    }
}
#endif

enum PairLoginRuntimeError: LocalizedError, Equatable {
    case completeFailed(PairLoginCompleteFailureKind)
    case serverMismatch(message: String)

    var errorDescription: String? {
        switch self {
        case .completeFailed:
            return "Pair login failed"
        case .serverMismatch(let message):
            return message
        }
    }
}

enum WatchCompatibleSession {
    static var nativeSessionId: String {
        if let existing = OpenMatesSharedEnvironment.defaults.string(forKey: sessionIdDefaultsKey) {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: sessionIdDefaultsKey) {
            OpenMatesSharedEnvironment.defaults.set(existing, forKey: sessionIdDefaultsKey)
            return existing
        }
        let newValue = UUID().uuidString
        UserDefaults.standard.set(newValue, forKey: sessionIdDefaultsKey)
        OpenMatesSharedEnvironment.defaults.set(newValue, forKey: sessionIdDefaultsKey)
        return newValue
    }

    static func makeNativeDeviceInfo() -> DeviceInfo {
        let os: String
        #if os(watchOS)
        os = "watchOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #elseif os(iOS)
        os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #elseif os(macOS)
        os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #else
        os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #endif

        return DeviceInfo(
            os: os,
            deviceModel: getNativeDeviceModel(),
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        )
    }

    static func resetNativeSessionId() {
        UserDefaults.standard.removeObject(forKey: sessionIdDefaultsKey)
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: sessionIdDefaultsKey)
    }

    private static let sessionIdDefaultsKey = "openmates.apple.auth.session_id"

    private static func getNativeDeviceModel() -> String {
        #if os(iOS)
        return UIDevice.current.model
        #else
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        var model = [CChar](repeating: 0, count: max(size, 1))
        sysctlbyname("hw.model", &model, &size, nil, 0)
        return String(cString: model)
        #endif
    }
}
