// TextKit 2 attachment-view provider for native composer atoms.
// The provider owns only the reusable platform view and its layout bounds.
// Controller state remains keyed by the attachment's stable semantic node id.
// Embed snapshots are rendered through the explicit native renderer registry.
// Mention atoms use the same TextKit provider with compact token-based chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
// ────────────────────────────────────────────────────────────────────

#if canImport(UIKit)
import SwiftUI
import UIKit
import ObjectiveC

@MainActor private var composerHostingControllerKey: UInt8 = 0

final class ComposerAttachmentViewProvider: NSTextAttachmentViewProvider {
    private static let embedHeight: CGFloat = 200
    private static let mentionHeight: CGFloat = 28

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
        guard let attachment = textAttachment as? ComposerTextAttachment,
              let node = attachment.nodeSnapshot else {
            view = MainActor.assumeIsolated {
                let unavailableView = UIView(frame: .zero)
                unavailableView.accessibilityIdentifier = "native-composer-attachment-unavailable"
                return unavailableView
            }
            return
        }
        let hosted = MainActor.assumeIsolated {
            let controller = UIHostingController(rootView: ComposerAttachmentContent(node: node))
            controller.view.backgroundColor = .clear
            controller.view.accessibilityIdentifier = platformIdentifier(for: node)
            objc_setAssociatedObject(
                controller.view as Any,
                &composerHostingControllerKey,
                controller,
                .OBJC_ASSOCIATION_RETAIN_NONATOMIC
            )
            return controller.view
        }
        view = hosted
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
            height: attachmentHeight
        )
    }

    private var attachmentHeight: CGFloat {
        (textAttachment as? ComposerTextAttachment)?.nodeSnapshot?.kind == "mention"
            ? Self.mentionHeight
            : Self.embedHeight
    }
}
#elseif canImport(AppKit)
import AppKit
import SwiftUI

final class ComposerAttachmentViewProvider: NSTextAttachmentViewProvider {
    private static let embedHeight: CGFloat = 200
    private static let mentionHeight: CGFloat = 28

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
        guard let attachment = textAttachment as? ComposerTextAttachment,
              let node = attachment.nodeSnapshot else {
            view = MainActor.assumeIsolated {
                let unavailableView = NSView(frame: .zero)
                unavailableView.identifier = NSUserInterfaceItemIdentifier("native-composer-attachment-unavailable")
                return unavailableView
            }
            return
        }
        let hosted = MainActor.assumeIsolated {
            let hosted = NSHostingView(rootView: ComposerAttachmentContent(node: node))
            hosted.identifier = NSUserInterfaceItemIdentifier(platformIdentifier(for: node))
            return hosted
        }
        view = hosted
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
            height: attachmentHeight
        )
    }

    private var attachmentHeight: CGFloat {
        (textAttachment as? ComposerTextAttachment)?.nodeSnapshot?.kind == "mention"
            ? Self.mentionHeight
            : Self.embedHeight
    }
}
#endif

private func platformIdentifier(for node: ComposerNodeV1) -> String {
    node.kind == "mention"
        ? "native-composer-mention-\(node.id)"
        : "native-composer-embed-\(node.id)"
}

private struct ComposerAttachmentContent: View {
    let node: ComposerNodeV1

    @ViewBuilder
    var body: some View {
        if node.kind == "mention" {
            Text(node.displayLabel ?? node.canonicalSyntax ?? "")
                .font(.omSmall)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing2)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        } else if let embedType = node.embedType,
                  let descriptor = AppleComposerRendererRegistry.shared.descriptor(for: embedType),
                  let lifecycle = try? AppleComposerRendererRegistry.shared.lifecycleState(for: node) {
            AppleComposerEmbedPreview(
                descriptor: descriptor,
                node: node,
                lifecycle: lifecycle,
                embedRecord: nil,
                allEmbedRecords: [:],
                actions: AppleComposerEmbedActions(
                    onOpen: { _ in },
                    onRetry: { _ in },
                    onRemove: { _ in }
                )
            )
        } else {
            Text(node.display?.title ?? node.embedType ?? "")
                .font(.omSmall)
                .foregroundStyle(Color.fontPrimary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
    }
}
