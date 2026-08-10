// Shared submit and newline decisions for every native composer host.
// Platform input policy is separate from transport and encryption boundaries.
// Marked text and conversion work cannot submit partial composer content.
// Embed blockers produce immutable node-generation requirements for deferral.
// Request and revision guards prevent duplicate remote handoffs.

import Foundation

enum ComposerSubmitPlatform: Equatable, Sendable {
    case touch
    case desktop
}

enum ComposerSubmitTrigger: Equatable, Sendable {
    case returnKey
    case sendButton
}

struct ComposerSubmitModifiers: OptionSet, Sendable {
    let rawValue: Int

    static let shift = ComposerSubmitModifiers(rawValue: 1 << 0)
    static let option = ComposerSubmitModifiers(rawValue: 1 << 1)
}

enum ComposerSubmitBlockedReason: Equatable, Sendable {
    case empty
    case markedText
}

enum ComposerSubmitDecision: Equatable, Sendable {
    case insertHardBreak
    case submit
    case deferred([ComposerEmbedBlocker])
    case blocked(ComposerSubmitBlockedReason)
}

enum ComposerSubmitPolicy {
    static func decision(
        document: ComposerDocumentV1,
        platform: ComposerSubmitPlatform,
        trigger: ComposerSubmitTrigger,
        modifiers: ComposerSubmitModifiers,
        markedTextRange: NSRange?,
        conversionInFlight: Bool
    ) -> ComposerSubmitDecision {
        if markedTextRange != nil {
            return .blocked(.markedText)
        }
        if trigger == .returnKey,
           platform == .touch || modifiers.contains(.shift) || modifiers.contains(.option) {
            return .insertHardBreak
        }
        if conversionInFlight {
            return .deferred([])
        }

        let blockers = document.nodes.compactMap { node -> ComposerEmbedBlocker? in
            guard node.kind == "embed",
                  let status = node.status,
                  let state = AppleComposerEmbedLifecycleState(rawValue: status),
                  ComposerEmbedLifecycle.isBlocking(state) else {
                return nil
            }
            return ComposerEmbedBlocker(nodeId: node.id, generation: 1)
        }
        if !blockers.isEmpty {
            return .deferred(blockers)
        }

        let hasVisibleText = document.nodes.contains { node in
            node.kind == "text"
                && !(node.source ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        let mentionCount = document.nodes.filter { $0.kind == "mention" }.count
        let hasSendableEmbed = document.nodes.contains { node in
            guard node.kind == "embed",
                  let status = node.status,
                  let state = AppleComposerEmbedLifecycleState(rawValue: status) else {
                return false
            }
            return state == .finished || state == .processing
        }
        return hasVisibleText || mentionCount > 1 || hasSendableEmbed
            ? .submit
            : .blocked(.empty)
    }
}

actor ComposerSubmitGuard {
    private var consumedRequestIds: Set<String> = []
    private var consumedRevisions: Set<Int> = []

    func begin(requestId: String, documentRevision: Int) -> Bool {
        guard !consumedRequestIds.contains(requestId),
              !consumedRevisions.contains(documentRevision) else {
            return false
        }
        consumedRequestIds.insert(requestId)
        consumedRevisions.insert(documentRevision)
        return true
    }

    func complete(requestId: String) {
        // Consumed identities intentionally remain reserved after completion.
        _ = requestId
    }
}
