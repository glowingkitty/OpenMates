// Maps the shared core's answer-body embed rule (bodyEnforceBlockEmbeds) onto Apple embed records.
// Swift only builds the reference records and maps the returned slots to views; the decision
// (invocation -> activity + result cards, unknown children -> hidden placeholder) lives in Rust:
// packages/openmates-rust/src/embed_read/body_enforce.rs.
// ─── Web source ─────────────────────────────────────────────────────
// Logic:   frontend/packages/ui/src/services/bodyEmbedPolicy.ts (block embeds)
// Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte (body embed groups)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/architecture/app-skill-execution/specification.yml
// Assertions: app-skills.answer.only-result-embeds-in-body
import Foundation

// spec: app-skills.answer.only-result-embeds-in-body
// Maps one block of adjacent body embeds onto what the answer body shows. The
// rule (invocation embeds give way to their result cards, activity line, hidden
// placeholder while children are unknown) lives in the Rust core
// (embed_read::body_enforce, generated `bodyEnforceBlockEmbeds`); this file only
// builds the core input from EmbedRecords and maps slots back to records.

/// What the body renders for one slot of an embed group.
enum BodyEmbedSlotView: Equatable {
    /// A result or regular card.
    case card(EmbedRecord)
    /// The skill-activity container for the invocation embed.
    case activity(EmbedRecord)
    /// Keeps the position until the invocation's children arrive.
    case hidden(embedId: String)

    static func == (lhs: BodyEmbedSlotView, rhs: BodyEmbedSlotView) -> Bool {
        switch (lhs, rhs) {
        case (.card(let a), .card(let b)), (.activity(let a), .activity(let b)): return a.id == b.id
        case (.hidden(let a), .hidden(let b)): return a == b
        default: return false
        }
    }
}

enum BodyEmbedSlotProjection {
    static func project(
        embeds: [EmbedRecord],
        allEmbedRecords: [String: EmbedRecord],
        activityIds: [String] = [],
        expandsResults: Bool = true
    ) -> [BodyEmbedSlotView] {
        let refs = embeds.map { refRecord(id: $0.id, embed: $0, type: nil) }
        let slots = bodyEnforceBlockEmbeds(groups: [refs], activityIds: activityIds).first ?? []
        let groupIDs = Set(embeds.map(\.id))
        return slots.compactMap { slot in
            switch slot {
            case .card(let ref, let id):
                let key = id ?? ref
                // The assistant activity projection already placed result cards
                // after their activity run; here only the group's own cards stay.
                guard expandsResults || groupIDs.contains(key) else { return nil }
                guard let record = allEmbedRecords[key] ?? embeds.first(where: { $0.id == key }) else { return nil }
                return .card(record)
            case .activity(let id, _, _, _):
                guard let record = embeds.first(where: { $0.id == id }) else { return nil }
                return .activity(record)
            case .hidden(let id):
                return .hidden(embedId: id)
            }
        }
    }

    /// Core input for one block reference. Children count as known once the
    /// invocation lists them or has finished; until then the core keeps a hidden slot.
    static func refRecord(id: String, embed: EmbedRecord?, type: String?) -> BodyEmbedRefRecord {
        BodyEmbedRefRecord(
            embedRef: id,
            embedId: embed?.id ?? id,
            typeName: embed.map { $0.isAppSkillUse ? "app-skill-use" : $0.type } ?? type,
            appId: embed?.appId,
            skillId: embed?.skillId,
            // Like web `resolveBodySkillChildren`: a running invocation has no final
            // child list yet, so its results stay pending behind the activity.
            childIds: embed.flatMap { $0.status == .processing ? nil : $0.childEmbedIds }
        )
    }
}
