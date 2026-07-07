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
}

struct WatchPairLoginRequest: Equatable {
    let token: String
    let pairURLString: String
    let deviceName: String
    let createdAt: Int
}

struct WatchPairLoginApproval: Equatable {
    let token: String
    let pin: String
}

enum PairLoginRuntime {
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

    static func initiate(deviceHint: String = officialAppDeviceHint) async throws -> PairLoginInitiation {
        let response: PairInitiateResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/pair/initiate",
            body: PairInitiateRequest(deviceHint: deviceHint)
        )
        let token = response.token.uppercased()
        let webURL = await APIClient.shared.webAppURL
        return PairLoginInitiation(
            token: token,
            pairURLString: buildPairURL(webAppURL: webURL, token: token)
        )
    }

    static func poll(token: String) async throws -> PairPollResponse {
        try await APIClient.shared.request(.get, path: "/v1/auth/pair/poll/\(token)")
    }

    static func complete(token: String, pin: String, stayLoggedIn: Bool) async throws -> PairLoginResult {
        let completeResponse: PairCompleteResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/pair/complete/\(token)",
            body: PairCompleteRequest(pin: pin)
        )

        guard completeResponse.success else {
            throw PairLoginRuntimeError.completeFailed(failureKind(for: completeResponse.message))
        }

        let (bundle, masterKey) = try await decryptLoginBundle(from: completeResponse, token: token, pin: pin)
        let loginResponse: LoginResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/login",
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
        return PairLoginResult(loginResponse: loginResponse, masterKey: masterKey)
    }

    static func authorize(
        token: String,
        currentUser: UserProfile,
        authorizerDeviceName: String
    ) async throws -> String {
        let pin = generatePairPIN()
        let credentials: PairCredentialsResponse = try await APIClient.shared.request(
            .get,
            path: "/v1/auth/pair/credentials"
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
}

enum WatchPairLoginConnectivityPayload {
    static let kindKey = "kind"
    static let tokenKey = "token"
    static let pairURLKey = "pair_url"
    static let deviceNameKey = "device_name"
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
        [
            kindKey: watchLoginRequestKind,
            tokenKey: request.token.uppercased(),
            pairURLKey: request.pairURLString,
            deviceNameKey: request.deviceName,
            createdAtKey: request.createdAt,
        ]
    }

    static func parseRequest(_ message: [String: Any]) -> WatchPairLoginRequest? {
        guard message[kindKey] as? String == watchLoginRequestKind,
              let token = message[tokenKey] as? String,
              let pairURLString = message[pairURLKey] as? String else { return nil }
        return WatchPairLoginRequest(
            token: token.uppercased(),
            pairURLString: pairURLString,
            deviceName: message[deviceNameKey] as? String ?? "Apple Watch",
            createdAt: message[createdAtKey] as? Int ?? Int(Date().timeIntervalSince1970)
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

    private var approvalHandler: ((WatchPairLoginApproval) -> Void)?

    func start(onApproval: @escaping (WatchPairLoginApproval) -> Void) {
        approvalHandler = onApproval
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        isPhoneReachable = session.isReachable
    }

    @discardableResult
    func sendLoginRequest(_ request: WatchPairLoginRequest) -> Bool {
        guard WCSession.isSupported(), WCSession.default.isReachable else {
            isPhoneReachable = false
            didSendRequest = false
            return false
        }
        isPhoneReachable = true
        didSendRequest = true
        WCSession.default.sendMessage(
            WatchPairLoginConnectivityPayload.requestMessage(request),
            replyHandler: { message in
                guard let approval = WatchPairLoginConnectivityPayload.parseApproval(message) else { return }
                Task { @MainActor in self.approvalHandler?(approval) }
            },
            errorHandler: { _ in
                Task { @MainActor in self.didSendRequest = false }
            }
        )
        return true
    }

    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.isPhoneReachable = session.isReachable }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.isPhoneReachable = session.isReachable }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let approval = WatchPairLoginConnectivityPayload.parseApproval(message) else { return }
        Task { @MainActor in self.approvalHandler?(approval) }
    }
}
#endif

#if os(iOS)
@MainActor
final class PhoneWatchLoginBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneWatchLoginBridge()

    @Published private(set) var pendingRequest: WatchPairLoginRequest?
    @Published private(set) var lastError: String?

    private override init() {
        super.init()
    }

    func start() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    func denyPendingRequest() {
        pendingRequest = nil
        lastError = nil
    }

    func approvePendingRequest(authManager: AuthManager) async throws {
        guard let request = pendingRequest else { return }
        guard let currentUser = authManager.currentUser else {
            lastError = AppStrings.loginFailed
            throw AuthError.invalidCredentials
        }
        let pin = try await PairLoginRuntime.authorize(
            token: request.token,
            currentUser: currentUser,
            authorizerDeviceName: UIDevice.current.name
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
    }

    private func receive(_ request: WatchPairLoginRequest) {
        pendingRequest = request
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

    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}

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

    var errorDescription: String? {
        switch self {
        case .completeFailed:
            return "Pair login failed"
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
