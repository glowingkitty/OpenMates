// Native controller for the product-owned ComposerDocument model.
// TextKit receives one attachment character for each atomic embed node.
// Selection uses UTF-16 offsets so UIKit, AppKit, and web fixtures agree.
// Attachment objects are cached by node id across non-structural updates.
// This controller owns no networking, persistence, or encryption material.

import Foundation

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

enum NativeComposerControllerError: Error, Equatable {
    case invalidSelection(NSRange)
    case duplicateNodeID(String)
    case nodeNotFound(String)
    case expectedEmbed(String)
}

final class ComposerTextAttachment: NSTextAttachment {
    let nodeID: String
    var onActivate: (() -> Void)?

    init(nodeID: String, onActivate: (() -> Void)? = nil) {
        self.nodeID = nodeID
        self.onActivate = onActivate
        super.init(data: nil, ofType: nil)
        allowsTextAttachmentView = true
    }

    required init?(coder: NSCoder) {
        guard let nodeID = coder.decodeObject(of: NSString.self, forKey: "nodeID") as? String else {
            return nil
        }
        self.nodeID = nodeID
        self.onActivate = nil
        super.init(coder: coder)
    }

    override func encode(with coder: NSCoder) {
        super.encode(with: coder)
        coder.encode(nodeID, forKey: "nodeID")
    }

    override var usesTextAttachmentView: Bool { true }

    #if canImport(UIKit)
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
    #elseif canImport(AppKit)
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

#if canImport(UIKit)
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
        MainActor.assumeIsolated {
            let button = UIButton(type: .custom)
            button.accessibilityIdentifier = "native-composer-embed-prototype"
            button.addAction(UIAction { [weak self] _ in
                (self?.textAttachment as? ComposerTextAttachment)?.onActivate?()
            }, for: .touchUpInside)
            view = button
        }
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
        MainActor.assumeIsolated {
            let button = ComposerAttachmentButton()
            button.onActivate = { [weak self] in
                (self?.textAttachment as? ComposerTextAttachment)?.onActivate?()
            }
            button.identifier = NSUserInterfaceItemIdentifier("native-composer-embed-prototype")
            view = button
        }
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

private final class ComposerAttachmentButton: NSButton {
    var onActivate: (() -> Void)?

    override func mouseUp(with event: NSEvent) {
        super.mouseUp(with: event)
        onActivate?()
    }
}
#endif

final class NativeComposerController {
    private(set) var document: ComposerDocumentV1
    private(set) var selection: NSRange
    private(set) var markedTextRange: NSRange?
    private(set) var attributedString = NSAttributedString()

    private var attachments: [String: ComposerTextAttachment] = [:]

    var canSubmit: Bool {
        markedTextRange == nil && !attributedString.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    init(document: ComposerDocumentV1, selection: NSRange) {
        self.document = document
        self.selection = selection
        rebuildAttributedString()
    }

    func setMarkedTextRange(_ range: NSRange?) {
        markedTextRange = range
    }

    func insertEmbed(_ embed: ComposerNodeV1) throws {
        guard embed.kind == "embed" else {
            throw NativeComposerControllerError.expectedEmbed(embed.id)
        }
        guard !document.nodes.contains(where: { $0.id == embed.id }) else {
            throw NativeComposerControllerError.duplicateNodeID(embed.id)
        }
        guard selection.length == 0 else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }

        let nodes = try nodesByInserting(embed, atUTF16Offset: selection.location)
        document = ComposerDocumentV1(version: document.version, nodes: nodes)
        selection = NSRange(location: selection.location + 1, length: 0)
        rebuildAttributedString()
    }

    func updateEmbed(id: String, status: String) throws {
        guard let index = document.nodes.firstIndex(where: { $0.id == id }) else {
            throw NativeComposerControllerError.nodeNotFound(id)
        }
        guard document.nodes[index].kind == "embed" else {
            throw NativeComposerControllerError.expectedEmbed(id)
        }

        var nodes = document.nodes
        nodes[index] = nodes[index].updatingStatus(status)
        document = ComposerDocumentV1(version: document.version, nodes: nodes)
        rebuildAttributedString()
    }

    private func nodesByInserting(
        _ embed: ComposerNodeV1,
        atUTF16Offset offset: Int
    ) throws -> [ComposerNodeV1] {
        guard offset >= 0, offset <= semanticLength else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }

        var result: [ComposerNodeV1] = []
        var cursor = 0
        var inserted = false

        for node in document.nodes {
            let length = semanticLength(of: node)
            if !inserted, offset >= cursor, offset <= cursor + length {
                if node.kind == "text", let source = node.source {
                    let localOffset = offset - cursor
                    guard let splitIndex = stringIndex(in: source, utf16Offset: localOffset) else {
                        throw NativeComposerControllerError.invalidSelection(selection)
                    }
                    let left = String(source[..<splitIndex])
                    let right = String(source[splitIndex...])
                    if !left.isEmpty {
                        result.append(.text(id: node.id, source: left))
                    }
                    result.append(embed)
                    if !right.isEmpty {
                        result.append(.text(id: nextTextNodeID(), source: right))
                    }
                } else if offset == cursor {
                    result.append(embed)
                    result.append(node)
                } else if offset == cursor + length {
                    result.append(node)
                    result.append(embed)
                } else {
                    throw NativeComposerControllerError.invalidSelection(selection)
                }
                inserted = true
            } else {
                result.append(node)
            }
            cursor += length
        }

        if !inserted, offset == cursor {
            result.append(embed)
            inserted = true
        }
        guard inserted else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }
        return result
    }

    private var semanticLength: Int {
        document.nodes.reduce(0) { $0 + semanticLength(of: $1) }
    }

    private func semanticLength(of node: ComposerNodeV1) -> Int {
        switch node.kind {
        case "text": node.source?.utf16.count ?? 0
        case "hardBreak", "mention", "embed": 1
        default: 0
        }
    }

    private func stringIndex(in source: String, utf16Offset: Int) -> String.Index? {
        guard utf16Offset >= 0, utf16Offset <= source.utf16.count else { return nil }
        let index = source.utf16.index(source.utf16.startIndex, offsetBy: utf16Offset)
        return String.Index(index, within: source)
    }

    private func nextTextNodeID() -> String {
        var index = 0
        let ids = Set(document.nodes.map(\.id))
        while ids.contains("composer:text:\(index)") { index += 1 }
        return "composer:text:\(index)"
    }

    private func rebuildAttributedString() {
        let value = NSMutableAttributedString(string: "")
        for node in document.nodes {
            switch node.kind {
            case "text":
                value.append(NSAttributedString(string: node.source ?? ""))
            case "hardBreak":
                value.append(NSAttributedString(string: "\n"))
            case "mention":
                value.append(NSAttributedString(string: node.displayLabel ?? node.canonicalSyntax ?? ""))
            case "embed":
                let attachment = attachments[node.id] ?? ComposerTextAttachment(nodeID: node.id)
                attachments[node.id] = attachment
                value.append(NSAttributedString(attachment: attachment))
            default:
                continue
            }
        }
        attributedString = value.copy() as? NSAttributedString ?? value
    }
}
