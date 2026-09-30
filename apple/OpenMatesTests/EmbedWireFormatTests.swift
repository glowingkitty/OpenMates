import XCTest
@testable import OpenMates

final class EmbedWireFormatTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testBackendSheetAliasAndQuotedToonScalarsHydrateMultilineTable() throws {
        let table = "| Name | Note |\n| --- | --- |\n| Ada | A \\\"quoted\\\" path \\\\ |"
        let encodedTable = String(decoding: try JSONEncoder().encode(table), as: UTF8.self)
        let fields = EmbedRecord.parseContent("type: sheet\ntitle: Team\ntable: \(encodedTable)")
        XCTAssertEqual(fields["table"] as? String, table)
        XCTAssertEqual(EmbedType.normalized(rawValue: "sheet"), .sheetsSheet)
        let record = EmbedRecord(id: "synthetic-sheet", type: "sheet", status: .finished, data: nil,
                                 parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil, createdAt: nil)
            .decryptedCopy(content: "type: sheet\ntitle: Team\ntable: \(encodedTable)", type: "sheet")
        XCTAssertEqual(record.type, EmbedType.sheetsSheet.rawValue)
        let parsed = ParsedSheetTable(data: record.rawData)
        XCTAssertEqual(parsed.headers, ["Name", "Note"])
        XCTAssertEqual(parsed.rows.count, 1)
    }
}
