// SettingsItem's optional credits display slot.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/SettingsItem.svelte
// CSS: SettingsItem.svelte .credits-display, .credits-display-text, .credits-display-coins
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.composition.canonical-and-accessible
import SwiftUI

// Shared SettingsItem creditsDisplay slot, also used by read-only context groups.
struct OMSettingsCreditsDisplay: View {
    let value: String
    var body: some View {
        HStack(spacing: .spacing2) {
            Text(value).font(.omSmall.weight(.medium))
            Icon("coins", size: 18) // SettingsItem.svelte .credits-display-coins: 18px.
        }
        .foregroundStyle(Color.grey50)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(value + " " + AppStrings.credits)
    }
}
