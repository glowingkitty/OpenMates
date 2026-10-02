// Contract support for deterministic Workflow message templates.
// Web source: frontend/packages/ui/src/components/workflows/__tests__/workflowMessageTokens.test.ts
// Specification: specifications/features/workflows/specification.yml

import XCTest
import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif
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

    #if canImport(AppKit)
    // contract-test: supporting surface=gui.apple assertions=workflows.message.standard,workflows.control.typed-data
    @MainActor
    func testProductionAppKitTextViewEnablesNativeUndo() {
        let view = WorkflowTemplateTextView.makeNativeTextView()
        XCTAssertTrue(view.allowsUndo, "The production view must enable native undo before coordinator insertion.")
        XCTAssertTrue(view.isRichText, "The production view must preserve rendered reference attachments.")
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=workflows.message.standard,workflows.control.typed-data
    @MainActor
    func testPickerInsertionPublishesEmptyQuestionAsAttributedChip() {
        var question = ""
        let output = WorkflowMessageOutput(reference: "$nodes.weather.output.rain_probability",
                                           label: "Weather · Rain Probability", appId: "weather")
        let coordinator = WorkflowTemplateTextView.Coordinator(
            value: Binding(get: { question }, set: { question = $0 }), outputs: [output])
        let view = WorkflowUndoTemplateView()
        coordinator.textView = view
        setRendered(WorkflowAttributedTemplate.render(question, outputs: [output]), in: view)
        view.templateUndoManager.beginUndoGrouping()
        coordinator.insert(WorkflowMessageTokens.storageSyntax(for: output.reference))
        view.templateUndoManager.endUndoGrouping()

        XCTAssertEqual(question, "{{steps.weather.rain_probability}}", "The actual draft binding must receive canonical storage.")
        let rendered = renderedText(view)
        XCTAssertEqual(rendered.string, "\u{FFFC}", "The native editor must contain an attachment, not raw syntax.")
        let attachment = rendered.attribute(.attachment, at: 0, effectiveRange: nil) as? NSTextAttachment
        XCTAssertNotNil(attachment?.image)
        XCTAssertEqual(WorkflowAttributedTemplate.storage(rendered), question)
        XCTAssertEqual(WorkflowAttributedTemplate.accessibleText(question, outputs: [output]), output.label)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.message.standard,workflows.control.typed-data
    @MainActor
    func testPickerInsertionReplacesSelectionAndUndoRestoresDraftAndCaret() {
        let original = "Before 😀 after"
        var question = original
        let output = WorkflowMessageOutput(reference: "$nodes.weather.output.rain_probability",
                                           label: "Weather · Rain Probability", appId: "weather")
        let coordinator = WorkflowTemplateTextView.Coordinator(
            value: Binding(get: { question }, set: { question = $0 }), outputs: [output])
        let view = WorkflowUndoTemplateView()
        coordinator.textView = view
        setRendered(WorkflowAttributedTemplate.render(question, outputs: [output]), in: view)
        let selection = NSRange(location: 7, length: 2)
        setSelection(selection, in: view)
        view.templateUndoManager.beginUndoGrouping()
        coordinator.insert(WorkflowMessageTokens.storageSyntax(for: output.reference))
        view.templateUndoManager.endUndoGrouping()

        XCTAssertEqual(question, "Before {{steps.weather.rain_probability}} after")
        XCTAssertEqual(renderedText(view).string, "Before \u{FFFC} after")
        XCTAssertEqual(selectedRange(view), NSRange(location: 8, length: 0))
        view.templateUndoManager.undo()
        XCTAssertEqual(question, original)
        XCTAssertEqual(selectedRange(view), selection)
        view.templateUndoManager.redo()
        XCTAssertEqual(question, "Before {{steps.weather.rain_probability}} after")
        XCTAssertEqual(selectedRange(view), NSRange(location: 8, length: 0))
    }

    @MainActor private func setRendered(_ value: NSAttributedString, in view: WorkflowUndoTemplateView) {
        #if canImport(UIKit)
        view.attributedText = value
        #else
        view.textStorage?.setAttributedString(value)
        #endif
    }
    @MainActor private func renderedText(_ view: WorkflowUndoTemplateView) -> NSAttributedString {
        #if canImport(UIKit)
        return view.attributedText
        #else
        return view.attributedString()
        #endif
    }
    @MainActor private func setSelection(_ value: NSRange, in view: WorkflowUndoTemplateView) {
        #if canImport(UIKit)
        view.selectedRange = value
        #else
        view.setSelectedRange(value)
        #endif
    }
    @MainActor private func selectedRange(_ view: WorkflowUndoTemplateView) -> NSRange {
        #if canImport(UIKit)
        return view.selectedRange
        #else
        return view.selectedRange()
        #endif
    }
}

#if canImport(UIKit)
@MainActor private final class WorkflowUndoTemplateView: UITextView {
    let templateUndoManager: UndoManager = {
        let manager = UndoManager(); manager.groupsByEvent = false; return manager
    }()
    override var undoManager: UndoManager? { templateUndoManager }
}
#elseif canImport(AppKit)
@MainActor private final class WorkflowUndoTemplateView: NSTextView {
    let templateUndoManager: UndoManager = {
        let manager = UndoManager(); manager.groupsByEvent = false; return manager
    }()
    override var undoManager: UndoManager? { templateUndoManager }
}
#endif
