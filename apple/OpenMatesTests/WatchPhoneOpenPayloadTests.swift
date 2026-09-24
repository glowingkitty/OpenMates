import Foundation
import XCTest
@testable import OpenMates

final class WatchPhoneOpenPayloadTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testItemRoundTripContainsOnlyOpaqueRoutingFields() throws {
        let item = try XCTUnwrap(WatchItemOpenRequest(kind: .task, id: "task-123"))
        let payload = WatchPhoneOpenPayload.item(item, serverProfileId: "development")
        XCTAssertEqual(Set(payload.message.keys), Set(["kind", "item_kind", "item_id", "server_profile_id"]))
        XCTAssertEqual(WatchPhoneOpenPayload.parse(payload.message), payload)
        XCTAssertNil(payload.message["title"])
        XCTAssertNil(payload.message["url"])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testExactTaskAndWorkflowDestinationsStrictlyEncodeID() throws {
        let id = "a/b ?#% é"
        let task = try XCTUnwrap(WatchItemOpenRequest(kind: .task, id: id))
        let workflow = try XCTUnwrap(WatchItemOpenRequest(kind: .workflow, id: id))
        XCTAssertEqual(
            WatchPhoneOpenPayload.item(task, serverProfileId: "development")
                .destination(currentProfile: .development)?.absoluteString,
            "https://app.dev.openmates.org/tasks/a%2Fb%20%3F%23%25%20%C3%A9"
        )
        XCTAssertEqual(
            WatchPhoneOpenPayload.item(workflow, serverProfileId: "development")
                .destination(currentProfile: .development)?.absoluteString,
            "https://app.dev.openmates.org/workflows#workflow-id=a%2Fb%20%3F%23%25%20%C3%A9&workflow-tab=details"
        )
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testSettingsAndCollectionDestinationsUseCurrentWebOrigin() {
        let profile = ServerProfile.custom(domain: "app.selfhosted.example")
        XCTAssertEqual(
            WatchPhoneOpenPayload.settings(serverProfileId: profile.id)
                .destination(currentProfile: profile)?.absoluteString,
            "https://app.selfhosted.example/#settings"
        )
        XCTAssertEqual(
            WatchPhoneOpenPayload.collection(.task, serverProfileId: profile.id)
                .destination(currentProfile: profile)?.absoluteString,
            "https://app.selfhosted.example/tasks"
        )
        XCTAssertEqual(
            WatchPhoneOpenPayload.collection(.workflow, serverProfileId: profile.id)
                .destination(currentProfile: profile)?.absoluteString,
            "https://app.selfhosted.example/workflows"
        )
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testRejectsMalformedAndWrongProfileMessages() throws {
        let item = try XCTUnwrap(WatchItemOpenRequest(kind: .task, id: "task-123"))
        let valid = WatchPhoneOpenPayload.item(item, serverProfileId: "development")
        XCTAssertNil(valid.destination(currentProfile: .production))

        var malformed = valid.message
        malformed["url"] = "https://example.invalid/private"
        XCTAssertNil(WatchPhoneOpenPayload.parse(malformed))
        malformed = valid.message
        malformed["item_id"] = "bad\nidentifier"
        XCTAssertNil(WatchPhoneOpenPayload.parse(malformed))
        malformed = valid.message
        malformed["server_profile_id"] = ""
        XCTAssertNil(WatchPhoneOpenPayload.parse(malformed))
        malformed = WatchPhoneOpenPayload.settings(serverProfileId: "development").message
        malformed["item_id"] = "unexpected"
        XCTAssertNil(WatchPhoneOpenPayload.parse(malformed))
    }
}
