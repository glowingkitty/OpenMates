import XCTest
@testable import OpenMates

/// Project Specifications model: failures are shown, approval names exactly the viewed
/// current revision and its content hash, older revisions cannot be approved, and the
/// reader keeps requirements no chapter references.
@MainActor
final class ProjectSpecificationsModelTests: XCTestCase {
    private final class RecordingLoader: ProjectSpecificationsLoading {
        let inner = ProjectSpecificationsPreviewLoader()
        var failList = false
        var failApprove = false
        var approvals: [(String, String)] = []

        func list(projectId: String, teamId: String?) async throws -> [ProjectSpecificationListItem] {
            if failList { throw ProjectSpecificationsError.noCore }
            return try await inner.list(projectId: projectId, teamId: teamId)
        }
        func open(projectId: String, teamId: String?, specificationId: String, revisionId: String?) async throws
            -> ProjectSpecificationOpened {
            try await inner.open(projectId: projectId, teamId: teamId, specificationId: specificationId,
                                 revisionId: revisionId)
        }
        func approve(projectId: String, teamId: String?, specificationId: String, revisionId: String,
                     contentHash: String) async throws {
            if failApprove { throw ProjectSpecificationsError.noCore }
            approvals.append((revisionId, contentHash))
            try await inner.approve(projectId: projectId, teamId: teamId, specificationId: specificationId,
                                    revisionId: revisionId, contentHash: contentHash)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=contracts.surface.semantic-parity
    func testLoadFailureIsShownAndRetrySucceeds() async {
        let loader = RecordingLoader()
        loader.failList = true
        let model = ProjectSpecificationsModel(loader: loader, projectId: "p", teamId: nil)
        await model.load()
        XCTAssertTrue(model.loadFailed)
        XCTAssertFalse(model.loaded)
        loader.failList = false
        await model.load()
        XCTAssertFalse(model.loadFailed)
        XCTAssertEqual(model.items.map(\.id), ["spec-recipes"])
        XCTAssertEqual(model.items.first?.proofStale, 1)
    }

    // contract-test: direct surface=gui.apple assertions=contracts.revision.exact-approval
    func testApprovalNamesTheViewedCurrentRevisionAndHash() async {
        let loader = RecordingLoader()
        let model = ProjectSpecificationsModel(loader: loader, projectId: "p", teamId: nil)
        await model.open("spec-recipes")
        XCTAssertEqual(model.opened?.approvalState, "stale")
        XCTAssertEqual(model.opened?.canApprove, true)

        await model.selectRevision("rev-1")
        XCTAssertEqual(model.opened?.viewedRevisionId, "rev-1")
        XCTAssertEqual(model.opened?.canApprove, false, "An older revision is read-only")
        await model.approveViewed()
        XCTAssertTrue(loader.approvals.isEmpty)

        await model.selectRevision("rev-2")
        await model.approveViewed()
        XCTAssertEqual(loader.approvals.map(\.0), ["rev-2"])
        XCTAssertEqual(loader.approvals.map(\.1), ["hash-2"])
        XCTAssertEqual(model.opened?.approvalState, "approved")
        XCTAssertEqual(model.opened?.isApproved, true)
        XCTAssertEqual(model.items.first?.status, "approved")
    }

    // contract-test: supporting surface=gui.apple assertions=contracts.revision.exact-approval
    func testApproveFailureIsShownAndStateUnchanged() async {
        let loader = RecordingLoader()
        loader.failApprove = true
        let model = ProjectSpecificationsModel(loader: loader, projectId: "p", teamId: nil)
        await model.open("spec-recipes")
        await model.approveViewed()
        XCTAssertTrue(model.actionFailed)
        XCTAssertEqual(model.opened?.approvalState, "stale")
    }

    // contract-test: direct surface=gui.apple assertions=contracts.ui.human-readable-default
    func testUnreferencedRequirementsGetATrailingChapter() async throws {
        let opened = try await ProjectSpecificationsPreviewLoader()
            .open(projectId: "p", teamId: nil, specificationId: "spec-recipes", revisionId: "rev-2")
        let chapters = opened.document.displayChapters(otherTitle: "Other requirements")
        XCTAssertEqual(chapters.map(\.id), ["search", "shopping", "unassigned"])
        XCTAssertEqual(chapters.last?.requirementIds, ["recipes.list.share"])
        XCTAssertEqual(chapters.last?.title, "Other requirements")
        XCTAssertEqual(opened.sortedRevisions.map(\.number), [2, 1])
    }
}
