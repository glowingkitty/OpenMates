// Watch push identity and routing fences, independent of the iOS auth graph.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle, apple-notifications.action.routing-coherent
import Foundation

struct WatchPushIdentity: Codable, Equatable {
    let accountID: String
    let serverScope: String
    let generation: UInt64

    func matches(accountID: String?, serverScope: String, generation: UInt64) -> Bool {
        self.accountID == accountID && self.serverScope == serverScope && self.generation == generation
    }
}

struct WatchPushRegistration: Codable, Equatable {
    let identity: WatchPushIdentity
    let token: String
    let deviceID: String

    func isCurrent(identity: WatchPushIdentity?, token: String?, permission: Bool, online: Bool) -> Bool {
        permission && online && self.identity == identity && self.token == token
    }
}

enum WatchNotificationResolution: Equatable {
    case opened, unavailable, retry, stale
}

/// Local revocation is unconditional. Server removal can wait for the same
/// verified account and server without keeping OS presentation enabled.
@MainActor
final class WatchPushRevocation {
    private(set) var pendingCleanup: WatchPushRegistration?

    init(pendingCleanup: WatchPushRegistration? = nil) { self.pendingCleanup = pendingCleanup }

    func revoke(_ registration: WatchPushRegistration?, cleanupLocal: () -> Void) {
        if let registration { pendingCleanup = registration }
        cleanupLocal()
    }

    func cleanupFor(identity: WatchPushIdentity?, online: Bool) -> WatchPushRegistration? {
        guard online, let identity, let pendingCleanup,
              pendingCleanup.identity.accountID == identity.accountID,
              pendingCleanup.identity.serverScope == identity.serverScope else { return nil }
        return pendingCleanup
    }

    func acknowledge(_ registration: WatchPushRegistration) {
        if pendingCleanup == registration { pendingCleanup = nil }
    }
}

struct WatchNotificationVisibility {
    private(set) var chatID: String?
    private var identity: WatchPushIdentity?

    mutating func show(_ chatID: String?, identity: WatchPushIdentity?) {
        self.chatID = chatID
        self.identity = identity
    }

    mutating func invalidateUnlessMatching(_ identity: WatchPushIdentity?) {
        if identity == nil || self.identity != identity { show(nil, identity: nil) }
    }

    func shouldPresent(chatID: String?, identity: WatchPushIdentity?, active: Bool) -> Bool {
        WatchNotificationRoute.shouldPresent(chatID: chatID,
            viewedChatID: self.identity == identity && identity != nil ? self.chatID : nil, active: active)
    }
}

struct WatchNotificationRoute: Equatable, Identifiable {
    let id: UUID
    let chatID: String
    let identity: WatchPushIdentity

    init?(chatID: String, identity: WatchPushIdentity) {
        let chatID = chatID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !chatID.isEmpty, chatID.count <= 256,
              !chatID.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { return nil }
        self.id = UUID()
        self.chatID = chatID
        self.identity = identity
    }

    func permitsOpen(identity: WatchPushIdentity?, online: Bool) -> Bool {
        online && self.identity == identity
    }

    static func shouldPresent(chatID: String?, viewedChatID: String?, active: Bool) -> Bool {
        !(active && chatID != nil && chatID == viewedChatID)
    }
}
