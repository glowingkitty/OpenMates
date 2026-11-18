// Banner of an unsaved suggested Memory and the references hint under the
// Memory text, both on the Memory entry page.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/MemoryEntryPage.svelte
//          (memory-draft-banner, memories.draft_unsaved, memories.references_hint)
//          frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
// Tokens:  uses OMSettingsInfoBox (warning / info), no own styling
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor, app-memories.references.embeds

import SwiftUI

/// Warning box shown above an unsaved suggestion (web `memory-draft-banner`).
struct MemoryDraftBanner: View {
    var body: some View {
        OMSettingsInfoBox(kind: .warning, message: AppStrings.memoriesDraftUnsaved, identifier: "memory-draft-banner")
    }
}

/// Info box under the Memory text explaining how to add an embed.
struct MemoryReferencesHint: View {
    var body: some View {
        OMSettingsInfoBox(message: AppStrings.memoriesReferencesHint, identifier: "memory-references-hint")
    }
}
