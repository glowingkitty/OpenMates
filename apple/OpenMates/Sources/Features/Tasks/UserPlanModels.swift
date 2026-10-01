// Encrypted Plans V1 models shown alongside Tasks on the workspace board.
// Wire names mirror frontend/packages/ui/src/services/userPlanService.ts.

import Foundation

enum UserPlanStatus: String, Codable, Sendable, CaseIterable, Identifiable {
    case draft
    case checkingAssumptions = "checking_assumptions"
    case awaitingConfirmation = "awaiting_confirmation"
    case active
    case executing
    case runningChecks = "running_checks"
    case blocked
    case completed
    case archived

    var id: String { rawValue }
    var title: String { rawValue.replacingOccurrences(of: "_", with: " ").capitalized }

    var boardColumn: UserTaskStatus? {
        switch self {
        case .archived: nil
        case .completed: .done
        case .blocked: .blocked
        case .executing, .runningChecks: .inProgress
        case .checkingAssumptions, .awaitingConfirmation, .active: .todo
        case .draft: .backlog
        }
    }
}

struct UserPlanKeyWrapper: Codable, Sendable {
    let keyType: String
    let encryptedPlanKey: String
    let hashedChatId: String?
    let hashedProjectId: String?
    let createdAt: Int
    let expiresAt: Int?
}

struct EncryptedUserPlanRecord: Codable, Sendable {
    let planId: String
    let encryptedTitle: String
    let encryptedGoal: String
    let encryptedScopeIn: String?
    let encryptedScopeOut: String?
    let encryptedUserFlows: String?
    let encryptedAssumptions: String?
    let encryptedOpenQuestions: String?
    let encryptedConstraints: String?
    let encryptedDecisions: String?
    let encryptedRisks: String?
    let encryptedLinkedProjectIds: String?
    let status: UserPlanStatus
    let primaryChatId: String?
    let linkedProjectIds: [String]?
    let linkedProjectHashes: [String]?
    let plannerFocusId: String?
    let version: Int?
    let createdAt: Int
    let updatedAt: Int
    let completedAt: Int?
    let keyWrappers: [UserPlanKeyWrapper]?
}

struct UserPlanFlowStep: Codable, Sendable, Identifiable {
    let stepId: String
    let text: String
    var id: String { stepId }
}

struct UserPlanFlow: Codable, Sendable, Identifiable {
    let flowId: String
    let title: String
    let expectedOutcome: String
    let steps: [UserPlanFlowStep]
    var id: String { flowId }
}

struct UserPlanItem: Identifiable, Sendable {
    let record: EncryptedUserPlanRecord
    let title: String
    let goal: String
    let scopeIn: String
    let scopeOut: String
    let userFlows: [UserPlanFlow]
    let assumptions: String
    let openQuestions: String
    let constraints: String
    let decisions: String
    let risks: String
    let linkedProjectIds: [String]

    var id: String { record.planId }
    var status: UserPlanStatus { record.status }
    var primaryChatId: String? { record.primaryChatId }
    var version: Int { record.version ?? 1 }
    var updatedAt: Int { record.updatedAt }
}

struct EncryptedPlanCriterion: Codable, Sendable, Identifiable {
    let criterionId: String
    let type: String?
    let status: String
    let required: Bool?
    let linkedTaskIds: [String]?
    let verificationIds: [String]?
    let coverageStatus: String?
    let verificationScope: String?
    let version: Int?
    let encryptedText: String?
    let encryptedEvidence: String?
    let encryptedCoverageNote: String?
    let encryptedWaiverReason: String?
    var id: String { criterionId }
}

struct EncryptedPlanVerification: Codable, Sendable, Identifiable {
    let verificationId: String
    let kind: String
    let phase: String?
    let status: String
    let requiredForDone: Bool?
    let covers: [String]?
    let lifecycleStatus: String?
    let linkedTaskId: String?
    let encryptedDescription: String?
    let encryptedCommand: String?
    let encryptedResultSummary: String?
    let encryptedRequiredFixes: String?
    var id: String { verificationId }
}

struct EncryptedPlanAssumption: Codable, Sendable, Identifiable {
    let assumptionId: String
    let category: String?
    let status: String
    let requiredBefore: String?
    let encryptedText: String?
    let encryptedCorrectedText: String?
    let encryptedEvidenceSummary: String?
    let encryptedBlockerReason: String?
    var id: String { assumptionId }
}

struct EncryptedPlanReferencePattern: Codable, Sendable, Identifiable {
    let patternId: String
    let status: String
    let sourceCount: Int?
    let encryptedTitle: String?
    let encryptedEvidenceSummary: String?
    var id: String { patternId }
}

struct UserPlanDetailEntry: Identifiable, Sendable {
    let id: String
    let title: String
    let subtitle: String
    let evidence: String
    let status: String
}

struct UserPlanDetailState: Sendable {
    let assumptions: [UserPlanDetailEntry]
    let criteria: [UserPlanDetailEntry]
    let verifications: [UserPlanDetailEntry]
    let referencePatterns: [UserPlanDetailEntry]
}
