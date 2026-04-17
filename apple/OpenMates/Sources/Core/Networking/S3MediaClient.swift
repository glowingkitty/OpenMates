// S3 encrypted media download and decryption client.
// Handles downloading AES-encrypted media files (images, audio, PDFs)
// from S3, decrypting them with embed-specific keys, and caching results.

import Foundation
import CryptoKit

actor S3MediaClient {
    static let shared = S3MediaClient()

    private var cache: [String: Data] = [:]
    private var inFlight: [String: Task<Data, Error>] = [:]

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

        if let existing = inFlight[cacheKey] {
            return try await existing.value
        }

        let task = Task<Data, Error> {
            let encryptedData = try await downloadFromS3(url: s3Url)
            let decrypted = try decryptAESGCM(
                data: encryptedData,
                keyHex: aesKeyHex,
                nonceHex: aesNonceHex
            )
            cache[cacheKey] = decrypted
            inFlight.removeValue(forKey: cacheKey)
            return decrypted
        }

        inFlight[cacheKey] = task
        return try await task.value
    }

    func clearCache() {
        cache.removeAll()
    }

    // MARK: - Download

    private func downloadFromS3(url urlString: String) async throws -> Data {
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

    private func decryptAESGCM(data: Data, keyHex: String, nonceHex: String) throws -> Data {
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
