// Support remains a contact surface without creating provider payment orders.
import XCTest
@testable import OpenMates

@MainActor
final class SettingsSupportParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testSupportContactUsesTeamEmailWithoutPrivatePrefilledData() throws {
        let url = try XCTUnwrap(SettingsSupportView.contactURL)
        XCTAssertEqual(url.scheme, "mailto")
        XCTAssertEqual(url.path, "support@openmates.org")
        XCTAssertEqual(SettingsSupportView.contactEmail, url.path)
        XCTAssertNil(url.query, "Contact must not prefill account or conversation data")
        XCTAssertNil(url.fragment)
    }
}
