import XCTest
@testable import OpenMates

final class APIResponseDecodingDiagnosticsTests: XCTestCase {
    private struct Key: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testDiagnosticsReportSchemaFieldAndRejectDynamicKeysAndDebugValues() {
        let context = DecodingError.Context(codingPath: [Key(stringValue: "tasks"), Key(stringValue: "private-record-id"), Key(stringValue: "status")],
                                           debugDescription: "Private response and token contents")
        let summary = APIResponseDecodingDiagnostics.summary(error: DecodingError.dataCorrupted(context), responseType: TaskBoardRecord.self)
        XCTAssertTrue(summary.contains("failure=dataCorrupted"))
        XCTAssertTrue(summary.contains("field_path=tasks.field.status"))
        XCTAssertFalse(summary.contains("private-record-id"))
        XCTAssertFalse(summary.contains("Private response"))
        XCTAssertFalse(summary.contains("token contents"))
    }
}
