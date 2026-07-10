// Native controller for the product-owned ComposerDocument model.
// Commands edit semantic nodes directly and never parse transient editor text.
// Selection and marked ranges use platform-compatible UTF-16 offsets.
// Undo snapshots restore document, selection, and marked composition atomically.
// Attachment objects remain cached by stable node id across every transaction.

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
    case expectedMention(String)
    case platformSynchronizationFailed
}

@MainActor
final class NativeComposerController {
    private struct Snapshot {
        let document: ComposerDocumentV1
        let selection: NSRange
        let markedTextRange: NSRange?
    }

    private struct DeletionResult {
        let nodes: [ComposerNodeV1]
        let removedNodes: [ComposerNodeV1]
    }

    private(set) var document: ComposerDocumentV1
    private(set) var selection: NSRange
    private(set) var markedTextRange: NSRange?
    private(set) var attributedString = NSAttributedString()
    private(set) var revision = 0

    private var attachments: [String: ComposerTextAttachment] = [:]
    private var undoSnapshots: [Snapshot] = []
    private var redoSnapshots: [Snapshot] = []

    var canSubmit: Bool {
        markedTextRange == nil
            && !attributedString.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    init(document: ComposerDocumentV1, selection: NSRange) throws {
        self.document = document
        self.selection = selection
        var nodeIDs = Set<String>()
        for node in document.nodes where !nodeIDs.insert(node.id).inserted {
            throw NativeComposerControllerError.duplicateNodeID(node.id)
        }
        guard isValid(range: selection) else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }
        rebuildAttributedString()
    }

    func setSelection(_ range: NSRange) throws {
        guard isValid(range: range) else {
            throw NativeComposerControllerError.invalidSelection(range)
        }
        selection = range
    }

    func setMarkedTextRange(_ range: NSRange?) throws {
        if let range, !isValid(range: range) {
            throw NativeComposerControllerError.invalidSelection(range)
        }
        markedTextRange = range
    }

    func canonicalMarkdown() throws -> String {
        try ComposerMarkdownAdapter.serialize(document)
    }

    func loadDocument(_ document: ComposerDocumentV1) throws {
        var nodeIDs = Set<String>()
        for node in document.nodes where !nodeIDs.insert(node.id).inserted {
            throw NativeComposerControllerError.duplicateNodeID(node.id)
        }
        self.document = document
        selection = NSRange(
            location: document.nodes.reduce(0) { $0 + semanticLength(of: $1) },
            length: 0
        )
        markedTextRange = nil
        undoSnapshots.removeAll()
        redoSnapshots.removeAll()
        attachments = attachments.filter { nodeIDs.contains($0.key) }
        revision += 1
        rebuildAttributedString()
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
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            selection: NSRange(location: selection.location + 1, length: 0),
            markedTextRange: adjusted(markedTextRange, insertingAt: selection.location, length: 1)
        )
    }

    func insertMention(_ mention: ComposerNodeV1, replacing queryRange: NSRange? = nil) throws {
        guard mention.kind == "mention" else {
            throw NativeComposerControllerError.expectedMention(mention.id)
        }
        guard !document.nodes.contains(where: { $0.id == mention.id }) else {
            throw NativeComposerControllerError.duplicateNodeID(mention.id)
        }
        let replacementRange = queryRange ?? selection
        guard isValid(range: replacementRange) else {
            throw NativeComposerControllerError.invalidSelection(replacementRange)
        }

        let deletion = try deleting(range: replacementRange)
        let nodes = try nodesByInserting(
            mention,
            into: deletion.nodes,
            atUTF16Offset: replacementRange.location
        )
        let markedAfterDeletion = adjusted(markedTextRange, deleting: replacementRange)
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            selection: NSRange(location: replacementRange.location + 1, length: 0),
            markedTextRange: adjusted(
                markedAfterDeletion,
                insertingAt: replacementRange.location,
                length: 1
            )
        )
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
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            selection: selection,
            markedTextRange: markedTextRange
        )
    }

    func replaceEmbed(id: String, with replacement: ComposerNodeV1) throws {
        guard replacement.kind == "embed", replacement.id == id else {
            throw NativeComposerControllerError.expectedEmbed(replacement.id)
        }
        guard let index = document.nodes.firstIndex(where: { $0.id == id }) else {
            throw NativeComposerControllerError.nodeNotFound(id)
        }
        guard document.nodes[index].kind == "embed" else {
            throw NativeComposerControllerError.expectedEmbed(id)
        }
        var nodes = document.nodes
        nodes[index] = replacement
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            selection: selection,
            markedTextRange: markedTextRange
        )
    }

    #if !OPENMATES_SHARE_EXTENSION
    func configureEmbedActions(id: String, actions: AppleComposerEmbedActions) throws {
        guard let attachment = attachments[id] else {
            throw NativeComposerControllerError.nodeNotFound(id)
        }
        attachment.embedActions = actions
    }

    func configureEmbedPreview(
        id: String,
        embedRecord: EmbedRecord?,
        localPreviewData: Data?
    ) throws {
        guard let attachment = attachments[id] else {
            throw NativeComposerControllerError.nodeNotFound(id)
        }
        attachment.updatePreview(embedRecord: embedRecord, localPreviewData: localPreviewData)
    }
    #endif

    func removeEmbed(id: String) throws {
        guard let index = document.nodes.firstIndex(where: { $0.id == id }) else {
            throw NativeComposerControllerError.nodeNotFound(id)
        }
        guard document.nodes[index].kind == "embed" else {
            throw NativeComposerControllerError.expectedEmbed(id)
        }

        let range = NSRange(
            location: document.nodes[..<index].reduce(0) { $0 + semanticLength(of: $1) },
            length: 1
        )
        let result = try deleting(range: range)
        applyDeletion(result, range: range, selection: adjusted(selection, deleting: range))
    }

    func deleteBackward() throws {
        if selection.length > 0 {
            try deleteSelection()
            return
        }
        guard let range = deletionRangeBefore(selection.location) else { return }
        let result = try deleting(range: range)
        applyDeletion(result, range: range, selection: NSRange(location: range.location, length: 0))
    }

    func deleteForward() throws {
        if selection.length > 0 {
            try deleteSelection()
            return
        }
        guard let range = deletionRangeAfter(selection.location) else { return }
        let result = try deleting(range: range)
        applyDeletion(result, range: range, selection: selection)
    }

    func deleteSelection() throws {
        guard selection.length > 0 else { return }
        let range = selection
        let result = try deleting(range: range)
        applyDeletion(
            result,
            range: range,
            selection: NSRange(location: range.location, length: 0)
        )
    }

    func cutSelection() throws -> ComposerDocumentV1 {
        guard selection.length > 0 else {
            return ComposerDocumentV1(version: document.version, nodes: [])
        }
        let range = selection
        let result = try deleting(range: range)
        applyDeletion(
            result,
            range: range,
            selection: NSRange(location: range.location, length: 0)
        )
        return ComposerDocumentV1(version: document.version, nodes: result.removedNodes)
    }

    func replaceSelection(with source: String) throws {
        let replacedRange = selection
        let result = try deleting(range: replacedRange)
        let retainedIDs = Set(result.nodes.map(\.id))
        let preferredNodeID = result.removedNodes
            .first(where: { $0.kind == "text" && !retainedIDs.contains($0.id) })?
            .id
        let nodes = try nodesByInsertingText(
            source,
            into: result.nodes,
            atUTF16Offset: replacedRange.location,
            preferredNodeID: preferredNodeID
        )
        let replacementRange = NSRange(location: replacedRange.location, length: source.utf16.count)
        let nextMarkedRange = markedTextRange == nil
            ? nil
            : replacementRange
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: nodes),
            selection: NSRange(location: NSMaxRange(replacementRange), length: 0),
            markedTextRange: nextMarkedRange
        )
    }

    func undo() throws {
        guard let snapshot = undoSnapshots.popLast() else { return }
        redoSnapshots.append(currentSnapshot)
        restore(snapshot)
    }

    func redo() throws {
        guard let snapshot = redoSnapshots.popLast() else { return }
        undoSnapshots.append(currentSnapshot)
        restore(snapshot)
    }

    private var currentSnapshot: Snapshot {
        Snapshot(
            document: document,
            selection: selection,
            markedTextRange: markedTextRange
        )
    }

    private func apply(
        document: ComposerDocumentV1,
        selection: NSRange,
        markedTextRange: NSRange?
    ) {
        undoSnapshots.append(currentSnapshot)
        redoSnapshots.removeAll()
        self.document = document
        self.selection = selection
        self.markedTextRange = markedTextRange
        revision += 1
        rebuildAttributedString()
    }

    private func restore(_ snapshot: Snapshot) {
        document = snapshot.document
        selection = snapshot.selection
        markedTextRange = snapshot.markedTextRange
        revision += 1
        rebuildAttributedString()
    }

    private func applyDeletion(
        _ result: DeletionResult,
        range: NSRange,
        selection: NSRange
    ) {
        apply(
            document: ComposerDocumentV1(version: document.version, nodes: result.nodes),
            selection: selection,
            markedTextRange: adjusted(markedTextRange, deleting: range)
        )
    }

    private func deleting(range: NSRange) throws -> DeletionResult {
        guard isValid(range: range) else {
            throw NativeComposerControllerError.invalidSelection(range)
        }
        guard range.length > 0 else {
            return DeletionResult(nodes: document.nodes, removedNodes: [])
        }

        var retained: [ComposerNodeV1] = []
        var removed: [ComposerNodeV1] = []
        var cursor = 0
        for node in document.nodes {
            let length = semanticLength(of: node)
            let nodeRange = NSRange(location: cursor, length: length)
            let intersection = NSIntersectionRange(nodeRange, range)
            defer { cursor += length }

            guard intersection.length > 0 else {
                retained.append(node)
                continue
            }
            guard node.kind == "text", let source = node.source else {
                removed.append(node)
                continue
            }

            let localStart = intersection.location - cursor
            let localEnd = localStart + intersection.length
            guard
                let prefix = substring(source, from: 0, to: localStart),
                let selected = substring(source, from: localStart, to: localEnd),
                let suffix = substring(source, from: localEnd, to: length)
            else {
                throw NativeComposerControllerError.invalidSelection(range)
            }
            if !prefix.isEmpty || !suffix.isEmpty {
                retained.append(.text(id: node.id, source: prefix + suffix))
            }
            if !selected.isEmpty {
                let selectedID = prefix.isEmpty && suffix.isEmpty
                    ? node.id
                    : nextTextNodeID(
                        in: document.nodes,
                        reserving: Set(removed.map(\.id))
                    )
                removed.append(.text(id: selectedID, source: selected))
            }
        }
        return DeletionResult(nodes: retained, removedNodes: removed)
    }

    private func nodesByInserting(
        _ node: ComposerNodeV1,
        atUTF16Offset offset: Int
    ) throws -> [ComposerNodeV1] {
        try nodesByInserting(node, into: document.nodes, atUTF16Offset: offset)
    }

    private func nodesByInserting(
        _ insertedNode: ComposerNodeV1,
        into sourceNodes: [ComposerNodeV1],
        atUTF16Offset offset: Int
    ) throws -> [ComposerNodeV1] {
        let sourceLength = sourceNodes.reduce(0) { $0 + semanticLength(of: $1) }
        guard offset >= 0, offset <= sourceLength else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }

        var result: [ComposerNodeV1] = []
        var cursor = 0
        var inserted = false

        for node in sourceNodes {
            let length = semanticLength(of: node)
            if !inserted, offset >= cursor, offset <= cursor + length {
                if node.kind == "text", let source = node.source {
                    let localOffset = offset - cursor
                    if localOffset == 0 {
                        result.append(insertedNode)
                        result.append(node)
                    } else if localOffset == length {
                        result.append(node)
                        result.append(insertedNode)
                    } else if
                        let left = substring(source, from: 0, to: localOffset),
                        let right = substring(source, from: localOffset, to: length)
                    {
                        result.append(.text(id: node.id, source: left))
                        result.append(insertedNode)
                        result.append(.text(
                            id: nextTextNodeID(in: sourceNodes, reserving: [insertedNode.id]),
                            source: right
                        ))
                    } else {
                        throw NativeComposerControllerError.invalidSelection(selection)
                    }
                } else if offset == cursor {
                    result.append(insertedNode)
                    result.append(node)
                } else if offset == cursor + length {
                    result.append(node)
                    result.append(insertedNode)
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
            result.append(insertedNode)
            inserted = true
        }
        guard inserted else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }
        return result
    }

    private func nodesByInsertingText(
        _ source: String,
        into nodes: [ComposerNodeV1],
        atUTF16Offset offset: Int,
        preferredNodeID: String?
    ) throws -> [ComposerNodeV1] {
        guard !source.isEmpty else { return nodes }

        var result = nodes
        var cursor = 0
        for index in result.indices {
            let node = result[index]
            let length = semanticLength(of: node)
            if node.kind == "text", let current = node.source,
               offset >= cursor, offset <= cursor + length {
                let localOffset = offset - cursor
                guard
                    let prefix = substring(current, from: 0, to: localOffset),
                    let suffix = substring(current, from: localOffset, to: length)
                else {
                    throw NativeComposerControllerError.invalidSelection(selection)
                }
                result[index] = .text(id: node.id, source: prefix + source + suffix)
                return result
            }
            if offset == cursor {
                result.insert(
                    .text(
                        id: preferredNodeID
                            ?? nextTextNodeID(in: result, reserving: Set(document.nodes.map(\.id))),
                        source: source
                    ),
                    at: index
                )
                return result
            }
            cursor += length
        }

        guard offset == cursor else {
            throw NativeComposerControllerError.invalidSelection(selection)
        }
        result.append(.text(
            id: preferredNodeID
                ?? nextTextNodeID(in: result, reserving: Set(document.nodes.map(\.id))),
            source: source
        ))
        return result
    }

    private func deletionRangeBefore(_ position: Int) -> NSRange? {
        guard position > 0 else { return nil }
        var cursor = 0
        for node in document.nodes {
            let length = semanticLength(of: node)
            if position > cursor, position <= cursor + length {
                guard node.kind == "text", let source = node.source else {
                    return NSRange(location: cursor, length: length)
                }
                let localOffset = position - cursor
                guard
                    let end = stringIndex(in: source, utf16Offset: localOffset),
                    end > source.startIndex
                else { return nil }
                let start = source.index(before: end)
                let removedLength = source[start..<end].utf16.count
                return NSRange(location: position - removedLength, length: removedLength)
            }
            cursor += length
        }
        return nil
    }

    private func deletionRangeAfter(_ position: Int) -> NSRange? {
        guard position < semanticLength else { return nil }
        var cursor = 0
        for node in document.nodes {
            let length = semanticLength(of: node)
            if position >= cursor, position < cursor + length {
                guard node.kind == "text", let source = node.source else {
                    return NSRange(location: cursor, length: length)
                }
                let localOffset = position - cursor
                guard
                    let start = stringIndex(in: source, utf16Offset: localOffset),
                    start < source.endIndex
                else { return nil }
                let end = source.index(after: start)
                return NSRange(location: position, length: source[start..<end].utf16.count)
            }
            cursor += length
        }
        return nil
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

    private func substring(_ source: String, from start: Int, to end: Int) -> String? {
        guard
            let startIndex = stringIndex(in: source, utf16Offset: start),
            let endIndex = stringIndex(in: source, utf16Offset: end)
        else { return nil }
        return String(source[startIndex..<endIndex])
    }

    private func stringIndex(in source: String, utf16Offset: Int) -> String.Index? {
        guard utf16Offset >= 0, utf16Offset <= source.utf16.count else { return nil }
        let index = source.utf16.index(source.utf16.startIndex, offsetBy: utf16Offset)
        return String.Index(index, within: source)
    }

    private func isValid(range: NSRange) -> Bool {
        guard
            range.location >= 0,
            range.length >= 0,
            range.location <= semanticLength,
            range.length <= semanticLength - range.location
        else { return false }
        return isValid(position: range.location) && isValid(position: NSMaxRange(range))
    }

    private func isValid(position: Int) -> Bool {
        var cursor = 0
        for node in document.nodes {
            let length = semanticLength(of: node)
            if position >= cursor, position <= cursor + length {
                if node.kind == "text", let source = node.source {
                    return stringIndex(in: source, utf16Offset: position - cursor) != nil
                }
                return position == cursor || position == cursor + length
            }
            cursor += length
        }
        return position == cursor
    }

    private func nextTextNodeID(
        in nodes: [ComposerNodeV1],
        reserving reservedIDs: Set<String> = []
    ) -> String {
        var index = 0
        let ids = Set(nodes.map(\.id)).union(reservedIDs)
        while ids.contains("composer:text:\(index)") { index += 1 }
        return "composer:text:\(index)"
    }

    private func adjusted(_ range: NSRange?, deleting deletedRange: NSRange) -> NSRange? {
        range.map { adjusted($0, deleting: deletedRange) }
    }

    private func adjusted(_ range: NSRange, deleting deletedRange: NSRange) -> NSRange {
        func position(_ value: Int) -> Int {
            if value <= deletedRange.location { return value }
            if value >= NSMaxRange(deletedRange) { return value - deletedRange.length }
            return deletedRange.location
        }
        let start = position(range.location)
        let end = position(NSMaxRange(range))
        return NSRange(location: start, length: end - start)
    }

    private func adjusted(_ range: NSRange?, insertingAt location: Int, length: Int) -> NSRange? {
        guard let range else { return nil }
        let start = range.location >= location ? range.location + length : range.location
        let end = NSMaxRange(range) >= location ? NSMaxRange(range) + length : NSMaxRange(range)
        return NSRange(location: start, length: end - start)
    }

    private func rebuildAttributedString() {
        let value = NSMutableAttributedString(string: "")
        for node in document.nodes {
            switch node.kind {
            case "text":
                value.append(NSAttributedString(string: node.source ?? ""))
            case "hardBreak":
                value.append(NSAttributedString(string: "\n"))
            case "mention", "embed":
                let attachment = attachments[node.id] ?? ComposerTextAttachment(node: node)
                attachment.update(node: node)
                attachments[node.id] = attachment
                value.append(NSAttributedString(attachment: attachment))
            default:
                continue
            }
        }
        attributedString = value.copy() as? NSAttributedString ?? value
    }
}
