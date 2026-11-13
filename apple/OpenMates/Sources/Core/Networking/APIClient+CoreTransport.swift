// App REST through the Rust core (plan apple-client-core-migration A4 lane 1).
// While the core holds a session, every `APIClient.request` to the selected
// API host goes through `ViewModelCore.httpRequest`: the core adds the session
// cookie and the client headers, stores rotated cookies and wipes the session
// on a 401 (`Session(Expired)`). While it holds none (sign-in ceremonies,
// public bootstrap: email lookup, signup and its passkey ceremony), requests
// use the pre-session transport, whose cookie jar is the ceremony's in-memory
// jar, never the shared one. Uploads go through `ViewModelCore.uploadFile`:
// the prepared bytes are written to a private temporary file whose path the
// core streams, and the file is removed when the call ends, also on error or
// cancellation. No cookie handling here; the Watch keeps its transport in
// `APIClient.swift`.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.credentials.snapshot-boundary, client-core.apple.strangler-order

#if os(iOS) || os(macOS)
import Foundation

extension APIClient {
    /// Headers the core sets itself; `buildRequest` adds them for the
    /// Watch and upload transports, so they are not forwarded.
    private static var coreOwnedHeaderNames: Set<String> {
        Set(nativeClientHeaders.keys.map { $0.lowercased() }).union(["origin", "cookie"])
    }

    /// Sends `request` with the core's session, or before any session exists
    /// through the pre-session transport. Non-2xx answers are
    /// `APIError.httpError`; the core's other errors are rethrown typed
    /// (`CoreError.Expired` as HTTP 401, `.Cancelled` as `CancellationError`).
    func executeThroughCoreOrPreSession(_ request: URLRequest, expectedAccountID: String?) async throws -> Data {
        guard let url = request.url else { throw APIError.invalidResponse }
        guard let route = try await Self.coreRoute(for: url, expectedAccountID: expectedAccountID) else {
            return try await executePreSession(request)
        }
        return try await executeThroughCore(request, url: url, core: route.core, basePath: route.basePath)
    }

    /// The core when it holds a session for `url`'s API host, else `nil`.
    @MainActor
    private static func coreRoute(for url: URL, expectedAccountID: String?) async throws
        -> (core: CoreSession, basePath: String)? {
        guard let core = CoreSession.shared else { return nil }
        await core.settled()
        let profile = ServerProfile.current()
        let api = profile.apiBaseURL
        guard url.scheme == api.scheme, url.host == api.host, url.port == api.port else { return nil }
        switch core.state {
        case .restored, .admitted, .verificationRequired, .accessDenied(.chatUnavailable):
            break
        case .notStarted, .starting, .signedOut, .expired, .accessDenied(.expired),
             .accessDenied(.scopeRevoked), .failed:
            return nil
        }
        if requiresProtectedAuthority(path: url.path) {
            try AuthManager.requireProtectedRequestAuthority(profile: profile)
        }
        if let expectedAccountID, await AuthManager.currentUserId() != expectedAccountID {
            throw CancellationError()
        }
        let basePath = URLComponents(url: api, resolvingAgainstBaseURL: false)?.percentEncodedPath ?? ""
        return (core, basePath.hasSuffix("/") ? String(basePath.dropLast()) : basePath)
    }

    private func executeThroughCore(_ request: URLRequest, url: URL, core: CoreSession,
                                    basePath: String) async throws -> Data {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        var path = components.percentEncodedPath
        if !basePath.isEmpty, path.hasPrefix(basePath) { path.removeFirst(basePath.count) }
        let ownHeaders = Self.coreOwnedHeaderNames
        let record = HttpRequestRecord(
            method: request.httpMethod ?? HTTPMethod.get.rawValue,
            path: path,
            query: (components.queryItems ?? []).map { HttpFieldRecord(name: $0.name, value: $0.value ?? "") },
            headers: (request.allHTTPHeaderFields ?? [:])
                .filter { !ownHeaders.contains($0.key.lowercased()) }
                .sorted { $0.key < $1.key }
                .map { HttpFieldRecord(name: $0.key, value: $0.value) },
            body: request.httpBody)
        let response: HttpResponseRecord
        do {
            response = try await core.httpRequest(record)
        } catch CoreError.Cancelled {
            throw CancellationError()
        } catch CoreError.Expired {
            // The core wiped the rejected session; callers know this as 401.
            throw APIError.httpError(status: 401, message: "Session expired")
        }
        return try checkedBody(status: Int(response.status), body: response.body,
                               method: record.method, transport: "core")
    }

    /// Folder of the temporary upload files inside the app's temporary
    /// directory; each file is named by a random id, never by its filename.
    static var coreUploadDirectory: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("openmates-core-uploads", isDirectory: true)
    }

    /// Uploads `data` as the `file` part to `url` through the core (`core`:
    /// the app's core, injected in tests). Non-2xx answers, 401 and 403
    /// included, are `APIError.httpError`; `CoreError.Cancelled` is
    /// `CancellationError`; other core errors are rethrown typed.
    func uploadThroughCore(url: URL, data: Data, filename: String, contentType: String,
                           fields: [HttpFieldRecord], core: CoreSession? = nil) async throws -> Data {
        let appCore: CoreSession? = await MainActor.run { CoreSession.shared }
        guard let core = core ?? appCore else { throw CoreSessionAdoptionError.coreUnavailable }
        let directory = Self.coreUploadDirectory
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fileURL = directory.appendingPathComponent(UUID().uuidString, isDirectory: false)
        #if os(iOS)
        try data.write(to: fileURL, options: [.atomic, .completeFileProtection])
        #else
        try data.write(to: fileURL, options: [.atomic])
        #endif
        defer {
            do {
                try FileManager.default.removeItem(at: fileURL)
            } catch {
                NativeDiagnostics.warning("phase=core.upload temp_file_cleanup_failed", category: "network")
            }
        }
        let request = UploadRequestRecord(url: url.absoluteString, filePath: fileURL.path,
            filename: filename, contentType: contentType, fields: fields)
        let response: HttpResponseRecord
        do {
            response = try await core.uploadFile(request)
        } catch CoreError.Cancelled {
            throw CancellationError()
        }
        return try checkedBody(status: Int(response.status), body: response.body,
                               method: HTTPMethod.post.rawValue, transport: "core_upload")
    }

    private func executePreSession(_ request: URLRequest) async throws -> Data {
        var request = request
        request.httpShouldHandleCookies = true
        let (data, response) = try await preSessionSession.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        return try checkedBody(status: httpResponse.statusCode, body: data,
                               method: request.httpMethod ?? "unknown", transport: "pre_session")
    }

    private func checkedBody(status: Int, body: Data, method: String, transport: String) throws -> Data {
        guard (200...299).contains(status) else {
            NativeDiagnostics.warning(
                "API request failed method=\(method) status=\(status) transport=\(transport) \(NativeClientIdentity.current.diagnosticSummary)",
                category: "network")
            let errorBody = try? decoder.decode(APIErrorResponse.self, from: body)
            throw APIError.httpError(status: status, message: errorBody?.detail ?? "Request failed (\(status))")
        }
        return body
    }
}
#endif
