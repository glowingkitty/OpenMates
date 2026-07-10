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

enum ComposerMentionError: Error, Equatable {
    case missingProviderId
    case missingAppId
    case missingMemoryType
}

struct ComposerMentionService {
    func node(candidate: ComposerMentionCandidate, nodeId: String) throws -> ComposerNodeV1 {
        let syntax = try canonicalSyntax(for: candidate)
        return .mention(
            id: nodeId,
            mentionKind: candidate.kind.rawValue,
            targetId: candidate.targetId,
            canonicalSyntax: syntax,
            displayLabel: candidate.displayLabel
        )
    }

    private func canonicalSyntax(for candidate: ComposerMentionCandidate) throws -> String {
        switch candidate.kind {
        case .mate:
            "@mate:\(candidate.targetId)"
        case .aiModel:
            guard let providerId = candidate.providerId, !providerId.isEmpty else {
                throw ComposerMentionError.missingProviderId
            }
            return "@ai-model:\(candidate.targetId):\(providerId)"
        case .bestModel:
            "@best-model:\(candidate.targetId)"
        case .skill:
            guard let appId = candidate.appId, !appId.isEmpty else {
                throw ComposerMentionError.missingAppId
            }
            return "@skill:\(appId):\(candidate.targetId)"
        case .focus:
            guard let appId = candidate.appId, !appId.isEmpty else {
                throw ComposerMentionError.missingAppId
            }
            return "@focus:\(appId):\(candidate.targetId)"
        case .project:
            "@project:\(candidate.targetId):\(candidate.accessMode ?? "read")"
        case .memory:
            guard let appId = candidate.appId, !appId.isEmpty else {
                throw ComposerMentionError.missingAppId
            }
            guard let memoryType = candidate.memoryType, !memoryType.isEmpty else {
                throw ComposerMentionError.missingMemoryType
            }
            return "@memory:\(appId):\(candidate.targetId):\(memoryType)"
        }
    }
}
