// Contract support for deterministic Workflow message templates.
// Web source: frontend/packages/ui/src/components/workflows/__tests__/workflowMessageTokens.test.ts
// Specification: specifications/features/workflows/specification.yml

import XCTest
@testable import OpenMates

final class WorkflowMessageTokensTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.message.standard
    @MainActor
    func testKnownOutputUsesCanonicalStorageSyntaxAndRoundTripsMultiline() {
        let output = WorkflowMessageOutput(
            reference: "$nodes.weather.output.rain_summary", label: "Weather · Rain summary", appId: "weather"
        )
        let template = "Before {{steps.weather.rain_summary}}\n\nAfter"
        let segments = WorkflowMessageTokens.parse(template, outputs: [output])
        XCTAssertEqual(WorkflowMessageTokens.serialize(segments), template)
        XCTAssertEqual(WorkflowMessageTokens.storageSyntax(for: output.reference), "{{steps.weather.rain_summary}}")
        guard case .output(let reference, let label, _, let appId) = segments[1] else {
            return XCTFail("Expected a typed output segment")
        }
        XCTAssertEqual(reference, output.reference)
        XCTAssertEqual(label, output.label)
        XCTAssertEqual(appId, "weather")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.message.standard
    @MainActor
    func testUnknownReferenceKeepsReadableStorageSyntax() {
        let segments = WorkflowMessageTokens.parse("At {{clock.now}}: {{$nodes.weather.output.count}}", outputs: [])
        XCTAssertEqual(WorkflowMessageTokens.serialize(segments), "At {{clock.now}}: {{$nodes.weather.output.count}}")
    }
}
