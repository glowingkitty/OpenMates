// Pure normalization models for search-style embeds.
// Converts raw EmbedRecord graphs into Swift presentation data matching the
// Svelte web/images search preview and fullscreen components.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation

struct SearchSkillPreviewModel {
    let embed: EmbedRecord
    let appId: String
    let skillId: String
    let query: String
    let provider: String
    let status: EmbedStatus
    let childEmbeds: [EmbedRecord]

    var websiteResults: [WebsiteResultModel] {
        childEmbeds.compactMap(WebsiteResultModel.init(embed:))
    }

    var imageResults: [ImageSearchResultModel] {
        childEmbeds.compactMap(ImageSearchResultModel.init(embed:))
    }

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        let typeParts = embed.type.split(separator: ":")
        let inferredAppId = typeParts.count >= 2 && typeParts[0] == "app" ? String(typeParts[1]) : nil
        let inferredSkillId = typeParts.count >= 3 && typeParts[0] == "app" ? String(typeParts[2]) : nil
        self.embed = embed
        appId = embed.appId ?? EmbedFieldReader.string(raw, keys: ["app_id"]) ?? inferredAppId ?? "web"
        skillId = embed.skillId ?? EmbedFieldReader.string(raw, keys: ["skill_id"]) ?? inferredSkillId ?? "search"
        query = EmbedFieldReader.string(raw, keys: ["query", "title"]) ?? EmbedType(rawValue: embed.type)?.displayName ?? skillId
        let fallbackProvider = appId == "images" ? "Brave" : "Brave Search"
        provider = EmbedFieldReader.string(raw, keys: ["provider"]).map(Self.displayProvider) ?? fallbackProvider
        status = embed.status
        childEmbeds = Self.resolveChildren(for: embed, appId: appId, allEmbedRecords: allEmbedRecords)
    }

    private static func displayProvider(_ provider: String) -> String {
        provider == "Brave" ? "Brave Search" : provider
    }

    private static func resolveChildren(
        for embed: EmbedRecord,
        appId: String,
        allEmbedRecords: [String: EmbedRecord]
    ) -> [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return deduplicated(explicit) }

        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        if !parented.isEmpty { return deduplicated(parented) }

        let fallback = allEmbedRecords.values
            .filter { child in
                guard child.id != embed.id else { return false }
                let type = EmbedType(rawValue: child.type)
                switch appId {
                case "web", "news":
                    return type == .webWebsite
                case "images", "photos":
                    return type == .imagesImageResult || type == .image
                default:
                    return child.appId == appId
                }
            }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        return deduplicated(fallback)
    }

    private static func deduplicated(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { seen.insert($0.id).inserted }
    }
}

struct WebsiteResultModel: Identifiable {
    let id: String
    let embed: EmbedRecord
    let title: String
    let url: String
    let sourceDomain: String
    let faviconURL: String?
    let previewImageURL: String?
    let snippet: String?
    let pageAge: String?

    init?(embed: EmbedRecord) {
        let raw = embed.rawData ?? [:]
        let resolvedURL = EmbedFieldReader.string(raw, keys: ["url"])
        guard let resolvedURL, !resolvedURL.isEmpty else { return nil }
        id = embed.id
        self.embed = embed
        url = resolvedURL
        sourceDomain = EmbedFieldReader.host(from: resolvedURL) ?? resolvedURL
        title = EmbedFieldReader.string(raw, keys: ["title", "site_name", "profile_name"]) ?? sourceDomain
        faviconURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: ["meta_url_favicon", "favicon_url", "favicon", "meta_url.favicon"]),
            maxWidth: 64
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: resolvedURL)
        previewImageURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: [
                "thumbnail_original", "thumbnail_src", "thumbnail_url",
                "thumbnail.original", "thumbnail.src", "preview_image_url",
                "image", "image_url", "meta_image", "og_image"
            ]),
            maxWidth: 1024
        )
        snippet = EmbedFieldReader.strippedHTML(
            EmbedFieldReader.string(raw, keys: ["snippet", "description", "meta_description", "summary"])
        )
        pageAge = EmbedFieldReader.string(raw, keys: ["page_age", "age", "data_date", "date", "published_date"])
    }
}

struct ImageSearchResultModel: Identifiable {
    let id: String
    let embed: EmbedRecord
    let title: String?
    let sourceDomain: String
    let imageURL: String?
    let thumbnailURL: String?
    let faviconURL: String?
    let sourcePageURL: String?

    init?(embed: EmbedRecord) {
        let raw = embed.rawData ?? [:]
        let image = EmbedFieldReader.string(raw, keys: ["image_url", "image", "url"])
        let thumbnail = EmbedFieldReader.string(raw, keys: ["thumbnail_url", "thumbnail_original", "thumbnail"])
        guard image != nil || thumbnail != nil else { return nil }
        id = embed.id
        self.embed = embed
        title = EmbedFieldReader.string(raw, keys: ["title", "name"])
        sourcePageURL = EmbedFieldReader.string(raw, keys: ["source_page_url", "url"])
        sourceDomain = EmbedFieldReader.string(raw, keys: ["source", "source_domain"])
            ?? EmbedFieldReader.host(from: sourcePageURL)
            ?? "Image"
        imageURL = EmbedFieldReader.proxiedImageURL(image, maxWidth: 1024)
        thumbnailURL = EmbedFieldReader.proxiedImageURL(thumbnail ?? image, maxWidth: 520)
        faviconURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: ["favicon_url", "favicon", "meta_url_favicon", "meta_url.favicon"]),
            maxWidth: 64
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: sourcePageURL)
    }
}

enum EmbedFieldReader {
    static func string(_ raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if key.contains("."),
               let value = nestedString(raw, path: key) {
                return value
            }
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
            if let value = raw[key]?.value as? Int {
                return String(value)
            }
            if key == "meta_url_favicon",
               let favicon = nestedString(raw, path: "meta_url.favicon") {
                return favicon
            }
        }
        return nil
    }

    static func host(from value: String?) -> String? {
        guard let value, let url = URL(string: value), let host = url.host else { return nil }
        return host.replacingOccurrences(of: "www.", with: "")
    }

    static func strippedHTML(_ text: String?) -> String? {
        guard let text, !text.isEmpty else { return nil }
        let withoutTags = text.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        let decoded = withoutTags
            .replacingOccurrences(of: "\\\"", with: "\"")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return decoded.isEmpty ? nil : decoded
    }

    static func proxiedImageURL(_ rawURL: String?, maxWidth: Int) -> String? {
        guard let rawURL, !rawURL.isEmpty else { return nil }
        if shouldLoadDirectly(rawURL) {
            return rawURL
        }
        if rawURL.hasPrefix("https://preview.openmates.org/api/v1/image")
            || rawURL.hasPrefix("data:")
            || rawURL.hasPrefix("/") {
            return rawURL
        }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/image")
        components?.queryItems = [
            URLQueryItem(name: "url", value: rawURL),
            URLQueryItem(name: "max_width", value: "\(maxWidth)")
        ]
        return components?.url?.absoluteString ?? rawURL
    }

    static func proxiedFaviconURL(pageURL: String?) -> String? {
        guard let pageURL, !pageURL.isEmpty else { return nil }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/favicon")
        components?.queryItems = [URLQueryItem(name: "url", value: pageURL)]
        return components?.url?.absoluteString
    }

    private static func shouldLoadDirectly(_ rawURL: String) -> Bool {
        guard let host = URL(string: rawURL)?.host?.lowercased() else { return false }
        return host == "imgs.search.brave.com"
    }

    private static func nestedString(_ raw: [String: AnyCodable], path: String) -> String? {
        let parts = path.split(separator: ".").map(String.init)
        guard let first = parts.first else { return nil }
        var current: Any? = raw[first]?.value
        for part in parts.dropFirst() {
            if let dict = current as? [String: Any] {
                current = dict[part]
            } else if let dict = current as? [String: AnyCodable] {
                current = dict[part]?.value
            } else {
                return nil
            }
        }
        if let value = current as? String, !value.isEmpty {
            return value
        }
        return nil
    }
}
