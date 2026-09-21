import Foundation
import CryptoKit

// Matches web updateProfile -> userDB local preferences, not a server endpoint.
@MainActor final class NativeModelDisabledPreferences {
    struct Value: Codable, Equatable {
        var disabled_ai_models: Set<String> = []
        var disabled_ai_servers: [String: Set<String>] = [:]
    }
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    private func key(server: String, user: String) -> String {
        let data = Data((server + "\u{0}" + user).utf8)
        return "model-disabled." + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    func read(server: String, user: String) -> Value {
        guard let data = defaults.data(forKey: key(server: server, user: user)), let value = try? JSONDecoder().decode(Value.self, from: data) else { return Value() }
        return value
    }
    func write(_ value: Value, server: String, user: String) throws {
        defaults.set(try JSONEncoder().encode(value), forKey: key(server: server, user: user))
    }
}
