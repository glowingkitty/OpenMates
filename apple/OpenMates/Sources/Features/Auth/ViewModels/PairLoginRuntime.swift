// Shared pair-login runtime for Apple auth surfaces.
// Owns the backend request sequence and cryptographic bundle decode for the
// QR/PIN Magic Pair Login flow while keeping each platform's SwiftUI view small.
// Used by the regular iOS/macOS login surface and by the standalone Watch app.
// Does not store sessions; callers decide how to persist the authenticated user.

import CryptoKit
import Foundation

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
}

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
