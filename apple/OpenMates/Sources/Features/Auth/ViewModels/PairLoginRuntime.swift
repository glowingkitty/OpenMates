// Shared pair-login runtime for Apple auth surfaces.
// Owns the QR/PIN entry points while PairV2Runtime performs client-to-client
// PAKE, grant completion, and backend message relay.
// Used by the regular iOS/macOS login surface and by the standalone Watch app.
// Does not store sessions; callers decide how to persist the authenticated user.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.iphone-first-fallback, apple-watch.pairing.private-session

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
import Combine
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

struct WatchPairLoginRequest: Equatable, Sendable {
    let token: String
    let pairURLString: String
    let deviceName: String
    let serverProfile: ServerProfile
    let createdAt: Int
}

struct WatchPairLoginApproval: Equatable, Sendable {
    let token: String
    let pin: String
}

struct WatchPairLoginAcknowledgment: Equatable, Sendable {
    enum Kind: String, Equatable, Sendable {
        case offered
        case approvalStarted
        case denied
        case approvalFailed
    }

    let token: String
    let kind: Kind
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
    private static let pinAlphabet = Set("ABCDEFGHJKLMNPQRTUVWXY3468")

    static func normalizedPIN(_ rawValue: String) -> String {
        String(
            rawValue
                .uppercased()
                .filter { $0.isLetter || $0.isNumber }
                .prefix(6)
        )
    }

    static func isValidPIN(_ pin: String) -> Bool {
        pin.count == 6 && pin.allSatisfy { pinAlphabet.contains($0) }
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
        try await PairV2Runtime.initiate(deviceHint: deviceHint, serverProfile: serverProfile)
    }

    static func poll(token: String, serverProfile: ServerProfile = ServerProfile.current()) async throws -> PairV2ReceiverPoll {
        try await PairV2Runtime.poll(token: token, serverProfile: serverProfile)
    }

    static func complete(
        token: String,
        pin: String,
        stayLoggedIn: Bool,
        serverProfile: ServerProfile = ServerProfile.current()
    ) async throws -> PairLoginResult {
        do {
            return try await PairV2Runtime.complete(token: token, pin: pin, serverProfile: serverProfile)
        } catch {
            await PairV2Runtime.cancel(token: token, serverProfile: serverProfile)
            throw error
        }
    }

    static func authorize(
        token: String,
        currentUser: UserProfile,
        authorizerDeviceName: String,
        autoLogoutMinutes: Int? = nil,
        serverProfile: ServerProfile = ServerProfile.current()
    ) async throws -> String {
        try await PairV2Runtime.authorize(
            token: token, currentUser: currentUser,
            authorizerDeviceName: authorizerDeviceName,
            autoLogoutMinutes: autoLogoutMinutes, serverProfile: serverProfile
        )
    }

    static func acknowledge(token: String, serverProfile: ServerProfile = ServerProfile.current()) async throws {
        do {
            try await PairV2Runtime.acknowledge(token: token, serverProfile: serverProfile)
        } catch {
            await PairV2Runtime.cancel(token: token, serverProfile: serverProfile)
            throw error
        }
    }

    static func generatePairPIN() throws -> String {
        let alphabet = Array("ABCDEFGHJKLMNPQRTUVWXY3468")
        return try SecureRandom.string(length: 6, alphabet: alphabet)
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

// Only accepted receipt identity survives the pairing view. The PIN itself is
// never retained here, logged, persisted, or reapplied during receipt replay.
struct WatchPairApprovalReceiptCache: Sendable {
    private struct Accepted: Sendable {
        let token: String
        let fingerprint: Data
        let profile: ServerProfile
        let expiresAt: Int
    }
    private var accepted: Accepted?
    var expiresAt: Int? { accepted?.expiresAt }

    mutating func remember(_ approval: WatchPairLoginApproval, profile: ServerProfile,
                           expiresAt: Int, now: Int) -> Bool {
        guard expiresAt > now, PairLoginRuntime.isValidPIN(approval.pin),
              approval.token.range(of: "^[A-Z0-9]{6}$", options: .regularExpression) != nil else { return false }
        let fingerprint = Self.fingerprint(approval)
        if let accepted {
            // Receipt replay cannot change the PIN or extend the original deadline.
            guard accepted.token == approval.token,
                  accepted.fingerprint == fingerprint,
                  Self.sameServer(accepted.profile, profile), accepted.expiresAt == expiresAt else { return false }
        }
        accepted = Accepted(token: approval.token, fingerprint: fingerprint,
                            profile: profile, expiresAt: expiresAt)
        return true
    }

    func matches(_ approval: WatchPairLoginApproval, profile: ServerProfile, now: Int) -> Bool {
        guard let accepted, accepted.expiresAt > now,
              Self.sameServer(accepted.profile, profile), accepted.token == approval.token,
              PairLoginRuntime.isValidPIN(approval.pin) else { return false }
        return accepted.fingerprint == Self.fingerprint(approval)
    }

    mutating func prune(profile: ServerProfile, now: Int) {
        if let accepted, accepted.expiresAt <= now || !Self.sameServer(accepted.profile, profile) { clear() }
    }

    mutating func clear() { accepted = nil }

    private static func fingerprint(_ approval: WatchPairLoginApproval) -> Data {
        Data(SHA256.hash(data: Data((approval.token + "\0" + approval.pin).utf8)))
    }

    private static func sameServer(_ lhs: ServerProfile, _ rhs: ServerProfile) -> Bool {
        // Preserve current server equivalence: DEV selected via self-hosted input
        // and the built-in DEV profile address the same web/API endpoints.
        lhs.webBaseURL == rhs.webBaseURL && lhs.apiBaseURL == rhs.apiBaseURL
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
    static let watchLoginAcknowledgmentKind = "openmates.watch.pair_login.acknowledgment"
    static let acknowledgmentKey = "acknowledgment"
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

    // A receipt carries only the request identity, never the PIN or account data.
    static func approvalReceiptMessage(token: String) -> [String: Any] {
        [kindKey: "openmates.watch.pair_login.receipt", tokenKey: token.uppercased()]
    }

    static func parseApprovalReceipt(_ message: [String: Any]) -> String? {
        guard message[kindKey] as? String == "openmates.watch.pair_login.receipt",
              let token = message[tokenKey] as? String,
              token.range(of: "^[A-Z0-9]{6}$", options: .regularExpression) != nil,
              message[pinKey] == nil, !containsForbiddenSecretKeys(message) else { return nil }
        return token
    }

    static func canReceiveApproval(_ approval: WatchPairLoginApproval,
                                   token: String?, status: PairLoginStatus) -> Bool {
        approval.token == token && (status == .waiting || status == .ready)
            && PairLoginRuntime.isValidPIN(approval.pin)
    }

    static func acknowledgmentMessage(_ acknowledgment: WatchPairLoginAcknowledgment) -> [String: Any] {
        [
            kindKey: watchLoginAcknowledgmentKind,
            tokenKey: acknowledgment.token.uppercased(),
            acknowledgmentKey: acknowledgment.kind.rawValue,
        ]
    }

    static func parseAcknowledgment(_ message: [String: Any]) -> WatchPairLoginAcknowledgment? {
        guard message[kindKey] as? String == watchLoginAcknowledgmentKind,
              let token = message[tokenKey] as? String,
              !token.isEmpty,
              let rawKind = message[acknowledgmentKey] as? String,
              let kind = WatchPairLoginAcknowledgment.Kind(rawValue: rawKind) else { return nil }
        return WatchPairLoginAcknowledgment(token: token.uppercased(), kind: kind)
    }

    static func containsForbiddenSecretKeys(_ message: [String: Any]) -> Bool {
        let keys = Set(message.keys.map { $0.lowercased() })
        return forbiddenSecretKeys.contains { keys.contains($0) }
    }
}

#if os(watchOS)
// WatchConnectivity permits invoking this response on our delegate's chosen queue.
// The immutable callback crosses actors once; no received dictionary is retained.
private struct WatchPairReceiptReply: @unchecked Sendable {
    let reply: ([String: Any]) -> Void
}

@MainActor
final class WatchPhoneLoginBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchPhoneLoginBridge()
    @Published private(set) var isPhoneReachable = false

    private let diagnosticsCategory = "watch_pair_login"

    private var approvalHandler: (@MainActor (WatchPairLoginApproval) -> Bool)?
    private var acknowledgmentHandler: (@MainActor (WatchPairLoginAcknowledgment) -> Void)?
    private var receiptCache = WatchPairApprovalReceiptCache()
    private var receiptExpiryTask: Task<Void, Never>?
    private var receiptGeneration = UUID()
    private var profileObserver: NSObjectProtocol?

    private override init() {
        super.init()
        profileObserver = NotificationCenter.default.addObserver(
            forName: ServerConfiguration.didChangeNotification, object: nil, queue: nil
        ) { @Sendable [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.receiptCache.prune(profile: ServerProfile.current(), now: Int(Date().timeIntervalSince1970))
                if self.receiptCache.expiresAt == nil { self.clearPairingReceipts() }
            }
        }
    }

    func clearPairingReceipts() {
        receiptGeneration = UUID()
        receiptExpiryTask?.cancel()
        receiptExpiryTask = nil
        receiptCache.clear()
    }

    @discardableResult
    func rememberAcceptedApproval(_ approval: WatchPairLoginApproval,
                                 profile: ServerProfile, expiresAt: Int) -> Bool {
        let now = Int(Date().timeIntervalSince1970)
        guard receiptCache.remember(approval, profile: profile, expiresAt: expiresAt, now: now) else { return false }
        receiptExpiryTask?.cancel()
        let run = UUID()
        receiptGeneration = run
        receiptExpiryTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                let remaining = expiresAt - Int(Date().timeIntervalSince1970)
                if remaining <= 0 {
                    guard let self, self.receiptGeneration == run else { return }
                    self.clearPairingReceipts()
                    return
                }
                do { try await Task.sleep(for: .seconds(remaining)) } catch { return }
            }
        }
        return true
    }

    // Authenticated surfaces release the PIN/view callback. Only a previously
    // accepted fingerprint may produce another receipt before its actual expiry.
    func startAuthenticatedTransport() {
        approvalHandler = nil
        acknowledgmentHandler = nil
        receiptCache.prune(profile: ServerProfile.current(), now: Int(Date().timeIntervalSince1970))
        if receiptCache.expiresAt == nil { clearPairingReceipts() }
        activateTransport()
    }

    private func receiveApproval(_ approval: WatchPairLoginApproval) -> Bool {
        if let approvalHandler { return approvalHandler(approval) }
        let now = Int(Date().timeIntervalSince1970)
        receiptCache.prune(profile: ServerProfile.current(), now: now)
        return receiptCache.matches(approval, profile: ServerProfile.current(), now: now)
    }

    func start(
        onApproval: @escaping @MainActor (WatchPairLoginApproval) -> Bool,
        onAcknowledgment: @escaping @MainActor (WatchPairLoginAcknowledgment) -> Void
    ) {
        clearPairingReceipts()
        approvalHandler = onApproval
        acknowledgmentHandler = onAcknowledgment
        activateTransport()
    }

    private func activateTransport() {
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
            NativeDiagnostics.warning(
                "phase=bridge.send.skipped reason=notReachable supported=\(WCSession.isSupported()) serverKind=\(request.serverProfile.diagnosticsKind)",
                category: diagnosticsCategory
            )
            return false
        }
        isPhoneReachable = true
        NativeDiagnostics.info(
            "phase=bridge.send.start serverKind=\(request.serverProfile.diagnosticsKind) reachable=\(WCSession.default.isReachable)",
            category: diagnosticsCategory
        )
        WCSession.default.sendMessage(
            WatchPairLoginConnectivityPayload.requestMessage(request),
            replyHandler: nil,
            errorHandler: nil
        )
        return true
    }

    private nonisolated func dispatchToMain(_ work: @MainActor @escaping (WatchPhoneLoginBridge) -> Void) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            work(self)
        }
    }

    @discardableResult
    func sendEmbedOpenRequest(_ request: WatchEmbedOpenRequest) -> Bool {
        guard WCSession.isSupported() else {
            NativeDiagnostics.warning("phase=bridge.embedOpen.skipped reason=unsupported", category: diagnosticsCategory)
            return false
        }
        let message = WatchEmbedOpenConnectivityPayload.requestMessage(request)
        if WCSession.default.isReachable {
            WCSession.default.sendMessage(message, replyHandler: nil, errorHandler: { _ in })
        } else {
            WCSession.default.transferUserInfo(message)
        }
        NativeDiagnostics.info(
            "phase=bridge.embedOpen.sent reachable=\(WCSession.default.isReachable)",
            category: diagnosticsCategory
        )
        return true
    }

    @discardableResult
    func sendItemOpenRequest(_ request: WatchItemOpenRequest) -> Bool {
        sendWebOpenPayload(.item(request, serverProfileId: WatchServerProfileStore().currentProfile().id))
    }

    @discardableResult
    func sendCollectionOpenRequest(kind: WatchItemOpenRequest.Kind) -> Bool {
        sendWebOpenPayload(.collection(kind, serverProfileId: WatchServerProfileStore().currentProfile().id))
    }

    @discardableResult
    func sendSettingsOpenRequest() -> Bool {
        sendWebOpenPayload(.settings(serverProfileId: WatchServerProfileStore().currentProfile().id))
    }

    private func sendWebOpenPayload(_ payload: WatchPhoneOpenPayload) -> Bool {
        guard WCSession.isSupported() else { return false }
        let session = WCSession.default
        let message = payload.message
        if session.isReachable {
            session.sendMessage(message, replyHandler: nil, errorHandler: { _ in
                session.transferUserInfo(message)
            })
        } else {
            session.transferUserInfo(message)
        }
        NativeDiagnostics.info("phase=bridge.webOpen.sent reachable=\(session.isReachable)", category: diagnosticsCategory)
        return true
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
        if let approval = WatchPairLoginConnectivityPayload.parseApproval(message) {
            dispatchToMain { bridge in
                NativeDiagnostics.info("phase=bridge.receivedApproval", category: bridge.diagnosticsCategory)
                _ = bridge.receiveApproval(approval)
            }
        } else if let acknowledgment = WatchPairLoginConnectivityPayload.parseAcknowledgment(message) {
            dispatchToMain { bridge in
                NativeDiagnostics.info("phase=bridge.receivedAcknowledgment kind=\(acknowledgment.kind.rawValue)", category: bridge.diagnosticsCategory)
                bridge.acknowledgmentHandler?(acknowledgment)
            }
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any],
                             replyHandler: @escaping ([String: Any]) -> Void) {
        // Parse before crossing actors; dictionaries may contain non-Sendable values.
        guard let approval = WatchPairLoginConnectivityPayload.parseApproval(message) else {
            replyHandler(["status": "ignored"])
            return
        }
        let receipt = WatchPairReceiptReply(reply: replyHandler)
        Task { @MainActor [weak self] in
            guard let self, self.receiveApproval(approval) else {
                receipt.reply(["status": "ignored"])
                return
            }
            receipt.reply(WatchPairLoginConnectivityPayload.approvalReceiptMessage(token: approval.token))
        }
    }

}
#endif

#if os(iOS)
// Inject only transport/time boundaries; production approval state stays in the bridge.
@MainActor
struct PhoneWatchPairDependencies {
    var profile: @MainActor () -> ServerProfile = { ServerProfile.current() }
    var now: @MainActor () -> Int = { Int(Date().timeIntervalSince1970) }
    var reachable: @MainActor () -> Bool = { WCSession.isSupported() && WCSession.default.isReachable }
    var authorize: @MainActor (WatchPairLoginRequest, UserProfile) async throws -> PairV2Authorization = { request, user in
        try await PairV2Runtime.startAuthorization(token: request.token, currentUser: user,
            authorizerDeviceName: UIDevice.current.name, autoLogoutMinutes: nil,
            serverProfile: request.serverProfile)
    }
    var poll: @MainActor (WatchPairLoginRequest) async throws -> PairV2AuthorizerPoll = { request in
        try await PairV2Runtime.authorizerPoll(token: request.token, serverProfile: request.serverProfile)
    }
    var cancel: @MainActor (WatchPairLoginRequest) async -> Void = { request in
        let _: Data? = try? await APIClient.shared.request(.delete,
            path: "/v1/auth/pair/v2/\(request.token)", serverProfile: request.serverProfile)
    }
    var send: @MainActor (WatchPairLoginApproval, @escaping @MainActor (String?) -> Void) -> Void = { approval, completion in
        WCSession.default.sendMessage(WatchPairLoginConnectivityPayload.approvalMessage(approval),
            replyHandler: { @Sendable reply in
                let receivedToken = WatchPairLoginConnectivityPayload.parseApprovalReceipt(reply)
                Task { @MainActor in completion(receivedToken) }
            }, errorHandler: { @Sendable _ in
                Task { @MainActor in completion(nil) }
            })
    }
    var stepUpMethods: @MainActor (ServerProfile) async throws -> PairV2StepUpMethods = { profile in
        try await PairV2Runtime.stepUpMethods(serverProfile: profile)
    }
    var pause: @MainActor () async throws -> Void = { try await Task.sleep(for: .seconds(1)) }
    var usesConnectivity = true
    var offersNotification = true
}

@MainActor
final class PhoneWatchLoginBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneWatchLoginBridge()

    @Published private(set) var pendingRequest: WatchPairLoginRequest?
    @Published private(set) var lastError: String?

    private let diagnosticsCategory = "watch_pair_login"

    private var isAuthenticatedProvider: (@MainActor () -> Bool)?
    private let dependencies: PhoneWatchPairDependencies
    private var generation = UUID()
    private var approvalFlight: Task<Void, Error>?
    private var authorization: PairV2Authorization?
    private var sendFlight: UUID?
    private var approvalAccountID: String?
    private var authBindings: Set<AnyCancellable> = []
    @Published private(set) var pinReceiptReceived = false
    @Published private(set) var completedRequestToken: String?
    var hasPendingApproval: Bool { authorization != nil }

    init(dependencies: PhoneWatchPairDependencies = PhoneWatchPairDependencies()) {
        self.dependencies = dependencies
        super.init()
    }

    func stepUpMethodsForPendingRequest() async throws -> PairV2StepUpMethods {
        guard let request = pendingRequest else { throw CancellationError() }
        return try await dependencies.stepUpMethods(request.serverProfile)
    }

    private func bindApprovalIdentity(_ authManager: AuthManager, userID: String) {
        authBindings.removeAll()
        approvalAccountID = userID
        authManager.$state.combineLatest(authManager.$currentUser).sink { [weak self] state, user in
            guard let self else { return }
            if state != .authenticated || user?.id != userID { self.invalidateApproval() }
        }.store(in: &authBindings)
        NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)
            .sink { @Sendable [weak self] _ in
                Task { @MainActor in
                    guard let self, let request = self.pendingRequest else { return }
                    if !WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(
                        request, currentProfile: self.dependencies.profile()) { self.invalidateApproval() }
                }
            }.store(in: &authBindings)
    }

    private func invalidateApproval(cancelRemote: Bool = true) {
        let request = pendingRequest
        generation = UUID()
        approvalFlight?.cancel()
        approvalFlight = nil
        authorization?.relayTask.cancel()
        authorization = nil
        sendFlight = nil
        approvalAccountID = nil
        pinReceiptReceived = false
        authBindings.removeAll()
        pendingRequest = nil
        if cancelRemote, let request { Task { await dependencies.cancel(request) } }
    }

    func start(isAuthenticated: @escaping @MainActor () -> Bool) {
        isAuthenticatedProvider = isAuthenticated
        guard dependencies.usesConnectivity else { return }
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
        if let pendingRequest { sendAcknowledgment(.denied, token: pendingRequest.token) }
        invalidateApproval()
        lastError = nil
    }

    func approvePendingRequest(authManager: AuthManager) async throws {
        if let approvalFlight { return try await approvalFlight.value }
        guard let request = pendingRequest, authManager.state == .authenticated,
              let user = authManager.currentUser else { throw AuthError.invalidCredentials }
        let run = generation
        bindApprovalIdentity(authManager, userID: user.id)
        sendAcknowledgment(.approvalStarted, token: request.token)
        let flight = Task { try await self.performApproval(request, user: user, run: run) }
        approvalFlight = flight
        do {
            try await flight.value
        } catch APIError.httpError(let status, _) where status == 401 || status == 403 || status == 428 {
            // Step-up before approval may retry. Once minted, never approve twice.
            if generation == run, authorization == nil { approvalFlight = nil; authBindings.removeAll() }
            throw errorForStepUp(status)
        } catch {
            if generation == run {
                lastError = error.localizedDescription
                sendAcknowledgment(.approvalFailed, token: request.token)
                invalidateApproval()
            }
            throw error
        }
    }

    private func errorForStepUp(_ status: Int) -> APIError {
        .httpError(status: status, message: "Pair approval requires recent authentication")
    }

    private func isCurrent(_ request: WatchPairLoginRequest, run: UUID) -> Bool {
        generation == run && pendingRequest == request && approvalAccountID != nil
            && WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(
                request, currentProfile: dependencies.profile())
    }

    private func performApproval(_ request: WatchPairLoginRequest, user: UserProfile, run: UUID) async throws {
        guard isCurrent(request, run: run) else { throw CancellationError() }
        NativeDiagnostics.info("phase=phoneBridge.approve.start", category: diagnosticsCategory)
        let result = try await dependencies.authorize(request, user)
        guard !Task.isCancelled, isCurrent(request, run: run), result.expiresAt > dependencies.now(),
              PairLoginRuntime.isValidPIN(result.pin) else {
            result.relayTask.cancel()
            await dependencies.cancel(request)
            throw CancellationError()
        }
        authorization = result
        NativeDiagnostics.info("phase=phoneBridge.approval.minted", category: diagnosticsCategory)
        while true {
            try Task.checkCancellation()
            guard isCurrent(request, run: run), dependencies.now() < result.expiresAt else {
                throw PairOpaqueError.invalidExchange
            }
            sendApprovalIfPossible(request, run: run)
            do {
                let status = try await dependencies.poll(request)
                try Task.checkCancellation()
                guard isCurrent(request, run: run), status.expiresAt == result.expiresAt,
                      dependencies.now() < result.expiresAt else {
                    throw PairOpaqueError.invalidExchange
                }
                if ["failed", "cancelled"].contains(status.status) { throw PairOpaqueError.invalidExchange }
                if status.status == "acknowledged", pinReceiptReceived {
                    completedRequestToken = request.token
                    invalidateApproval(cancelRemote: false)
                    NativeDiagnostics.info("phase=phoneBridge.approve.completed", category: diagnosticsCategory)
                    return
                }
            } catch APIError.httpError(let status, _) where [401, 403, 404].contains(status) {
                throw PairOpaqueError.invalidExchange
            } catch is CancellationError {
                throw CancellationError()
            } catch is PairOpaqueError {
                throw PairOpaqueError.invalidExchange
            } catch {
                // Transient polling errors retain this exact approval until its deadline.
                NativeDiagnostics.warning("phase=phoneBridge.approval.pollRetry", category: diagnosticsCategory)
            }
            try await dependencies.pause()
        }
    }

    private func sendApprovalIfPossible(_ request: WatchPairLoginRequest, run: UUID) {
        guard isCurrent(request, run: run), !pinReceiptReceived, sendFlight == nil,
              let authorization, dependencies.now() < authorization.expiresAt,
              dependencies.reachable() else { return }
        let attempt = UUID()
        sendFlight = attempt
        dependencies.send(WatchPairLoginApproval(token: request.token, pin: authorization.pin)) { [weak self] token in
            guard let self, self.isCurrent(request, run: run), self.sendFlight == attempt,
                  let active = self.authorization, self.dependencies.now() < active.expiresAt else { return }
            self.sendFlight = nil
            if token == request.token {
                self.pinReceiptReceived = true
                NativeDiagnostics.info("phase=phoneBridge.approval.receipt", category: self.diagnosticsCategory)
            } else {
                NativeDiagnostics.warning("phase=phoneBridge.approval.sendRetry", category: self.diagnosticsCategory)
            }
        }
    }

    func receive(_ request: WatchPairLoginRequest) {
        let currentProfile = dependencies.profile()
        guard WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: currentProfile,
            isAuthenticated: isAuthenticatedProvider?() ?? false,
            now: dependencies.now()
        ) else {
            NativeDiagnostics.info(
                "phase=phoneBridge.request.ignored reason=ineligible requestServerKind=\(request.serverProfile.diagnosticsKind) currentServerKind=\(currentProfile.diagnosticsKind)",
                category: diagnosticsCategory
            )
            return
        }
        if let pendingRequest {
            guard pendingRequest.token != request.token else {
                sendAcknowledgment(.offered, token: request.token)
                return
            }
            guard pendingRequest.createdAt <= request.createdAt else {
                NativeDiagnostics.info(
                    "phase=phoneBridge.request.ignored reason=olderThanPending",
                    category: diagnosticsCategory
                )
                return
            }
        }
        if pendingRequest != nil { invalidateApproval() }
        generation = UUID()
        completedRequestToken = nil
        pendingRequest = request
        sendAcknowledgment(.offered, token: request.token)
        NativeDiagnostics.info(
            "phase=phoneBridge.request.received serverKind=\(request.serverProfile.diagnosticsKind)",
            category: diagnosticsCategory
        )
        if dependencies.offersNotification { requestNotification(for: request) }
    }

    private func sendAcknowledgment(_ kind: WatchPairLoginAcknowledgment.Kind, token: String) {
        guard dependencies.usesConnectivity else { return }
        guard WCSession.isSupported(), WCSession.default.isReachable else { return }
        let acknowledgment = WatchPairLoginAcknowledgment(token: token, kind: kind)
        WCSession.default.sendMessage(
            WatchPairLoginConnectivityPayload.acknowledgmentMessage(acknowledgment),
            replyHandler: nil,
            errorHandler: nil
        )
    }

    private func receive(_ request: WatchEmbedOpenRequest) {
        NativeDiagnostics.info("phase=phoneBridge.embedOpen.received", category: diagnosticsCategory)
        Task { await PushNotificationManager.shared.showWatchEmbedNotification(chatId: request.chatId, embedId: request.embedId) }
    }

    private func receive(_ payload: WatchPhoneOpenPayload) {
        guard payload.serverProfileId == ServerProfile.current().id else {
            NativeDiagnostics.warning("phase=phoneBridge.webOpen.ignored reason=serverMismatch", category: diagnosticsCategory)
            return
        }
        Task { await PushNotificationManager.shared.showWatchWebOpenNotification(payload) }
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
        if let request = WatchPairLoginConnectivityPayload.parseRequest(message) {
            Task { @MainActor in self.receive(request) }
            return
        }
        if let request = WatchEmbedOpenConnectivityPayload.parseRequest(message) {
            Task { @MainActor in self.receive(request) }
            return
        }
        if let payload = WatchPhoneOpenPayload.parse(message) {
            Task { @MainActor in self.receive(payload) }
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        if let request = WatchPairLoginConnectivityPayload.parseRequest(message) {
            Task { @MainActor in self.receive(request) }
            replyHandler(["status": "pending"])
            return
        }
        if let request = WatchEmbedOpenConnectivityPayload.parseRequest(message) {
            Task { @MainActor in self.receive(request) }
            replyHandler(["status": "notification_scheduled"])
            return
        }
        if let payload = WatchPhoneOpenPayload.parse(message) {
            Task { @MainActor in self.receive(payload) }
            replyHandler(["status": "notification_scheduled"])
            return
        }
        replyHandler(["status": "ignored"])
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        if let request = WatchEmbedOpenConnectivityPayload.parseRequest(userInfo) {
            Task { @MainActor in self.receive(request) }
            return
        }
        if let payload = WatchPhoneOpenPayload.parse(userInfo) {
            Task { @MainActor in self.receive(payload) }
        }
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

enum WatchSessionRefreshDisposition: Equatable {
    case authenticated
    case transientFailure
    case revoked
}

enum WatchSessionRefreshPolicy {
    static func disposition(for error: Error) -> WatchSessionRefreshDisposition {
        if case APIError.httpError(status: 401, message: _) = error {
            return .revoked
        }
        return .transientFailure
    }
}
