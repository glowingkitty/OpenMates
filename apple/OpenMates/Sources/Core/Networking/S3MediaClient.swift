// S3 encrypted media download and decryption client.
// Handles downloading AES-encrypted media files (images, audio, PDFs)
// from S3, decrypting them with embed-specific keys, and caching results.

import Foundation
import CryptoKit
import ImageIO

enum S3MediaCachePolicy {
    case persistent
    /// Private document pages may only exist in the caller and an in-flight task.
    /// This path never reads or writes the shared decrypted media disk cache.
    case memoryOnly
}

actor S3MediaClient {
    static let shared = S3MediaClient()
    static let noncePrefixedEncryption = "aes-gcm-nonce-prefixed-v1"

    private var cache: [String: Data] = [:]
    private var inFlight: [String: Task<Data, Error>] = [:]
    private let diskCache: MediaDiskCache
    private let encryptedDataLoader: @Sendable (String, String?) async throws -> Data

    private init() {
        diskCache = MediaDiskCache(directoryName: "s3-media")
        encryptedDataLoader = Self.downloadFromS3
    }

    // Isolated test seam: a real encrypted payload exercises the cache policy
    // without an API request or persistent user media.
    init(diskCache: MediaDiskCache,
         encryptedDataLoader: @escaping @Sendable (String, String?) async throws -> Data) {
        self.diskCache = diskCache
        self.encryptedDataLoader = encryptedDataLoader
    }

    func fetchAndDecrypt(
        s3Url: String,
        aesKeyHex: String,
        aesNonceHex: String?,
        encryption: String? = nil,
        s3Key: String? = nil,
        cacheNamespace: String? = nil,
        cachePolicy: S3MediaCachePolicy = .persistent
    ) async throws -> Data {
        let cacheKey = Self.cacheKey(s3Url: s3Url, aesKey: aesKeyHex, nonce: aesNonceHex,
                                     encryption: encryption, s3Key: s3Key, namespace: cacheNamespace)
        let flightKey = (cachePolicy == .memoryOnly ? "memory:" : "persistent:") + cacheKey

        if cachePolicy == .persistent {
            if let cached = cache[cacheKey] {
                return cached
            }
            if let cached = try? diskCache.load(cacheKey: cacheKey) {
                cache[cacheKey] = cached
                return cached
            }
        }

        if let existing = inFlight[flightKey] {
            return try await existing.value
        }

        let task = Task<Data, Error> {
            let encryptedData = try await encryptedDataLoader(s3Url, s3Key)
            return try Self.decryptAESGCM(
                data: encryptedData,
                encodedKey: aesKeyHex,
                encodedNonce: aesNonceHex,
                encryption: encryption
            )
        }

        inFlight[flightKey] = task
        do {
            let decrypted = try await task.value
            if cachePolicy == .persistent {
                cache[cacheKey] = decrypted
                try? diskCache.save(decrypted, cacheKey: cacheKey)
            }
            inFlight.removeValue(forKey: flightKey)
            return decrypted
        } catch {
            inFlight.removeValue(forKey: flightKey)
            throw error
        }
    }

    static func cacheKey(s3Url: String, aesKey: String, nonce: String?, encryption: String?, s3Key: String?, namespace: String?) -> String {
        let mediaIdentity = s3Key ?? s3Url
        guard let namespace else { return mediaIdentity }
        let material = "\(namespace):\(mediaIdentity):\(aesKey):\(nonce ?? ""):\(encryption ?? "")"
        return SHA256.hash(data: Data(material.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func clearCache() {
        cache.removeAll()
    }

    // MARK: - Download

    private static func downloadFromS3(url urlString: String, s3Key: String?) async throws -> Data {
        let downloadURLString: String
        if let s3Key, !s3Key.isEmpty {
            let encoded = s3Key.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? s3Key
            let response: PresignedURLResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/embeds/presigned-url?s3_key=\(encoded)"
            )
            downloadURLString = response.url
        } else {
            downloadURLString = urlString
        }

        guard let url = URL(string: downloadURLString) else {
            throw S3Error.invalidURL
        }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw S3Error.downloadFailed
        }
        return data
    }

    // MARK: - Decrypt

    static func decryptAESGCM(
        data: Data,
        encodedKey: String,
        encodedNonce: String?,
        encryption: String?
    ) throws -> Data {
        let keyData = decodeKeyMaterial(encodedKey, expectedByteCount: 32)

        guard keyData.count == 32 else { throw S3Error.invalidKey }

        let key = SymmetricKey(data: keyData)

        let tagLength = 16
        let nonceLength = 12
        guard data.count > tagLength else { throw S3Error.dataTooShort }

        let nonceData: Data
        let encryptedBody: Data.SubSequence
        if let encryption, encryption != noncePrefixedEncryption {
            throw S3Error.unsupportedEncryptionMarker
        }
        if encryption == noncePrefixedEncryption || encodedNonce?.isEmpty != false {
            guard data.count > nonceLength + tagLength else { throw S3Error.dataTooShort }
            nonceData = data.prefix(nonceLength)
            encryptedBody = data.dropFirst(nonceLength)
        } else {
            nonceData = decodeKeyMaterial(encodedNonce!, expectedByteCount: nonceLength)
            guard nonceData.count == nonceLength else { throw S3Error.invalidNonce }
            encryptedBody = data[...]
        }

        let nonce = try AES.GCM.Nonce(data: nonceData)

        let ciphertext = encryptedBody.prefix(encryptedBody.count - tagLength)
        let tag = encryptedBody.suffix(tagLength)

        let sealedBox = try AES.GCM.SealedBox(nonce: nonce, ciphertext: ciphertext, tag: tag)
        return try AES.GCM.open(sealedBox, using: key)
    }

    private static func decodeKeyMaterial(_ value: String, expectedByteCount: Int) -> Data {
        if value.count == expectedByteCount * 2,
           value.utf8.allSatisfy({ byte in
               (48...57).contains(byte) || (65...70).contains(byte) || (97...102).contains(byte)
           }) {
            return Data(hexString: value)
        }
        if let base64 = Data(base64Encoded: value), !base64.isEmpty {
            return base64
        }
        return Data(hexString: value)
    }
}

private struct PresignedURLResponse: Decodable {
    let url: String
}

enum EmbedMediaPayload {
    static func s3Key(from raw: [String: AnyCodable]?) -> String? {
        guard let raw else { return nil }
        return originalS3Key(from: raw)
    }

    static func previewS3Key(from raw: [String: AnyCodable]?) -> String? {
        guard let raw else { return nil }
        return variant(from: raw, named: "preview")?["s3_key"] as? String
            ?? originalS3Key(from: raw)
    }

    static func s3URL(from raw: [String: AnyCodable]?) -> String? {
        guard let raw else { return nil }
        if let direct = string(raw, keys: ["s3_url"]), !direct.isEmpty {
            return direct
        }
        guard let base = string(raw, keys: ["s3_base_url"]), !base.isEmpty,
              let key = originalS3Key(from: raw), !key.isEmpty else {
            return nil
        }
        return base.hasSuffix("/") ? "\(base)\(key)" : "\(base)/\(key)"
    }

    static func previewS3URL(from raw: [String: AnyCodable]?) -> String? {
        guard let raw else { return nil }
        if let direct = string(raw, keys: ["preview_s3_url"]), !direct.isEmpty {
            return direct
        }
        if let base = string(raw, keys: ["s3_base_url"]), !base.isEmpty,
           let key = variant(from: raw, named: "preview")?["s3_key"] as? String,
           !key.isEmpty {
            return base.hasSuffix("/") ? "\(base)\(key)" : "\(base)/\(key)"
        }
        return s3URL(from: raw)
    }

    static func encryption(from raw: [String: AnyCodable]?) -> String? {
        if let direct = string(raw, keys: ["encryption"]) { return direct }
        if let variantMarker = originalVariant(from: raw)?["encryption"] as? String,
           !variantMarker.isEmpty {
            return variantMarker
        }

        // The upload API represents nonce-prefixed media with an empty
        // top-level `aes_nonce` and an encryption marker on each file variant.
        // Older Apple upload models did not preserve the variant marker when
        // constructing the encrypted embed. Recognize only that exact shape so
        // current uploads remain readable while absent legacy metadata still
        // fails closed.
        if let rawNonce = raw?["aes_nonce"]?.value as? String,
           rawNonce.isEmpty,
           string(raw, keys: ["aes_key"]) != nil {
            return S3MediaClient.noncePrefixedEncryption
        }
        return nil
    }

    static func string(_ raw: [String: AnyCodable]?, keys: [String]) -> String? {
        guard let raw else { return nil }
        return string(raw, keys: keys)
    }

    private static func string(_ raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private static func originalS3Key(from raw: [String: AnyCodable]) -> String? {
        originalVariant(from: raw)?["s3_key"] as? String
    }

    private static func originalVariant(from raw: [String: AnyCodable]?) -> [String: Any]? {
        guard let raw,
              let files = raw["files"]?.value as? [String: Any] else { return nil }
        if let original = files["original"] as? [String: Any] {
            return original
        }
        for value in files.values {
            if let variant = value as? [String: Any] { return variant }
        }
        return nil
    }

    private static func variant(from raw: [String: AnyCodable]?, named name: String) -> [String: Any]? {
        guard let raw,
              let files = raw["files"]?.value as? [String: Any] else { return nil }
        return files[name] as? [String: Any]
    }
}

actor RemoteImageCache {
    static let shared = RemoteImageCache()

    private struct CachedPayload { let data: Data; let isRaster: Bool }
    private var memoryCache: [String: CachedPayload] = [:]
    private var inFlight: [String: Task<Data, Error>] = [:]
    private let diskCache = MediaDiskCache(directoryName: "remote-images")

    private init() {}

    func data(for urlString: String, allowStaticSVG: Bool = false) async -> Data? {
        if let cached = memoryCache[urlString], cached.isRaster || allowStaticSVG {
            return cached.data
        }
        if let cached = try? diskCache.load(cacheKey: urlString) {
            let isRaster = Self.isDecodableImageData(cached)
            guard isRaster || (allowStaticSVG && StaticSVGImageSource(data: cached) != nil) else {
                return nil
            }
            memoryCache[urlString] = CachedPayload(data: cached, isRaster: isRaster)
            return cached
        }
        return nil
    }

    func fetch(_ urlString: String, allowStaticSVG: Bool = false) async throws -> Data {
        if let cached = await data(for: urlString, allowStaticSVG: allowStaticSVG) {
            return cached
        }
        let requestKey = allowStaticSVG ? "static-svg:\(urlString)" : urlString
        if let existing = inFlight[requestKey] {
            return try await existing.value
        }
        let task = Task<Data, Error> {
            try await Self.download(urlString, allowStaticSVG: allowStaticSVG)
        }
        inFlight[requestKey] = task
        do {
            let data = try await task.value
            memoryCache[urlString] = CachedPayload(data: data, isRaster: Self.isDecodableImageData(data))
            try? diskCache.save(data, cacheKey: urlString)
            inFlight.removeValue(forKey: requestKey)
            return data
        } catch {
            inFlight.removeValue(forKey: requestKey)
            throw error
        }
    }

    func prefetch(_ urlStrings: [String]) async {
        for urlString in Array(Set(urlStrings)).prefix(80) {
            if Task.isCancelled { return }
            if await data(for: urlString) != nil { continue }
            _ = try? await fetch(urlString)
        }
    }

    typealias ImageTransport = @Sendable (URL) async throws -> (Data, URLResponse)

    static func request(for url: URL, appWebURL: URL = ServerProfile.current().webBaseURL) -> URLRequest {
        var request = URLRequest(url: url)
        // The public preview service validates the web app's Referer. Send only
        // its origin, and only to that service's image endpoints. Other remote
        // image hosts must not learn the user's selected app domain or path.
        let imageEndpoints = ["/api/v1/image", "/api/v1/favicon"]
        if url.scheme == "https", url.host == "preview.openmates.org",
           imageEndpoints.contains(url.path),
           appWebURL.scheme == "https", let appHost = appWebURL.host,
           appHost == "openmates.org" || appHost.hasSuffix(".openmates.org") {
            request.setValue("https://\(appHost)/", forHTTPHeaderField: "Referer")
        }
        return request
    }

    static func download(
        _ urlString: String,
        allowStaticSVG: Bool = false,
        transport: ImageTransport = { try await URLSession.shared.data(for: RemoteImageCache.request(for: $0)) }
    ) async throws -> Data {
        guard let url = URL(string: urlString) else { throw S3Error.invalidURL }
        let (data, response) = try await transport(url)
        guard let response = response as? HTTPURLResponse,
              (200...299).contains(response.statusCode),
              isDecodableImageData(data) || (allowStaticSVG && StaticSVGImageSource(data: data) != nil) else {
            // Public preview proxy failure must never expose the user's IP by
            // retrying its `url` parameter against the third-party origin.
            throw S3Error.downloadFailed
        }
        return data
    }

    static func isDecodableImageData(_ data: Data) -> Bool {
        guard !data.isEmpty,
              let source = CGImageSourceCreateWithData(data as CFData,
                  [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetCount(source) > 0 else { return false }
        // Image MIME alone is insufficient: UIImage cannot display an SVG,
        // even though it legitimately has an image/svg+xml content type.
        // Avoid eagerly decoding/caching the full pixel buffer during validation.
        return CGImageSourceCreateImageAtIndex(source, 0,
            [kCGImageSourceShouldCache: false] as CFDictionary) != nil
    }

}

/// Bounded static SVGs for public image rendering. The XML allowlist is applied
/// before bytes enter the opt-in cache; raster-only consumers retain their
/// existing validation contract. WebKit renders these as an inert data image.
struct StaticSVGImageSource {
    let data: Data

    init?(data: Data) {
        guard !data.isEmpty, data.count <= 2_000_000,
              let text = String(data: data, encoding: .utf8),
              text.range(of: #"<!\s*(DOCTYPE|ENTITY)\b"#,
                         options: [.regularExpression, .caseInsensitive]) == nil else { return nil }
        let delegate = StaticSVGXMLValidator()
        let parser = XMLParser(data: data)
        parser.shouldProcessNamespaces = true
        parser.shouldResolveExternalEntities = false
        parser.delegate = delegate
        guard parser.parse(), delegate.valid, delegate.sawRoot, delegate.depth == 0 else { return nil }
        self.data = data
    }
}

private final class StaticSVGXMLValidator: NSObject, XMLParserDelegate {
    var valid = true
    var sawRoot = false
    var depth = 0
    private var elementCount = 0
    private let elements: Set<String> = ["svg", "g", "path", "rect", "circle", "ellipse", "line",
        "polyline", "polygon", "defs", "lineargradient", "radialgradient", "stop", "clippath",
        "mask", "title", "desc", "text", "tspan", "use"]
    private let attributes: Set<String> = ["xmlns", "xmlns:xlink", "id", "viewbox", "width", "height",
        "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr",
        "d", "points", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
        "stroke-opacity", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
        "stroke-dasharray", "stroke-dashoffset", "opacity", "transform", "gradienttransform",
        "gradientunits", "spreadmethod", "offset", "stop-color", "stop-opacity", "clip-path",
        "clip-rule", "clippathunits", "mask", "maskunits", "maskcontentunits", "preserveaspectratio",
        "href", "xlink:href", "font-family", "font-size", "font-weight", "text-anchor", "dx", "dy"]

    private func reject(_ parser: XMLParser) { valid = false; parser.abortParsing() }

    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?,
                qualifiedName: String?, attributes values: [String: String]) {
        depth += 1
        elementCount += 1
        guard depth <= 32, elementCount <= 4096, values.count <= 64,
              namespaceURI == "http://www.w3.org/2000/svg", elements.contains(name.lowercased()) else {
            reject(parser); return
        }
        if depth == 1 {
            guard !sawRoot, name.lowercased() == "svg" else { reject(parser); return }
            sawRoot = true
        }
        for (name, value) in values {
            let name = name.lowercased()
            guard attributes.contains(name), value.utf8.count <= 262_144 else { reject(parser); return }
            if name == "href" || name == "xlink:href" {
                guard value.range(of: #"^#[A-Za-z0-9_.:-]+$"#, options: .regularExpression) != nil else {
                    reject(parser); return
                }
            }
            // Only local paint/clip references are allowed. No CSS escape or
            // external resource URL can enter an attribute through url().
            let remainder = value.replacingOccurrences(of: #"url\(\s*#[A-Za-z0-9_.:-]+\s*\)"#,
                with: "", options: [.regularExpression, .caseInsensitive])
            if remainder.range(of: #"url\s*\(|\\"#, options: [.regularExpression, .caseInsensitive]) != nil {
                reject(parser); return
            }
        }
    }

    func parser(_ parser: XMLParser, didEndElement: String, namespaceURI: String?, qualifiedName: String?) { depth -= 1 }
    func parser(_ parser: XMLParser, foundProcessingInstructionWithTarget: String, data: String?) { reject(parser) }
    func parser(_ parser: XMLParser, parseErrorOccurred: Error) { valid = false }
}

struct EmbedMediaOfflineCache {
    static func prefetchEmbeds(_ embeds: [EmbedRecord]) {
        guard !embeds.isEmpty else { return }
        Task.detached(priority: .utility) {
            await prefetchEmbedsAsync(embeds)
        }
    }

    private static func prefetchEmbedsAsync(_ embeds: [EmbedRecord]) async {
        var remoteURLs: [String] = []
        for embed in embeds {
            guard let raw = embed.rawData else { continue }
            remoteURLs.append(contentsOf: remoteImageURLs(from: raw))
            let aesNonce = firstString(in: raw, keys: ["aes_nonce"])
            let encryption = EmbedMediaPayload.encryption(from: raw)
            if let s3URL = EmbedMediaPayload.s3URL(from: raw),
               let aesKey = firstString(in: raw, keys: ["aes_key"]),
               aesNonce != nil || encryption != nil {
                _ = try? await S3MediaClient.shared.fetchAndDecrypt(
                    s3Url: s3URL,
                    aesKeyHex: aesKey,
                    aesNonceHex: aesNonce,
                    encryption: encryption
                )
            }
        }
        await RemoteImageCache.shared.prefetch(remoteURLs)
    }

    private static func remoteImageURLs(from raw: [String: AnyCodable]) -> [String] {
        [
            "image_url", "thumbnail_url", "thumbnail_original", "preview_image_url",
            "image", "meta_image", "og_image", "favicon_url", "favicon", "meta_url_favicon"
        ].compactMap { key in
            firstString(in: raw, keys: [key])
        }.filter { value in
            guard let url = URL(string: value), let scheme = url.scheme?.lowercased() else { return false }
            return scheme == "https" || scheme == "http"
        }
    }

    private static func firstString(in raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }
}

struct MediaDiskCache {
    let directoryName: String
    var baseDirectory: URL? = nil

    func load(cacheKey: String) throws -> Data? {
        let url = try fileURL(cacheKey: cacheKey)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try Data(contentsOf: url)
    }

    func save(_ data: Data, cacheKey: String) throws {
        let directory = try cacheDirectory()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try data.write(to: try fileURL(cacheKey: cacheKey), options: .atomic)
    }

    private func fileURL(cacheKey: String) throws -> URL {
        try cacheDirectory().appendingPathComponent(sha256(cacheKey), isDirectory: false)
    }

    private func cacheDirectory() throws -> URL {
        let base = try baseDirectory ?? FileManager.default.url(
            for: .cachesDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent("OpenMatesMediaCache", isDirectory: true)
            .appendingPathComponent(directoryName, isDirectory: true)
    }

    private func sha256(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}

enum S3Error: LocalizedError {
    case invalidURL
    case downloadFailed
    case invalidKey
    case invalidNonce
    case dataTooShort
    case decryptionFailed
    case unsupportedEncryptionMarker

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid S3 URL"
        case .downloadFailed: return "Failed to download media"
        case .invalidKey: return "Invalid encryption key"
        case .invalidNonce: return "Invalid encryption nonce"
        case .dataTooShort: return "Encrypted data too short"
        case .decryptionFailed: return "Media decryption failed"
        case .unsupportedEncryptionMarker: return "Unsupported media encryption marker"
        }
    }
}
