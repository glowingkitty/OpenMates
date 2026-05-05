// HTTP API client for the OpenMates backend.
// Handles auth tokens, cookie-based sessions, and JSON encoding/decoding.
// Supports both Encodable bodies and raw dictionary bodies.

import Foundation

/// Wrapper for sending pre-serialized JSON data without re-encoding through JSONEncoder.
struct JSONRawBody: Encodable {
    let data: Data
    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(data)
    }
}

actor APIClient {
    static let shared = APIClient()

    static var nativeClientHeaders: [String: String] {
        [
            "User-Agent": "OpenMates-Apple/\(appVersion)",
            "X-OpenMates-Client": platformClientIdentifier,
            "X-OpenMates-Bundle-ID": bundleIdentifier,
        ]
    }

    private let session: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    private init() {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = .shared
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        self.session = URLSession(configuration: config)

        self.encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase

        self.decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    // MARK: - Configuration

    var baseURL: URL {
        #if DEBUG
        URL(string: "https://api.dev.openmates.org")!
        #else
        URL(string: "https://api.openmates.org")!
        #endif
    }

    var webAppURL: URL {
        #if DEBUG
        URL(string: "https://app.dev.openmates.org")!
        #else
        URL(string: "https://app.openmates.org")!
        #endif
    }

    // MARK: - Encodable body

    func request(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        headers: [String: String]? = nil
    ) async throws -> Data {
        var urlRequest = buildRequest(method, path: path, headers: headers)

        if let body {
            if let rawBody = body as? JSONRawBody {
                urlRequest.httpBody = rawBody.data
            } else {
                urlRequest.httpBody = try encoder.encode(body)
            }
        }

        return try await execute(urlRequest)
    }

    func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        headers: [String: String]? = nil
    ) async throws -> T {
        let data = try await request(method, path: path, body: body, headers: headers)
        return try decoder.decode(T.self, from: data)
    }

    // MARK: - Dictionary body (for ad-hoc requests without Encodable structs)

    func request(
        _ method: HTTPMethod,
        path: String,
        body dict: [String: Any],
        headers: [String: String]? = nil
    ) async throws -> Data {
        var urlRequest = buildRequest(method, path: path, headers: headers)
        urlRequest.httpBody = try JSONSerialization.data(withJSONObject: dict)
        return try await execute(urlRequest)
    }

    func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body dict: [String: Any],
        headers: [String: String]? = nil
    ) async throws -> T {
        let data: Data = try await request(method, path: path, body: dict, headers: headers)
        return try decoder.decode(T.self, from: data)
    }

    // MARK: - Private

    private func buildRequest(
        _ method: HTTPMethod,
        path: String,
        headers: [String: String]?
    ) -> URLRequest {
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let pathAndQuery = normalizedPath.split(separator: "?", maxSplits: 1).map(String.init)
        var url = baseURL.appendingPathComponent(pathAndQuery[0])
        if pathAndQuery.count == 2, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.percentEncodedQuery = pathAndQuery[1]
            url = components.url ?? url
        }
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        Self.nativeClientHeaders.forEach { key, value in
            request.setValue(value, forHTTPHeaderField: key)
        }

        if let headers {
            for (key, value) in headers {
                request.setValue(value, forHTTPHeaderField: key)
            }
        }

        return request
    }

    private static var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
    }

    private static var bundleIdentifier: String {
        Bundle.main.bundleIdentifier ?? "org.openmates.app"
    }

    private static var platformClientIdentifier: String {
        #if os(iOS)
        return "ios"
        #elseif os(macOS)
        return "macos"
        #else
        return "apple"
        #endif
    }

    private func execute(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let errorBody = try? decoder.decode(APIErrorResponse.self, from: data)
            throw APIError.httpError(
                status: httpResponse.statusCode,
                message: errorBody?.detail ?? "Request failed (\(httpResponse.statusCode))"
            )
        }

        return data
    }
}

// MARK: - Supporting types

enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case patch = "PATCH"
    case delete = "DELETE"
}

enum APIError: LocalizedError {
    case invalidResponse
    case httpError(status: Int, message: String)
    case decodingError(Error)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid server response"
        case .httpError(let status, let message):
            return "Server error (\(status)): \(message)"
        case .decodingError(let error):
            return "Data error: \(error.localizedDescription)"
        }
    }
}

struct APIErrorResponse: Decodable {
    let detail: String?
}
