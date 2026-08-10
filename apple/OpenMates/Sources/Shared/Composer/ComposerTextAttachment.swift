// Stable TextKit attachment atom for native composer semantic nodes.
// The node id reconnects reused attachment views to controller-owned state.
// Attachment instances contain no upload, persistence, or encryption services.
// UIKit and AppKit use the same archive representation and provider contract.
// Each attachment occupies exactly one UTF-16 position in the editor surface.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
// ────────────────────────────────────────────────────────────────────

import Foundation

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

final class ComposerTextAttachment: NSTextAttachment {
    let nodeID: String
    private(set) var nodeSnapshot: ComposerNodeV1?
    #if !OPENMATES_SHARE_EXTENSION
    private(set) var embedRecord: EmbedRecord?
    private(set) var localPreviewData: Data?
    var embedActions = AppleComposerEmbedActions(
        onOpen: { _ in },
        onRetry: { _ in },
        onRemove: { _ in }
    )
    #endif

    init(node: ComposerNodeV1) {
        self.nodeID = node.id
        self.nodeSnapshot = node
        super.init(data: nil, ofType: nil)
        #if OPENMATES_SHARE_EXTENSION
        // Share hosts need atomic document positions but do not load app renderers.
        #if canImport(UIKit)
        image = UIImage(systemName: "paperclip")
        #elseif canImport(AppKit)
        image = NSImage(systemSymbolName: "paperclip", accessibilityDescription: node.display?.title)
        #endif
        #else
        allowsTextAttachmentView = true
        #endif
    }

    required init?(coder: NSCoder) {
        guard let nodeID = coder.decodeObject(of: NSString.self, forKey: "nodeID") as? String else {
            return nil
        }
        self.nodeID = nodeID
        self.nodeSnapshot = nil
        super.init(coder: coder)
    }

    override func encode(with coder: NSCoder) {
        super.encode(with: coder)
        coder.encode(nodeID, forKey: "nodeID")
    }

    override var usesTextAttachmentView: Bool {
        #if OPENMATES_SHARE_EXTENSION
        false
        #else
        true
        #endif
    }

    func update(node: ComposerNodeV1) {
        guard node.id == nodeID else { return }
        nodeSnapshot = node
    }

    #if !OPENMATES_SHARE_EXTENSION
    func updatePreview(embedRecord: EmbedRecord?, localPreviewData: Data?) {
        self.embedRecord = embedRecord
        self.localPreviewData = localPreviewData
    }
    #endif

    #if !OPENMATES_SHARE_EXTENSION && canImport(UIKit)
    override func viewProvider(
        for parentView: UIView?,
        location: any NSTextLocation,
        textContainer: NSTextContainer?
    ) -> NSTextAttachmentViewProvider? {
        ComposerAttachmentViewProvider(
            textAttachment: self,
            parentView: parentView,
            textLayoutManager: textContainer?.textLayoutManager,
            location: location
        )
    }
    #elseif !OPENMATES_SHARE_EXTENSION && canImport(AppKit)
    override func viewProvider(
        for parentView: NSView?,
        location: any NSTextLocation,
        textContainer: NSTextContainer?
    ) -> NSTextAttachmentViewProvider? {
        ComposerAttachmentViewProvider(
            textAttachment: self,
            parentView: parentView,
            textLayoutManager: textContainer?.textLayoutManager,
            location: location
        )
    }
    #endif
}
