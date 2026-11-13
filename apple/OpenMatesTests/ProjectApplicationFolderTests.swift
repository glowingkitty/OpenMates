// Tests of the Project browser tree (`ProjectBrowserTree`): an adopted
// application is listed first inside its folder, hosted files group into
// virtual folders with direct-children rows, and nothing leaks across folders.
// Web counterpart: frontend/packages/ui/src/services/projectBrowserTree.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.files.application-single-source, projects.surface.semantic-parity
import XCTest
@testable import OpenMates

final class ProjectApplicationFolderTests: XCTestCase {
    private func item(_ id: String, source: String, path: String, kind: String = "embed") -> ProjectWorkspaceItem {
        ProjectWorkspaceItem(id: id, kind: kind, targetID: "t-\(id)", name: id,
                             metadata: ["source": source, "path": path],
                             folderHash: nil, position: 0, createdAt: 0)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.application-single-source
    func testApplicationCardLeadsItsFolderAheadOfFiles() {
        let items = [item("file", source: "hosted_project_file", path: "web-app/index.html"),
                     item("app", source: "project_application", path: "web-app")]
        let root = ProjectBrowserTree.view(items: items, virtualPath: nil)
        XCTAssertEqual(root.folders.map(\.path), ["web-app"])
        XCTAssertTrue(root.items.isEmpty)
        let folder = ProjectBrowserTree.view(items: items, virtualPath: "web-app")
        XCTAssertEqual(folder.items.map(\.id), ["app", "file"])
        XCTAssertTrue(folder.folders.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testFolderCardListsDirectChildrenFoldersFirst() {
        let items = [item("a", source: "hosted_project_file", path: "web-app/b.txt"),
                     item("b", source: "hosted_project_file", path: "web-app/src/main.ts"),
                     item("c", source: "project_application", path: "web-app/inner")]
        let root = ProjectBrowserTree.view(items: items, virtualPath: nil)
        XCTAssertEqual(root.folders.first?.children,
                       [ProjectVirtualFolderChild(name: "inner", isFolder: true),
                        ProjectVirtualFolderChild(name: "src", isFolder: true),
                        ProjectVirtualFolderChild(name: "b.txt", isFolder: false)])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testRowNameIsLastPathSegmentAndUnpathedItemsStayAtRoot() {
        let hosted = item("x", source: "hosted_project_file", path: "web-app/src/main.ts")
        XCTAssertEqual(ProjectBrowserTree.itemName(hosted), "main.ts")
        let chat = ProjectWorkspaceItem(id: "c", kind: "chat", targetID: "chat", name: "Chat",
                                        metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        XCTAssertEqual(ProjectBrowserTree.view(items: [chat], virtualPath: nil).items.map(\.id), ["c"])
        XCTAssertTrue(ProjectBrowserTree.view(items: [chat], virtualPath: "web-app").items.isEmpty)
    }
}
