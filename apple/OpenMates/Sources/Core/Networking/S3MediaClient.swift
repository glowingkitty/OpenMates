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
        aesNonceHex: String
    ) async throws -> Data {
        let cacheKey = s3Url

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
            let encryptedData = try await Self.downloadFromS3(url: s3Url)
            return try Self.decryptAESGCM(
                data: encryptedData,
                keyHex: aesKeyHex,
                nonceHex: aesNonceHex
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

    private static func downloadFromS3(url urlString: String) async throws -> Data {
        guard let url = URL(string: urlString) else {
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

    private static func decryptAESGCM(data: Data, keyHex: String, nonceHex: String) throws -> Data {
        let keyData = Data(hexString: keyHex)
        let nonceData = Data(hexString: nonceHex)

        guard keyData.count == 32 else { throw S3Error.invalidKey }
        guard nonceData.count == 12 else { throw S3Error.invalidNonce }

        let key = SymmetricKey(data: keyData)
        let nonce = try AES.GCM.Nonce(data: nonceData)

        let tagLength = 16
        guard data.count > tagLength else { throw S3Error.dataTooShort }

        let ciphertext = data.prefix(data.count - tagLength)
        let tag = data.suffix(tagLength)

        let sealedBox = try AES.GCM.SealedBox(nonce: nonce, ciphertext: ciphertext, tag: tag)
        return try AES.GCM.open(sealedBox, using: key)
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
            return cached
        }
        if let cached = try? diskCache.load(cacheKey: urlString) {
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
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw S3Error.downloadFailed
        }
        return data
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
            if let s3URL = firstString(in: raw, keys: ["s3_url", "s3_base_url"]),
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
