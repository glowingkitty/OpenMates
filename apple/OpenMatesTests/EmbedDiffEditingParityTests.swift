// Unit coverage for native embed version-history parity.
// These tests are deterministic and avoid network, credentials, or private
// persisted content. They guard the REST/sync model contract used by the native
// fullscreen timeline.

import XCTest
@testable import OpenMates

final class EmbedDiffEditingParityTests: XCTestCase {
    func testRelatedRecordsDeduplicateLatestPayloadWhilePreservingFirstSeenOrder() throws {
        let parent = embed(
            id: "parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "child-one|child-two"
        )
        let staleChild = embed(id: "child-one", type: "web-website", data: ["title": "Stale"])
        let secondChild = embed(id: "child-two", type: "web-website", data: ["title": "Second"])
        let currentChild = embed(id: "child-one", type: "web-website", data: ["title": "Current"])

        let related = EmbedRecord.relatedRecords(
            referencedIds: [parent.id],
            from: [parent, staleChild, secondChild, currentChild],
            context: "test.relatedRecords.deduplication"
        )

        XCTAssertEqual(related.map(\.id), ["parent", "child-one", "child-two"])
        XCTAssertEqual(related[1].rawData?["title"]?.value as? String, "Current")
    }

    func testRelatedRecordsResolveParentAndChildrenFromEitherRelationshipDirection() throws {
        let parent = embed(
            id: "parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "declared-child"
        )
        let declaredChild = embed(id: "declared-child", type: "web-website")
        let reverseLinkedChild = embed(
            id: "reverse-child",
            type: "web-website",
            parentEmbedId: parent.id
        )

        let fromParent = EmbedRecord.relatedRecords(
            referencedIds: [parent.id],
            from: [parent, declaredChild, reverseLinkedChild],
            context: "test.relatedRecords.fromParent"
        )
        let fromChild = EmbedRecord.relatedRecords(
            referencedIds: [reverseLinkedChild.id],
            from: [parent, declaredChild, reverseLinkedChild],
            context: "test.relatedRecords.fromChild"
        )

        XCTAssertEqual(fromParent.map(\.id), ["parent", "declared-child", "reverse-child"])
        XCTAssertEqual(fromChild.map(\.id), ["parent", "declared-child", "reverse-child"])
    }

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
          "content": "{}"
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

    private func embed(
        id: String,
        type: String,
        data: [String: Any] = [:],
        parentEmbedId: String? = nil,
        embedIds: String? = nil
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: .finished,
            data: data.isEmpty ? nil : .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: nil,
            skillId: nil,
            embedIds: embedIds,
            createdAt: nil
        )
    }
}
