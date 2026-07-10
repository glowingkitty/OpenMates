// Canonical mention atom construction for the native composer.
// Display labels remain localized presentation while syntax remains durable data.
// Candidate metadata is injected by host catalogs rather than hardcoded views.
// Every supported kind maps deterministically to the existing web syntax.
// Selection-aware insertion is performed by NativeComposerController.

import Foundation

enum ComposerMentionKind: String, Sendable {
    case mate
    case aiModel
    case bestModel
    case skill
    case focus
    case project
    case memory
}

struct ComposerMentionCandidate: Equatable, Sendable {
    let kind: ComposerMentionKind
    let targetId: String
    let displayLabel: String
    let appId: String?
    let providerId: String?
    let accessMode: String?
    let memoryType: String?

    init(
        kind: ComposerMentionKind,
        targetId: String,
        displayLabel: String,
        appId: String? = nil,
        providerId: String? = nil,
        accessMode: String? = nil,
        memoryType: String? = nil
    ) {
        self.kind = kind
        self.targetId = targetId
        self.displayLabel = displayLabel
        self.appId = appId
        self.providerId = providerId
        self.accessMode = accessMode
        self.memoryType = memoryType
    }
}

struct ComposerMentionService {
    func node(candidate: ComposerMentionCandidate, nodeId: String) -> ComposerNodeV1 {
        .mention(
            id: nodeId,
            mentionKind: candidate.kind.rawValue,
            targetId: candidate.targetId,
            canonicalSyntax: canonicalSyntax(for: candidate),
            displayLabel: candidate.displayLabel
        )
    }

    private func canonicalSyntax(for candidate: ComposerMentionCandidate) -> String {
        switch candidate.kind {
        case .mate:
            "@mate:\(candidate.targetId)"
        case .aiModel:
            "@ai-model:\(candidate.targetId):\(candidate.providerId ?? "")"
        case .bestModel:
            "@best-model:\(candidate.targetId)"
        case .skill:
            "@skill:\(candidate.appId ?? ""):\(candidate.targetId)"
        case .focus:
            "@focus:\(candidate.appId ?? ""):\(candidate.targetId)"
        case .project:
            "@project:\(candidate.targetId):\(candidate.accessMode ?? "read")"
        case .memory:
            "@memory:\(candidate.appId ?? ""):\(candidate.targetId):\(candidate.memoryType ?? "text")"
        }
    }
}
