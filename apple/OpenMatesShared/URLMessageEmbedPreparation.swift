// Shared pre-send URL materialization for the app and share extension.
// Web: frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
//      frontend/packages/ui/src/components/enter_message/services/urlMetadataService.ts
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.persistence.client-encrypted, chats.surface.semantic-parity
// URLs and metadata remain transient until the existing encrypted send commits.

import Foundation

struct URLMessageEmbedPreparation {
    struct Prepared {
        let content: String
        let embeds: [BackgroundPreparedEmbed]
    }

    struct Match: Equatable {
        let url: String
        let range: NSRange
    }

    // Keep the web send detector's protocol-free YouTube support and code fences.
    static func matches(in text: String) -> [Match] {
        let whole = NSRange(text.startIndex..., in: text)
        let fences = try! NSRegularExpression(pattern: #"```[\s\S]*?```"#)
            .matches(in: text, range: whole).map(\.range)
        let detector = try! NSRegularExpression(pattern: #"(?:https?://[^\s\])"'<>]+|(?<![/\w@])(?:(?:www\.|m\.)?youtube\.com/(?:watch\?v=|embed/|shorts/|v/)[^\s\])"'<>]+|youtu\.be/[^\s\])"'<>]+))"#)
        return detector.matches(in: text, range: whole).compactMap { match in
            guard !fences.contains(where: { NSIntersectionRange($0, match.range).length == match.range.length }),
                  let range = Range(match.range, in: text) else { return nil }
            let raw = String(text[range])
            return Match(url: raw.hasPrefix("http://") || raw.hasPrefix("https://") ? raw : "https://\(raw)", range: match.range)
        }
    }

    static func videoID(for value: String) -> String? {
        guard let url = URLComponents(string: value),
              ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be", "m.youtu.be"].contains(url.host?.lowercased() ?? "") else { return nil }
        let parts = url.path.split(separator: "/")
        let candidate: String?
        if url.host?.lowercased().hasSuffix("youtu.be") == true {
            candidate = parts.first.map(String.init)
        } else if url.path == "/watch" {
            candidate = url.queryItems?.first(where: { $0.name == "v" })?.value
        } else if let first = parts.first, ["embed", "shorts", "v"].contains(String(first)), parts.count > 1 {
            candidate = String(parts[1])
        } else { candidate = nil }
        guard let candidate, candidate.range(of: #"^[a-zA-Z0-9_-]{11}$"#, options: .regularExpression) != nil else { return nil }
        return candidate
    }

    static func cachedCredits(accountID: String?, defaults: UserDefaults = OpenMatesSharedEnvironment.defaults) -> Double {
        guard let accountID, let data = defaults.data(forKey: "openmates.apple.auth.cached_user"),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["id"] as? String == accountID else { return 0 }
        return (object["credits"] as? NSNumber)?.doubleValue ?? 0
    }

    static func prepare(
        text: String,
        credits: Double,
        validate: () async throws -> Void,
        fetch: ((String, String) async throws -> [String: Any]?)? = nil,
        makeID: () -> String = { UUID().uuidString.lowercased() },
        metadataBudget: TimeInterval = 3,
        clock: () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Prepared {
        try Task.checkCancellation()
        try await validate()
        let matches = matches(in: text)
        // Optional metadata has one monotonic deadline for the entire message.
        // Every URL still receives its local fallback when that budget expires.
        let metadataDeadline = clock() + max(0, metadataBudget)
        var embeds: [BackgroundPreparedEmbed] = []
        for match in matches {
            try Task.checkCancellation()
            try await validate()
            let videoID = videoID(for: match.url)
            let endpoint = videoID == nil ? "metadata" : "youtube"
            var metadata: [String: Any]?
            let remainingBudget = metadataDeadline - clock()
            if (videoID == nil || credits > 0), remainingBudget > 0 {
                do {
                    if let fetch { metadata = try await fetch(endpoint, match.url) }
                    else { metadata = try await fetchMetadata(endpoint: endpoint, url: match.url, timeout: remainingBudget) }
                    if clock() > metadataDeadline { metadata = nil }
                }
                catch is CancellationError { throw CancellationError() }
                catch { metadata = nil }
            }
            // A response from a previous account/server/session may not be used.
            try Task.checkCancellation()
            try await validate()
            let embed = materialize(url: match.url, videoID: videoID, metadata: metadata, id: makeID())
            embeds.append(embed)
        }
        var content = text
        for (match, embed) in zip(matches, embeds).reversed() {
            guard let range = Range(match.range, in: content) else { continue }
            var before = String(content[..<range.lowerBound])
            var after = String(content[range.upperBound...])
            if !before.isEmpty && !before.hasSuffix("\n") { before += "\n" }
            if !after.isEmpty && !after.hasPrefix("\n") { after = "\n" + after }
            content = before + reference(for: embed, fallbackURL: match.url) + after
        }
        try await validate()
        return Prepared(content: content, embeds: embeds)
    }

    static func reference(for embed: BackgroundPreparedEmbed, fallbackURL: String) -> String {
        let object = ["type": embed.referenceType, "embed_id": embed.id, "url": fallbackURL]
        let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        return "```json\n\(String(decoding: data, as: UTF8.self))\n```"
    }

    static func materialize(url: String, videoID: String?, metadata: [String: Any]?, id: String) -> BackgroundPreparedEmbed {
        var content: [String: Any] = ["url": url, "fetched_at": ISO8601DateFormatter().string(from: Date())]
        let type = videoID == nil ? "website" : "video"
        if let videoID {
            // Never borrow another video's title, thumbnail, or statistics.
            let metadata = metadata?["video_id"] as? String == videoID ? metadata : nil
            content["video_id"] = videoID
            content["url"] = metadata?["url"] as? String ?? "https://www.youtube.com/watch?v=\(videoID)"
            for key in ["title", "description", "channel_name", "channel_id", "channel_thumbnail", "view_count", "like_count", "published_at"] {
                content[key] = metadata?[key] ?? NSNull()
            }
            if let thumbnails = metadata?["thumbnails"] as? [String: Any] {
                content["thumbnail"] = ["maxres", "high", "medium", "default"].compactMap { thumbnails[$0] as? String }.first
            }
            if let duration = metadata?["duration"] as? [String: Any] {
                content["duration_seconds"] = duration["total_seconds"]
                content["duration_formatted"] = duration["formatted"]
            }
        } else {
            for key in ["title", "description", "favicon", "image", "site_name"] { content[key] = metadata?[key] ?? NSNull() }
        }
        let title = content["title"] as? String
        let duration = content["duration_formatted"] as? String
        let preview = title.map { $0 + (duration.map { " (\($0))" } ?? "") } ?? url
        return BackgroundPreparedEmbed(id: id, type: type, referenceType: type, status: "finished", content: content, textPreview: preview)
    }

    static func fetchMetadata(endpoint: String, url: String, timeout: TimeInterval) async throws -> [String: Any]? {
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/\(endpoint)")!
        components.queryItems = [URLQueryItem(name: "url", value: url)]
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        // Resource timeout also bounds a slow/dribbling response; request timeout
        // alone restarts whenever more bytes arrive and cannot bound total work.
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.httpShouldHandleCookies = false
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode),
              data.count <= 1_048_576, let metadata = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if endpoint == "youtube", metadata["video_id"] as? String == nil { return nil }
        return metadata
    }
}
