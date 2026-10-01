// Recipient-only encrypted share URL validation and key blob decoding.
// Web: frontend/packages/ui/src/services/shareEncryption.ts
//      frontend/packages/ui/src/services/shortUrlEncryption.ts
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open

import CryptoKit
import Foundation

enum SharedChatRecipientError: Error, Equatable {
    case invalidLink, passwordRequired, invalidPassword, expired, unavailable
    case shortLinkUnavailable, shortLinkDisabled, network, invalidResponse
}

struct SharedChatRecipientLink {
    enum Target { case chat(id: String, blob: String, messageID: String?), short(token: String, key: String) }
    let url: URL
    let apiBaseURL: URL
    let target: Target

    static func parse(_ url: URL) throws -> Self {
        guard url.absoluteString.utf8.count <= 131_072,
              url.scheme == "https", url.user == nil, url.password == nil,
              url.port == nil, url.query == nil,
              let host = url.host?.lowercased(),
              ["openmates.org", "app.openmates.org", "app.dev.openmates.org"].contains(host),
              let fragment = url.fragment, !fragment.isEmpty else {
            throw SharedChatRecipientError.invalidLink
        }
        let api = host == "app.dev.openmates.org" ? ServerProfile.development.apiBaseURL : ServerProfile.production.apiBaseURL
        let parts = url.pathComponents
        if parts.count == 3, parts[1] == "s",
           matches(parts[2], "^[A-Za-z0-9]{6,12}$"), matches(fragment, "^[A-Za-z0-9]{4,22}$") {
            return .init(url: url, apiBaseURL: api, target: .short(token: parts[2], key: fragment))
        }
        if parts.count == 2, parts[1] == "s", let split = fragment.firstIndex(of: "-") {
            let token = String(fragment[..<split]), key = String(fragment[fragment.index(after: split)...])
            guard matches(token, "^[A-Za-z0-9]{6,12}$"), matches(key, "^[A-Za-z0-9]{4,22}$") else {
                throw SharedChatRecipientError.invalidLink
            }
            return .init(url: url, apiBaseURL: api, target: .short(token: token, key: key))
        }
        guard parts.count == 4, parts[1] == "share", parts[2] == "chat",
              matches(parts[3], "^[A-Za-z0-9_-]{1,128}$") else { throw SharedChatRecipientError.invalidLink }
        let values = try parameters(fragment)
        guard let blob = values["key"], matches(blob, "^[A-Za-z0-9_-]+$"),
              Set(values.keys).isSubset(of: ["key", "messageid"]),
              values["messageid"].map({ matches($0, "^[A-Za-z0-9_-]{1,128}$") }) ?? true else {
            throw SharedChatRecipientError.invalidLink
        }
        return .init(url: url, apiBaseURL: api, target: .chat(id: parts[3], blob: blob, messageID: values["messageid"]))
    }

    static func parameters(_ text: String) throws -> [String: String] {
        var result: [String: String] = [:]
        for item in text.split(separator: "&", omittingEmptySubsequences: false) {
            let pair = item.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2,
                  let name = String(pair[0]).replacingOccurrences(of: "+", with: " ").removingPercentEncoding,
                  let value = String(pair[1]).replacingOccurrences(of: "+", with: " ").removingPercentEncoding,
                  result[name] == nil else { throw SharedChatRecipientError.invalidLink }
            result[name] = value
        }
        return result
    }

    private static func matches(_ value: String, _ pattern: String) -> Bool {
        value.range(of: pattern, options: .regularExpression) != nil
    }
}

enum SharedChatRecipientCrypto {
    static func chatKey(id: String, blob: String, serverTime: Int, password: String?) async throws -> SymmetricKey {
        let values: [String: String]
        do {
            let outerKey = try await CryptoManager.shared.deriveWrappingKeyFromPassword(
                password: id, salt: Data("openmates-share-v1".utf8))
            values = try SharedChatRecipientLink.parameters(openURLSafe(blob, key: outerKey))
        } catch { throw SharedChatRecipientError.invalidLink }
        guard let keyValue = values["chat_encryption_key"], !keyValue.isEmpty,
              let generated = Int(values["generated_at"] ?? ""), generated >= 0,
              let duration = Int(values["duration_seconds"] ?? ""), duration >= 0,
              let flag = values["pwd"], ["0", "1"].contains(flag) else { throw SharedChatRecipientError.invalidLink }
        // Web checks password presence before expiry, and accepts the exact expiry second.
        if flag == "1", password?.isEmpty != false { throw SharedChatRecipientError.passwordRequired }
        let (expiry, overflow) = generated.addingReportingOverflow(duration)
        guard !overflow else { throw SharedChatRecipientError.invalidLink }
        if duration > 0, serverTime > expiry { throw SharedChatRecipientError.expired }
        var rawKey = keyValue
        if flag == "1", let password {
            do {
                let passwordKey = try await CryptoManager.shared.deriveWrappingKeyFromPassword(
                    password: password, salt: Data("openmates-pwd-\(id)".utf8))
                rawKey = try openURLSafe(keyValue, key: passwordKey)
            } catch { throw SharedChatRecipientError.invalidPassword }
        }
        guard let bytes = Data(base64Encoded: rawKey), bytes.count == 32 else { throw SharedChatRecipientError.invalidLink }
        return SymmetricKey(data: bytes)
    }

    private static func openURLSafe(_ value: String, key: SymmetricKey) throws -> String {
        guard value.utf8.count <= 131_072,
              value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else {
            throw SharedChatRecipientError.invalidLink
        }
        var encoded = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
        guard let bytes = Data(base64Encoded: encoded), bytes.count >= 28,
              let text = String(data: try AES.GCM.open(AES.GCM.SealedBox(combined: bytes), using: key), encoding: .utf8) else {
            throw SharedChatRecipientError.invalidLink
        }
        return text
    }
}
