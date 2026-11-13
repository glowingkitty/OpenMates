// Typed string accessors for the chat cards that close the 2026-11-12 web
// parity audit gaps: image-generate card states, the Recommendations card and
// the assistant-created Project card. Every key exists in the web locale file
// (frontend/packages/ui/src/i18n/locales/en.json); no English is hardcoded.
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12)

import Foundation

// MARK: - Image generate

extension AppStrings {
    static var imageGenerateSkillGenerate: String { localized("common.generate") }
    static var imageGenerateSkillDraft: String { localized("embeds.image_generate_draft") }
    static var imageModifyTitle: String { localized("embeds.image_modify.title") }
    static var imageGenerateFailed: String { localized("embeds.image_generate.error") }
    static var imageGenerateLoading: String { localized("embeds.image_generate.loading") }
    static var imageGenerateCancelled: String { localized("embeds.cancelled") }
    static var imageGenerateStatusError: String { localized("embeds.error") }

    /// Stage label of a vector drawing (`svgDraftStageLabelKey` in svgDraft.ts).
    /// `drawing` has no label on the web, so it returns nil.
    static func imageGenerateDraftStage(_ stage: String) -> String? {
        switch stage {
        case "checking": return localized("embeds.image_generate.checking")
        case "correcting": return localized("embeds.image_generate.correcting")
        case "scripting": return localized("embeds.image_generate.scripting")
        default: return nil
        }
    }

    /// Step text of images.modify (`imageModifyStageKey` + `showsAttempt` in imageDraft.ts).
    static func imageModifyStep(_ stage: String, attempt: Int?) -> String? {
        guard ["writing", "running", "checking", "correcting"].contains(stage) else { return nil }
        let step = localized("embeds.image_modify.\(stage)")
        guard let attempt, attempt >= 2 else { return step }
        let attemptText = LocalizationManager.shared.text("embeds.image_modify.attempt", replacements: ["n": "\(attempt)"])
        return "\(step) · \(attemptText)"
    }
}

// MARK: - Recommendations

extension AppStrings {
    static var recommendationsCardTitle: String { localized("recommendations.card_title") }
    static var recommendationsCreate: String { localized("recommendations.create") }
    static var recommendationsUpdate: String { localized("recommendations.update") }
    static var recommendationsPreparing: String { localized("recommendations.preparing") }
    static var recommendationsPrevious: String { localized("recommendations.previous") }
    static var recommendationsNext: String { localized("recommendations.next") }
    static var recommendationsTypeMemory: String { localized("recommendations.type_memory") }
    static var recommendationsTypeWorkflow: String { localized("recommendations.type_workflow") }
    static var recommendationsMemoryUpToDate: String { localized("memories.suggestion_up_to_date") }

    /// `HEADING_KEYS[kind][action]` in RecommendationsCard.svelte.
    static func recommendationsHeading(kind: String, action: String) -> String {
        let kindKey = kind == "workflow" ? "workflow" : "memory"
        let actionKey = action == "update" ? "update" : "create"
        return localized("recommendations.heading_\(kindKey)_\(actionKey)")
    }

    static func recommendationsPosition(current: Int, total: Int) -> String {
        LocalizationManager.shared.text("recommendations.position",
                                        replacements: ["current": "\(current)", "total": "\(total)"])
    }
}

// MARK: - Assistant-created Project

extension AppStrings {
    static var projectCreatedLabel: String { localized("projects.created_project_label") }
    static var projectCreatedUndone: String { localized("projects.created_project_undone") }
    static var projectCreatedUndo: String { localized("projects.created_project_undo") }
    static var projectCreatedUndoFailed: String { localized("projects.created_project_undo_failed") }
    static var projectWorkOnLabel: String { localized("projects.work_on_label") }
    static var projectFocusNotActive: String { localized("projects.focus_not_active") }
}
