// Anonymous, presentation-scoped media for shared-chat recipients.
// Web: frontend/apps/web_app/src/routes/share/chat/[chatId]/+page.svelte
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls

import Foundation
import SwiftUI
import AVFoundation
import UniformTypeIdentifiers

/// Recipient media never consults owner identity, API settings, or disk caches.
@MainActor
final class RecipientMediaContext {
    let generation = UUID()
    let namespace: String
    let client: S3MediaClient
    let webBaseURL: URL
    let apiBaseURL: URL
    private let transport: RecipientMediaTransport
    private let isCurrent: () -> Bool
    private var cancelled = false
    private var audioPlayers: [AVAudioPlayer] = []
    private var playback: [RecipientMemoryPlayback] = []

    init(linkURL: URL, namespace: String = UUID().uuidString,
         isCurrent: @escaping () -> Bool = { true },
         requestLoader: RecipientMediaTransport.RequestLoader? = nil) throws {
        let link = try SharedChatRecipientLink.parse(linkURL)
        apiBaseURL = link.apiBaseURL
        webBaseURL = URL(string: "https://\(link.url.host!.lowercased())/")!
        self.namespace = namespace
        self.isCurrent = isCurrent
        let transport = RecipientMediaTransport(apiBaseURL: apiBaseURL, webBaseURL: webBaseURL, requestLoader: requestLoader)
        self.transport = transport
        client = S3MediaClient(encryptedDataLoader: { url, key in
            try await transport.encrypted(url: url, key: key)
        })
    }

    func resolvedPublicURL(_ value: String) -> URL? {
        guard let url = URL(string: value, relativeTo: webBaseURL)?.absoluteURL,
              RecipientMediaTransport.allowed(url) else { return nil }
        return url
    }

    func checkCurrent() throws {
        try Task.checkCancellation()
        guard !cancelled, isCurrent() else { throw CancellationError() }
    }

    func cancel() {
        cancelled = true
        transport.cancel()
        for player in audioPlayers { player.stop() }
        audioPlayers.removeAll()
        for item in playback { item.cancel() }
        playback.removeAll()
        Task { await client.cancelAll() }
    }

    func fetchAndDecrypt(s3Url: String, aesKeyHex: String, aesNonceHex: String?,
                         encryption: String? = nil, s3Key: String? = nil) async throws -> Data {
        try checkCurrent()
        let data = try await client.fetchAndDecrypt(s3Url: s3Url, aesKeyHex: aesKeyHex,
            aesNonceHex: aesNonceHex, encryption: encryption, s3Key: s3Key,
            cacheNamespace: namespace, cachePolicy: .memoryOnly)
        try checkCurrent()
        return data
    }

    func download(_ url: URL) async throws -> Data {
        try checkCurrent()
        let data = try await transport.download(url)
        try checkCurrent()
        return data
    }

    func track(_ player: AVAudioPlayer) throws {
        try checkCurrent()
        audioPlayers.append(player)
    }

    func player(url: URL) async throws -> AVPlayer {
        let bytes = try await download(url)
        return try player(data: bytes)
    }

    func player(data: Data, contentType: String = UTType.mpeg4Movie.identifier) throws -> AVPlayer {
        try checkCurrent()
        let item = RecipientMemoryPlayback(data: data, contentType: contentType)
        playback.append(item)
        return item.player
    }

    static func fetchAndDecrypt(context: RecipientMediaContext?, s3Url: String, aesKeyHex: String,
        aesNonceHex: String?, encryption: String? = nil, s3Key: String? = nil,
        cacheNamespace: String? = nil, cachePolicy: S3MediaCachePolicy = .persistent) async throws -> Data {
        if let context {
            return try await context.fetchAndDecrypt(s3Url: s3Url, aesKeyHex: aesKeyHex,
                aesNonceHex: aesNonceHex, encryption: encryption, s3Key: s3Key)
        }
        return try await S3MediaClient.shared.fetchAndDecrypt(s3Url: s3Url, aesKeyHex: aesKeyHex,
            aesNonceHex: aesNonceHex, encryption: encryption, s3Key: s3Key,
            cacheNamespace: cacheNamespace, cachePolicy: cachePolicy)
    }

    static func download(context: RecipientMediaContext?, url: URL) async throws -> Data {
        if let context { return try await context.download(url) }
        return try await URLSession.shared.data(from: url).0
    }
}

private struct RecipientMediaContextKey: EnvironmentKey {
    static let defaultValue: RecipientMediaContext? = nil
}

extension EnvironmentValues {
    var recipientMediaContext: RecipientMediaContext? {
        get { self[RecipientMediaContextKey.self] }
        set { self[RecipientMediaContextKey.self] = newValue }
    }
}

/// No redirects, credentials, cookies, persistent URL cache, or owner API client.
final class RecipientMediaTransport: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    typealias RequestLoader = @Sendable (URLRequest) async throws -> (Data, URLResponse)
    static let maximumMediaBytes = 64 * 1024 * 1024
    private let apiBaseURL: URL
    private let webBaseURL: URL
    private let requestLoader: RequestLoader?
    private var session: URLSession!

    init(apiBaseURL: URL, webBaseURL: URL, requestLoader: RequestLoader? = nil) {
        self.apiBaseURL = apiBaseURL
        self.webBaseURL = webBaseURL
        self.requestLoader = requestLoader
        super.init()
        session = URLSession(configuration: Self.configuration(), delegate: self, delegateQueue: nil)
    }

    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 120
        return config
    }

    func cancel() { session.invalidateAndCancel() }

    func encrypted(url: String, key: String?) async throws -> Data {
        if let key, !key.isEmpty {
            guard key.utf8.count <= 4096, !key.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
                throw URLError(.badURL)
            }
            var components = URLComponents(url: apiBaseURL.appendingPathComponent("v1/embeds/presigned-url"), resolvingAgainstBaseURL: false)!
            components.queryItems = [.init(name: "s3_key", value: key)]
            let bytes = try await request(components.url!, limit: 65_536, accept: "application/json")
            guard let payload = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
                  let value = payload["url"] as? String, let target = URL(string: value) else {
                throw URLError(.cannotParseResponse)
            }
            return try await download(target)
        }
        guard let target = URL(string: url) else { throw URLError(.badURL) }
        return try await download(target)
    }

    func download(_ url: URL) async throws -> Data {
        try await request(url, limit: Self.maximumMediaBytes, accept: "application/octet-stream")
    }

    static func allowed(_ url: URL) -> Bool {
        guard url.absoluteString.utf8.count <= 16_384, url.scheme == "https",
              url.user == nil, url.password == nil, url.port == nil, url.fragment == nil,
              let host = url.host?.lowercased(), host.contains("."),
              !host.hasSuffix(".local"), !host.hasSuffix(".localhost"),
              !host.hasSuffix(".internal"), !host.contains(":"),
              !host.allSatisfy({ $0.isNumber || $0 == "." }),
              host.range(of: "^[a-z0-9][a-z0-9.-]*[a-z0-9]$", options: .regularExpression) != nil else { return false }
        return true
    }

    private func request(_ url: URL, limit: Int, accept: String) async throws -> Data {
        try Task.checkCancellation()
        guard Self.allowed(url) else { throw URLError(.badURL) }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = "GET"
        request.httpShouldHandleCookies = false
        request.setValue(accept, forHTTPHeaderField: "Accept")
        // Preview proxies require the share's validated web origin. Send no
        // fragment, share path, owner profile, or header to any other endpoint.
        let previewEndpoints = ["/api/v1/image", "/api/v1/favicon", "/api/v1/youtube"]
        if url.host?.lowercased() == "preview.openmates.org", previewEndpoints.contains(url.path),
           let host = webBaseURL.host,
           ["openmates.org", "app.openmates.org", "app.dev.openmates.org"].contains(host) {
            request.setValue("https://\(host)/", forHTTPHeaderField: "Referer")
        }
        let data: Data
        let response: URLResponse
        if let requestLoader {
            (data, response) = try await requestLoader(request)
        } else {
            // Stop at the byte limit while receiving, before accumulating an
            // unbounded ciphertext or public-media buffer in memory.
            let (bytes, received) = try await session.bytes(for: request)
            response = received
            guard received.expectedContentLength <= Int64(limit) else { throw URLError(.dataLengthExceedsMaximum) }
            var buffer = Data()
            for try await byte in bytes {
                guard buffer.count < limit else { throw URLError(.dataLengthExceedsMaximum) }
                buffer.append(byte)
            }
            data = buffer
        }
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse,
              (200...299).contains(http.statusCode), http.url == url else { throw URLError(.badServerResponse) }
        guard data.count <= limit else { throw URLError(.dataLengthExceedsMaximum) }
        return data
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust {
            completionHandler(.performDefaultHandling, nil)
        } else { completionHandler(.cancelAuthenticationChallenge, nil) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

/// AVFoundation reads recipient video from a bounded memory buffer, never a file.
private final class RecipientMemoryPlayback: NSObject, AVAssetResourceLoaderDelegate, @unchecked Sendable {
    private var data: Data
    private let contentType: String
    private let queue = DispatchQueue(label: "org.openmates.recipient-media")
    let player: AVPlayer

    init(data: Data, contentType: String) {
        self.data = data
        self.contentType = contentType
        let asset = AVURLAsset(url: URL(string: "openmates-recipient-media://buffer/\(UUID().uuidString)")!)
        player = AVPlayer(playerItem: AVPlayerItem(asset: asset))
        super.init()
        asset.resourceLoader.setDelegate(self, queue: queue)
    }

    func cancel() {
        player.pause()
        player.replaceCurrentItem(with: nil)
        queue.async { self.data.removeAll() }
    }

    func resourceLoader(_ resourceLoader: AVAssetResourceLoader,
                        shouldWaitForLoadingOfRequestedResource request: AVAssetResourceLoadingRequest) -> Bool {
        request.contentInformationRequest?.contentType = contentType
        request.contentInformationRequest?.contentLength = Int64(data.count)
        request.contentInformationRequest?.isByteRangeAccessSupported = true
        if let range = request.dataRequest {
            let offset = max(range.requestedOffset, range.currentOffset)
            guard offset >= 0, offset <= Int64(data.count) else {
                request.finishLoading(with: URLError(.cannotDecodeContentData)); return true
            }
            let start = Int(offset)
            let end = range.requestsAllDataToEndOfResource ? data.count : start + min(data.count - start, max(range.requestedLength, 0))
            range.respond(with: data.subdata(in: start..<end))
        }
        request.finishLoading()
        return true
    }
}
