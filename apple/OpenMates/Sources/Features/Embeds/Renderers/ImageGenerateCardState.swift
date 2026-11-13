// ImageGenerateCardState — which state an image generation card shows.
// Pure presentation choice over already-decrypted embed content and the embed
// status; mirrors the {#if} order of ImageGenerateEmbedPreview.svelte and the
// helpers in svgDraft.ts / imageDraft.ts. No protocol, sync or crypto logic.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/svgDraft.ts
//          frontend/packages/ui/src/components/embeds/images/imageDraft.ts
// ────────────────────────────────────────────────────────────────────
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12, image-generate card states)

import Foundation

enum ImageGenerateCardState: Equatable {
    /// Finished with image file metadata: the whole picture fills the card.
    case image
    /// images.modify running: step text over the computed draft picture.
    case modifyProgress(stage: String?, attempt: Int?, draftBase64: String?)
    /// Vector author drawing (processing with an `svg_draft`).
    case svgDraft(stage: String?)
    /// Processing, cancelled, or finished while the picture is not available
    /// yet: skeleton lines, plus the stage label while only a script is written.
    case pending(stageLabelStage: String?)
    /// Failed generation (status `error`).
    case failed(message: String?)

    /// Web `skillId` values that share this card.
    static let skillIds: Set<String> = ["generate", "generate_draft", "modify"]

    static func resolve(data: [String: AnyCodable]?, status: EmbedStatus, skillId: String) -> Self {
        let raw = data ?? [:]
        let error = Self.string(raw["error"])
        let stage = Self.string(raw["draft_stage"])
        if status == .finished, error == nil, Self.hasImageFile(raw) { return .image }
        if skillId == "modify", status == .processing {
            let modifyStage = stage.flatMap { ["writing", "running", "checking", "correcting"].contains($0) ? $0 : nil }
            let draft = Self.validDraftBase64(raw["image_draft"])
            if modifyStage != nil || draft != nil {
                return .modifyProgress(stage: modifyStage, attempt: Self.attempt(raw["draft_attempt"]), draftBase64: draft)
            }
        }
        let svgStage = stage.flatMap { ["drawing", "checking", "correcting", "scripting"].contains($0) ? $0 : nil }
        if status == .processing, let draft = Self.string(raw["svg_draft"]),
           !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .svgDraft(stage: svgStage)
        }
        if status != .error {
            // shouldShowDraftStatusOnly: processing, no picture, a labelled stage.
            let labelled = status == .processing && svgStage != nil && svgStage != "drawing"
            return .pending(stageLabelStage: labelled ? svgStage : nil)
        }
        return .failed(message: error)
    }

    /// The card has a picture to show. The web additionally needs a preview,
    /// full or original file (`cardImageFile`); the native image view keeps its
    /// existing contract and fetches from `s3_base_url` with `aes_key`.
    static func hasImageFile(_ raw: [String: AnyCodable]) -> Bool {
        Self.string(raw["s3_base_url"]) != nil && Self.string(raw["aes_key"]) != nil
    }

    /// `isValidBase64` in imageDraft.ts: well-formed base64 of at most 90,000 characters.
    static func validDraftBase64(_ value: AnyCodable?) -> String? {
        guard let text = value?.value as? String, !text.isEmpty, text.count <= 90_000, text.count % 4 == 0 else { return nil }
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
        guard text.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return nil }
        // Padding may only appear at the end (at most two characters).
        let trimmed = text.drop { $0 != "=" }
        guard trimmed.count <= 2, trimmed.allSatisfy({ $0 == "=" }) else { return nil }
        return text
    }

    private static func attempt(_ value: AnyCodable?) -> Int? {
        guard let number = value?.value as? Int, number >= 1 else { return nil }
        return number
    }

    private static func string(_ value: AnyCodable?) -> String? {
        guard let text = value?.value as? String, !text.isEmpty else { return nil }
        return text
    }
}
