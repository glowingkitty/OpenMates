import XCTest
@testable import OpenMates

final class ProjectReferenceEmbedModelTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testReferencesRetainScopeAndPathWithoutCopyingRemoteContent() {
        let raw: [String: Any] = ["project_id": "project", "project_name": "Shared Project", "team_id": "team",
            "query": "README", "results": [
                ["source_id": "source", "path": " README.md ", "line": 12, "content": "must not be copied"],
                ["embed_id": "file", "path": "docs/guide.md", "line": true],
                ["path": "missing-reference.md"], ["embed_id": "file", "path": " "]
            ]]
        let record = EmbedRecord(id: "references", type: "app:projects:search", status: .finished,
            data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil, appId: "projects",
            skillId: "search", embedIds: nil, createdAt: nil)
        let model = ProjectReferenceEmbedModel(embed: record)
        XCTAssertEqual(model.references.count, 2)
        XCTAssertEqual(model.references.map(\.projectID), ["project", "project"])
        XCTAssertEqual(model.references.map(\.teamID), ["team", "team"])
        XCTAssertEqual(model.references.map(\.path), ["README.md", "docs/guide.md"])
        XCTAssertEqual(model.references[0].sourceID, "source")
        XCTAssertEqual(model.references[0].line, 12)
        XCTAssertNil(model.references[1].line, "JSON booleans are not line numbers")
        XCTAssertEqual(model.query, "README")
        XCTAssertEqual(model.projectName, "Shared Project")
        XCTAssertTrue(ProjectReferenceEmbedModel.isReference(record))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalLegacyAndGenericProjectSkillFormsHaveTypedDispatch() {
        for type in ["app:projects:read", "projects-read", "app_skill_use", "app-skill-use"] {
            let record = EmbedRecord(id: "references", type: type, status: .processing,
                data: .raw(["app_id": AnyCodable("projects"), "skill_id": AnyCodable("read")]),
                parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
            XCTAssertTrue(ProjectReferenceEmbedModel.isReference(record))
            XCTAssertEqual(ProjectReferenceEmbedModel(embed: record).skillID, "read")
            XCTAssertEqual(ProjectReferenceEmbedModel(embed: record).status, .processing)
            XCTAssertTrue(ProjectReferenceEmbedModel(embed: record).references.isEmpty)
        }
        XCTAssertEqual(EmbedType.normalized(rawValue: "projects-search"), .projectsSearch)
        XCTAssertEqual(EmbedType.normalized(rawValue: "projects-read"), .projectsRead)
    }
}
