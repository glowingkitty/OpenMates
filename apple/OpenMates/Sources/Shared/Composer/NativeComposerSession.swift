// Host-owned state container for the native Apple message composer.
// One controller owns semantic nodes, selection, marked text, undo, and revision.
// Canonical markdown is a published compatibility boundary, not a second model.
// Pending attachment atoms omit fake durable references until service resolution.
// All mutations publish from the controller after successful serialization.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.embeds.gated-send

import Combine
import Foundation
import OSLog

@MainActor
final class NativeComposerSession: ObservableObject {
    @Published private(set) var canonicalMarkdown: String
    @Published private(set) var revision: Int
    @Published private(set) var hasBlockingEmbeds: Bool

    @Published private(set) var isDictating = false

    private struct Dictation {
        var range: NSRange
        var expectedDocument: String
        var inserted = false
    }

    private var dictation: Dictation?

    let controller: NativeComposerController

    init(canonicalMarkdown: String = "") {
        controller = Self.makeController(canonicalMarkdown: canonicalMarkdown)
        self.canonicalMarkdown = canonicalMarkdown
        self.revision = controller.revision
        self.hasBlockingEmbeds = Self.containsBlockingEmbeds(controller.document)
        publishControllerState()
    }

    func replaceMarkdown(_ markdown: String) {
        guard markdown != canonicalMarkdown else { return }
        do {
            try controller.loadDocument(ComposerMarkdownAdapter.parse(markdown))
            publishControllerState()
        } catch {
            Self.report(error, operation: "markdown replacement")
        }
    }

    func loadDocument(_ document: ComposerDocumentV1) throws {
        try controller.loadDocument(document)
        publishControllerState()
    }

    func replaceSelection(with text: String) throws {
        try controller.replaceSelection(with: text)
        publishControllerState()
    }

    /// The live draft uses the same editable document and undo path as typing.
    func beginDictation() {
        let selected = controller.selection
        dictation = Dictation(range: NSRange(location: selected.location, length: 0),
            expectedDocument: controller.attributedString.string)
        isDictating = true
    }

    @discardableResult
    func updateDictation(_ words: String) -> Bool {
        let text = words.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var capture = dictation, !text.isEmpty else { return false }
        // Manual edits win over delayed partials and corrections.
        guard capture.expectedDocument == controller.attributedString.string else { return capture.inserted }
        let source = capture.expectedDocument as NSString
        let left = source.substring(to: capture.range.location).last
        let right = source.substring(from: NSMaxRange(capture.range)).first
        let prefix = left.map { $0.isLetter || $0.isNumber } == true ? " " : ""
        let suffix = right.map { $0.isLetter || $0.isNumber } == true ? " " : ""
        let insertion = prefix + text + suffix
        if source.substring(with: capture.range) == insertion { return capture.inserted }
        do {
            try controller.setSelection(capture.range)
            try replaceSelection(with: insertion)
            capture.range.length = insertion.utf16.count
            capture.expectedDocument = controller.attributedString.string
            capture.inserted = true
            dictation = capture
            return true
        } catch {
            Self.report(error, operation: "dictation insertion")
            return capture.inserted
        }
    }

    @discardableResult
    func finishDictation(_ words: String?) -> Bool {
        if let words { updateDictation(words) }
        let inserted = dictation?.inserted == true
        dictation = nil
        isDictating = false
        return inserted
    }

    func cancelDictation() {
        if let capture = dictation, capture.inserted,
           capture.expectedDocument == controller.attributedString.string {
            do {
                try controller.setSelection(capture.range)
                try replaceSelection(with: "")
            } catch {
                Self.report(error, operation: "dictation cancellation")
            }
        }
        dictation = nil
        isDictating = false
    }

    func insertPendingEmbed(
        nodeID: String,
        embedType: String,
        title: String,
        localPreviewData: Data? = nil
    ) throws {
        let node = ComposerNodeV1(
            kind: "embed",
            id: nodeID,
            embedType: embedType,
            status: AppleComposerEmbedLifecycleState.draft.rawValue,
            referenceOnly: true,
            canonicalSource: "",
            display: ComposerEmbedDisplayV1(title: title, mediaKind: embedType)
        )
        try controller.insertEmbed(node)
        #if !OPENMATES_SHARE_EXTENSION
        try controller.configureEmbedPreview(
            id: nodeID,
            embedRecord: nil,
            localPreviewData: localPreviewData
        )
        #endif
        publishControllerState()
    }

    /// Recording completion appends without replacing an earlier selection or draft content.
    /// Keep the existing controller and node identities; never rebuild from preview text.
    func appendPendingEmbed(
        nodeID: String,
        embedType: String,
        title: String,
        localPreviewData: Data? = nil
    ) throws {
        let previousSelection = controller.selection
        try controller.setSelection(NSRange(location: controller.attributedString.length, length: 0))
        do {
            try insertPendingEmbed(nodeID: nodeID, embedType: embedType,
                                   title: title, localPreviewData: localPreviewData)
        } catch {
            try? controller.setSelection(previousSelection)
            throw error
        }
    }

    #if !OPENMATES_SHARE_EXTENSION
    func resolveEmbed(
        nodeID: String,
        durableEmbedID: String,
        referenceType: String,
        status: String,
        embedRecord: EmbedRecord? = nil,
        localPreviewData: Data? = nil
    ) throws {
        guard let current = controller.document.nodes.first(where: { $0.id == nodeID }) else {
            throw NativeComposerControllerError.nodeNotFound(nodeID)
        }
        let canonicalSource = "```json\n{\"type\": \"\(referenceType)\", \"embed_id\": \"\(durableEmbedID)\"}\n```"
        let resolved = ComposerNodeV1(
            kind: "embed",
            id: nodeID,
            embedType: current.embedType,
            status: status,
            contentRef: "embed:\(durableEmbedID)",
            referenceOnly: true,
            canonicalSource: canonicalSource,
            display: current.display
        )
        try controller.configureEmbedPreview(
            id: nodeID,
            embedRecord: embedRecord,
            localPreviewData: localPreviewData
        )
        try controller.replaceEmbed(id: nodeID, with: resolved)
        publishControllerState()
    }

    func updateEmbed(nodeID: String, status: String) throws {
        try controller.updateEmbed(id: nodeID, status: status)
        publishControllerState()
    }

    /// Publishes a provisional transcript on the existing local embed atom.
    /// Durable identity and canonical source remain unset until upload resolves.
    func updatePendingEmbedTitle(nodeID: String, title: String) throws {
        guard let current = controller.document.nodes.first(where: { $0.id == nodeID }),
              current.kind == "embed",
              current.contentRef == nil else {
            throw NativeComposerControllerError.nodeNotFound(nodeID)
        }
        let replacement = ComposerNodeV1(
            kind: current.kind,
            id: current.id,
            source: current.source,
            mentionKind: current.mentionKind,
            targetId: current.targetId,
            canonicalSyntax: current.canonicalSyntax,
            displayLabel: current.displayLabel,
            embedType: current.embedType,
            status: current.status,
            contentRef: current.contentRef,
            referenceOnly: current.referenceOnly,
            canonicalSource: current.canonicalSource,
            display: ComposerEmbedDisplayV1(
                title: title,
                mediaKind: current.display?.mediaKind ?? current.embedType ?? "recording"
            )
        )
        try controller.replaceEmbed(id: nodeID, with: replacement)
        publishControllerState()
    }

    func configureEmbedActions(
        nodeID: String,
        onOpen: @escaping (String) -> Void,
        onRetry: @escaping (String) -> Void,
        onRemove: @escaping (String) -> Void
    ) throws {
        try controller.configureEmbedActions(
            id: nodeID,
            actions: AppleComposerEmbedActions(
                onOpen: onOpen,
                onRetry: onRetry,
                onRemove: { [weak self] id in
                    Task { @MainActor in
                        guard let self else { return }
                        let durableID = self.controller.document.nodes
                            .first(where: { $0.id == id })?
                            .contentRef?
                            .replacingOccurrences(of: "embed:", with: "")
                        try? self.removeEmbed(nodeID: id)
                        onRemove(durableID ?? id)
                    }
                }
            )
        )
    }
    #endif

    func removeEmbed(nodeID: String) throws {
        try controller.removeEmbed(id: nodeID)
        publishControllerState()
    }

    func removeSentSnapshotNodes(_ snapshot: ComposerDocumentV1) throws {
        let snapshotNodes = Dictionary(uniqueKeysWithValues: snapshot.nodes.map { ($0.id, $0) })
        let remainingNodes = controller.document.nodes.filter { node in
            guard let snapshotNode = snapshotNodes[node.id] else { return true }
            // Resolved embeds differ from their queued atom, but must be removed after send.
            // Text only disappears when it has not been edited since the user queued the send.
            return node.kind != "embed" && node != snapshotNode
        }
        try controller.loadDocument(ComposerDocumentV1(version: 1, nodes: remainingNodes))
        publishControllerState()
    }

    func clear() {
        do {
            try controller.loadDocument(ComposerDocumentV1(version: 1, nodes: []))
            publishControllerState()
        } catch {
            Self.report(error, operation: "clear")
        }
    }

    func canonicalMarkdownForSend() throws -> String {
        try controller.canonicalMarkdown()
    }

    func publishControllerState(canonicalMarkdown knownCanonicalMarkdown: String? = nil) {
        do {
            if let knownCanonicalMarkdown {
                canonicalMarkdown = knownCanonicalMarkdown
            } else {
                canonicalMarkdown = try controller.canonicalMarkdown()
            }
            revision = controller.revision
            hasBlockingEmbeds = Self.containsBlockingEmbeds(controller.document)
        } catch {
            Self.report(error, operation: "state publication")
        }
    }

    private static func containsBlockingEmbeds(_ document: ComposerDocumentV1) -> Bool {
        document.nodes.contains { node in
            guard node.kind == "embed",
                  let status = node.status,
                  let state = AppleComposerEmbedLifecycleState(rawValue: status) else {
                return false
            }
            return ComposerEmbedLifecycle.isBlocking(state)
        }
    }

    private static func makeController(canonicalMarkdown: String) -> NativeComposerController {
        do {
            let document = try ComposerMarkdownAdapter.parse(canonicalMarkdown)
            // Canonical wire references occupy one semantic editor atom.
            // The controller owns end selection in that semantic coordinate space.
            return try NativeComposerController(document: document)
        } catch {
            Self.report(error, operation: "session recovery")
            let fallback = ComposerDocumentV1(
                version: 1,
                nodes: [.text(id: "composer:text:recovery", source: canonicalMarkdown)]
            )
            do {
                return try NativeComposerController(
                    document: fallback,
                    selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
                )
            } catch {
                preconditionFailure("Valid native composer recovery document was rejected")
            }
        }
    }

    private static func report(_ error: Error, operation: String) {
        #if OPENMATES_SHARE_EXTENSION
        Logger(subsystem: "org.openmates.app.share", category: "native_composer")
            .warning("Native composer \(operation, privacy: .public) failed: \(String(describing: type(of: error)), privacy: .public)")
        #else
        NativeDiagnostics.warning(
            "Native composer \(operation) failed: \(type(of: error))",
            category: "apple_composer"
        )
        #endif
    }
}
