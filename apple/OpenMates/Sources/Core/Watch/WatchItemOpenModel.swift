// Minimal Watch-to-iPhone item handoff. Item content and URLs stay on the
// receiving device; this payload carries only the kind and opaque server ID.

import Foundation

struct WatchItemOpenRequest: Equatable, Sendable {
    enum Kind: String, Sendable {
        case task
        case workflow
    }

    let kind: Kind
    let id: String

    init?(kind: Kind, id: String) {
        guard Self.isValidID(id) else { return nil }
        self.kind = kind
        self.id = id
    }

    var payload: [String: String] {
        ["kind": kind.rawValue, "id": id]
    }

    static func parse(_ payload: [String: Any]) -> WatchItemOpenRequest? {
        guard let rawKind = payload["kind"] as? String,
              let kind = Kind(rawValue: rawKind),
              let id = payload["id"] as? String else { return nil }
        return WatchItemOpenRequest(kind: kind, id: id)
    }

    private static func isValidID(_ id: String) -> Bool {
        guard !id.isEmpty, id.count <= 256,
              id == id.trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
        return !id.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
    }
}
