import XCTest
@testable import OpenMates

@MainActor
final class ProjectCreateFileEntriesTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.items.create-documents
    func testEntriesUseWebOrderAndTestIDs() {
        XCTAssertEqual(ProjectCreateFileEntry.all.map(\.identifier), [
            "project-create-document", "project-create-sheet", "project-create-slides", "project-create-code",
        ])
        XCTAssertEqual(ProjectCreateFileEntry.all.map(\.kind.rawValue), ["document", "sheet", "slides", "code"])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.items.create-documents
    func testDraftPrefillsDefaultNameAndTrimsSubmission() {
        var draft = ProjectCreateFileDraft()
        XCTAssertNil(draft.submission)
        draft.choose(.sheet, defaultName: "Untitled sheet")
        XCTAssertEqual(draft.pending, .sheet)
        XCTAssertEqual(draft.submission?.name, "Untitled sheet")
        draft.name = "  Budget  "
        XCTAssertEqual(draft.submission?.kind, .sheet)
        XCTAssertEqual(draft.submission?.name, "Budget")
        draft.name = "   "
        XCTAssertNil(draft.submission)
        draft.cancel()
        XCTAssertNil(draft.pending)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.items.create-documents
    func testCoreWireKindsMatchTheCoreContract() {
        XCTAssertEqual(ProjectDocumentKind.allCases.map(\.rawValue), ["document", "sheet", "slides", "code"])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.items.create-documents
    func testProjectFileClientWithoutCoreThrowsNoCore() async {
        let client = CoreProjectFiles(sessionProvider: { nil })
        do {
            _ = try await client.createProjectFile(projectId: "p", teamId: nil, kind: .code, name: "a.py", folderId: nil)
            XCTFail("expected noCore")
        } catch {
            XCTAssertEqual(error as? ProjectFileCreateError, .noCore)
        }
    }
}
