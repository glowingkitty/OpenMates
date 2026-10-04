// TextKit 2 attachment-view provider for native composer atoms.
// The provider owns only the reusable platform view and its layout bounds.
// Controller state remains keyed by the attachment's stable semantic node id.
// Embed snapshots are rendered through the explicit native renderer registry.
// Mention atoms use the same TextKit provider with compact token-based chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
// ────────────────────────────────────────────────────────────────────

// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.embeds.gated-send

#if canImport(UIKit)
import SwiftUI
import UIKit
import ObjectiveC

@MainActor private var composerHostingControllerKey: UInt8 = 0
@MainActor private var composerAttachmentLongPressKey: UInt8 = 0

// TextKit's ancestor recognizers must be allowed to track the same touch. Scope
// this bridge to one attachment host instead of changing the editor's gestures.
@MainActor
final class ComposerAttachmentLongPressBridge: NSObject, UIGestureRecognizerDelegate {
    private weak var attachment: ComposerTextAttachment?
    private var isPressActive = false
    let recognizer: UILongPressGestureRecognizer

    private init(host: UIView, attachment: ComposerTextAttachment) {
        self.attachment = attachment
        recognizer = UILongPressGestureRecognizer()
        super.init()
        recognizer.minimumPressDuration = 0.6
        recognizer.cancelsTouchesInView = false
        recognizer.delegate = self
        recognizer.addTarget(self, action: #selector(handleLongPress(_:)))
        host.addGestureRecognizer(recognizer)
    }

    @discardableResult
    static func install(on host: UIView, attachment: ComposerTextAttachment) -> ComposerAttachmentLongPressBridge {
        if let installed = objc_getAssociatedObject(host, &composerAttachmentLongPressKey) as? ComposerAttachmentLongPressBridge {
            return installed
        }
        let bridge = ComposerAttachmentLongPressBridge(host: host, attachment: attachment)
        objc_setAssociatedObject(host, &composerAttachmentLongPressKey, bridge, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
        return bridge
    }

    @objc private func handleLongPress(_ gesture: UILongPressGestureRecognizer) {
        handle(state: gesture.state)
    }

    func handle(state: UIGestureRecognizer.State) {
        switch state {
        case .began:
            guard !isPressActive, let attachment else { return }
            isPressActive = true
            attachment.setShowsRemovalAction(!attachment.showsRemovalAction)
        case .ended, .cancelled, .failed:
            isPressActive = false
        default:
            break
        }
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                           shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool {
        guard gestureRecognizer === recognizer, let otherView = otherGestureRecognizer.view else { return false }
        var ancestor = recognizer.view?.superview
        while let view = ancestor {
            if let textView = view as? UITextView {
                return otherView === textView || otherView.isDescendant(of: textView)
            }
            ancestor = view.superview
        }
        return false
    }
}

final class ComposerAttachmentViewProvider: NSTextAttachmentViewProvider {
    private static let embedHeight: CGFloat = 200
    private static let mentionHeight: CGFloat = 20

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
        let content = ComposerAttachmentContent(attachment: attachment)
        let hosted = MainActor.assumeIsolated {
            let controller = UIHostingController(
                rootView: content
            )
            controller.view.backgroundColor = .clear
            controller.view.accessibilityIdentifier = platformIdentifier(for: node)
            if node.kind == "embed" {
                content.installLongPress(on: controller.view)
            }
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
            x: 0,
            y: 0,
            width: attachmentWidth(proposedLineFragment.width),
            height: attachmentHeight
        )
    }

    private func attachmentWidth(_ available: CGFloat) -> CGFloat {
        guard let node = (textAttachment as? ComposerTextAttachment)?.nodeSnapshot,
              node.kind == "mention" else { return available }
        let syntax = node.canonicalSyntax ?? ""
        let label = MainActor.assumeIsolated { NativeMentionPresentation.parse(syntax)?.label ?? node.displayLabel ?? syntax }
        #if canImport(UIKit)
        let font = UIFont(name: syntax.hasPrefix("@best-model:") ? "LexendDeca-SemiBold" : FontRegistration.mediumPostScriptName, size: 16)
            ?? UIFont.systemFont(ofSize: 16, weight: .medium)
        #else
        let font = NSFont(name: syntax.hasPrefix("@best-model:") ? "LexendDeca-SemiBold" : FontRegistration.mediumPostScriptName, size: 16)
            ?? NSFont.systemFont(ofSize: 16, weight: .medium)
        #endif
        return min(available, ceil((label as NSString).size(withAttributes: [.font: font]).width) + 2)
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
    private static let mentionHeight: CGFloat = 20

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
        let content = ComposerAttachmentContent(attachment: attachment)
        let hosted = MainActor.assumeIsolated {
            let hosted = NSHostingView(
                rootView: content
            )
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
            x: 0,
            y: 0,
            width: attachmentWidth(proposedLineFragment.width),
            height: attachmentHeight
        )
    }

    private func attachmentWidth(_ available: CGFloat) -> CGFloat {
        guard let node = (textAttachment as? ComposerTextAttachment)?.nodeSnapshot,
              node.kind == "mention" else { return available }
        let syntax = node.canonicalSyntax ?? ""
        let label = MainActor.assumeIsolated { NativeMentionPresentation.parse(syntax)?.label ?? node.displayLabel ?? syntax }
        #if canImport(UIKit)
        let font = UIFont(name: syntax.hasPrefix("@best-model:") ? "LexendDeca-SemiBold" : FontRegistration.mediumPostScriptName, size: 16)
            ?? UIFont.systemFont(ofSize: 16, weight: .medium)
        #else
        let font = NSFont(name: syntax.hasPrefix("@best-model:") ? "LexendDeca-SemiBold" : FontRegistration.mediumPostScriptName, size: 16)
            ?? NSFont.systemFont(ofSize: 16, weight: .medium)
        #endif
        return min(available, ceil((label as NSString).size(withAttributes: [.font: font]).width) + 2)
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
    @ObservedObject var attachment: ComposerTextAttachment

    #if canImport(UIKit)
    @MainActor
    func installLongPress(on host: UIView) {
        ComposerAttachmentLongPressBridge.install(on: host, attachment: attachment)
    }
    #endif

    @ViewBuilder
    var body: some View {
        Group {
            if let node = attachment.nodeSnapshot, node.kind == "mention" {
                if let mention = NativeMentionPresentation.parse(node.canonicalSyntax ?? "") {
                    NativeMentionLabel(mention: mention)
                } else {
                    Text(node.displayLabel ?? node.canonicalSyntax ?? "").font(.omP)
                }
            } else if let node = attachment.nodeSnapshot,
                      let embedType = node.embedType,
                      let descriptor = AppleComposerRendererRegistry.shared.descriptor(for: embedType),
                      let lifecycle = try? AppleComposerRendererRegistry.shared.lifecycleState(for: node) {
                AppleComposerEmbedPreview(
                    descriptor: descriptor,
                    node: node,
                    lifecycle: lifecycle,
                    embedRecord: attachment.embedRecord,
                    allEmbedRecords: attachment.embedRecord.map { [$0.id: $0] } ?? [:],
                    localPreviewData: attachment.localPreviewData,
                    actions: attachment.embedActions,
                    hostedRemovalAction: hostedRemovalAction
                )
            } else {
                Text(attachment.nodeSnapshot?.display?.title ?? attachment.nodeSnapshot?.embedType ?? "")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var hostedRemovalAction: Binding<Bool>? {
        #if canImport(UIKit)
        Binding(get: { attachment.showsRemovalAction }, set: { attachment.setShowsRemovalAction($0) })
        #else
        nil
        #endif
    }
}
