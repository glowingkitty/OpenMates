// Synthetic only: no account key, projection, or share link leaves this process.
// Specification: specifications/features/workflows/specification.yml
// Supporting existing assertions: workflows.content.encrypted-retained,
// workflows.access.boundaries. Template behavior follows the deployed web contract.

import CryptoKit
import XCTest
@testable import OpenMates

final class WorkflowTemplateProjectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.content.encrypted-retained
    func testProjectionEncryptsPortableFieldsAndRoundTripsWithFragmentKey() throws {
        let workflow = try fixtureWorkflow()
        let payload = try WorkflowTemplateProjection.buildPayload(from: workflow)
        let key = SymmetricKey(size: .bits256)
        let encrypted = try WorkflowTemplateProjection.encrypt(payload, key: key)

        XCTAssertFalse(encrypted.ciphertext.contains(workflow.title))
        XCTAssertEqual(encrypted.checksum, WorkflowTemplateProjection.checksum(encrypted.ciphertext))
        let opened = try WorkflowTemplateProjection.decrypt(
            ciphertext: encrypted.ciphertext,
            checksum: encrypted.checksum,
            fragmentKey: WorkflowTemplateProjection.fragmentKey(key)
        )
        XCTAssertEqual(opened.title, workflow.title)
        XCTAssertEqual(opened.requiredCapabilities, ["weather", "weather.forecast"])
        XCTAssertEqual(opened.bindingRequirements.count, 2)
        XCTAssertEqual(opened.nodeTemplates.first?.id, "weather")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testProjectionRejectsCredentialShapedConfigFields() throws {
        let workflow = try fixtureWorkflow(apiKey: "placeholder")
        XCTAssertThrowsError(try WorkflowTemplateProjection.buildPayload(from: workflow)) { error in
            guard case WorkflowTemplateProjectionError.nonPortableField = error else {
                return XCTFail("Expected portable-field rejection")
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    @MainActor
    func testTemplateDeepLinkAcceptsOnlyCurrentHTTPSHostAndFragmentKey() {
        let key = String(repeating: "A", count: 43)
        let domain = "app.dev.openmates.org"
        let valid = URL(string: "https://\(domain)/share/workflow-template/wt_fixture#key=\(key)")!
        let parsed = DeepLinkHandler.workflowTemplateLink(from: valid, selectedDomain: domain)
        XCTAssertEqual(parsed?.templateID, "wt_fixture")
        XCTAssertEqual(parsed?.fragmentKey, key)
        XCTAssertEqual(parsed?.webDomain, domain)
        let withUnrelatedParameters = URL(
            string: "https://\(domain)/share/workflow-template/wt_fixture?view=compact#other=placeholder&key=\(key)"
        )!
        XCTAssertEqual(
            DeepLinkHandler.workflowTemplateLink(from: withUnrelatedParameters, selectedDomain: domain)?.fragmentKey,
            key
        )

        let rejected = [
            "https://other.openmates.org/share/workflow-template/wt_fixture#key=\(key)",
            "http://\(domain)/share/workflow-template/wt_fixture#key=\(key)",
            "https://\(domain)/share/workflow-template/wt_fixture?key=\(key)",
            "https://\(domain)/share/workflow-template/wt_fixture/extra#key=\(key)",
            "https://\(domain)/share/workflow-template/wt_fixture#key=\(key)&key=\(key)",
        ]
        for text in rejected {
            XCTAssertNil(DeepLinkHandler.workflowTemplateLink(from: URL(string: text)!, selectedDomain: domain), text)
        }
        let path = WorkflowTemplateShareService.publicProjectionPath(templateId: "wt_fixture")
        XCTAssertEqual(path, "/v1/workflows/template-projections/wt_fixture")
        XCTAssertFalse(path.contains(key))
    }

    private func fixtureWorkflow(apiKey: String? = nil) throws -> WorkflowDetail {
        let extra = apiKey.map { ", \"api_key\": \"\($0)\"" } ?? ""
        let json = """
        {
          "id":"workflow-fixture", "title":"Morning weather", "status":"active", "enabled":true,
          "lifecycle":"persisted", "source":"manual", "created_by_assistant":false,
          "run_content_retention":"last_5", "current_version_id":"version-fixture",
          "created_at":1, "updated_at":2,
          "graph": {"version":1,"trigger_node_id":"trigger","nodes":[
            {"id":"trigger","type":"schedule_trigger","config":{"schedule":{"type":"daily","time":"09:00","timezone":"Europe/Berlin"}}},
            {"id":"weather","type":"app_skill_action","config":{"app_id":"weather","skill_id":"forecast"\(extra)}}
          ],"edges":[{"from":"trigger","to":"weather"}]}
        }
        """
        return try JSONDecoder().decode(WorkflowDetail.self, from: Data(json.utf8))
    }
}
