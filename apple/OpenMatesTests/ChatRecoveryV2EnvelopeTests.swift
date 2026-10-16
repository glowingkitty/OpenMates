// Exact synthetic vector from backend/tests/fixtures/chat_recovery_output_v2.json
// at published dev c8e961da9281a85667208d05b446d03f7964d4a2. Kept inline like
// v1 recovery fixtures so this test needs no private runtime or bundle resource.
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

final class ChatRecoveryV2EnvelopeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.privacy.ciphertext-boundary
    func testPublishedSharedFixtureDecryptsExactPlaintext() throws {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Self.fixtureData)
        let opened = try fixture.envelope.open(recoveryPrivateKey: fixture.recoveryPrivateKey, identity: fixture.identity)
        XCTAssertEqual(opened, Data(fixture.plaintext.utf8))
        XCTAssertEqual(String(data: opened, encoding: .utf8), #"{"content":"sealed child output"}"#)
        let aad = try fixture.identity.associatedData()
        XCTAssertEqual(aad.prefix(5), Data("OMCR2".utf8))
        XCTAssertEqual(aad.count, 242)
        XCTAssertEqual(aad.suffix(8), Data([0, 0, 0, 7, 0, 0, 0, 1]))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary
    func testEveryAuthenticatedIdentityFieldRejectsTampering() throws {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Self.fixtureData)
        let original = try fixtureObject()["identity"] as! [String: Any]
        for field in ["owner_id", "root_chat_id", "target_chat_id", "turn_id", "record_id",
                      "subject_id", "output_kind", "key_version", "output_version"] {
            var changed = original
            if field.hasSuffix("_version") { changed[field] = (original[field] as! Int) + 1 }
            else if field == "subject_id" || field == "output_kind" { changed[field] = "changed-identity" }
            else { changed[field] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }
            // These are otherwise valid identities. The AEAD must reject them.
            let identity = try decode(ChatRecoveryV2Envelope.Identity.self, object: changed)
            XCTAssertThrowsError(try fixture.envelope.open(recoveryPrivateKey: fixture.recoveryPrivateKey, identity: identity), field)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary
    func testCanonicalIdentityAndPositiveUInt32VersionsAreRequired() throws {
        let original = try fixtureObject()["identity"] as! [String: Any]
        for field in ["owner_id", "root_chat_id", "target_chat_id", "turn_id", "record_id"] {
            for value in ["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "not-a-uuid", "{aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa}"] {
                var changed = original; changed[field] = value
                XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.Identity.self, object: changed), field)
            }
        }
        for field in ["key_version", "output_version"] {
            let invalidVersions: [Any] = [0, -1, UInt64(UInt32.max) + 1, 1.5, true, "1"]
            for value in invalidVersions {
                var changed = original; changed[field] = value
                XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.Identity.self, object: changed), field)
            }
        }
        for field in ["subject_id", "output_kind"] {
            var changed = original; changed[field] = ""
            XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.Identity.self, object: changed), field)
        }
        var extra = original; extra["legacy_job_id"] = "unpublished"
        XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.Identity.self, object: extra))
        var missing = original; missing.removeValue(forKey: "target_chat_id")
        XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.Identity.self, object: missing))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary
    func testEnvelopeIsV2OnlyAndRejectsMalformedShape() throws {
        let original = try fixtureObject()["envelope"] as! [String: Any]
        let invalidVersions: [Any] = [0, 1, 3, -1, UInt64(UInt32.max) + 1, 2.5, true, "2"]
        for value in invalidVersions {
            var changed = original; changed["v"] = value
            XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: changed))
        }
        var extra = original; extra["content"] = "plaintext"
        XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: extra))
        for field in ["v", "epk", "nonce", "ciphertext"] {
            var missing = original; missing.removeValue(forKey: field)
            XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: missing))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary
    func testEnvelopeRejectsNoncanonicalBase64URLAndInvalidLengths() throws {
        let original = try fixtureObject()["envelope"] as! [String: Any]
        for field in ["epk", "nonce", "ciphertext"] {
            let valid = original[field] as! String
            let invalid = ["", valid + "=", valid + "\n", " " + valid, "+" + valid.dropFirst(), "/" + valid.dropFirst(), "A"]
            for value in invalid {
                var changed = original; changed[field] = value
                XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: changed), field)
            }
        }
        // The final 'o' of this 32-byte epk has unused low bits. 'p' decodes
        // the same bytes in permissive decoders but is not canonical encoding.
        var noncanonical = original
        noncanonical["epk"] = String((original["epk"] as! String).dropLast()) + "p"
        XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: noncanonical))
        for (field, lengths) in [("epk", [31, 33]), ("nonce", [11, 13]), ("ciphertext", [1, 15])] {
            for length in lengths {
                var changed = original; changed[field] = encodeURL(Data(repeating: 1, count: length))
                XCTAssertThrowsError(try decode(ChatRecoveryV2Envelope.self, object: changed), field)
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary
    func testCryptographicTamperingAndInvalidPrivateKeysNeverReturnPlaintext() throws {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Self.fixtureData)
        let original = try fixtureObject()["envelope"] as! [String: Any]
        for field in ["epk", "nonce", "ciphertext"] {
            var bytes = decodeURL(original[field] as! String)
            bytes[bytes.count - 1] ^= 1
            var changed = original; changed[field] = encodeURL(bytes)
            let envelope = try decode(ChatRecoveryV2Envelope.self, object: changed)
            XCTAssertThrowsError(try envelope.open(recoveryPrivateKey: fixture.recoveryPrivateKey, identity: fixture.identity), field)
        }
        var zeroKey = original; zeroKey["epk"] = encodeURL(Data(repeating: 0, count: 32))
        let invalid = try decode(ChatRecoveryV2Envelope.self, object: zeroKey)
        XCTAssertThrowsError(try invalid.open(recoveryPrivateKey: fixture.recoveryPrivateKey, identity: fixture.identity))
        for key in ["", fixture.recoveryPrivateKey + "=", fixture.recoveryPrivateKey + "\n",
                    encodeURL(Data(repeating: 1, count: 31)), encodeURL(Data(repeating: 1, count: 33)),
                    encodeURL(Data(repeating: 1, count: 32))] {
            XCTAssertThrowsError(try fixture.envelope.open(recoveryPrivateKey: key, identity: fixture.identity))
        }
        let noncanonicalKey = String(fixture.recoveryPrivateKey.dropLast()) + "x"
        XCTAssertThrowsError(try fixture.envelope.open(recoveryPrivateKey: noncanonicalKey, identity: fixture.identity))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testAADPrefixesUTF8ByteLengthsRatherThanCharacterCounts() throws {
        var identity = try fixtureObject()["identity"] as! [String: Any]
        identity["subject_id"] = "猫🧪"
        let decoded = try decode(ChatRecoveryV2Envelope.Identity.self, object: identity)
        let aad = try decoded.associatedData()
        let subjectOffset = 5 + 5 * (4 + 36)
        XCTAssertEqual(aad.subdata(in: subjectOffset..<(subjectOffset + 4)), Data([0, 0, 0, 7]))
        XCTAssertEqual(aad.subdata(in: (subjectOffset + 4)..<(subjectOffset + 11)), Data("猫🧪".utf8))
    }

    private struct Fixture: Decodable {
        let recoveryPrivateKey: String
        let identity: ChatRecoveryV2Envelope.Identity
        let plaintext: String
        let envelope: ChatRecoveryV2Envelope
        enum CodingKeys: String, CodingKey {
            case recoveryPrivateKey = "recovery_private_key", identity, plaintext, envelope
        }
    }

    private func fixtureObject() throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Self.fixtureData) as? [String: Any])
    }
    private func decode<T: Decodable>(_ type: T.Type, object: [String: Any]) throws -> T {
        try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
    private func encodeURL(_ bytes: Data) -> String {
        bytes.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
    private func decodeURL(_ value: String) -> Data {
        let base64 = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        return Data(base64Encoded: base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4))!
    }

    private static let fixtureData = Data(#"""
    {
      "recovery_private_key": "gpeKnanRKoU2GGJGmwWqkaJGbdENwoYEB-juL6eHGQw",
      "identity": {
        "owner_id": "11111111-1111-4111-8111-111111111111",
        "root_chat_id": "22222222-2222-4222-8222-222222222222",
        "target_chat_id": "99999999-9999-4999-8999-999999999999",
        "turn_id": "33333333-3333-4333-8333-333333333333",
        "record_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "subject_id": "child-output-1",
        "output_kind": "message",
        "output_version": 1,
        "key_version": 7
      },
      "plaintext": "{\"content\":\"sealed child output\"}",
      "envelope": {
        "v": 2,
        "epk": "AQmRm95-KoLyT5E5vucEKjQCkRAtn2K9o2x-tGsMeWo",
        "nonce": "l16dsWf_cGsC30N-",
        "ciphertext": "yOcslQqtQypJO-2Lr4AVoZlf3SyOuGJfXBu79q3XcsoMLTkvfIv0NXmmNDPMalCK7Q"
      }
    }
    """#.utf8)
}
