// Count line of the in-chat Memory approval ("Ask first") prompt: "2/3 entries".
// Mirrors the web category row; the pure formatter is unit-tested.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/AppSettingsMemoriesPermissionDialog.svelte
//          (.category-count, data-testid memory-category-count)
// Tokens:  ColorTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.selection.source-scoped, app-memories.surface.semantic-parity

import SwiftUI

enum MemoryConsentCountFormat {
    /// "selected/total entry|entries" using the shared chat.permissions.entry_* strings.
    static func text(selected: Int, total: Int, singular: String, plural: String) -> String {
        "\(selected)/\(total) \(total == 1 ? singular : plural)"
    }
}

struct MemoryConsentCountLabel: View {
    let selected: Int
    let total: Int

    var body: some View {
        Text(MemoryConsentCountFormat.text(
            selected: selected, total: total,
            singular: AppStrings.localized("chat.permissions.entry_singular"),
            plural: AppStrings.localized("chat.permissions.entry_plural")))
            .font(.omXs)
            .foregroundStyle(Color.fontSecondary)
            .accessibilityIdentifier("memory-category-count")
    }
}
