// Watch adaptation of the web/iPhone encrypted chat share flow.
// Web: frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Crypto: frontend/packages/ui/src/services/shareEncryption.ts, shortUrlEncryption.ts
// No plaintext key, password or complete URL is transmitted or logged.
import CryptoKit
import Foundation

@MainActor
struct WatchChatShareDependencies {
    let key: (WatchChatSummary, WatchChatRequestContext) async throws -> SymmetricKey
    let request: (String, Data, WatchChatRequestContext) async throws -> Data

    static var live: Self {
        Self(key: { chat, context in
            try context.check()
            guard let account = context.accountID,
                  let wrapped = chat.offlineWrappedChatKey ?? chat.encryptedChatKey,
                  let master = try await CryptoManager.shared.loadMasterKey(for: account) else {
                throw WatchChatShareError.unavailable
            }
            let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: master)
            try context.check()
            return key
        }, request: { path, data, context in
            try await APIClient.shared.requestForVerifiedWatchSession(.post, path: path,
                serverProfile: context.profile, body: JSONRawBody(data: data), validate: { try context.check() })
        })
    }

#if DEBUG
    /// Only selected by an explicitly launched, account-free preview fixture.
    static var fixture: Self {
        Self(key: { _, _ in SymmetricKey(data: Data(repeating: 7, count: 32)) },
             request: { _, _, _ in Data("{\"success\":true}".utf8) })
    }
#endif
}

enum WatchChatShareError: Error { case unavailable, invalidPassword, publicationFailed }

@MainActor
enum WatchChatShareService {
    static func canShare(_ chat: WatchChatSummary) -> Bool {
        !chat.isSupportChat && !chat.isSharedRecipient && !chat.id.hasPrefix("incognito-")
            && chat.category != "onboarding_support" && chat.category != "support"
    }

    static func create(chat: WatchChatSummary, context: WatchChatRequestContext,
                       duration: ShareDuration, password: String?,
                       dependencies: WatchChatShareDependencies = .live) async throws -> URL {
        guard canShare(chat), context.accountID != nil else { throw WatchChatShareError.unavailable }
        if let password, password.isEmpty || password.count > 10 { throw WatchChatShareError.invalidPassword }
        try context.check()
        let key = try await dependencies.key(chat, context)
        try context.check()
        let blob = try await ShareLinkCrypto.encryptedShareBlob(identifier: chat.id, key: key,
            duration: duration, password: password, keyField: "chat_encryption_key")
        let longURL = try ShareLinkCrypto.urlWithFragment(context.profile.webBaseURL
            .appendingPathComponent("share/chat").appendingPathComponent(chat.id), fragment: "key=\(blob)")
        let encrypted = try await ShareLinkCrypto.encryptedShortURL(longURL)
        try context.check()
        let shortBody: [String: Any] = [
            "token": encrypted.token, "encrypted_url": encrypted.encryptedURL,
            "content_type": "chat", "content_id": chat.id,
            "password_protected": password != nil,
            "ttl_seconds": duration == .noExpiration ? NSNull() : duration.rawValue
        ]
        try await publish("/v1/share/short-url", body: shortBody, context: context, dependencies: dependencies)
        try context.check()
        let url = try ShareLinkCrypto.shortURL(webURL: context.profile.webBaseURL, token: encrypted.token, shortKey: encrypted.shortKey)
        let stored = try await CryptoManager.shared.encryptContent(url.absoluteString, key: key)
        try context.check()
        let metadata: [String: Any] = [
            "chat_id": chat.id, "title": chat.title ?? NSNull(), "summary": chat.preview ?? NSNull(),
            "category": chat.category ?? NSNull(), "icon": chat.icon ?? NSNull(),
            "is_shared": true, "share_pii": false, "share_highlights": false,
            "encrypted_shared_short_url": stored
        ]
        try await publish("/v1/share/chat/metadata", body: metadata, context: context, dependencies: dependencies)
        try context.check()
        return url
    }

    private static func publish(_ path: String, body: [String: Any], context: WatchChatRequestContext,
                                dependencies: WatchChatShareDependencies) async throws {
        try context.check()
        let data = try await dependencies.request(path, JSONSerialization.data(withJSONObject: body), context)
        try context.check()
        guard let result = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              result["success"] as? Bool == true else { throw WatchChatShareError.publicationFailed }
    }
}
