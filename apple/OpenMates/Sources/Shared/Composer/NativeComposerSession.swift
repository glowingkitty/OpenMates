// Host-owned state container for the native Apple message composer.
// One controller owns semantic nodes, selection, marked text, undo, and revision.
// Canonical markdown is a published compatibility boundary, not a second model.
// Pending attachment atoms omit fake durable references until service resolution.
// All mutations publish from the controller after successful serialization.

import Combine
import Foundation
import OSLog

@MainActor
final class NativeComposerSession: ObservableObject {
    @Published private(set) var canonicalMarkdown: String
    @Published private(set) var revision: Int
    @Published private(set) var hasBlockingEmbeds: Bool

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
            return try NativeComposerController(
                document: document,
                selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
            )
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
