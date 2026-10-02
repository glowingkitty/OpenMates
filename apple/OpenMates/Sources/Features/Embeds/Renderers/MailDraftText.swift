// Exact Mail CSS line boxes: 14px medium Lexend with line-height: 1.45.
// Web: frontend/packages/ui/src/components/embeds/mail/MailEmbedFullscreen.svelte
// Uses the same paragraph line-height contract as SheetFullscreenTableMetrics.
import SwiftUI

#if canImport(UIKit)
import UIKit

struct MailDraftText: UIViewRepresentable {
    let value: String
    var italic = false
    private static let lineHeight: CGFloat = 20.3

    func makeUIView(context: Context) -> UITextView { Self.makeTextView() }

    static func makeTextView() -> UITextView {
        let label = UITextView()
        label.backgroundColor = .clear
        label.isEditable = false
        label.isSelectable = true
        label.isScrollEnabled = false
        label.textContainerInset = .zero
        label.textContainer.lineFragmentPadding = 0
        label.textContainer.lineBreakMode = .byWordWrapping
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return label
    }

    func updateUIView(_ label: UITextView, context: Context) {
        Self.update(value: value, italic: italic, in: label)
    }

    static func update(value: String, italic: Bool = false, in label: UITextView) {
        let base = UIFont(name: FontRegistration.mediumPostScriptName, size: 14)
            ?? UIFont.systemFont(ofSize: 14, weight: .medium)
        let font: UIFont
        if italic, let descriptor = base.fontDescriptor.withSymbolicTraits(.traitItalic) {
            font = UIFont(descriptor: descriptor, size: 14)
        } else { font = base }
        let paragraph = NSMutableParagraphStyle()
        paragraph.minimumLineHeight = lineHeight
        paragraph.maximumLineHeight = lineHeight
        paragraph.lineBreakMode = .byWordWrapping
        let next = NSAttributedString(string: value, attributes: [
            .font: font, .foregroundColor: UIColor(Color.fontPrimary), .paragraphStyle: paragraph
        ])
        // Parent geometry refreshes must not replace unchanged TextKit storage
        // and discard the user's current selection.
        if !label.attributedText.isEqual(to: next) { label.attributedText = next }
        label.accessibilityLabel = value
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        guard let width = proposal.width, width > 0 else { return nil }
        let size = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        // TextKit rounds its measured height to pixels. Keep whole CSS line boxes,
        // including the single-line values where intrinsic height uses font metrics.
        let lines = max(1, Int((size.height / Self.lineHeight).rounded()))
        return CGSize(width: width, height: CGFloat(lines) * Self.lineHeight)
    }
}
#elseif canImport(AppKit)
import AppKit

struct MailDraftText: NSViewRepresentable {
    let value: String
    var italic = false
    private static let lineHeight: CGFloat = 20.3

    func makeNSView(context: Context) -> NSTextField {
        let label = NSTextField(wrappingLabelWithString: "")
        label.maximumNumberOfLines = 0
        label.isSelectable = true
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return label
    }

    func updateNSView(_ label: NSTextField, context: Context) {
        let base = NSFont(name: FontRegistration.mediumPostScriptName, size: 14)
            ?? NSFont.systemFont(ofSize: 14, weight: .medium)
        let font = italic ? NSFontManager.shared.convert(base, toHaveTrait: .italicFontMask) : base
        let paragraph = NSMutableParagraphStyle()
        paragraph.minimumLineHeight = Self.lineHeight
        paragraph.maximumLineHeight = Self.lineHeight
        paragraph.lineBreakMode = .byWordWrapping
        let next = NSAttributedString(string: value, attributes: [
            .font: font, .foregroundColor: NSColor(Color.fontPrimary), .paragraphStyle: paragraph
        ])
        if !label.attributedStringValue.isEqual(to: next) { label.attributedStringValue = next }
        label.setAccessibilityLabel(value)
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSTextField, context: Context) -> CGSize? {
        guard let width = proposal.width, width > 0 else { return nil }
        let size = nsView.cell?.cellSize(forBounds: CGRect(x: 0, y: 0, width: width, height: .greatestFiniteMagnitude)) ?? .zero
        let lines = max(1, Int((size.height / Self.lineHeight).rounded()))
        return CGSize(width: width, height: CGFloat(lines) * Self.lineHeight)
    }
}
#endif
