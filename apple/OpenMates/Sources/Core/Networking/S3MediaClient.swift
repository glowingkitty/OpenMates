// S3 encrypted media download and decryption client.
// Handles downloading AES-encrypted media files (images, audio, PDFs)
// from S3, decrypting them with embed-specific keys, and caching results.

import Foundation
import CryptoKit

actor S3MediaClient {
    static let shared = S3MediaClient()

    private var cache: [String: Data] = [:]
    private var inFlight: [String: Task<Data, Error>] = [:]
    private let diskCache = MediaDiskCache(directoryName: "s3-media")

    private init() {}

    func fetchAndDecrypt(
        s3Url: String,
        aesKeyHex: String,
        aesNonceHex: String,
        s3Key: String? = nil
    ) async throws -> Data {
        let cacheKey = s3Key ?? s3Url

        if let cached = cache[cacheKey] {
            return cached
        }
        if let cached = try? diskCache.load(cacheKey: cacheKey) {
            cache[cacheKey] = cached
            return cached
        }

        if let existing = inFlight[cacheKey] {
            return try await existing.value
        }

        let task = Task<Data, Error> {
            let encryptedData = try await Self.downloadFromS3(url: s3Url, s3Key: s3Key)
            return try Self.decryptAESGCM(
                data: encryptedData,
                encodedKey: aesKeyHex,
                encodedNonce: aesNonceHex
            )
        }

        inFlight[cacheKey] = task
        do {
            let decrypted = try await task.value
            cache[cacheKey] = decrypted
            try? diskCache.save(decrypted, cacheKey: cacheKey)
            inFlight.removeValue(forKey: cacheKey)
            return decrypted
        } catch {
            inFlight.removeValue(forKey: cacheKey)
            throw error
        }
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

    private static func decryptAESGCM(data: Data, encodedKey: String, encodedNonce: String) throws -> Data {
        let keyData = decodeKeyMaterial(encodedKey)

        guard keyData.count == 32 else { throw S3Error.invalidKey }

        let key = SymmetricKey(data: keyData)

        let tagLength = 16
        let nonceLength = 12
        guard data.count > tagLength else { throw S3Error.dataTooShort }

        let nonceData: Data
        let encryptedBody: Data.SubSequence
        if encodedNonce.isEmpty {
            guard data.count > nonceLength + tagLength else { throw S3Error.dataTooShort }
            nonceData = data.prefix(nonceLength)
            encryptedBody = data.dropFirst(nonceLength)
        } else {
            nonceData = decodeKeyMaterial(encodedNonce)
            guard nonceData.count == nonceLength else { throw S3Error.invalidNonce }
            encryptedBody = data[...]
        }

        let nonce = try AES.GCM.Nonce(data: nonceData)

        let ciphertext = encryptedBody.prefix(encryptedBody.count - tagLength)
        let tag = encryptedBody.suffix(tagLength)

        let sealedBox = try AES.GCM.SealedBox(nonce: nonce, ciphertext: ciphertext, tag: tag)
        return try AES.GCM.open(sealedBox, using: key)
    }

    private static func decodeKeyMaterial(_ value: String) -> Data {
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
        guard let files = raw["files"]?.value as? [String: Any] else { return nil }
        if let original = files["original"] as? [String: Any], let key = original["s3_key"] as? String {
            return key
        }
        for value in files.values {
            if let variant = value as? [String: Any], let key = variant["s3_key"] as? String {
                return key
            }
        }
        return nil
    }
}

actor RemoteImageCache {
    static let shared = RemoteImageCache()

    private var memoryCache: [String: Data] = [:]
    private var inFlight: [String: Task<Data, Error>] = [:]
    private let diskCache = MediaDiskCache(directoryName: "remote-images")

    private init() {}

    func data(for urlString: String) async -> Data? {
        if let cached = memoryCache[urlString] {
            guard !Self.isClearlyInvalidImageData(cached) else {
                memoryCache.removeValue(forKey: urlString)
                return nil
            }
            return cached
        }
        if let cached = try? diskCache.load(cacheKey: urlString) {
            guard !Self.isClearlyInvalidImageData(cached) else {
                return nil
            }
            memoryCache[urlString] = cached
            return cached
        }
        return nil
    }

    func fetch(_ urlString: String) async throws -> Data {
        if let cached = await data(for: urlString) {
            return cached
        }
        if let existing = inFlight[urlString] {
            return try await existing.value
        }
        let task = Task<Data, Error> {
            try await Self.download(urlString)
        }
        inFlight[urlString] = task
        do {
            let data = try await task.value
            memoryCache[urlString] = data
            try? diskCache.save(data, cacheKey: urlString)
            inFlight.removeValue(forKey: urlString)
            return data
        } catch {
            inFlight.removeValue(forKey: urlString)
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

    private static func download(_ urlString: String) async throws -> Data {
        guard let url = URL(string: urlString) else { throw S3Error.invalidURL }
        let (data, response) = try await URLSession.shared.data(from: url)
        if let httpResponse = response as? HTTPURLResponse,
           (200...299).contains(httpResponse.statusCode),
           isRenderableImage(data, response: httpResponse) {
            return data
        }
        if let originalURL = originalImageURL(fromProxyURL: urlString) {
            return try await download(originalURL)
        }
        throw S3Error.downloadFailed
    }

    private static func originalImageURL(fromProxyURL urlString: String) -> String? {
        guard let components = URLComponents(string: urlString),
              components.host == "preview.openmates.org",
              components.path == "/api/v1/image",
              let original = components.queryItems?.first(where: { $0.name == "url" })?.value,
              original != urlString else {
            return nil
        }
        return original
    }

    private static func isRenderableImage(_ data: Data, response: HTTPURLResponse) -> Bool {
        guard !data.isEmpty else { return false }
        if response.mimeType?.lowercased().hasPrefix("image/") == true {
            return true
        }
        return data.starts(with: [0xFF, 0xD8, 0xFF])
            || data.starts(with: [0x89, 0x50, 0x4E, 0x47])
            || data.starts(with: [0x47, 0x49, 0x46])
            || data.starts(with: [0x52, 0x49, 0x46, 0x46])
    }

    private static func isClearlyInvalidImageData(_ data: Data) -> Bool {
        guard !data.isEmpty else { return true }
        let prefix = String(decoding: data.prefix(80), as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return prefix.hasPrefix("<!doctype html")
            || prefix.hasPrefix("<html")
            || prefix.hasPrefix("{\"detail\"")
    }
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
            if let s3URL = EmbedMediaPayload.s3URL(from: raw),
               let aesKey = firstString(in: raw, keys: ["aes_key"]),
               let aesNonce = firstString(in: raw, keys: ["aes_nonce"]) {
                _ = try? await S3MediaClient.shared.fetchAndDecrypt(
                    s3Url: s3URL,
                    aesKeyHex: aesKey,
                    aesNonceHex: aesNonce
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

private struct MediaDiskCache {
    let directoryName: String

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
        let base = try FileManager.default.url(
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

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid S3 URL"
        case .downloadFailed: return "Failed to download media"
        case .invalidKey: return "Invalid encryption key"
        case .invalidNonce: return "Invalid encryption nonce"
        case .dataTooShort: return "Encrypted data too short"
        case .decryptionFailed: return "Media decryption failed"
        }
    }
}
