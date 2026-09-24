// Watch-to-phone web handoff. Only opaque IDs cross Watch Connectivity;
// the phone derives the destination from its own selected server profile.

import Foundation

enum WatchPhoneOpenPayload: Equatable {
    case item(WatchItemOpenRequest, serverProfileId: String)
    case collection(WatchItemOpenRequest.Kind, serverProfileId: String)
    case settings(serverProfileId: String)

    private static let kindKey = "kind"
    private static let itemKindKey = "item_kind"
    private static let itemIdKey = "item_id"
    private static let serverProfileIdKey = "server_profile_id"
    private static let itemKind = "openmates.watch.item_open.request"
    private static let collectionKind = "openmates.watch.collection_open.request"
    private static let settingsKind = "openmates.watch.settings_open.request"

    var message: [String: Any] {
        switch self {
        case .item(let request, let profileId):
            return [Self.kindKey: Self.itemKind,
                    Self.itemKindKey: request.kind.rawValue,
                    Self.itemIdKey: request.id,
                    Self.serverProfileIdKey: profileId]
        case .collection(let collection, let profileId):
            return [Self.kindKey: Self.collectionKind,
                    Self.itemKindKey: collection.rawValue,
                    Self.serverProfileIdKey: profileId]
        case .settings(let profileId):
            return [Self.kindKey: Self.settingsKind,
                    Self.serverProfileIdKey: profileId]
        }
    }

    static func parse(_ message: [String: Any]) -> WatchPhoneOpenPayload? {
        guard let kind = message[kindKey] as? String,
              let profileId = message[serverProfileIdKey] as? String,
              !profileId.isEmpty else { return nil }
        switch kind {
        case itemKind:
            guard Set(message.keys) == Set([kindKey, itemKindKey, itemIdKey, serverProfileIdKey]),
                  let rawItemKind = message[itemKindKey] as? String,
                  let itemKind = WatchItemOpenRequest.Kind(rawValue: rawItemKind),
                  let itemId = message[itemIdKey] as? String,
                  let request = WatchItemOpenRequest(kind: itemKind, id: itemId) else { return nil }
            return .item(request, serverProfileId: profileId)
        case collectionKind:
            guard Set(message.keys) == Set([kindKey, itemKindKey, serverProfileIdKey]),
                  let rawItemKind = message[itemKindKey] as? String,
                  let collection = WatchItemOpenRequest.Kind(rawValue: rawItemKind),
                  message[itemIdKey] == nil else { return nil }
            return .collection(collection, serverProfileId: profileId)
        case settingsKind:
            guard Set(message.keys) == Set([kindKey, serverProfileIdKey]) else { return nil }
            return .settings(serverProfileId: profileId)
        default:
            return nil
        }
    }

    var serverProfileId: String {
        switch self {
        case .item(_, let profileId), .collection(_, let profileId), .settings(let profileId): return profileId
        }
    }

    func destination(currentProfile: ServerProfile) -> URL? {
        guard serverProfileId == currentProfile.id,
              currentProfile.webBaseURL.scheme == "https",
              currentProfile.webBaseURL.host != nil else { return nil }
        let base = currentProfile.webBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        switch self {
        case .item(let request, _):
            let encodedId = Self.encodeURIComponent(request.id)
            switch request.kind {
            case .task: return URL(string: "\(base)/tasks/\(encodedId)")
            case .workflow: return URL(string: "\(base)/workflows#workflow-id=\(encodedId)&workflow-tab=details")
            }
        case .collection(let collection, _):
            switch collection {
            case .task: return URL(string: "\(base)/tasks")
            case .workflow: return URL(string: "\(base)/workflows")
            }
        case .settings:
            return URL(string: "\(base)/#settings")
        }
    }

    // Encode UTF-8 bytes using the same unescaped set as encodeURIComponent.
    // In particular, '/', '?', '#', and '%' never become URL syntax.
    private static func encodeURIComponent(_ value: String) -> String {
        let hex = Array("0123456789ABCDEF".utf8)
        var result = ""
        for byte in value.utf8 {
            if (65...90).contains(byte) || (97...122).contains(byte) ||
                (48...57).contains(byte) || [45, 95, 46, 33, 126, 42, 39, 40, 41].contains(byte) {
                result.append(Character(UnicodeScalar(byte)))
            } else {
                result.append("%")
                result.append(Character(UnicodeScalar(hex[Int(byte >> 4)])))
                result.append(Character(UnicodeScalar(hex[Int(byte & 15)])))
            }
        }
        return result
    }
}
