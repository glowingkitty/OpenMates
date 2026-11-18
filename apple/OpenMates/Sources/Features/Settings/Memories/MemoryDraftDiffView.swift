// Per-field "current" text of an unsaved suggested Memory: one heading and one
// quote card per field the suggestion changes. Which fields changed is
// decided by the Rust core (`diffMemoryDraftFields`).
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/MemoryEntryPage.svelte (memory-draft-diff-{field})
//          frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsQuote.svelte
// Tokens:  Color.grey0 / grey40 / grey70, .spacing*, .radius8, Font.omP
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor

import SwiftUI

/// What one diff block shows; separate from the view so tests can check it.
struct MemoryDraftDiffItem: Equatable, Identifiable {
    /// Web field name: `title`, `when_to_use` or `body`.
    let field: String
    /// Heading, e.g. "Title: current".
    let heading: String
    /// Saved text, or an em dash when the saved field is empty (web `|| '—'`).
    let quote: String
    var id: String { field }
    var identifier: String { "memory-draft-diff-\(field)" }

    @MainActor
    init(_ change: MemoryFieldChangeRecord) {
        let label: String
        switch change.field {
        case .title: field = "title"; label = AppStrings.memoriesFieldTitle
        case .whenToUse: field = "when_to_use"; label = AppStrings.memoriesWhenToUse
        case .body: field = "body"; label = AppStrings.memoriesPractices
        }
        heading = "\(label): \(AppStrings.memoriesDraftCurrent)"
        quote = change.current.isEmpty ? "—" : change.current
    }
}

/// One block per changed field; shows nothing when `changes` is empty.
struct MemoryDraftDiffView: View {
    let changes: [MemoryFieldChangeRecord]

    var body: some View {
        ForEach(changes.map(MemoryDraftDiffItem.init)) { item in
            VStack(alignment: .leading, spacing: .spacing4) {
                OMSettingsSectionHeading(title: item.heading, icon: "document")
                MemoryQuoteCard(text: item.quote)
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier(item.identifier)
        }
    }
}

/// Quoted text card (web SettingsQuote, not clickable).
struct MemoryQuoteCard: View {
    let text: String

    var body: some View {
        Text(text)
            .font(Font.omP.weight(.bold))
            .foregroundStyle(Color.grey70)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity, minHeight: 112)
            .padding(.vertical, .spacing10)
            .padding(.horizontal, .spacing8)
            .background(Color.grey0)
            .overlay(alignment: .topTrailing) {
                Icon("quote", size: 16).foregroundStyle(Color.grey40).padding(.top, .spacing4).padding(.trailing, .spacing6)
            }
            .overlay(alignment: .bottomLeading) {
                Icon("quote", size: 16).foregroundStyle(Color.grey40).rotationEffect(.degrees(180))
                    .padding(.bottom, .spacing6).padding(.leading, .spacing6)
            }
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
            .padding(.horizontal, .spacing5)
            .accessibilityElement(children: .combine)
    }
}
