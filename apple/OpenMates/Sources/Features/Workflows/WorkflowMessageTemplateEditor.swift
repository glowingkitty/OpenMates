// Focused Workflow message editor with cursor insertion of typed earlier outputs.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowMessageEditor.svelte

import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

private struct WorkflowReferenceInsertion: Equatable {
    let id = UUID()
    let syntax: String
}

private final class WorkflowReferenceAttachment: NSTextAttachment {
    let syntax: String

    @MainActor init(syntax: String, label: String, appId: String?) {
        self.syntax = syntax
        super.init(data: nil, ofType: nil)
        let chip = Text(label)
            .font(.system(size: 16, weight: .medium))
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
private enum WorkflowAttributedTemplate {
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

struct WorkflowMessageTemplateEditor: View {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    var placeholder: String = ""

    @State private var insertion: WorkflowReferenceInsertion?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            ZStack(alignment: .topLeading) {
                if value.isEmpty {
                    Text(placeholder)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.spacing5)
                        .allowsHitTesting(false)
                }
                WorkflowTemplateTextView(value: $value, outputs: outputs, insertion: $insertion)
                    .frame(minHeight: 128)
                    .accessibilityIdentifier("workflow-message-template")
            }
            .background(Color.grey10, in: RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(Color.grey30, lineWidth: 1))

            if !outputs.isEmpty {
                Text(AppStrings.workflowBuilder(.select_output))
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontSecondary)
                ScrollView(.horizontal) {
                    HStack(spacing: .spacing3) {
                        ForEach(outputs) { output in
                            Button(output.label) {
                                insertion = WorkflowReferenceInsertion(
                                    syntax: WorkflowMessageTokens.storageSyntax(for: output.reference)
                                )
                            }
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.fontButton)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing3)
                            .background(LinearGradient.primary, in: Capsule())
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("workflow-message-output-reference")
                        }
                    }
                }
            }
        }
    }
}

#if canImport(UIKit)
private struct WorkflowTemplateTextView: UIViewRepresentable {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    @Binding var insertion: WorkflowReferenceInsertion?

    func makeCoordinator() -> Coordinator { Coordinator(value: $value) }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.delegate = context.coordinator
        textView.backgroundColor = .clear
        textView.font = UIFont.preferredFont(forTextStyle: .body)
        textView.textColor = UIColor(Color.fontPrimary)
        textView.textContainerInset = UIEdgeInsets(top: 11, left: 9, bottom: 11, right: 9)
        textView.isScrollEnabled = true
        textView.adjustsFontForContentSizeCategory = true
        textView.attributedText = WorkflowAttributedTemplate.render(value, outputs: outputs)
        context.coordinator.textView = textView
        return textView
    }

    func updateUIView(_ textView: UITextView, context: Context) {
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
        guard let insertion, context.coordinator.lastInsertionId != insertion.id else { return }
        context.coordinator.lastInsertionId = insertion.id
        textView.insertText(insertion.syntax)
        value = WorkflowAttributedTemplate.storage(textView.attributedText)
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        @Binding var value: String
        weak var textView: UITextView?
        var lastInsertionId: UUID?
        var outputSignature = ""

        init(value: Binding<String>) { _value = value }

        func textViewDidChange(_ textView: UITextView) {
            value = WorkflowAttributedTemplate.storage(textView.attributedText)
        }
    }
}
#elseif canImport(AppKit)
private struct WorkflowTemplateTextView: NSViewRepresentable {
    @Binding var value: String
    let outputs: [WorkflowMessageOutput]
    @Binding var insertion: WorkflowReferenceInsertion?

    func makeCoordinator() -> Coordinator { Coordinator(value: $value) }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.drawsBackground = false
        let textView = NSTextView()
        textView.delegate = context.coordinator
        textView.isRichText = false
        textView.font = NSFont.systemFont(ofSize: 16)
        textView.textColor = .labelColor
        textView.drawsBackground = false
        textView.isVerticallyResizable = true
        textView.textContainerInset = NSSize(width: 12, height: 11)
        textView.textStorage?.setAttributedString(WorkflowAttributedTemplate.render(value, outputs: outputs))
        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        let rendered = textView.attributedString()
        let outputSignature = outputs.map { "\($0.reference)|\($0.label)|\($0.appId ?? "")" }.joined(separator: "\u{1F}")
        if WorkflowAttributedTemplate.storage(rendered) != value
            || context.coordinator.outputSignature != outputSignature {
            let storageCursor = WorkflowAttributedTemplate.storageOffset(
                for: textView.selectedRange().location, in: rendered)
            let updated = WorkflowAttributedTemplate.render(value, outputs: outputs)
            textView.textStorage?.setAttributedString(updated)
            textView.setSelectedRange(NSRange(location: WorkflowAttributedTemplate.visualOffset(
                for: storageCursor, in: updated), length: 0))
            context.coordinator.outputSignature = outputSignature
        }
        guard let insertion, context.coordinator.lastInsertionId != insertion.id else { return }
        context.coordinator.lastInsertionId = insertion.id
        textView.insertText(insertion.syntax, replacementRange: textView.selectedRange())
        value = WorkflowAttributedTemplate.storage(textView.attributedString())
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        @Binding var value: String
        var lastInsertionId: UUID?
        var outputSignature = ""

        init(value: Binding<String>) { _value = value }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            value = WorkflowAttributedTemplate.storage(textView.attributedString())
        }
    }
}
#endif
