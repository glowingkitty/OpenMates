// HTTP API client for the OpenMates backend.
// Handles auth tokens, cookie-based sessions, and JSON encoding/decoding.
// Supports both Encodable bodies and raw dictionary bodies.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.embeds.gated-send
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation

import Foundation

/// Wrapper for sending pre-serialized JSON data without re-encoding through JSONEncoder.
struct JSONRawBody: Encodable, Sendable {
    let data: Data
    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(data)
    }
}

struct APIRequestTeamContext: Sendable {
    let epoch: UInt64
    let teamID: String?
}

/// Metadata only. Never use a ciphertext GET to decide reference readiness.
enum EmbedReferenceAvailabilityState: String, Sendable {
    case ready, missing, unusable
}

actor APIClient {
    static let shared = APIClient()

    static let uploadTimeout: TimeInterval = 10 * 60

    static var nativeClientHeaders: [String: String] {
        [
            "User-Agent": "OpenMates-Apple/\(appVersion)",
            "X-OpenMates-Client": platformClientIdentifier,
            "X-OpenMates-Bundle-ID": bundleIdentifier,
        ]
    }

    private let session: URLSession
    private let uploadSession: URLSession
    private let cookieStorage: HTTPCookieStorage
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(session: URLSession? = nil, uploadSession: URLSession? = nil, cookieStorage: HTTPCookieStorage = OpenMatesSharedEnvironment.cookieStorage) {
        self.cookieStorage = cookieStorage
        self.session = session ?? URLSession(configuration: Self.makeStandardSessionConfiguration())
        self.uploadSession = uploadSession ?? URLSession(configuration: Self.makeUploadSessionConfiguration())

        self.encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase

        self.decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    /// The availability endpoint is verified on deployed dev 8addcd7 only.
    /// Production/custom profiles retain their explicitly supported legacy path.
    nonisolated static func supportsEmbedReferenceAvailability(_ profile: ServerProfile) -> Bool {
        profile == .development
    }

    nonisolated static func embedReferenceAvailabilityPath(chatID: String, teamID: String?) throws -> String {
        guard !chatID.isEmpty, chatID.utf8.count <= 512,
              !chatID.contains(where: { "/?#%".contains($0) }) else { throw APIError.invalidResponse }
        let path = "/v1/embeds/chats/\(chatID)/references/availability"
        guard let teamID else { return path }
        guard !teamID.isEmpty else { throw APIError.invalidResponse }
        var query = URLComponents()
        query.queryItems = [URLQueryItem(name: "team_id", value: teamID)]
        guard let encoded = query.percentEncodedQuery else { throw APIError.invalidResponse }
        return path + "?" + encoded.replacingOccurrences(of: "+", with: "%2B")
    }

    nonisolated static func embedReferenceAvailabilityBody(_ ids: [String]) throws -> Data {
        guard !ids.isEmpty, ids.count <= 20, Set(ids).count == ids.count,
              ids.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }) else { throw APIError.invalidResponse }
        let json = try JSONSerialization.data(withJSONObject: ["embed_ids": ids], options: [.sortedKeys])
        // 8add measures Python's ASCII-escaped JSON, not just incoming UTF-8.
        // Escape UTF-16 code units so Unicode IDs also honor that exact bound.
        var escaped = ""
        for unit in String(decoding: json, as: UTF8.self).utf16 {
            if unit >= 127 { escaped += String(format: "\\u%04x", Int(unit)) }
            else { escaped.unicodeScalars.append(UnicodeScalar(UInt32(unit))!) }
        }
        let body = Data(escaped.utf8)
        guard body.count <= 4 * 1024 else { throw APIError.invalidResponse }
        return body
    }

    nonisolated static func embedReferenceAvailabilityBatches(_ ids: [String]) throws -> [[String]] {
        guard Set(ids).count == ids.count,
              ids.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }) else { throw APIError.invalidResponse }
        var batches: [[String]] = []
        var batch: [String] = []
        for id in ids {
            if (try? embedReferenceAvailabilityBody(batch + [id])) == nil {
                guard !batch.isEmpty else { throw APIError.invalidResponse }
                batches.append(batch)
                batch = []
            }
            batch.append(id)
            _ = try embedReferenceAvailabilityBody(batch)
        }
        if !batch.isEmpty { batches.append(batch) }
        return batches
    }

    nonisolated static func decodeEmbedReferenceAvailability(_ data: Data, requestedIDs: [String]) throws
        -> [String: EmbedReferenceAvailabilityState] {
        _ = try embedReferenceAvailabilityBody(requestedIDs)
        guard data.count <= 8 * 1024,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["results"], let results = object["results"] as? [[String: Any]],
              results.count == requestedIDs.count else { throw APIError.invalidResponse }
        let requested = Set(requestedIDs)
        var states: [String: EmbedReferenceAvailabilityState] = [:]
        for result in results {
            guard Set(result.keys) == ["embed_id", "state"],
                  let id = result["embed_id"] as? String, requested.contains(id), states[id] == nil,
                  let raw = result["state"] as? String, let state = EmbedReferenceAvailabilityState(rawValue: raw)
            else { throw APIError.invalidResponse }
            states[id] = state
        }
        guard Set(states.keys) == requested else { throw APIError.invalidResponse }
        return states
    }

    func embedReferenceAvailability(chatID: String, embedIDs: [String], serverProfile: ServerProfile,
                                   expectedAccountID: String, expectedScope: UUID,
                                   expectedTeamContext: APIRequestTeamContext) async throws
        -> [String: EmbedReferenceAvailabilityState] {
        let path = try Self.embedReferenceAvailabilityPath(chatID: chatID, teamID: expectedTeamContext.teamID)
        let batches = try Self.embedReferenceAvailabilityBatches(embedIDs)
        var states: [String: EmbedReferenceAvailabilityState] = [:]
        for batch in batches {
            let response: Data = try await request(.post, path: path, serverProfile: serverProfile,
                body: JSONRawBody(data: try Self.embedReferenceAvailabilityBody(batch)),
                expectedAccountID: expectedAccountID, expectedScope: expectedScope,
                expectedTeamContext: expectedTeamContext)
            // A response from a revoked Team/account must not authorize a send.
            try await checkUploadContext(accountID: expectedAccountID, scope: expectedScope, profile: serverProfile)
            try await checkTeamContext(expectedTeamContext)
            try Task.checkCancellation()
            for (id, state) in try Self.decodeEmbedReferenceAvailability(response, requestedIDs: batch) {
                guard states[id] == nil else { throw APIError.invalidResponse }
                states[id] = state
            }
        }
        return states
    }

    // MARK: - Configuration

    var baseURL: URL {
        ServerConfiguration.current.apiBaseURL
    }

    var webAppURL: URL {
        ServerConfiguration.current.webAppURL
    }

    var uploadBaseURL: URL {
        ServerConfiguration.current.uploadBaseURL
    }

    func uploadFile(
        data: Data,
        filename: String,
        contentType: String,
        chatId: String
    ) async throws -> Data {
        try await uploadFile(data: data, filename: filename, contentType: contentType,
                             optionalChatID: chatId)
    }

    /// Hosted Project imports create an independently keyed embed and therefore
    /// omit chat_id, matching uploadFileToProject's multipart contract.
    func uploadProjectFile(data: Data, filename: String, contentType: String,
                           serverProfile: ServerProfile? = nil,
                           expectedAccountID: String? = nil, expectedScope: UUID? = nil) async throws -> Data {
        try await uploadFile(data: data, filename: filename, contentType: contentType,
                             optionalChatID: nil, serverProfile: serverProfile,
                             expectedAccountID: expectedAccountID, expectedScope: expectedScope)
    }

    private func uploadFile(data: Data, filename: String, contentType: String,
                            optionalChatID: String?, serverProfile: ServerProfile? = nil,
                            expectedAccountID: String? = nil, expectedScope: UUID? = nil) async throws -> Data {
        #if os(watchOS)
        let capturedAccountID = expectedAccountID
        let scope = expectedScope ?? UUID()
        #else
        let accountID = await AuthManager.currentUserId()
        let capturedAccountID = expectedAccountID ?? accountID
        let scope = await MainActor.run { expectedScope ?? OfflineStore.shared.scopeGeneration }
        #endif
        let boundary = UUID().uuidString
        #if os(iOS) || os(macOS)
        // Strip source image metadata before constructing any outbound bytes.
        // Filenames remain exact, including Project/workflow relative paths.
        let prepared = try NativeImageRaster.prepareUpload(data: data, filename: filename, contentType: contentType)
        let body = try Self.makeUploadBody(data: prepared.data, filename: prepared.filename,
            contentType: prepared.contentType, chatID: optionalChatID, boundary: boundary)
        #else
        let body = try Self.makeUploadBody(data: data, filename: filename,
            contentType: contentType, chatID: optionalChatID, boundary: boundary)
        #endif
        // Check the account immediately before each attempt: a refreshed cookie
        // must never upload the previous account's private file bytes.
        let profile = serverProfile ?? ServerProfile.current()
        let uploadURL = profile.uploadBaseURL.appendingPathComponent("v1/upload/file")
        let authenticationURL = profile.apiBaseURL
        let originURL = profile.webBaseURL

        try await checkUploadContext(accountID: capturedAccountID, scope: scope, profile: profile)
        let request = Self.makeUploadRequest(
            uploadURL: uploadURL,
            authenticationURL: authenticationURL,
            webAppURL: originURL,
            boundary: boundary,
            body: body,
            pinCookies: optionalChatID == nil
        )
        try await checkUploadContext(accountID: capturedAccountID, scope: scope, profile: profile)
        try Task.checkCancellation()
        do {
            // A retry must use the credential produced by recovery, rather
            // than race the ordinary request's background validation.
            return try await execute(request, using: uploadSession, awaitUnauthorizedRecovery: true)
        } catch where Self.shouldRetryUpload(after: error) {
            try await checkUploadContext(accountID: capturedAccountID, scope: scope, profile: profile)
            let retryRequest = Self.makeUploadRequest(
                uploadURL: uploadURL,
                authenticationURL: authenticationURL,
                webAppURL: originURL,
                boundary: boundary,
                body: body,
                pinCookies: optionalChatID == nil
            )
            try await checkUploadContext(accountID: capturedAccountID, scope: scope, profile: profile)
            try Task.checkCancellation()
            return try await execute(retryRequest, using: uploadSession)
        }
    }

    private func checkUploadContext(accountID: String?, scope: UUID, profile: ServerProfile) async throws {
        #if os(watchOS)
        // Project imports and their desktop/phone account fences are unavailable
        // in Watch. Keep the existing Watch transport bound to its service.
        guard accountID == nil, profile.apiBaseURL == ServerProfile.current().apiBaseURL,
              profile.uploadBaseURL == ServerProfile.current().uploadBaseURL else { throw CancellationError() }
        #else
        let currentAccountID = await AuthManager.currentUserId()
        let matches = await MainActor.run {
            Self.isUploadContextCurrent(expectedAccountID: accountID, currentAccountID: currentAccountID,
                expectedScope: scope, currentScope: OfflineStore.shared.scopeGeneration,
                serverProfile: profile, currentProfile: ServerProfile.current())
        }
        guard matches else { throw CancellationError() }
        #endif
    }

    private func checkTeamContext(_ expected: APIRequestTeamContext?) async throws {
        #if os(iOS) || os(macOS)
        guard let expected else { return }
        let matches = await MainActor.run {
            TeamWorkspaceContext.shared.contextEpoch == expected.epoch &&
                TeamWorkspaceContext.shared.teamID == expected.teamID
        }
        guard matches else { throw CancellationError() }
        #else
        // Watch has no Team workspace. Refuse a Team-scoped request there.
        guard expected == nil else { throw CancellationError() }
        #endif
    }

    static func isUploadContextCurrent(expectedAccountID: String?, currentAccountID: String?,
        expectedScope: UUID, currentScope: UUID, serverProfile: ServerProfile,
        currentProfile: ServerProfile) -> Bool {
        expectedAccountID == currentAccountID && expectedScope == currentScope &&
            serverProfile.apiBaseURL == currentProfile.apiBaseURL &&
            serverProfile.webBaseURL == currentProfile.webBaseURL &&
            serverProfile.uploadBaseURL == currentProfile.uploadBaseURL
    }

    static func makeUploadBody(data: Data, filename: String, contentType: String,
                               chatID: String?, boundary: String) throws -> Data {
        let forbidden = CharacterSet.controlCharacters
        guard !filename.isEmpty, filename.rangeOfCharacter(from: forbidden) == nil,
              !contentType.isEmpty, contentType.rangeOfCharacter(from: forbidden) == nil,
              !boundary.isEmpty, boundary.rangeOfCharacter(from: forbidden) == nil else {
            throw APIError.invalidResponse
        }
        let escapedFilename = filename.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(escapedFilename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(contentType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        if let chatID {
            body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
            body.append(Data(chatID.utf8))
        }
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        return body
    }

    #if os(iOS) || os(macOS)
    /// Session rotation must publish cookies under the same authority fence as
    /// the user/token response. URLSession's automatic cookie handling otherwise
    /// installs a late old account response before AuthManager can reject it.
    func validateNativeSession(serverProfile: ServerProfile, body: SessionRequest,
                               expectedAccountID: String?,
                               isCurrent: @escaping @MainActor () -> Bool) async throws -> SessionResponse {
        var request = buildRequest(.post, path: "/v1/auth/session", headers: nil,
            baseURL: serverProfile.apiBaseURL, webAppURL: serverProfile.webBaseURL)
        request.httpBody = try encoder.encode(body)
        let prepared = request
        request = try await MainActor.run {
            guard isCurrent() else { throw CancellationError() }
            var pinned = prepared
            Self.pinAuthorizedCookies(in: &pinned, cookieStorage: cookieStorage)
            return pinned
        }
        let data = try await execute(request, using: session, authorizeSessionResponse: { response, data in
            guard isCurrent() else { return (false, false) }
            guard (200...299).contains(response.statusCode) else {
                return (true, response.statusCode == 401 || response.statusCode == 403)
            }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            guard let result = try? decoder.decode(SessionResponse.self, from: data) else { return (true, false) }
            let publishCookies = expectedAccountID == nil || result.user == nil || result.user?.id == expectedAccountID
            return (true, publishCookies)
        })
        return try decodeResponse(SessionResponse.self, from: data)
    }
    #endif

    // MARK: - Encodable body

    /// Watch services supply their verified account/session/deadline fence. Both
    /// dispatch and response publication use that fence and the pinned credential.
    func requestForVerifiedWatchSession(_ method: HTTPMethod, path: String, serverProfile: ServerProfile,
                                        body: (any Encodable & Sendable)? = nil, headers: [String: String]? = nil,
                                        verifyResponse: (@MainActor @Sendable (HTTPURLResponse, Data) throws -> Void)? = nil,
                                        validate: @escaping @MainActor @Sendable () throws -> Void) async throws -> Data {
        var request = buildRequest(method, path: path, headers: headers,
                                   baseURL: serverProfile.apiBaseURL, webAppURL: serverProfile.webBaseURL)
        if let body {
            if let rawBody = body as? JSONRawBody { request.httpBody = rawBody.data }
            else { request.httpBody = try encoder.encode(body) }
        }
        return try await execute(request, using: session, cookieAuthority: validate,
                                 authenticationURL: serverProfile.apiBaseURL, verifyCookieResponse: verifyResponse)
    }

    func uploadFileForVerifiedWatchSession(data: Data, filename: String, contentType: String,
        chatId: String, serverProfile: ServerProfile,
        validate: @escaping @MainActor @Sendable () throws -> Void) async throws -> Data {
        let boundary = UUID().uuidString
        let body = try Self.makeUploadBody(data: data, filename: filename,
            contentType: contentType, chatID: chatId, boundary: boundary)
        let request = Self.makeUploadRequest(uploadURL: serverProfile.uploadBaseURL.appendingPathComponent("v1/upload/file"),
            authenticationURL: serverProfile.apiBaseURL, webAppURL: serverProfile.webBaseURL,
            boundary: boundary, body: body, cookieStorage: cookieStorage)
        return try await execute(request, using: uploadSession, cookieAuthority: validate,
                                 authenticationURL: serverProfile.apiBaseURL)
    }

    func requestForWatchPush(_ method: HTTPMethod, path: String, serverProfile: ServerProfile,
                             body: [String: String],
                             validate: @escaping @MainActor @Sendable () throws -> Void) async throws -> Data {
        try await requestForVerifiedWatchSession(method, path: path, serverProfile: serverProfile,
                                                body: body, validate: validate)
    }

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

    func request(
        _ method: HTTPMethod,
        path: String,
        serverProfile: ServerProfile,
        body: (any Encodable)? = nil,
        headers: [String: String]? = nil,
        expectedAccountID: String? = nil, expectedScope: UUID? = nil,
        expectedTeamContext: APIRequestTeamContext? = nil
    ) async throws -> Data {
        var urlRequest = buildRequest(
            method,
            path: path,
            headers: headers,
            baseURL: serverProfile.apiBaseURL,
            webAppURL: serverProfile.webBaseURL
        )

        if let body {
            if let rawBody = body as? JSONRawBody {
                urlRequest.httpBody = rawBody.data
            } else {
                urlRequest.httpBody = try encoder.encode(body)
            }
        }

        if let expectedAccountID, let expectedScope {
            try await checkUploadContext(accountID: expectedAccountID, scope: expectedScope, profile: serverProfile)
            try await checkTeamContext(expectedTeamContext)
            Self.pinAuthorizedCookies(in: &urlRequest)
            try await checkUploadContext(accountID: expectedAccountID, scope: expectedScope, profile: serverProfile)
            try await checkTeamContext(expectedTeamContext)
            try Task.checkCancellation()
        } else if expectedAccountID != nil || expectedScope != nil || expectedTeamContext != nil {
            throw APIError.invalidResponse
        }
        return try await execute(urlRequest, expectedRecoveryAccountID: expectedAccountID)
    }

    func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        headers: [String: String]? = nil
    ) async throws -> T {
        let data = try await request(method, path: path, body: body, headers: headers)
        return try decodeResponse(T.self, from: data)
    }

    func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        serverProfile: ServerProfile,
        body: (any Encodable)? = nil,
        headers: [String: String]? = nil,
        expectedAccountID: String? = nil, expectedScope: UUID? = nil,
        expectedTeamContext: APIRequestTeamContext? = nil
    ) async throws -> T {
        let data = try await request(method, path: path, serverProfile: serverProfile, body: body, headers: headers,
                                     expectedAccountID: expectedAccountID, expectedScope: expectedScope,
                                     expectedTeamContext: expectedTeamContext)
        return try decodeResponse(T.self, from: data)
    }

    // MARK: - Dictionary body (for ad-hoc requests without Encodable structs)

    func request(_ method: HTTPMethod, path: String, serverProfile: ServerProfile,
                 body dict: [String: Any], headers: [String: String]? = nil,
                 expectedAccountID: String? = nil, expectedScope: UUID? = nil,
                 expectedTeamContext: APIRequestTeamContext? = nil) async throws -> Data {
        let raw = JSONRawBody(data: try JSONSerialization.data(withJSONObject: dict))
        return try await request(method, path: path, serverProfile: serverProfile, body: raw, headers: headers,
                                 expectedAccountID: expectedAccountID, expectedScope: expectedScope,
                                 expectedTeamContext: expectedTeamContext)
    }

    func request<T: Decodable>(_ method: HTTPMethod, path: String, serverProfile: ServerProfile,
                              body dict: [String: Any], headers: [String: String]? = nil,
                              expectedAccountID: String? = nil, expectedScope: UUID? = nil,
                              expectedTeamContext: APIRequestTeamContext? = nil) async throws -> T {
        let data: Data = try await request(method, path: path, serverProfile: serverProfile, body: dict, headers: headers,
                                          expectedAccountID: expectedAccountID, expectedScope: expectedScope,
                                          expectedTeamContext: expectedTeamContext)
        return try decodeResponse(T.self, from: data)
    }

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
        return try decodeResponse(T.self, from: data)
    }

    // MARK: - Private

    private func decodeResponse<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do { return try decoder.decode(type, from: data) }
        catch {
            APIResponseDecodingDiagnostics.record(error: error, responseType: type)
            throw error
        }
    }

    static func makeStandardSessionConfiguration() -> URLSessionConfiguration {
        makeSessionConfiguration(requestTimeout: 30, resourceTimeout: 60)
    }

    static func makeUploadSessionConfiguration() -> URLSessionConfiguration {
        makeSessionConfiguration(requestTimeout: uploadTimeout, resourceTimeout: uploadTimeout)
    }

    static func makeUploadRequest(
        uploadURL: URL,
        authenticationURL: URL? = nil,
        webAppURL: URL,
        boundary: String,
        body: Data,
        pinCookies: Bool = false,
        cookieStorage: HTTPCookieStorage = OpenMatesSharedEnvironment.cookieStorage
    ) -> URLRequest {
        var request = URLRequest(url: uploadURL)
        request.httpMethod = HTTPMethod.post.rawValue
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        nativeClientHeaders.forEach { key, value in
            request.setValue(value, forHTTPHeaderField: key)
        }
        // The upload service is on upload.openmates.org, while native sign-in
        // terminates at the selected API host. Some URLSession login responses
        // retain a host-only refresh cookie, so it is not considered eligible
        // for the upload host even though this is the trusted upload transport.
        // Forward only the authentication cookie; never copy unrelated API-host
        // cookies across hosts.
        let uploadCookies = cookieStorage.cookies(for: uploadURL) ?? []
        let authenticationRefreshCookie = authenticationURL.flatMap {
            Self.authoritativeRefreshCookie(in: cookieStorage, for: $0)
        }
        let authenticationCookieReachesUpload = authenticationRefreshCookie.map { authenticationCookie in
            uploadCookies.contains {
                $0.name == authenticationCookie.name
                    && $0.value == authenticationCookie.value
                    && $0.domain == authenticationCookie.domain
                    && $0.path == authenticationCookie.path
            }
        } ?? false
        // Keep upload-eligible cookies in the shared jar so URLSession resolves
        // the latest rotated token when the request is sent. A manually frozen
        // Cookie header can become invalid while another API request rotates the
        // session. Only bridge a host-only API cookie that cannot reach upload.
        if pinCookies {
            // Private Project file bytes must not acquire a different account's
            // cookies from URLSession's shared jar after the authority check.
            // A 401 retry takes a fresh snapshot only after revalidating scope.
            var cookies = uploadCookies
            if let refreshCookie = authenticationRefreshCookie {
                cookies.removeAll { $0.name == refreshCookie.name }
                cookies.append(refreshCookie)
            }
            request.httpShouldHandleCookies = false
            if !cookies.isEmpty {
                request.setValue(HTTPCookie.requestHeaderFields(with: cookies)["Cookie"],
                    forHTTPHeaderField: "Cookie")
            }
        } else if let refreshCookie = authenticationRefreshCookie,
           !authenticationCookieReachesUpload {
            let cookieHeader = HTTPCookie.requestHeaderFields(with: [refreshCookie])["Cookie"]
            request.setValue(cookieHeader, forHTTPHeaderField: "Cookie")
        }
        request.httpBody = body
        return request
    }

    static func shouldRetryUpload(after error: Error) -> Bool {
        guard case APIError.httpError(status: 401, message: _) = error else { return false }
        return true
    }

    static func pinAuthorizedCookies(in request: inout URLRequest,
                                    cookieStorage: HTTPCookieStorage = OpenMatesSharedEnvironment.cookieStorage,
                                    authenticationURL: URL? = nil) {
        request.httpShouldHandleCookies = false
        guard let url = request.url else { return }
        if authenticationURL == nil, request.value(forHTTPHeaderField: "Cookie") != nil { return }
        var cookies = cookieStorage.cookies(for: url) ?? []
        if let refreshCookie = Self.authoritativeRefreshCookie(in: cookieStorage, for: authenticationURL ?? url) {
            cookies.removeAll { $0.name == refreshCookie.name }
            cookies.append(refreshCookie)
        }
        request.setValue(cookies.isEmpty ? nil : HTTPCookie.requestHeaderFields(with: cookies)["Cookie"],
            forHTTPHeaderField: "Cookie")
    }

    private static func makeSessionConfiguration(
        requestTimeout: TimeInterval,
        resourceTimeout: TimeInterval
    ) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpShouldSetCookies = true
        configuration.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        configuration.timeoutIntervalForRequest = requestTimeout
        configuration.timeoutIntervalForResource = resourceTimeout
        return configuration
    }

    private func buildRequest(
        _ method: HTTPMethod,
        path: String,
        headers: [String: String]?
    ) -> URLRequest {
        buildRequest(method, path: path, headers: headers, baseURL: baseURL, webAppURL: webAppURL)
    }

    private func buildRequest(
        _ method: HTTPMethod,
        path: String,
        headers: [String: String]?,
        baseURL: URL,
        webAppURL: URL
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
        request.setValue(webAppURL.absoluteString, forHTTPHeaderField: "Origin")
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
        #if os(watchOS)
        return "watchos"
        #elseif os(iOS)
        return "ios"
        #elseif os(macOS)
        return "macos"
        #else
        return "apple"
        #endif
    }

    private func execute(_ request: URLRequest, expectedRecoveryAccountID: String? = nil) async throws -> Data {
        try await execute(request, using: session, expectedRecoveryAccountID: expectedRecoveryAccountID)
    }

    private func execute(_ request: URLRequest, using transport: URLSession,
                         expectedRecoveryAccountID: String? = nil,
                         awaitUnauthorizedRecovery: Bool = false,
                         authorizeSessionResponse: (@MainActor (HTTPURLResponse, Data) -> (isCurrent: Bool, publishCookies: Bool))? = nil,
                         cookieAuthority: (@MainActor @Sendable () throws -> Void)? = nil,
                         authenticationURL: URL? = nil,
                         verifyCookieResponse: (@MainActor @Sendable (HTTPURLResponse, Data) throws -> Void)? = nil) async throws -> Data {
        #if DEBUG
        if let stubbedData = Self.uiTestIssueReportResponse(for: request) {
            return stubbedData
        }
        #endif

        var dispatchedRequest = request
        var responseCookieAuthority = cookieAuthority
        var cookieAuthenticationURL = authenticationURL ?? request.url
        let explicitMutationProfile: ServerProfile?
        if request.url.map({ Self.isExplicitSessionMutation($0.path) }) == true {
            explicitMutationProfile = await MainActor.run { ServerProfile.current() }
        } else { explicitMutationProfile = nil }
        #if os(iOS) || os(macOS)
        var capturedContext: AuthSessionRecoveryContext?
        #endif
        // Auxiliary/public requests can carry a retained cookie during startup
        // or device verification. Pin every ordinary request, including nil
        // authenticated identity, so a late response cannot replace a login.
        if cookieAuthority == nil, authorizeSessionResponse == nil,
           let url = request.url, !Self.isExplicitSessionMutation(url.path) {
            #if os(iOS) || os(macOS)
            let snapshot = try await MainActor.run {
                let context = AuthManager.captureSessionRecoveryContext()
                if let expectedRecoveryAccountID, context?.accountID != expectedRecoveryAccountID {
                    throw CancellationError()
                }
                return (profile: ServerProfile.current(), accountID: AuthManager.notificationAccountId,
                        sessionID: AuthManager.nativeSessionId, context: context)
            }
            if let context = snapshot.context,
               context.profile.apiBaseURL.host == url.host || context.profile.uploadBaseURL.host == url.host {
                capturedContext = context
                cookieAuthenticationURL = context.profile.apiBaseURL
            }
            responseCookieAuthority = {
                let current = AuthManager.captureSessionRecoveryContext()
                // Recovery generation may advance while the same logical
                // session legitimately renews. Its identity must remain stable.
                guard ServerProfile.current() == snapshot.profile,
                      AuthManager.notificationAccountId == snapshot.accountID,
                      AuthManager.nativeSessionId == snapshot.sessionID,
                      current?.accountID == snapshot.context?.accountID else { throw CancellationError() }
            }
            #else
            let profile = ServerProfile.current()
            responseCookieAuthority = {
                guard ServerProfile.current() == profile else { throw CancellationError() }
            }
            #endif
        }
        #if os(iOS) || os(macOS)
        let recoveryContext = request.url?.path.hasPrefix("/v1/auth/") == false ? capturedContext : nil
        #endif
        if let responseCookieAuthority {
            let prepared = dispatchedRequest
            let authenticationURL = cookieAuthenticationURL
            dispatchedRequest = try await MainActor.run {
                try responseCookieAuthority()
                var pinned = prepared
                Self.pinAuthorizedCookies(in: &pinned, cookieStorage: cookieStorage, authenticationURL: authenticationURL)
                return pinned
            }
        }
        try Task.checkCancellation()
        let sentRequest = dispatchedRequest
        let cookieURL = cookieAuthenticationURL
        let (data, response) = try await transport.data(for: sentRequest)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if let authorizeSessionResponse {
            try await MainActor.run {
                let authorization = authorizeSessionResponse(httpResponse, data)
                guard authorization.isCurrent, !Task.isCancelled else { throw CancellationError() }
                if authorization.publishCookies {
                    Self.publishResponseCookies(httpResponse, request: sentRequest,
                        authenticationURL: cookieURL, cookieStorage: cookieStorage)
                }
            }
        } else if let responseCookieAuthority {
            try await MainActor.run {
                try responseCookieAuthority()
                try Task.checkCancellation()
                try verifyCookieResponse?(httpResponse, data)
                Self.publishResponseCookies(httpResponse, request: sentRequest,
                    authenticationURL: cookieURL, cookieStorage: cookieStorage)
            }
        } else if let explicitMutationProfile {
            await MainActor.run {
                guard ServerProfile.current() == explicitMutationProfile else { return }
                Self.reconcileExplicitSessionCookies(httpResponse, request: sentRequest,
                    profile: explicitMutationProfile, cookieStorage: cookieStorage)
            }
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            NativeDiagnostics.warning(
                "API request failed method=\(request.httpMethod ?? "unknown") status=\(httpResponse.statusCode)",
                category: "network"
            )
            #if os(iOS) || os(macOS)
            if httpResponse.statusCode == 401, let recoveryContext {
                if awaitUnauthorizedRecovery {
                    await AuthManager.recoverRejectedRequest(recoveryContext)
                    try Task.checkCancellation()
                } else {
                    Task { @MainActor in await AuthManager.recoverRejectedRequest(recoveryContext) }
                }
            }
            #endif
            let errorBody = try? decoder.decode(APIErrorResponse.self, from: data)
            throw APIError.httpError(
                status: httpResponse.statusCode,
                message: errorBody?.detail ?? "Request failed (\(httpResponse.statusCode))"
            )
        }

        return data
    }

    /// Login/pair completion create a new logical credential; explicit logout
    /// owns deletion. Their existing auth flows retain cookie handling.
    private static func isExplicitSessionMutation(_ path: String) -> Bool {
        ["/v1/auth/login", "/v1/auth/logout", "/v1/auth/logout-all",
         "/v1/auth/policy-violation-logout"].contains(path) ||
            path.hasPrefix("/v1/auth/pair/v2/complete/")
    }

    private static func refreshCredential(in request: URLRequest) -> String? {
        request.value(forHTTPHeaderField: "Cookie")?.split(separator: ";").compactMap { part -> String? in
            let pair = part.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2, pair[0].trimmingCharacters(in: .whitespaces) == "auth_refresh_token" else { return nil }
            return pair[1].trimmingCharacters(in: .whitespaces)
        }.first
    }

    /// The API host is the credential authority for bridged uploads. Prefer its
    /// host-only cookie to an overlapping parent-domain alias, consistently at
    /// dispatch and publication, and emit one refresh credential per request.
    private static func authoritativeRefreshCookie(in storage: HTTPCookieStorage, for url: URL) -> HTTPCookie? {
        let cookies = (storage.cookies(for: url) ?? []).filter { $0.name == "auth_refresh_token" }
        return cookies.first { $0.domain.lowercased() == url.host?.lowercased() } ?? cookies.first
    }

    private static func responseCookies(_ response: HTTPURLResponse, url: URL) -> [HTTPCookie] {
        let headers = response.allHeaderFields.reduce(into: [String: String]()) { values, entry in
            if let key = entry.key as? String, let value = entry.value as? String { values[key] = value }
        }
        return HTTPCookie.cookies(withResponseHeaderFields: headers, for: url)
    }

    /// Called only after an admitted response, without suspension. Retire refresh
    /// aliases eligible for these configured URLs; leave other names/hosts alone.
    @MainActor private static func installRefreshResponse(_ cookies: [HTTPCookie], responseURL: URL,
        authenticationURL: URL, scopeURLs: [URL], cookieStorage: HTTPCookieStorage) {
        guard let successor = cookies.first(where: { $0.name == "auth_refresh_token" }) else {
            cookieStorage.setCookies(cookies, for: responseURL, mainDocumentURL: nil)
            return
        }
        for url in scopeURLs {
            for cookie in cookieStorage.cookies(for: url) ?? [] where cookie.name == "auth_refresh_token" {
                cookieStorage.deleteCookie(cookie)
            }
        }
        cookieStorage.setCookies(cookies, for: responseURL, mainDocumentURL: nil)
        // A host-only upload renewal cannot reach the API host. Its trusted API
        // mirror narrows the domain while retaining the response's path, expiry,
        // Secure, HttpOnly and SameSite properties. Shared-domain responses keep
        // their original attributes and need no mirror.
        guard !successor.value.isEmpty, successor.expiresDate.map({ $0 > Date() }) ?? true,
              Self.authoritativeRefreshCookie(in: cookieStorage, for: authenticationURL)?.value != successor.value,
              var properties = successor.properties, let host = authenticationURL.host else { return }
        properties[.domain] = host
        properties[.originURL] = authenticationURL
        if let mirror = HTTPCookie(properties: properties) { cookieStorage.setCookie(mirror) }
    }

    /// Compare and publish on MainActor without suspension. A duplicate response
    /// for the installed successor is harmless; older responses cannot retire
    /// aliases or overwrite a newer credential. No HTTP write is replayed.
    @MainActor private static func publishResponseCookies(_ response: HTTPURLResponse, request: URLRequest,
        authenticationURL: URL?, cookieStorage: HTTPCookieStorage) {
        guard let url = request.url else { return }
        let authURL = authenticationURL ?? url
        let cookies = Self.responseCookies(response, url: url)
        let current = Self.authoritativeRefreshCookie(in: cookieStorage, for: authURL)?.value
            ?? Self.authoritativeRefreshCookie(in: cookieStorage, for: url)?.value
        let successor = cookies.first { $0.name == "auth_refresh_token" }?.value
        guard current == refreshCredential(in: request) || (successor != nil && successor == current) else { return }
        Self.installRefreshResponse(cookies, responseURL: url, authenticationURL: authURL,
            scopeURLs: [authURL, url], cookieStorage: cookieStorage)
    }

    /// Explicit login/logout already owns cookie creation/deletion. Reconcile
    /// only that response's refresh aliases so a prior API mirror cannot shadow
    /// a new shared-domain login or survive logout.
    @MainActor private static func reconcileExplicitSessionCookies(_ response: HTTPURLResponse, request: URLRequest,
        profile: ServerProfile, cookieStorage: HTTPCookieStorage) {
        guard let url = request.url else { return }
        let cookies = Self.responseCookies(response, url: url)
        guard cookies.contains(where: { $0.name == "auth_refresh_token" }) else { return }
        let isConfiguredAPI = url.host == profile.apiBaseURL.host
        let authURL = isConfiguredAPI ? profile.apiBaseURL : url
        let urls = isConfiguredAPI ? [authURL, profile.uploadBaseURL] : [url]
        Self.installRefreshResponse(cookies, responseURL: url, authenticationURL: authURL,
            scopeURLs: urls, cookieStorage: cookieStorage)
    }

    #if DEBUG
    private static func uiTestIssueReportResponse(for request: URLRequest) -> Data? {
        guard ProcessInfo.processInfo.arguments.contains("--ui-test-report-issue-success") else {
            return nil
        }
        guard request.httpMethod == HTTPMethod.post.rawValue,
              let path = request.url?.path else {
            return nil
        }

        if path.hasSuffix("/v1/settings/issues") {
            return Data(
                #"{"success":true,"message":"UI test issue created","issue_id":"issue-ios-ui-test","short_issue_id":"OPE-IOS-UI-TEST","screenshot_uploaded":false}"#.utf8
            )
        }
        if path.hasSuffix("/v1/settings/issue-logs") {
            return Data(#"{"success":true}"#.utf8)
        }
        return nil
    }
    #endif
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

enum APIResponseDecodingDiagnostics {
    // Only static schema names are admitted. Dictionary keys, record IDs,
    // typed text and values never enter diagnostics.
    private static let fields: Set<String> = [
        "tasks", "plans", "projects", "workflows", "workflow", "task", "plan", "project",
        "status", "assigneeType", "assigneeIdentity", "linkedProjectHashes", "linkedProjectIds",
        "createdAt", "updatedAt", "dueAt", "position", "version", "keyWrappers", "keyType",
        "encryptedTaskKey", "encryptedPlanKey", "encryptedTitle", "encryptedGoal", "encryptedDescription",
        "currentVersionId", "createdByAssistant", "graph", "triggerNodeId", "inputMapping",
        "scope", "sources", "entries", "total", "count", "data", "encryptedContent"
    ]

    static func summary(error: Error, responseType: Any.Type) -> String {
        let kind: String
        var path: [any CodingKey]
        switch error {
        case DecodingError.typeMismatch(_, let context): kind = "typeMismatch"; path = context.codingPath
        case DecodingError.valueNotFound(_, let context): kind = "valueNotFound"; path = context.codingPath
        case DecodingError.keyNotFound(let key, let context): kind = "keyNotFound"; path = context.codingPath + [key]
        case DecodingError.dataCorrupted(let context): kind = "dataCorrupted"; path = context.codingPath
        default: kind = "other"; path = []
        }
        let safePath = path.map { key in
            key.intValue != nil ? "item" : (fields.contains(key.stringValue) ? key.stringValue : "field")
        }.joined(separator: ".")
        return "response_type=\(String(describing: responseType)) failure=\(kind) field_path=\(safePath.isEmpty ? "root" : safePath)"
    }

    static func record(error: Error, responseType: Any.Type) {
        NativeDiagnostics.error("API response decoding failed \(summary(error: error, responseType: responseType))", category: "network")
    }
}
