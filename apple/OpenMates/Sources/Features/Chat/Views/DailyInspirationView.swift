// Daily inspiration banner — shows a rotating inspiration prompt.
// Tapping creates a new chat with the inspiration as the first message.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/DailyInspirationBanner.svelte
// CSS:     DailyInspirationBanner.svelte <style>
//          Banner height: 240px desktop, 190px mobile (≤730px)
//          Background: getCategoryGradientColors per inspiration category
// i18n:    common.daily_inspiration (AppStrings.dailyInspiration)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct DailyInspirationBanner: View {
    let inspiration: DailyInspiration?
    let onTap: (String) -> Void

    struct DailyInspiration: Decodable {
        let text: String
        let category: String?
        let iconName: String?
    }

    var body: some View {
        if let inspiration {
            Button {
                onTap(inspiration.text)
            } label: {
                HStack(spacing: .spacing3) {
                    Image(systemName: "lightbulb.fill")
                        .foregroundStyle(Color.buttonPrimary)
                        .accessibilityHidden(true)

                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(AppStrings.dailyInspiration)
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(Color.fontTertiary)
                        Text(inspiration.text)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, .spacing4)
            .padding(.top, .spacing2)
            .accessibilityElement(children: .combine)
            .accessibleButton("Daily inspiration: \(inspiration.text)", hint: "Starts a new chat with this inspiration as the opening message")
        }
    }
}
