import XCTest
@testable import OpenMates

final class MemoriesParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=app-memories.selection.source-scoped
    func testCountLabelUsesSingularForOneEntry() {
        XCTAssertEqual(MemoryConsentCountFormat.text(selected: 1, total: 1, singular: "entry", plural: "entries"), "1/1 entry")
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.selection.source-scoped
    func testCountLabelShowsSelectedOfTotalPlural() {
        XCTAssertEqual(MemoryConsentCountFormat.text(selected: 2, total: 3, singular: "entry", plural: "entries"), "2/3 entries")
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.selection.source-scoped
    func testCountLabelZeroSelectedIsPlural() {
        XCTAssertEqual(MemoryConsentCountFormat.text(selected: 0, total: 0, singular: "entry", plural: "entries"), "0/0 entries")
    }
}
