// Shared basic information bar for native embed previews.
// Mirrors BasicInfosBar.svelte's desktop preview layout: app gradient circle,
// optional skill icon or title favicon, and title/status text.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct EmbedBasicInfoBar: View {
    private enum Constants {
        static let height: CGFloat = 61
        static let appIconSize: CGFloat = 61
        static let skillIconSize: CGFloat = 29
        static let faviconSize: CGFloat = 20
        static let cornerRadius: CGFloat = 30
    }

    let appId: String
    let skillIconName: String
    let title: String
    let subtitle: String?
    let faviconURL: String?
    let showSkillIcon: Bool

    var body: some View {
        HStack(spacing: .spacing5) {
            AppIconView(appId: appId, size: Constants.appIconSize)
                .accessibilityHidden(true)

            leadingInlineIcon

            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(subtitle == nil ? 2 : 1)

                if let subtitle {
                    Text(subtitle)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Spacer(minLength: 0)
        }
        .frame(height: Constants.height)
        .padding(.trailing, .spacing5)
        .background(Color.grey30)
        .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
    }

    @ViewBuilder
    private var leadingInlineIcon: some View {
        if let faviconURL, let url = URL(string: faviconURL) {
            CachedRemoteImage(url: url) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                Icon(skillIconName, size: 16)
                    .foregroundStyle(Color.grey70)
            }
            .frame(width: Constants.faviconSize, height: Constants.faviconSize)
            .clipShape(RoundedRectangle(cornerRadius: .radius1))
            .accessibilityHidden(true)
        } else if showSkillIcon {
            Icon(skillIconName, size: Constants.skillIconSize)
                .foregroundStyle(Color.grey70)
                .accessibilityHidden(true)
        }
    }
}
