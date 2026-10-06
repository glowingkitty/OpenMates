// Focused Workflow message editor with cursor insertion of typed earlier outputs.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowMessageEditor.svelte
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.message.standard, workflows.control.typed-data

import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

// The picker invokes native editing from its Button action, never from a
// representable update callback. Native selection remains owned by the editor.
@MainActor
fileprivate final class WorkflowTemplateInsertionBridge {
    var insert: ((String) -> Void)?
}

private final class WorkflowReferenceAttachment: NSTextAttachment {
    let syntax: String

    @MainActor init(syntax: String, label: String, appId: String?) {
        self.syntax = syntax
        super.init(data: nil, ofType: nil)
        let chip = Text(label)
            .font(.omP.weight(.medium))
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, 8)
            .padding(.vertical, 1)
            .background(AppIconView.gradient(forAppId: appId ?? "workflows"), in: Capsule())
        let renderer = ImageRenderer(content: chip)
        #if canImport(UIKit)
        renderer.scale = UIScreen.main.scale
        image = renderer.uiImage
        #elseif canImport(AppKit)
        renderer.scale = NSScreen.main?.backingScaleFactor ?? 2
        image = renderer.nsImage
        #endif
        if let image { bounds = CGRect(x: 0, y: -3, width: image.size.width, height: image.size.height) }
    }

    required init?(coder: NSCoder) { return nil }
}

@MainActor
enum WorkflowAttributedTemplate {
    static func render(_ storage: String, outputs: [WorkflowMessageOutput]) -> NSAttributedString {
        let rendered = NSMutableAttributedString(string: "")
        for segment in WorkflowMessageTokens.parse(storage, outputs: outputs) {
            switch segment {
            case .text(let text): rendered.append(NSAttributedString(string: text))
            case .output(_, let label, let syntax, let appId):
                rendered.append(NSAttributedString(attachment:
                    WorkflowReferenceAttachment(syntax: syntax, label: label, appId: appId)))
            }
        }
        #if canImport(UIKit)
        let font = UIFontMetrics(forTextStyle: .body).scaledFont(for: UIFont(name: FontRegistration.mediumPostScriptName, size: 16) ?? UIFont.systemFont(ofSize: 16))
        let color = UIColor(Color.fontPrimary)
        #else
        let font = NSFont(name: FontRegistration.mediumPostScriptName, size: 16) ?? NSFont.systemFont(ofSize: 16)
        let color = NSColor(Color.fontPrimary)
        #endif
        rendered.addAttributes([.font: font, .foregroundColor: color], range: NSRange(location: 0, length: rendered.length))
        return rendered
    }

    static func storage(_ rendered: NSAttributedString) -> String {
        var result = ""
        rendered.enumerateAttributes(in: NSRange(location: 0, length: rendered.length)) { attributes, range, _ in
            if let token = attributes[.attachment] as? WorkflowReferenceAttachment {
                result += token.syntax
            } else {
                result += rendered.attributedSubstring(from: range).string
            }
        }
        return result
    }

    static func accessibleText(_ storage: String, outputs: [WorkflowMessageOutput]) -> String {
        WorkflowMessageTokens.parse(storage, outputs: outputs).map { segment in
            switch segment {
            case .text(let text): text
            case .output(_, let label, _, _): label
            }
        }.joined()
    }

    static func storageOffset(for visualOffset: Int, in rendered: NSAttributedString) -> Int {
        var result = 0
        let safeEnd = min(max(0, visualOffset), rendered.length)
        guard safeEnd > 0 else { return 0 }
        rendered.enumerateAttributes(in: NSRange(location: 0, length: safeEnd)) { attributes, range, _ in
            if let token = attributes[.attachment] as? WorkflowReferenceAttachment {
                result += (token.syntax as NSString).length
            } else { result += range.length }
        }
        return result
    }

    static func visualOffset(for storageOffset: Int, in rendered: NSAttributedString) -> Int {
        guard storageOffset > 0 else { return 0 }
        var consumed = 0
        var visual = 0
        rendered.enumerateAttributes(in: NSRange(location: 0, length: rendered.length)) { attributes, range, stop in
            let storedLength = (attributes[.attachment] as? WorkflowReferenceAttachment)
                .map { ($0.syntax as NSString).length } ?? range.length
            if storageOffset <= consumed {
                visual = range.location
                stop.pointee = true
            } else if consumed + storedLength >= storageOffset {
                visual = range.location + (attributes[.attachment] == nil
                    ? max(0, storageOffset - consumed) : range.length)
                stop.pointee = true
            } else {
                consumed += storedLength
                visual = NSMaxRange(range)
            }
        }
        return min(visual, rendered.length)
    }
}

@MainActor
struct WorkflowMessageTemplateEditor: View {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    var placeholder: String = ""
    var sourceTitles: [String: String] = [:]
    var minimumInputHeight: CGFloat = 168

    @State private var selectedSourceId: String?
    @State private var insertionBridge = WorkflowTemplateInsertionBridge()

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            variablePicker
            ZStack(alignment: .topLeading) {
                if value.isEmpty {
                    Text(placeholder)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.spacing5)
                        .allowsHitTesting(false)
                        .accessibilityIdentifier("workflow-message-placeholder")
                }
                WorkflowTemplateTextView(value: $value, outputs: outputs, insertionBridge: insertionBridge)
                    .frame(minHeight: minimumInputHeight)
                    .accessibilityIdentifier("workflow-message-template")
            }
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 12))
            .shadow(color: .black.opacity(0.12), radius: 8, y: 4)
        }
        // Callers identify the complete instruction editor. Own that identity
        // here so it cannot replace the variable picker's child identifier.
        .accessibilityElement(children: .contain)
        .accessibilityValue(value)
    }

    private func sourceID(_ output: WorkflowMessageOutput) -> String {
        let parts = output.reference.split(separator: ".")
        return parts.count > 1 ? String(parts[1]) : output.reference
    }

    @ViewBuilder private var variablePicker: some View {
        if !outputs.isEmpty {
            let sourceIds = outputs.map(sourceID).reduce(into: [String]()) { ids, id in
                if !ids.contains(id) { ids.append(id) }
            }
            HStack(spacing: .spacing4) {
                Text(AppStrings.localized("workflows.builder.variable_add"))
                    .font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontSecondary)
                ScrollView(.horizontal) {
                    HStack(spacing: .spacing3) {
                        ForEach(sourceIds, id: \.self) { id in
                            if let output = outputs.first(where: { sourceID($0) == id }) {
                                Button { selectedSourceId = selectedSourceId == id ? nil : id } label: {
                                    HStack(spacing: .spacing2) {
                                        Icon(AppIconView.iconName(forAppId: output.appId ?? "workflows"), size: 14)
                                        Text("@ " + (sourceTitles[id] ?? output.label.components(separatedBy: " · ").first ?? output.label))
                                            .lineLimit(1)
                                    }
                                    .font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontButton)
                                    .padding(.horizontal, .spacing4).padding(.vertical, .spacing2)
                                    .background(AppIconView.gradient(forAppId: output.appId ?? "workflows"), in: Capsule())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("workflow-variable-source-" + id)
                                .accessibilityValue(selectedSourceId == id ? "expanded" : "collapsed")
                            }
                        }
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("workflow-variable-picker")
            if let selectedSourceId {
                VStack(alignment: .leading, spacing: .spacing3) {
                    ForEach(outputs.filter { sourceID($0) == selectedSourceId }) { output in
                        Button {
                            insertionBridge.insert?(WorkflowMessageTokens.storageSyntax(for: output.reference))
                            self.selectedSourceId = nil
                        } label: {
                            HStack {
                                Text("+ " + (output.label.components(separatedBy: " · ").last ?? output.label))
                                Spacer()
                            }.font(.omP).foregroundStyle(Color.fontPrimary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workflow-message-output-reference")
                    }
                }
                .padding(.spacing4)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius6))
            }
        }
    }

}

#if canImport(UIKit)
struct WorkflowTemplateTextView: UIViewRepresentable {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    fileprivate let insertionBridge: WorkflowTemplateInsertionBridge

    func makeCoordinator() -> Coordinator { Coordinator(value: $value, outputs: outputs) }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.delegate = context.coordinator
        textView.backgroundColor = .clear
        textView.font = UIFontMetrics(forTextStyle: .body).scaledFont(
            for: UIFont(name: FontRegistration.mediumPostScriptName, size: 16) ?? UIFont.systemFont(ofSize: 16))
        textView.textColor = UIColor(Color.fontPrimary)
        textView.textContainerInset = UIEdgeInsets(top: 11, left: 9, bottom: 11, right: 9)
        textView.isScrollEnabled = true
        textView.adjustsFontForContentSizeCategory = true
        textView.attributedText = WorkflowAttributedTemplate.render(value, outputs: outputs)
        context.coordinator.textView = textView
        insertionBridge.insert = { [weak coordinator = context.coordinator] syntax in
            coordinator?.insert(syntax)
        }
        context.coordinator.updateAccessibility()
        return textView
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        context.coordinator.valueBinding = $value
        context.coordinator.outputs = outputs
        let rendered = textView.attributedText ?? NSAttributedString(string: "")
        let outputSignature = outputs.map { "\($0.reference)|\($0.label)|\($0.appId ?? "")" }.joined(separator: "\u{1F}")
        if WorkflowAttributedTemplate.storage(rendered) != value
            || context.coordinator.outputSignature != outputSignature {
            let storageCursor = WorkflowAttributedTemplate.storageOffset(
                for: textView.selectedRange.location, in: rendered)
            let updated = WorkflowAttributedTemplate.render(value, outputs: outputs)
            textView.attributedText = updated
            textView.selectedRange = NSRange(location: WorkflowAttributedTemplate.visualOffset(
                for: storageCursor, in: updated), length: 0)
            context.coordinator.outputSignature = outputSignature
        }
        context.coordinator.updateAccessibility()
    }

    @MainActor
    final class Coordinator: NSObject, UITextViewDelegate {
        var valueBinding: Binding<String>
        var outputs: [WorkflowMessageOutput]
        weak var textView: UITextView?
        var outputSignature = ""

        init(value: Binding<String>, outputs: [WorkflowMessageOutput]) {
            valueBinding = value; self.outputs = outputs
        }

        func insert(_ syntax: String) {
            guard let textView else { return }
            let next = NSMutableAttributedString(attributedString: textView.attributedText ?? NSAttributedString(string: ""))
            let selected = textView.selectedRange
            let token = WorkflowAttributedTemplate.render(syntax, outputs: outputs)
            next.replaceCharacters(in: selected, with: token)
            apply(next, selection: NSRange(location: selected.location + token.length, length: 0))
        }

        private func apply(_ next: NSAttributedString, selection: NSRange) {
            guard let textView else { return }
            let previous = NSAttributedString(attributedString: textView.attributedText ?? NSAttributedString(string: ""))
            let previousSelection = textView.selectedRange
            textView.undoManager?.registerUndo(withTarget: self) { target in
                MainActor.assumeIsolated { target.apply(previous, selection: previousSelection) }
            }
            textView.textStorage.setAttributedString(next)
            textView.selectedRange = selection
            valueBinding.wrappedValue = WorkflowAttributedTemplate.storage(next)
            updateAccessibility()
        }

        func updateAccessibility() {
            guard let textView else { return }
            textView.accessibilityValue = WorkflowAttributedTemplate.accessibleText(
                WorkflowAttributedTemplate.storage(textView.attributedText), outputs: outputs)
        }

        func textViewDidChange(_ textView: UITextView) {
            valueBinding.wrappedValue = WorkflowAttributedTemplate.storage(textView.attributedText)
            updateAccessibility()
        }
    }
}
#elseif canImport(AppKit)
// AppKit's AX value setter edits NSTextView content and calls its delegate.
// Project readable chip labels through the getter without changing text storage.
@MainActor
private final class WorkflowAccessibleTemplateTextView: NSTextView {
    var templateOutputs: [WorkflowMessageOutput] = []

    override func accessibilityValue() -> String? {
        WorkflowAttributedTemplate.accessibleText(
            WorkflowAttributedTemplate.storage(attributedString()), outputs: templateOutputs)
    }
}

struct WorkflowTemplateTextView: NSViewRepresentable {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    fileprivate let insertionBridge: WorkflowTemplateInsertionBridge

    func makeCoordinator() -> Coordinator { Coordinator(value: $value, outputs: outputs) }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.drawsBackground = false
        let textView = Self.makeNativeTextView()
        textView.delegate = context.coordinator
        scrollView.documentView = textView
        context.coordinator.textView = textView
        context.coordinator.replaceRenderedText(WorkflowAttributedTemplate.render(value, outputs: outputs))
        insertionBridge.insert = { [weak coordinator = context.coordinator] syntax in
            coordinator?.insert(syntax)
        }
        context.coordinator.updateAccessibility()
        return scrollView
    }

    // Keep the production setup directly testable, rather than relying on a
    // test subclass whose injected undo manager can mask disabled native undo.
    @MainActor
    static func makeNativeTextView() -> NSTextView {
        let textView = WorkflowAccessibleTemplateTextView()
        textView.isRichText = true
        textView.allowsUndo = true
        textView.font = NSFont.systemFont(ofSize: 16)
        textView.textColor = .labelColor
        textView.drawsBackground = false
        textView.isVerticallyResizable = true
        textView.textContainerInset = NSSize(width: 12, height: 11)
        return textView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        context.coordinator.valueBinding = $value
        context.coordinator.outputs = outputs
        let rendered = textView.attributedString()
        let outputSignature = outputs.map { "\($0.reference)|\($0.label)|\($0.appId ?? "")" }.joined(separator: "\u{1F}")
        if WorkflowAttributedTemplate.storage(rendered) != value
            || context.coordinator.outputSignature != outputSignature {
            let storageCursor = WorkflowAttributedTemplate.storageOffset(
                for: textView.selectedRange().location, in: rendered)
            let updated = WorkflowAttributedTemplate.render(value, outputs: outputs)
            context.coordinator.replaceRenderedText(updated, selection: NSRange(
                location: WorkflowAttributedTemplate.visualOffset(for: storageCursor, in: updated), length: 0))
            context.coordinator.outputSignature = outputSignature
        }
        context.coordinator.updateAccessibility()
    }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate {
        var valueBinding: Binding<String>
        var outputs: [WorkflowMessageOutput]
        weak var textView: NSTextView?
        var outputSignature = ""
        private var isUpdatingText = false
        private var isHandlingTextChange = false

        init(value: Binding<String>, outputs: [WorkflowMessageOutput]) {
            valueBinding = value; self.outputs = outputs
        }

        func insert(_ syntax: String) {
            guard let textView else { return }
            let next = NSMutableAttributedString(attributedString: textView.attributedString())
            let selected = textView.selectedRange()
            let token = WorkflowAttributedTemplate.render(syntax, outputs: outputs)
            next.replaceCharacters(in: selected, with: token)
            apply(next, selection: NSRange(location: selected.location + token.length, length: 0))
        }

        func replaceRenderedText(_ next: NSAttributedString, selection: NSRange? = nil) {
            guard let textView else { return }
            let wasUpdatingText = isUpdatingText
            isUpdatingText = true
            defer { isUpdatingText = wasUpdatingText }
            textView.textStorage?.setAttributedString(next)
            if let selection { textView.setSelectedRange(selection) }
            updateAccessibility()
        }

        private func apply(_ next: NSAttributedString, selection: NSRange) {
            guard let textView, !isUpdatingText else { return }
            isUpdatingText = true
            defer { isUpdatingText = false }
            let previous = NSAttributedString(attributedString: textView.attributedString())
            let previousSelection = textView.selectedRange()
            textView.undoManager?.registerUndo(withTarget: self) { target in
                MainActor.assumeIsolated { target.apply(previous, selection: previousSelection) }
            }
            replaceRenderedText(next, selection: selection)
            valueBinding.wrappedValue = WorkflowAttributedTemplate.storage(next)
            updateAccessibility()
        }

        func updateAccessibility() {
            guard let textView = textView as? WorkflowAccessibleTemplateTextView else { return }
            textView.templateOutputs = outputs
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView,
                  textView === self.textView, !isUpdatingText, !isHandlingTextChange else { return }
            isHandlingTextChange = true
            defer { isHandlingTextChange = false }
            valueBinding.wrappedValue = WorkflowAttributedTemplate.storage(textView.attributedString())
            updateAccessibility()
        }
    }
}
#endif
