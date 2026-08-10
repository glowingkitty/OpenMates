// Cross-client encryption contract tests for the native Apple composer.
// The shared JSON contains deterministic synthetic keys and nonces only.
// Existing CryptoManager APIs prove web-compatible Formats A, C, and D.
// ComposerEmbedCrypto is the intentionally missing internal red-test seam.
// No production identity, content, credential, or secret is used here.

import CryptoKit
import XCTest
@testable import OpenMates

final class NativeComposerEncryptionCompatibilityTests: XCTestCase {
    func testCryptoManagerDecryptsWebFormatAFields() async throws {
        let fixture = try loadFixture()
        let chatKey = SymmetricKey(data: try decode(fixture.keys.chatKeyBase64))

        let message = try await CryptoManager.shared.decryptContent(
            base64String: fixture.formatA.message.ciphertextBase64,
            key: chatKey
        )
        let piiMappings = try await CryptoManager.shared.decryptContent(
            base64String: fixture.formatA.piiMappings.ciphertextBase64,
            key: chatKey
        )
        let embedReference = try await CryptoManager.shared.decryptContent(
            base64String: fixture.formatA.embedReference.ciphertextBase64,
            key: chatKey
        )

        XCTAssertEqual(message, fixture.plaintext.canonicalMessagePlaintext)
        XCTAssertEqual(piiMappings, fixture.plaintext.piiMappingsJSON)
        XCTAssertEqual(embedReference, fixture.plaintext.embedReferenceJSON)
    }

    func testCryptoManagerDecryptsWebFormatCAndFormatD() async throws {
        let fixture = try loadFixture()
        let masterKey = SymmetricKey(data: try decode(fixture.keys.masterKeyBase64))
        let expectedChatKey = try decode(fixture.keys.chatKeyBase64)

        let unwrappedChatKey = try await CryptoManager.shared.unwrapChatKey(
            encryptedChatKeyBase64: fixture.formatC.wrappedChatKeyBase64,
            masterKey: masterKey
        )
        let draft = try await CryptoManager.shared.decryptContent(
            base64String: fixture.formatD.draft.ciphertextBase64,
            key: masterKey
        )
        let preview = try await CryptoManager.shared.decryptContent(
            base64String: fixture.formatD.preview.ciphertextBase64,
            key: masterKey
        )

        XCTAssertEqual(rawData(unwrappedChatKey), expectedChatKey)
        XCTAssertEqual(draft, fixture.plaintext.canonicalDraftMarkdown)
        XCTAssertEqual(preview, fixture.plaintext.draftPreview)
    }

    func testFormatARejectsWrongExistingChatKeyWithoutReplacement() async throws {
        let fixture = try loadFixture()
        let wrongKey = SymmetricKey(data: try decode(fixture.keys.wrongKeyBase64))

        do {
            _ = try await CryptoManager.shared.decryptContent(
                base64String: fixture.formatA.message.ciphertextBase64,
                key: wrongKey
            )
            XCTFail("A wrong existing-chat key must not decrypt or trigger replacement-key generation")
        } catch {
            XCTAssertFalse(error.localizedDescription.isEmpty)
        }
    }

    func testComposerEmbedCryptoMatchesWebHKDFAndWrappingVectors() throws {
        let fixture = try loadFixture()
        let masterKey = SymmetricKey(data: try decode(fixture.keys.masterKeyBase64))
        let chatKey = SymmetricKey(data: try decode(fixture.keys.chatKeyBase64))
        let expectedEmbedKey = try decode(fixture.embed.derivedKeyBase64)

        let derivedKey = ComposerEmbedCrypto.deriveKey(
            chatKey: chatKey,
            embedId: fixture.embed.id
        )
        XCTAssertEqual(rawData(derivedKey), expectedEmbedKey)
        XCTAssertEqual(
            rawData(try ComposerEmbedCrypto.unwrapKey(
                fixture.embed.masterWrappedKey.ciphertextBase64,
                using: masterKey
            )),
            expectedEmbedKey
        )
        XCTAssertEqual(
            rawData(try ComposerEmbedCrypto.unwrapKey(
                fixture.embed.chatWrappedKey.ciphertextBase64,
                using: chatKey
            )),
            expectedEmbedKey
        )
        XCTAssertEqual(
            try ComposerEmbedCrypto.decryptContent(
                fixture.embed.encryptedContent.ciphertextBase64,
                using: derivedKey
            ),
            fixture.embed.contentPlaintext
        )
    }

    func testFixtureIsExplicitlySyntheticAndCiphertextOmitsPlaintext() throws {
        let fixture = try loadFixture()
        let fixtureData = try Data(contentsOf: fixtureURL())
        let serialized = try XCTUnwrap(String(data: fixtureData, encoding: .utf8))

        XCTAssertEqual(fixture.schemaVersion, 1)
        XCTAssertTrue(fixture.syntheticNotice.contains("composer-fixture.invalid"))
        XCTAssertTrue(fixture.embed.id.hasSuffix(".invalid"))
        XCTAssertFalse(fixture.formatA.message.ciphertextBase64.contains(fixture.plaintext.canonicalMessagePlaintext))
        XCTAssertFalse(fixture.formatD.draft.ciphertextBase64.contains(fixture.plaintext.canonicalDraftMarkdown))
        XCTAssertFalse(serialized.contains("BEGIN PRIVATE KEY"))
        XCTAssertFalse(serialized.contains("Bearer "))
    }

    private func loadFixture() throws -> ComposerEncryptionFixture {
        try JSONDecoder().decode(
            ComposerEncryptionFixture.self,
            from: Data(contentsOf: fixtureURL())
        )
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("shared/composer/fixtures/apple-composer-encryption-v1.json")
    }

    private func decode(_ value: String) throws -> Data {
        try XCTUnwrap(Data(base64Encoded: value))
    }

    private func rawData(_ key: SymmetricKey) -> Data {
        key.withUnsafeBytes { Data($0) }
    }
}

private struct ComposerEncryptionFixture: Decodable {
    let schemaVersion: Int
    let syntheticNotice: String
    let keys: FixtureKeys
    let plaintext: FixturePlaintext
    let formatA: FixtureFormatA
    let formatC: FixtureFormatC
    let formatD: FixtureFormatD
    let embed: FixtureEmbed

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case syntheticNotice = "synthetic_notice"
        case keys, plaintext, embed
        case formatA = "format_a"
        case formatC = "format_c"
        case formatD = "format_d"
    }
}

private struct FixtureKeys: Decodable {
    let masterKeyBase64: String
    let chatKeyBase64: String
    let wrongKeyBase64: String

    enum CodingKeys: String, CodingKey {
        case masterKeyBase64 = "master_key_base64"
        case chatKeyBase64 = "chat_key_base64"
        case wrongKeyBase64 = "wrong_key_base64"
    }
}

private struct FixturePlaintext: Decodable {
    let canonicalDraftMarkdown: String
    let draftPreview: String
    let canonicalMessagePlaintext: String
    let piiMappingsJSON: String
    let embedReferenceJSON: String

    enum CodingKeys: String, CodingKey {
        case canonicalDraftMarkdown = "canonical_draft_markdown"
        case draftPreview = "draft_preview"
        case canonicalMessagePlaintext = "canonical_message_plaintext"
        case piiMappingsJSON = "pii_mappings_json"
        case embedReferenceJSON = "embed_reference_json"
    }
}

private struct FixtureFormatA: Decodable {
    let message: FixtureCipherVector
    let piiMappings: FixtureCipherVector
    let embedReference: FixtureCipherVector

    enum CodingKeys: String, CodingKey {
        case message
        case piiMappings = "pii_mappings"
        case embedReference = "embed_reference"
    }
}

private struct FixtureFormatC: Decodable {
    let wrappedChatKeyBase64: String

    enum CodingKeys: String, CodingKey {
        case wrappedChatKeyBase64 = "wrapped_chat_key_base64"
    }
}

private struct FixtureFormatD: Decodable {
    let draft: FixtureCipherVector
    let preview: FixtureCipherVector
}

private struct FixtureEmbed: Decodable {
    let id: String
    let contentPlaintext: String
    let derivedKeyBase64: String
    let masterWrappedKey: FixtureCipherVector
    let chatWrappedKey: FixtureCipherVector
    let encryptedContent: FixtureCipherVector

    enum CodingKeys: String, CodingKey {
        case id
        case contentPlaintext = "content_plaintext"
        case derivedKeyBase64 = "derived_key_base64"
        case masterWrappedKey = "master_wrapped_key"
        case chatWrappedKey = "chat_wrapped_key"
        case encryptedContent = "encrypted_content"
    }
}

private struct FixtureCipherVector: Decodable {
    let ciphertextBase64: String

    enum CodingKeys: String, CodingKey {
        case ciphertextBase64 = "ciphertext_base64"
    }
}
