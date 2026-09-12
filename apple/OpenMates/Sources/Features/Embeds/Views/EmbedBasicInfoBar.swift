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
        HStack(spacing: showSkillIcon ? 10 : 6) {
            Circle()
                .fill(AppIconView.gradient(forAppId: appId))
                .frame(width: Constants.appIconSize, height: Constants.appIconSize)
                .overlay {
                    // BasicInfosBar uses a 26pt wrapper and 25pt CSS glyph.
                    Icon(AppIconView.iconName(forAppId: appId), size: 25)
                        .foregroundStyle(.white)
                        .frame(width: 26, height: 26)
                }
                .accessibilityHidden(true)

            if showSkillIcon {
                Icon(skillIconName, size: Constants.skillIconSize)
                    .foregroundStyle(Color.grey70)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: subtitle == nil ? 0 : 2) {
                HStack(spacing: 8) {
                    titleFavicon
                    Text(title)
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.grey100)
                        .lineLimit(subtitle == nil ? 2 : 1)
                        // Bundled Lexend ascender/descender total 1.25em;
                        // add the remaining 0.15em for web's 1.4 line box.
                        .lineSpacing(subtitle == nil ? 2.4 : 0)
                        .padding(.vertical, subtitle == nil ? 1.2 : 0)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                if let subtitle {
                    Text(subtitle)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(height: Constants.height)
        .background(Color.grey30)
        .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
    }

    @ViewBuilder
    private var titleFavicon: some View {
        if let faviconURL, let url = URL(string: faviconURL) {
            CachedRemoteImage(url: url) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                Icon(skillIconName, size: 16)
                    .foregroundStyle(Color.grey70)
            }
            .frame(width: Constants.faviconSize, height: Constants.faviconSize)
            .clipShape(RoundedRectangle(cornerRadius: 2))
            .accessibilityHidden(true)
        }
    }
}
