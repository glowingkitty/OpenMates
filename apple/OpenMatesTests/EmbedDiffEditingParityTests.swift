// Unit coverage for native embed version-history parity.
// These tests are deterministic and avoid network, credentials, or private
// persisted content. They guard the REST/sync model contract used by the native
// fullscreen timeline.

import XCTest
@testable import OpenMates

final class EmbedDiffEditingParityTests: XCTestCase {
    func testEmbedRecordDecodesVersionMetadataFromWebPayload() throws {
        let json = """
        {
          "embed_id": "embed-1",
          "type": "code",
          "status": "finished",
          "version_number": 3,
          "content_hash": "hash-v3",
          "version_history_readonly": true,
          "version_history": [
            { "version_number": 1, "created_at": 1760000000, "has_snapshot": true, "has_patch": false, "content_hash": "hash-v1" },
            { "version_number": 2, "created_at": 1760000100, "has_snapshot": false, "has_patch": true },
            { "version_number": 3, "created_at": 1760000200, "has_snapshot": false, "has_patch": true, "content_hash": "hash-v3" }
          ],
          "content": "{\"type\":\"code\",\"code\":\"print(1)\"}"
        }
        """.data(using: .utf8)!

        let record = try JSONDecoder().decode(EmbedRecord.self, from: json)

        XCTAssertEqual(record.id, "embed-1")
        XCTAssertEqual(record.versionNumber, 3)
        XCTAssertEqual(record.contentHash, "hash-v3")
        XCTAssertTrue(record.versionHistoryReadonly)
        XCTAssertEqual(record.versionHistory.map(\.versionNumber), [1, 2, 3])
        XCTAssertEqual(record.versionHistory.first?.hasSnapshot, true)
        XCTAssertEqual(record.versionHistory.last?.contentHash, "hash-v3")
    }

    func testRestoreRequestEncodesSnakeCaseContract() throws {
        let request = EmbedVersionRestoreRequest(embedId: "embed-1", versionNumber: 1)
        let data = try JSONEncoder().encode(request)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(object?["embed_id"] as? String, "embed-1")
        XCTAssertEqual(object?["version_number"] as? Int, 1)
    }
}
