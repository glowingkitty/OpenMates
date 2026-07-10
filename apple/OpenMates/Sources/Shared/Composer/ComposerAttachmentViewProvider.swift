// TextKit 2 attachment-view provider for native composer atoms.
// The provider owns only the reusable platform view and its layout bounds.
// Controller state remains keyed by the attachment's stable semantic node id.
// Interactive preview content will be supplied by the renderer registry.
// No user-visible copy or product styling is defined in this adapter layer.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
// ────────────────────────────────────────────────────────────────────

#if canImport(UIKit)
import UIKit

final class ComposerAttachmentViewProvider: NSTextAttachmentViewProvider {
    private static let prototypeHeight: CGFloat = 60

    override init(
        textAttachment: NSTextAttachment,
        parentView: UIView?,
        textLayoutManager: NSTextLayoutManager?,
        location: any NSTextLocation
    ) {
        super.init(
            textAttachment: textAttachment,
            parentView: parentView,
            textLayoutManager: textLayoutManager,
            location: location
        )
        tracksTextAttachmentViewBounds = true
    }

    override func loadView() {
        let button = MainActor.assumeIsolated {
            let button = UIButton(type: .custom)
            button.accessibilityIdentifier = "native-composer-embed-prototype"
            return button
        }
        view = button
    }

    override func attachmentBounds(
        for attributes: [NSAttributedString.Key: Any],
        location: any NSTextLocation,
        textContainer: NSTextContainer?,
        proposedLineFragment: CGRect,
        position: CGPoint
    ) -> CGRect {
        CGRect(
            x: proposedLineFragment.minX,
            y: 0,
            width: proposedLineFragment.width,
            height: Self.prototypeHeight
        )
    }
}
#elseif canImport(AppKit)
import AppKit

final class ComposerAttachmentViewProvider: NSTextAttachmentViewProvider {
    private static let prototypeHeight: CGFloat = 60

    override init(
        textAttachment: NSTextAttachment,
        parentView: NSView?,
        textLayoutManager: NSTextLayoutManager?,
        location: any NSTextLocation
    ) {
        super.init(
            textAttachment: textAttachment,
            parentView: parentView,
            textLayoutManager: textLayoutManager,
            location: location
        )
        tracksTextAttachmentViewBounds = true
    }

    override func loadView() {
        let button = MainActor.assumeIsolated {
            let button = NSButton(frame: .zero)
            button.identifier = NSUserInterfaceItemIdentifier("native-composer-embed-prototype")
            return button
        }
        view = button
    }

    override func attachmentBounds(
        for attributes: [NSAttributedString.Key: Any],
        location: any NSTextLocation,
        textContainer: NSTextContainer?,
        proposedLineFragment: CGRect,
        position: CGPoint
    ) -> CGRect {
        CGRect(
            x: proposedLineFragment.minX,
            y: 0,
            width: proposedLineFragment.width,
            height: Self.prototypeHeight
        )
    }
}
#endif
