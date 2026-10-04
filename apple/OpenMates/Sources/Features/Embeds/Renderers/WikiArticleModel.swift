// Wikipedia identity, wire summary and per-request publication fence.
// Web: frontend/packages/ui/src/components/embeds/wiki/WikipediaFullscreen.svelte
//      frontend/packages/ui/src/components/embeds/wiki/WikiInlineLink.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import Foundation

struct WikiArticleIdentity: Hashable {
    let title: String
    let language: String

    init(title: String, language: String = "en") {
        self.title = title.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "_", with: " ")
        let code = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            .replacingOccurrences(of: "_", with: "-").split(separator: "-").first.map(String.init) ?? "en"
        self.language = Self.languages.contains(code) ? code : "en"
    }

    init(data: [String: AnyCodable], fallbackLanguage: String = "en") {
        let sourceURL = (data["url"]?.value as? String).flatMap(Self.articleURL)
        let sourceLanguage = sourceURL?.host?.split(separator: ".").first.map(String.init)
        self.init(title: (data["wiki_title"]?.value as? String)
            ?? sourceURL.map { String($0.path.dropFirst("/wiki/".count)) }
            ?? (data["title"]?.value as? String) ?? "",
            language: (data["language"]?.value as? String) ?? sourceLanguage ?? fallbackLanguage)
    }

    static let languages: Set<String> = ["en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
        "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"]

    var pageURL: URL? {
        guard !title.isEmpty else { return nil }
        // An article title is one path value: slash, query and fragment syntax
        // in titles must never change the external destination or API query.
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        guard let encoded = title.replacingOccurrences(of: " ", with: "_")
            .addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
        return URL(string: "https://\(language).wikipedia.org/wiki/\(encoded)")
    }

    var summaryPath: String {
        var components = URLComponents()
        components.path = "/v1/wikipedia/summary"
        components.queryItems = [.init(name: "title", value: title), .init(name: "language", value: language)]
        components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        return components.string ?? ""
    }

    static func articleURL(_ value: String) -> URL? {
        guard let url = URL(string: value), url.scheme == "https", url.user == nil, url.password == nil,
              url.port == nil, let host = url.host?.lowercased(),
              host.hasSuffix(".wikipedia.org"), url.path.hasPrefix("/wiki/"),
              host.split(separator: ".").count == 3 else { return nil }
        return url
    }

    func inlineRecord() -> EmbedRecord {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in "\(language):\(title)".utf8 { hash ^= UInt64(byte); hash &*= 1_099_511_628_211 }
        var data: [String: AnyCodable] = ["title": AnyCodable(title), "wiki_title": AnyCodable(title),
            "language": AnyCodable(language)]
        if let pageURL { data["url"] = AnyCodable(pageURL.absoluteString) }
        return EmbedRecord(id: "wiki-\(String(hash, radix: 16))", type: EmbedType.wiki.rawValue,
            status: .finished, data: .raw(data), parentEmbedId: nil, appId: EmbedType.wiki.appId,
            skillId: nil, embedIds: nil, createdAt: nil)
    }
}

struct WikiArticleSummary: Decodable {
    let title: String?
    let description: String?
    let extract: String?
    let thumbnail: ImageSource?
    let originalImage: ImageSource?
    let contentURLs: ContentURLs?

    struct ImageSource: Decodable { let source: String? }
    struct ContentURLs: Decodable {
        let desktop: PageURL?
        struct PageURL: Decodable { let page: String? }
    }
    enum CodingKeys: String, CodingKey {
        case title, description, extract, thumbnail
        case originalImage = "originalimage"
        case contentURLs = "content_urls"
    }
    var imageURL: String? { originalImage?.source ?? thumbnail?.source }
    var pageURL: URL? { contentURLs?.desktop?.page.flatMap(WikiArticleIdentity.articleURL) }

    static func proxiedImageURL(_ value: String?, webBaseURL: URL) -> URL? {
        guard let raw = value?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty,
              raw.hasPrefix("/") && !raw.hasPrefix("//") ||
                URL(string: raw).map({ $0.scheme == "https" && $0.host != nil && $0.user == nil && $0.password == nil }) == true,
              let proxied = EmbedFieldReader.proxiedImageURL(raw, maxWidth: 1024, webBaseURL: webBaseURL)
        else { return nil }
        return URL(string: proxied)
    }

    static func decode(_ data: Data) throws -> Self {
        // Preserve Wikimedia's wire keys, independent of APIClient's shared
        // convertFromSnakeCase decoder used for ordinary API models.
        try JSONDecoder().decode(Self.self, from: data)
    }
}

struct WikiArticleLoadState {
    private(set) var identity: WikiArticleIdentity?
    private(set) var requestID: UUID?
    private(set) var article: WikiArticleSummary?
    private(set) var isLoading = false
    private(set) var failed = false

    mutating func begin(_ identity: WikiArticleIdentity) -> UUID {
        self.identity = identity
        let request = UUID(); requestID = request
        article = nil; failed = false; isLoading = true
        return request
    }

    mutating func finish(_ article: WikiArticleSummary?, request: UUID, failed: Bool = false) {
        guard requestID == request else { return }
        self.article = article; self.failed = failed; isLoading = false
    }

    func article(for identity: WikiArticleIdentity) -> WikiArticleSummary? {
        self.identity == identity ? article : nil
    }
}
