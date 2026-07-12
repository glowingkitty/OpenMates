// Cross-runtime chat completion recovery cryptographic vector tests.
// Values mirror backend/tests/fixtures/chat_completion_recovery_vectors.json.
// The fixture is encoded here because it is outside the Apple test resources.
// All values are deterministic synthetic test material, never production data.
// Exact byte matching guards HKDF, X25519, AES-GCM, base64url, and AAD parity.

import CryptoKit
import XCTest
@testable import OpenMates

final class ChatCompletionRecoveryTests: XCTestCase {
    func testSharedCryptoVectors() async throws {
        let vector = RecoveryVector.shared
        let chatKey = SymmetricKey(data: try decodeBase64URL(vector.chatKey))

        let keyPair = try await CryptoManager.shared.deriveRecoveryKeyPair(
            chatKey: chatKey,
            chatId: vector.chatId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(keyPair.privateKey, vector.recoveryPrivateKey)
        XCTAssertEqual(keyPair.publicKey, vector.recoveryPublicKey)

        let associatedData = try await CryptoManager.shared.buildRecoveryAssociatedData(
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(encodeBase64URL(associatedData), vector.associatedData)

        let envelope = try await CryptoManager.shared.sealRecoveryPayload(
            Data(vector.plaintext.utf8),
            recoveryPublicKey: vector.recoveryPublicKey,
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion,
            ephemeralPrivateKey: vector.ephemeralPrivateKey,
            nonce: vector.nonce
        )
        XCTAssertEqual(envelope.v, 1)
        XCTAssertEqual(envelope.epk, vector.ephemeralPublicKey)
        XCTAssertEqual(envelope.nonce, vector.nonce)
        XCTAssertEqual(envelope.ciphertext, vector.ciphertext)

        let plaintext = try await CryptoManager.shared.openRecoveryEnvelope(
            envelope,
            recoveryPrivateKey: keyPair.privateKey,
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(plaintext, Data(vector.plaintext.utf8))
    }

    func testSharedCryptoVectorsRejectTampering() async throws {
        let vector = RecoveryVector.shared
        let fields = ["ciphertext", "nonce", "epk"]

        for field in fields {
            let envelope = CryptoManager.RecoveryEnvelope(
                v: 1,
                epk: field == "epk" ? tamper(vector.ephemeralPublicKey) : vector.ephemeralPublicKey,
                nonce: field == "nonce" ? tamper(vector.nonce) : vector.nonce,
                ciphertext: field == "ciphertext" ? tamper(vector.ciphertext) : vector.ciphertext
            )
            do {
                _ = try await CryptoManager.shared.openRecoveryEnvelope(
                    envelope,
                    recoveryPrivateKey: vector.recoveryPrivateKey,
                    ownerId: vector.ownerId,
                    chatId: vector.chatId,
                    turnId: vector.turnId,
                    jobId: vector.jobId,
                    assistantMessageId: vector.assistantMessageId,
                    keyVersion: vector.keyVersion
                )
                XCTFail("Expected \(field) tampering to fail")
            } catch {
                // Authentication or strict input validation must reject the envelope.
            }
        }

        let validEnvelope = CryptoManager.RecoveryEnvelope(
            v: 1,
            epk: vector.ephemeralPublicKey,
            nonce: vector.nonce,
            ciphertext: vector.ciphertext
        )
        do {
            _ = try await CryptoManager.shared.openRecoveryEnvelope(
                validEnvelope,
                recoveryPrivateKey: vector.recoveryPrivateKey,
                ownerId: vector.ownerId,
                chatId: vector.chatId,
                turnId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                jobId: vector.jobId,
                assistantMessageId: vector.assistantMessageId,
                keyVersion: vector.keyVersion
            )
            XCTFail("Expected associated-data tampering to fail")
        } catch {
            // Authentication must bind the stable recovery identities.
        }
    }

    private func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func decodeBase64URL(_ value: String) throws -> Data {
        var base64 = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        base64.append(String(repeating: "=", count: (4 - base64.count % 4) % 4))
        return try XCTUnwrap(Data(base64Encoded: base64))
    }

    private func tamper(_ value: String) -> String {
        let replacement = value.first == "A" ? "B" : "A"
        return replacement + String(value.dropFirst())
    }
}

private struct RecoveryVector {
    let chatKey: String
    let ownerId: String
    let chatId: String
    let turnId: String
    let jobId: String
    let assistantMessageId: String
    let keyVersion: UInt32
    let recoveryPrivateKey: String
    let recoveryPublicKey: String
    let ephemeralPrivateKey: String
    let ephemeralPublicKey: String
    let associatedData: String
    let nonce: String
    let plaintext: String
    let ciphertext: String

    // Source: backend/tests/fixtures/chat_completion_recovery_vectors.json,
    // vector "sequential-key-existing-chat-v1".
    static let shared = RecoveryVector(
        chatKey: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        ownerId: "11111111-1111-4111-8111-111111111111",
        chatId: "22222222-2222-4222-8222-222222222222",
        turnId: "33333333-3333-4333-8333-333333333333",
        jobId: "44444444-4444-4444-8444-444444444444",
        assistantMessageId: "55555555-5555-4555-8555-555555555555",
        keyVersion: 7,
        recoveryPrivateKey: "gpeKnanRKoU2GGJGmwWqkaJGbdENwoYEB-juL6eHGQw",
        recoveryPublicKey: "52h8oPfO4CzxXUVGx6abkertndIuIwYD6xGwerS9dAc",
        ephemeralPrivateKey: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
        ephemeralPublicKey: "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ",
        associatedData: "T01DUjEAAAAkMTExMTExMTEtMTExMS00MTExLTgxMTEtMTExMTExMTExMTExAAAAJDIyMjIyMjIyLTIyMjItNDIyMi04MjIyLTIyMjIyMjIyMjIyMgAAACQzMzMzMzMzMy0zMzMzLTQzMzMtODMzMy0zMzMzMzMzMzMzMzMAAAAkNDQ0NDQ0NDQtNDQ0NC00NDQ0LTg0NDQtNDQ0NDQ0NDQ0NDQ0AAAAJDU1NTU1NTU1LTU1NTUtNDU1NS04NTU1LTU1NTU1NTU1NTU1NQAAAAc",
        nonce: "AAECAwQFBgcICQoL",
        plaintext: "{\"assistant_message_id\":\"55555555-5555-4555-8555-555555555555\",\"chat_id\":\"22222222-2222-4222-8222-222222222222\",\"content\":\"Recovered hello\",\"job_id\":\"44444444-4444-4444-8444-444444444444\",\"key_version\":7,\"turn_id\":\"33333333-3333-4333-8333-333333333333\"}",
        ciphertext: "I-wuvO5hWgfrssqM8SYZ7Ah8j2VaKaG9k4dXSnECLD7H07S2odaMlDIl1p5BwUUn0_qOoBoLPzdPiPttqTTNN7aD43Fwebbzt-Ol8kxBVuwGfBwYQFVfVrjgMokd6aMPJlhhT8tV91ugFSeYyzW4IWl7rpgDWUbhFc4bOu84fxABXBWumc2DApYuXb-4iieU7fawubxy0e2tBvHWLP9UQSS5-NxoXfNVqgM29kxHaJtZJrENGlptRyiiIbaSZBfdJMoJF8o7nC7DQq_dzTw-yeegyejjgGQvllYWtVLKM_QAtkCF3pQ3MqiEy-d1CeBgQ1mXcaQFhq3oTLT9VJ3DXM8a0_ZwtVE6KQvqodE"
    )
}
