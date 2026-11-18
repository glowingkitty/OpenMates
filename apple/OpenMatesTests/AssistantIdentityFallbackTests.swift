import XCTest
@testable import OpenMates

final class AssistantIdentityFallbackTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=video-call.chat.assistant-identity
    func testMissingOrUnknownCategoryUsesOpenMatesIdentity() {
        XCTAssertTrue(ChatAssistantIdentityPolicy.usesOpenMatesIdentity(category: nil))
        XCTAssertTrue(ChatAssistantIdentityPolicy.usesOpenMatesIdentity(category: "retired_mate"))
        XCTAssertTrue(ChatAssistantIdentityPolicy.usesOpenMatesIdentity(category: "openmates_official"))
        XCTAssertFalse(ChatAssistantIdentityPolicy.usesOpenMatesIdentity(category: "software_development"))
        XCTAssertEqual(ChatAssistantIdentityPolicy.explicitDisplayName("  Ada "), "Ada")
        XCTAssertNil(ChatAssistantIdentityPolicy.explicitDisplayName("assistant"))
    }
}
