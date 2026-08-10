// Lightweight wrapper for heterogeneous JSON values.
// Used throughout the app for parsing untyped API responses,
// WebSocket messages, and embed data dictionaries.

import Foundation

struct AnyCodable: Decodable, @unchecked Sendable {
    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map(\.value)
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues(\.value)
        } else {
            value = NSNull()
        }
    }
}

extension AnyCodable: Encodable {
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }
}

extension AnyCodable: Equatable {
    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        valuesEqual(lhs.value, rhs.value)
    }

    private static func valuesEqual(_ lhs: Any, _ rhs: Any) -> Bool {
        switch (lhs, rhs) {
        case (_ as NSNull, _ as NSNull):
            return true
        case let (lhs as Bool, rhs as Bool):
            return lhs == rhs
        case let (lhs as Int, rhs as Int):
            return lhs == rhs
        case let (lhs as Double, rhs as Double):
            return lhs == rhs
        case let (lhs as Int, rhs as Double):
            return Double(lhs) == rhs
        case let (lhs as Double, rhs as Int):
            return lhs == Double(rhs)
        case let (lhs as String, rhs as String):
            return lhs == rhs
        case let (lhs as [Any], rhs as [Any]):
            guard lhs.count == rhs.count else { return false }
            return zip(lhs, rhs).allSatisfy(valuesEqual)
        case let (lhs as [String: Any], rhs as [String: Any]):
            guard lhs.keys == rhs.keys else { return false }
            return lhs.allSatisfy { key, value in
                guard let rhsValue = rhs[key] else { return false }
                return valuesEqual(value, rhsValue)
            }
        default:
            return false
        }
    }
}
