// Web-compatible encrypted sharing for chats and embeds.
// Keeps keys, passwords, and URL fragments on-device while sending only opaque
// durable-short-link ciphertext to the existing share API.
// Mirrors frontend/packages/ui/src/services/shareEncryption.ts and
// frontend/packages/ui/src/services/shortUrlEncryption.ts.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens:  none
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import Foundation

enum ShareDuration: Int, CaseIterable, Identifiable {
    case noExpiration = 0
    case oneMinute = 60
    case oneHour = 3_600
    case twentyFourHours = 86_400
    case sevenDays = 604_800
    case fourteenDays = 1_209_600
    case thirtyDays = 2_592_000
    case ninetyDays = 7_776_000

    var id: Int { rawValue }
}

enum ShareLinkCrypto {
    private static let shareSalt = "openmates-share-v1"
    private static let passwordSaltPrefix = "openmates-pwd-"
    private static let shortURLSaltPrefix = "omts-v1-"
    private static let shortURLAlphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")

    static func encryptedShareBlob(
        identifier: String,
        key: SymmetricKey,
        duration: ShareDuration,
        password: String?,
        keyField: String
    ) async throws -> String {
        let keyBase64 = key.withUnsafeBytes { Data($0).base64EncodedString() }
        let keyForBlob: String
        let passwordEnabled = password?.isEmpty == false

        if let password, passwordEnabled {
            let passwordKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(
                password: password,
                salt: Data("\(passwordSaltPrefix)\(identifier)".utf8)
            )
            keyForBlob = try encryptURLSafe(Data(keyBase64.utf8), using: passwordKey)
        } else {
            keyForBlob = keyBase64
        }

        let serialized = try serialize([
            keyField: keyForBlob,
            "generated_at": String(Int(Date().timeIntervalSince1970)),
            "duration_seconds": String(duration.rawValue),
            "pwd": passwordEnabled ? "1" : "0"
        ])
        let identifierKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(
            password: identifier,
            salt: Data(shareSalt.utf8)
        )
        return try encryptURLSafe(Data(serialized.utf8), using: identifierKey)
    }

    static func encryptedShortURL(_ longURL: URL) async throws -> (token: String, shortKey: String, encryptedURL: String) {
        let token = randomBase62(length: 8)
        let shortKey = randomBase62(length: 6)
        let encryptionKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(
            password: shortKey,
            salt: Data("\(shortURLSaltPrefix)\(token)".utf8),
            iterations: 200_000
        )
        return (token, shortKey, try encryptURLSafe(Data(longURL.absoluteString.utf8), using: encryptionKey))
    }

    static func shortURL(webURL: URL, token: String, shortKey: String) throws -> URL {
        try urlWithFragment(webURL.appendingPathComponent("s/\(token)"), fragment: shortKey)
    }

    static func urlWithFragment(_ url: URL, fragment: String) throws -> URL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw ShareLinkCryptoError.urlConstructionFailed
        }
        components.fragment = fragment
        guard let fragmentURL = components.url else {
            throw ShareLinkCryptoError.urlConstructionFailed
        }
        return fragmentURL
    }

    private static func encryptURLSafe(_ plaintext: Data, using key: SymmetricKey) throws -> String {
        let sealed = try AES.GCM.seal(plaintext, using: key)
        var combined = Data(sealed.nonce)
        combined.append(sealed.ciphertext)
        combined.append(sealed.tag)
        return base64URL(combined)
    }

    private static func serialize(_ values: [String: String]) throws -> String {
        var components = URLComponents()
        components.queryItems = values.map { URLQueryItem(name: $0.key, value: $0.value) }
        guard let query = components.percentEncodedQuery else {
            throw ShareLinkCryptoError.serializationFailed
        }
        return query
    }

    private static func randomBase62(length: Int) -> String {
        let bytes = (0..<length).map { _ in UInt8.random(in: .min ... .max) }
        return String(bytes.map { shortURLAlphabet[Int($0) % shortURLAlphabet.count] })
    }

    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

enum ShareLinkCryptoError: Error {
    case serializationFailed
    case urlConstructionFailed
}
