// Portable public text-only inference seam. No authenticated APIClient, cookies,
// paired identity, account keys, private cache or WebSocket dependencies.
// Source: backend/core/api/app/routes/anonymous.py (pinned 78e8d990).
import Foundation
import CryptoKit

// Canonical exact HTTPS API origin; public configuration carries no identity.
struct AnonymousPublicOrigin: Equatable, Sendable {
    let url: URL
    var identifier: String { url.absoluteString }
    var namespace: String { SHA256.hash(data: Data(identifier.utf8)).map { String(format: "%02x", $0) }.joined() }
    static let production = try! AnonymousPublicOrigin(URL(string: "https://api.openmates.org")!)
    init(_ url: URL) throws {
        guard var parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/" else { throw AnonymousPublicChatError.invalidDraft }
        parts.host = host.lowercased(); parts.path = ""
        guard let canonical = parts.url else { throw AnonymousPublicChatError.invalidDraft }
        self.url = canonical
    }
}

struct AnonymousPublicBudget: Decodable, Sendable {
    let active: Bool
    let canSendText: Bool
    let dailyRemainingPercent: Int?
    let resetAt: String?
    enum CodingKeys: String, CodingKey {
        case active, canSendText = "can_send_text", dailyRemainingPercent = "daily_remaining_percent", resetAt = "reset_at"
    }
}

struct AnonymousPublicTurn: Encodable, Sendable {
    struct History: Codable, Equatable, Sendable {
        let role: String
        let content: String
        let createdAt: Int
        enum CodingKeys: String, CodingKey { case role, content, createdAt = "created_at" }
    }
    let anonymousID: String
    let chatID: String
    let messageID: String
    let text: String
    let history: [History]
    enum CodingKeys: String, CodingKey {
        case anonymousID = "anonymous_id", chatID = "client_chat_id", messageID = "client_message_id"
        case text = "plaintext_message", history = "message_history"
    }
}

struct AnonymousPublicAnswer: Decodable, Sendable {
    let status: String
    let chatId: String
    let messageId: String
    let assistant: String
}

enum AnonymousPublicChatError: Error {
    case rejected(Int), invalidResponse, responseTooLarge, localStorage, invalidDraft
}

@MainActor
protocol AnonymousPublicChatTransport {
    func budget(anonymousID: String) async throws -> AnonymousPublicBudget
    func send(_ turn: AnonymousPublicTurn) async throws -> AnonymousPublicAnswer
}

@MainActor
final class AnonymousPublicHTTPTransport: AnonymousPublicChatTransport {
    // Public origin is explicitly injected from existing server configuration.
    // Never redirect an anonymous plaintext request to another origin.
    private final class NoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
    }
    private let session: URLSession
    private let baseURL: URL
    private let isCurrentOrigin: @MainActor () -> Bool
    init(origin: AnonymousPublicOrigin = .production, isCurrentOrigin: @escaping @MainActor () -> Bool = { true }) {
        self.baseURL = origin.url
        self.isCurrentOrigin = isCurrentOrigin
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 90
        session = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
    }
    static func request(baseURL: URL, path: String, anonymousID: String, body: Data? = nil) throws -> URLRequest {
        let origin = try AnonymousPublicOrigin(baseURL)
        guard !anonymousID.isEmpty, anonymousID.count <= 128 else { throw AnonymousPublicChatError.invalidDraft }
        var request = URLRequest(url: origin.url.appendingPathComponent("v1/anonymous/" + path))
        request.httpMethod = body == nil ? "GET" : "POST"
        request.httpBody = body
        request.httpShouldHandleCookies = false
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(anonymousID, forHTTPHeaderField: "X-OpenMates-Anonymous-ID")
        return request
    }
    func budget(anonymousID: String) async throws -> AnonymousPublicBudget {
        try await read(try Self.request(baseURL: baseURL, path: "free-usage/status", anonymousID: anonymousID))
    }
    func send(_ turn: AnonymousPublicTurn) async throws -> AnonymousPublicAnswer {
        guard !turn.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              turn.text.count <= 20_000, turn.history.count <= 50 else { throw AnonymousPublicChatError.invalidDraft }
        return try await read(try Self.request(baseURL: baseURL, path: "chat/stream", anonymousID: turn.anonymousID,
                                              body: JSONEncoder().encode(turn)))
    }
    private func read<T: Decodable>(_ request: URLRequest) async throws -> T {
        guard isCurrentOrigin(), !Task.isCancelled else { throw CancellationError() }
        let (bytes, response) = try await session.bytes(for: request)
        guard isCurrentOrigin(), !Task.isCancelled else { throw CancellationError() }
        guard let response = response as? HTTPURLResponse else { throw AnonymousPublicChatError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else { throw AnonymousPublicChatError.rejected(response.statusCode) }
        guard response.mimeType == "application/json" else { throw AnonymousPublicChatError.invalidResponse }
        var data = Data()
        for try await byte in bytes {
            guard isCurrentOrigin(), !Task.isCancelled else { throw CancellationError() }
            guard data.count < 512 * 1024 else { throw AnonymousPublicChatError.responseTooLarge }
            data.append(byte)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
