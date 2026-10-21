// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.payload.privacy-safe, apple-notifications.action.routing-coherent, apple-notifications.delivery.idempotent-visible, apple-notifications.action.direct-reply
// Shared notification routing only. The content extension never decrypts previews,
// reads cached users, contacts the network, or owns the normal chat send pipeline.

import CryptoKit
import Foundation
import Security

struct NotificationReplyContext: Codable, Equatable {
    struct Workspace: Codable, Equatable {
        let kind: String
        let hashedTeamID: String?
        enum CodingKeys: String, CodingKey { case kind; case hashedTeamID = "hashed_team_id" }

        var isValid: Bool {
            if kind == "personal" { return hashedTeamID == nil }
            guard kind == "team", let hash = hashedTeamID else { return false }
            return hash.count == 64 && hash.allSatisfy { "0123456789abcdef".contains($0) }
        }
        func matches(teamID: String?) -> Bool {
            guard isValid else { return false }
            if kind == "personal" { return teamID == nil }
            guard let teamID else { return false }
            return hashedTeamID == NotificationReplyStore.digest(Data(teamID.utf8))
        }
    }
    let version: Int
    let registrationContextID: String
    let recipientAccountID: String
    let notificationID: String
    let chatID: String
    let messageID: String
    let workspace: Workspace
    enum CodingKeys: String, CodingKey {
        case version, workspace
        case registrationContextID = "registration_context_id"
        case recipientAccountID = "recipient_account_id"
        case notificationID = "notification_id"
        case chatID = "chat_id"
        case messageID = "message_id"
    }
    var isValid: Bool {
        version == 1 && Self.canonicalUUID(registrationContextID, version: "4") &&
        Self.canonicalUUID(recipientAccountID) && Self.canonicalUUID(notificationID) &&
        Self.canonicalUUID(chatID) && Self.canonicalUUID(messageID) && workspace.isValid
    }
    static func canonicalUUID(_ value: String, version: Character? = nil) -> Bool {
        guard let uuid = UUID(uuidString: value), uuid.uuidString.lowercased() == value,
              uuid != UUID(uuid: (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)) else { return false }
        return version == nil || Array(value)[14] == version
    }
}

struct NotificationReplyBinding: Codable, Equatable {
    let registrationContextID: String
    let accountID: String
    let serverURL: String
    let keyFingerprint: String

    func isAcknowledged(by response: [String: Any]) -> Bool {
        response["success"] as? Bool == true && response["reply_context_id"] as? String == registrationContextID
    }

    func permits(_ context: NotificationReplyContext) -> Bool {
        context.isValid && registrationContextID == context.registrationContextID && accountID == context.recipientAccountID
    }
}

struct NotificationReplyTarget: Codable, Equatable {
    let requestID: String
    let payloadDigest: String
    let binding: NotificationReplyBinding
    let context: NotificationReplyContext
}

struct NotificationReplySubmission: Codable, Equatable {
    let target: NotificationReplyTarget
    let content: String
    var id: String { "notification-reply-" + NotificationReplyStore.digest(Data((target.requestID + "\u{0}" + target.payloadDigest).utf8)) }
}

enum NotificationReplyStoreError: Error { case invalidContext, conflictingSubmission, unavailable }

/// A separate service confines notification policy without changing global key
/// accessibility. Records never synchronize. SecItemAdd gives handoff records
/// immutable create-once semantics across processes and duplicate Send callbacks.
struct NotificationReplyStore {
    struct Operations {
        var copy: ([CFString: Any]) -> (OSStatus, Any?)
        var add: ([CFString: Any]) -> OSStatus
        var delete: ([CFString: Any]) -> OSStatus
        static var live: Operations { Operations(copy: { query in
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result)
        }, add: { SecItemAdd($0 as CFDictionary, nil) }, delete: { SecItemDelete($0 as CFDictionary) }) }
    }
    var accessGroup: String? = KeychainHelper.queryAccessGroup
    var operations: Operations = .live
    private static let service = "org.openmates.notification-reply.v1"
    private static let registrationKey = "registration"
    private static let unlockedKey = "editor-unlocked"

    static func digest(_ bytes: Data) -> String {
        SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
    static func payloadDigest(userInfo: [AnyHashable: Any]) -> String? {
        // Remote records bind the entire authenticated ciphertext; local records
        // use an app-generated marker and are created by the app before add().
        let object: [String: Any]
        if let encrypted = userInfo["encrypted_notification"] as? [String: Any] { object = encrypted }
        else if let marker = userInfo["openmates_local_reply_context"] as? String,
                NotificationReplyContext.canonicalUUID(marker, version: "4") { object = ["local": marker] }
        else { return nil }
        guard let bytes = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return nil }
        return digest(bytes)
    }
    private func query(_ account: String? = nil) throws -> [CFString: Any] {
        guard let accessGroup else { throw NotificationReplyStoreError.unavailable }
        var result: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: Self.service, kSecAttrAccessGroup: accessGroup,
            kSecAttrSynchronizable: false, kSecUseAuthenticationUI: kSecUseAuthenticationUIFail]
        #if os(macOS)
        result[kSecUseDataProtectionKeychain] = true
        #endif
        if let account { result[kSecAttrAccount] = account }
        return result
    }
    private func read<T: Decodable>(_ key: String, as: T.Type) throws -> T? {
        var request = try query(key)
        request[kSecReturnData] = true; request[kSecMatchLimit] = kSecMatchLimitOne
        let (status, result) = operations.copy(request)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let bytes = result as? Data else { throw NotificationReplyStoreError.unavailable }
        return try JSONDecoder().decode(T.self, from: bytes)
    }
    private func insert<T: Codable & Equatable>(_ value: T, key: String, unlocked: Bool) throws {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        var insertion = try query(key)
        insertion[kSecValueData] = try encoder.encode(value)
        insertion[kSecAttrAccessible] = unlocked ? kSecAttrAccessibleWhenUnlockedThisDeviceOnly : kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = operations.add(insertion)
        if status == errSecDuplicateItem {
            guard try read(key, as: T.self) == value else { throw NotificationReplyStoreError.conflictingSubmission }
        } else if status != errSecSuccess { throw NotificationReplyStoreError.unavailable }
    }
    func revoke() {
        guard let request = try? query() else { return }
        _ = operations.delete(request)
    }
    /// Called only after the containing app receives the authenticated durable
    /// register-device ACK and confirms that its captured generation is current.
    func acknowledge(_ binding: NotificationReplyBinding) throws {
        guard NotificationReplyContext.canonicalUUID(binding.registrationContextID, version: "4"),
              NotificationReplyContext.canonicalUUID(binding.accountID),
              !binding.serverURL.isEmpty, binding.keyFingerprint.count == 64 else { throw NotificationReplyStoreError.invalidContext }
        try insert(binding, key: Self.registrationKey, unlocked: false)
        do { try insert(binding, key: Self.unlockedKey, unlocked: true) }
        catch { revoke(); throw error }
    }
    func registration() throws -> NotificationReplyBinding? { try read(Self.registrationKey, as: NotificationReplyBinding.self) }
    func unlockedBinding() throws -> NotificationReplyBinding? {
        guard let binding = try registration(), try read(Self.unlockedKey, as: NotificationReplyBinding.self) == binding else { return nil }
        return binding
    }
    private func submissionID(requestID: String, payloadDigest: String) -> String {
        "notification-reply-" + Self.digest(Data((requestID + "\u{0}" + payloadDigest).utf8))
    }
    private func isCompleted(requestID: String, payloadDigest: String) throws -> Bool {
        try read("completed-" + submissionID(requestID: requestID, payloadDigest: payloadDigest), as: Bool.self) == true
    }
    /// Written only after the normal send pipeline confirms its remote durable
    /// ACK. Retained for the same lifetime as the immutable replay record, rather
    /// than relying on the containing ledger's bounded recent-completion list.
    func complete(_ target: NotificationReplyTarget) throws {
        let id = submissionID(requestID: target.requestID, payloadDigest: target.payloadDigest)
        try insert(true, key: "completed-" + id, unlocked: false)
        // The durable tombstone outlives replay data. Remove acknowledged text
        // promptly; a failed cleanup cannot restore editor/replay eligibility.
        _ = operations.delete(try query(id))
        _ = operations.delete(try query(targetKey(requestID: target.requestID, digest: target.payloadDigest)))
    }
    private func targetKey(requestID: String, digest: String) -> String {
        "target-" + Self.digest(Data((requestID + "\u{0}" + digest).utf8))
    }
    func saveValidatedTarget(_ context: NotificationReplyContext, requestID: String, payloadDigest: String,
                             keyFingerprint: String) throws {
        guard !requestID.isEmpty, payloadDigest.count == 64, let binding = try registration(),
              binding.permits(context), binding.keyFingerprint == keyFingerprint else { throw NotificationReplyStoreError.invalidContext }
        let target = NotificationReplyTarget(requestID: requestID, payloadDigest: payloadDigest, binding: binding, context: context)
        try insert(target, key: targetKey(requestID: requestID, digest: payloadDigest), unlocked: false)
    }
    func validatedTarget(requestID: String, payloadDigest: String, requireUnlocked: Bool = true) throws -> NotificationReplyTarget? {
        let binding = try (requireUnlocked ? unlockedBinding() : registration())
        guard let binding, try !isCompleted(requestID: requestID, payloadDigest: payloadDigest),
              let target = try read(targetKey(requestID: requestID, digest: payloadDigest), as: NotificationReplyTarget.self),
              target.requestID == requestID, target.payloadDigest == payloadDigest,
              target.binding == binding, binding.permits(target.context) else { return nil }
        return target
    }
    func submit(_ target: NotificationReplyTarget, content: String) throws -> NotificationReplySubmission {
        guard !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              try validatedTarget(requestID: target.requestID, payloadDigest: target.payloadDigest) == target else {
            throw NotificationReplyStoreError.invalidContext
        }
        let submission = NotificationReplySubmission(target: target, content: content)
        try insert(submission, key: submission.id, unlocked: true)
        // Revocation/locking during the write must never forward a stale target.
        guard try unlockedBinding() == target.binding else { throw NotificationReplyStoreError.invalidContext }
        return submission
    }
    func submission(requestID: String, payloadDigest: String) throws -> NotificationReplySubmission? {
        let key = submissionID(requestID: requestID, payloadDigest: payloadDigest)
        guard let result = try read(key, as: NotificationReplySubmission.self),
              try validatedTarget(requestID: requestID, payloadDigest: payloadDigest) == result.target else { return nil }
        return result
    }
    /// Recovers an explicit Send if the extension/app dies between forwarding and
    /// ledger persistence. Never consumes a submission before durable ledger ACK.
    func submissions() throws -> [NotificationReplySubmission] {
        guard let binding = try unlockedBinding() else { return [] }
        var request = try query(); request[kSecReturnAttributes] = true; request[kSecReturnData] = true
        request[kSecMatchLimit] = kSecMatchLimitAll
        let (status, result) = operations.copy(request)
        if status == errSecItemNotFound { return [] }
        guard status == errSecSuccess, let rows = result as? [[CFString: Any]] else { throw NotificationReplyStoreError.unavailable }
        return try rows.compactMap { row in
            guard let key = row[kSecAttrAccount] as? String, key.hasPrefix("notification-reply-"),
                  let bytes = row[kSecValueData] as? Data else { return nil }
            let submission = try JSONDecoder().decode(NotificationReplySubmission.self, from: bytes)
            guard key == submission.id, submission.target.binding == binding,
                  try validatedTarget(requestID: submission.target.requestID, payloadDigest: submission.target.payloadDigest) == submission.target else { return nil }
            return submission
        }
    }
}
