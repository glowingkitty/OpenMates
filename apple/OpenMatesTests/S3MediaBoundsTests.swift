// Synthetic encrypted README media and lazy streams; no network or owner state.
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class S3MediaBoundsTests: XCTestCase {
    private let imageLimit = 2 * 1024 * 1024
    private let key = Data(repeating: 3, count: 32)
    private let nonce = Data(repeating: 5, count: 12)

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testExactPlaintextBoundaryWorksForLegacyAndNoncePrefixedMedia() async throws {
        for prefixed in [false, true] {
            let plaintext = Data(repeating: 7, count: imageLimit)
            let ciphertext = try encrypt(plaintext, prefixed: prefixed)
            let limits = S3BoundsLimitReceipt()
            let client = S3MediaClient(encryptedDataLoader: { _, _ in throw URLError(.badURL) },
                boundedEncryptedDataLoader: { _, _, maximum in
                    await limits.append(maximum)
                    return ciphertext
                })
            let result = try await client.fetchAndDecryptBounded(s3Url: "", aesKeyHex: key.base64EncodedString(),
                aesNonceHex: prefixed ? nil : nonce.base64EncodedString(),
                encryption: prefixed ? S3MediaClient.noncePrefixedEncryption : nil,
                s3Key: "synthetic-readme-image", maximumPlaintextBytes: imageLimit)
            XCTAssertEqual(result, plaintext)
            let passedLimits = await limits.values
            XCTAssertEqual(passedLimits, [imageLimit + (prefixed ? 28 : 16)])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testOversizedStoredMediaIsRejectedBeforeKeyValidationAndDecryption() async throws {
        for prefixed in [false, true] {
            let ciphertext = try encrypt(Data(repeating: 7, count: imageLimit + 1), prefixed: prefixed)
            let client = S3MediaClient(encryptedDataLoader: { _, _ in throw URLError(.badURL) },
                boundedEncryptedDataLoader: { _, _, _ in ciphertext })
            do {
                _ = try await client.fetchAndDecryptBounded(s3Url: "", aesKeyHex: "deliberately-invalid-key",
                    aesNonceHex: prefixed ? nil : nonce.base64EncodedString(),
                    encryption: prefixed ? S3MediaClient.noncePrefixedEncryption : nil,
                    s3Key: "synthetic-readme-image", maximumPlaintextBytes: imageLimit)
                XCTFail("Oversized ciphertext must fail before decryption starts")
            } catch { XCTAssertEqual((error as? URLError)?.code, .dataLengthExceedsMaximum) }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testUnknownLengthStreamStopsBeforeAccumulatingBeyondLimit() async throws {
        let counter = S3BoundsByteSource(count: 1_000_000)
        let stream = AsyncStream<UInt8>(unfolding: { await counter.next() })
        do {
            _ = try await S3MediaClient.boundedResponseData(stream, response: response(), maximumBytes: 8)
            XCTFail("Unknown-length ciphertext must be stopped at its byte limit")
        } catch { XCTAssertEqual((error as? URLError)?.code, .dataLengthExceedsMaximum) }
        let reads = await counter.reads
        XCTAssertEqual(reads, 9, "Read only one overflow byte to detect the limit")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testDeclaredOversizeIsRejectedBeforeConsumingAnyBytes() async throws {
        let counter = S3BoundsByteSource(count: 16)
        let stream = AsyncStream<UInt8>(unfolding: { await counter.next() })
        do {
            _ = try await S3MediaClient.boundedResponseData(stream, response: response(length: 16), maximumBytes: 8)
            XCTFail("Declared oversized ciphertext must fail before reading")
        } catch { XCTAssertEqual((error as? URLError)?.code, .dataLengthExceedsMaximum) }
        let reads = await counter.reads
        XCTAssertEqual(reads, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testUnknownLengthExactBoundarySucceedsAndLimitMathFailsClosed() async throws {
        let counter = S3BoundsByteSource(count: 8)
        let data = try await S3MediaClient.boundedResponseData(
            AsyncStream<UInt8>(unfolding: { await counter.next() }), response: response(), maximumBytes: 8)
        XCTAssertEqual(data.count, 8)
        for invalid in [0, -1, Int.max, Int.max - 27] {
            XCTAssertThrowsError(try S3MediaClient.ciphertextLimit(maximumPlaintextBytes: invalid,
                encodedNonce: nil, encryption: nil))
        }
        XCTAssertThrowsError(try S3MediaClient.ciphertextLimit(maximumPlaintextBytes: 8,
            encodedNonce: nil, encryption: "unknown-encryption"))
    }

    private func encrypt(_ plaintext: Data, prefixed: Bool) throws -> Data {
        let sealed = try AES.GCM.seal(plaintext, using: SymmetricKey(data: key), nonce: AES.GCM.Nonce(data: nonce))
        return (prefixed ? nonce : Data()) + sealed.ciphertext + sealed.tag
    }
    private func response(length: Int? = nil) -> HTTPURLResponse {
        HTTPURLResponse(url: URL(string: "https://media.example.org/synthetic")!, statusCode: 200,
            httpVersion: nil, headerFields: length.map { ["Content-Length": "\($0)"] })!
    }
}

private actor S3BoundsLimitReceipt {
    private(set) var values: [Int] = []
    func append(_ value: Int) { values.append(value) }
}

private actor S3BoundsByteSource {
    let count: Int
    private(set) var reads = 0
    init(count: Int) { self.count = count }
    func next() -> UInt8? {
        reads += 1
        return reads <= count ? 1 : nil
    }
}
