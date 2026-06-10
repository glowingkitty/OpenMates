// Debug-only native embed preview gallery for simulator visual QA.
// Reproduces the web /dev/preview/embeds pages with real SwiftUI renderers.
// Xcode MCP can launch this surface, capture screenshots, and compare it with
// Playwright screenshots from the Svelte preview pages.
// This file is compiled in Debug builds only.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/embeds/[app]/+page.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/EmbeddPreview.styles.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import SwiftUI

struct DevPreviewRootView: View {
    let configuration: DevPreviewLaunchConfiguration

    var body: some View {
        switch configuration.surface {
        case .chatOpening:
            DevChatOpeningPreviewView()
        case .chatOpeningRecording:
            DevChatOpeningPreviewView(forceRecordingOverlay: true)
        case .embeds:
            DevEmbedPreviewGalleryView(initialApp: configuration.appSlug)
        }
    }
}

struct DevEmbedPreviewGalleryView: View {
    @State private var selectedApp: DevEmbedPreviewApp

    init(initialApp: DevEmbedPreviewApp) {
        _selectedApp = State(initialValue: initialApp)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing12) {
                    ForEach(DevEmbedPreviewFixtures.skills(for: selectedApp)) { skill in
                        DevEmbedPreviewSkillSection(skill: skill)
                    }
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing8)
            }
            .background(Color.grey0)
        }
        .background(Color.grey0.ignoresSafeArea())
        .environment(\.colorScheme, .light)
        .preferredColorScheme(.light)
        .accessibilityIdentifier("dev-embed-preview-gallery")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            HStack(spacing: .spacing4) {
                AppIconView(appId: selectedApp.rawValue, size: 44)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text("Native Embed Preview")
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                    Text("/dev/preview/embeds/\(selectedApp.rawValue)")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityIdentifier("dev-preview-route")
                }
                Spacer(minLength: 0)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(DevEmbedPreviewApp.allCases) { app in
                        Button {
                            selectedApp = app
                        } label: {
                            HStack(spacing: .spacing2) {
                                AppIconView(appId: app.rawValue, size: 22)
                                Text(app.title)
                                    .font(.omSmall)
                                    .fontWeight(.semibold)
                            }
                            .foregroundStyle(selectedApp == app ? Color.fontButton : Color.fontPrimary)
                            .padding(.horizontal, .spacing4)
                            .frame(height: 38)
                            .background(selectedApp == app ? Color.buttonPrimary : Color.grey20)
                            .clipShape(RoundedRectangle(cornerRadius: .radius4))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("dev-preview-app-\(app.rawValue)")
                    }
                }
            }
        }
        .padding(.horizontal, .spacing8)
        .padding(.top, .spacing8)
        .padding(.bottom, .spacing5)
        .background(Color.grey10)
    }
}

private struct DevEmbedPreviewSkillSection: View {
    let skill: DevEmbedPreviewSkill

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            HStack(spacing: .spacing3) {
                AppIconView(appId: skill.primaryEmbed.appId ?? "web", size: 28)
                Text(skill.label)
                    .font(.omH4)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
            }
            .accessibilityIdentifier("dev-preview-skill-\(skill.id)")

            DevEmbedTemplateControls()

            DevEmbedDisplayBlock(title: "INLINE LINK") {
                DevEmbedInlineLinkBlock(embed: skill.primaryEmbed)
            }

            DevEmbedDisplayBlock(title: "QUOTE BLOCK") {
                DevEmbedQuoteBlock(embed: skill.primaryEmbed)
            }

            DevEmbedDisplayBlock(title: "GROUP — SMALL") {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: .spacing4) {
                        ForEach(smallGroupEmbeds) { embed in
                            EmbedPreviewCard(embed: embed, allEmbedRecords: skill.allRecords) {}
                        }
                    }
                    .padding(.vertical, .spacing2)
                }
            }

            if !skill.childEmbeds.isEmpty {
                DevEmbedDisplayBlock(title: "GROUP — LARGE") {
                    groupedPreview
                }
            }

            DevEmbedDisplayBlock(title: "FULLSCREEN CLIPPED INLINE") {
                EmbedFullscreenContainer(
                    embeds: [skill.primaryEmbed],
                    initialEmbedId: skill.primaryEmbed.id,
                    allEmbedRecords: skill.allRecords,
                    chatId: nil
                )
                .frame(height: 560)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .overlay {
                    RoundedRectangle(cornerRadius: .radius8)
                        .stroke(Color.grey30, lineWidth: 1)
                }
            }
        }
        .padding(.spacing6)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
    }

    private var smallGroupEmbeds: [EmbedRecord] {
        let embeds = [skill.primaryEmbed] + skill.childEmbeds
        return Array(embeds.prefix(6))
    }

    private var groupedPreview: some View {
        GroupedEmbedView(
            group: EmbedGroup(
                id: "\(skill.id)-group-large",
                type: EmbedType(rawValue: skill.childEmbeds[0].type) ?? .webWebsite,
                embeds: skill.childEmbeds,
                isAppSkillUse: false
            ),
            allEmbedRecords: skill.allRecords
        ) { _ in }
    }
}

private struct DevEmbedTemplateControls: View {
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                Text("Template:")
                    .font(.omMicro)
                    .foregroundStyle(Color.fontSecondary)
                DevEmbedTemplateChip(title: "Default", isSelected: true)
                DevEmbedTemplateChip(title: "processing", isSelected: false)
            }
            DevEmbedTemplateChip(title: "Props", isSelected: false)
        }
    }
}

private struct DevEmbedTemplateChip: View {
    let title: String
    let isSelected: Bool

    var body: some View {
        Text(title)
            .font(.omMicro)
            .fontWeight(.semibold)
            .foregroundStyle(isSelected ? Color.fontButton : Color.fontPrimary)
            .frame(minWidth: 74, minHeight: 26)
            .padding(.horizontal, .spacing3)
            .background(isSelected ? Color.buttonPrimary : Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius2))
            .shadow(color: .black.opacity(0.16), radius: 4, x: 0, y: 2)
    }
}

private struct DevEmbedInlineLinkBlock: View {
    let embed: EmbedRecord

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text("The assistant found")
                .font(.omMicro)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontSecondary)
            HStack(spacing: .spacing2) {
                AppIconView(appId: embed.appId ?? "web", size: 16)
                Text(embedTitle)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.buttonPrimary)
                    .lineLimit(2)
            }
            Text("for you.")
                .font(.omMicro)
                .foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing5)
        .frame(maxWidth: 320, alignment: .leading)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .overlay {
            RoundedRectangle(cornerRadius: .radius4)
                .stroke(Color.grey30, lineWidth: 1)
        }
    }

    private var embedTitle: String {
        firstString(keys: ["title", "name", "query", "site_name"]) ?? EmbedType(rawValue: embed.type)?.displayName ?? embed.type
    }

    private func firstString(keys: [String]) -> String? {
        for key in keys {
            if let value = embed.rawData?[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }
}

private struct DevEmbedQuoteBlock: View {
    let embed: EmbedRecord

    var body: some View {
        HStack(alignment: .top, spacing: .spacing4) {
            RoundedRectangle(cornerRadius: .radiusFull)
                .fill(Color.buttonPrimary)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(quoteText)
                    .font(.omSmall)
                    .italic()
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(4)
                HStack(spacing: .spacing2) {
                    AppIconView(appId: embed.appId ?? "web", size: 14)
                    Text(embed.appId ?? "web")
                        .font(.omMicro)
                        .foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .padding(.spacing5)
        .frame(maxWidth: 320, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .overlay {
            RoundedRectangle(cornerRadius: .radius4)
                .stroke(Color.grey30, lineWidth: 1)
        }
    }

    private var quoteText: String {
        firstString(keys: ["description", "summary", "title", "name", "query"]) ?? EmbedType(rawValue: embed.type)?.displayName ?? embed.type
    }

    private func firstString(keys: [String]) -> String? {
        for key in keys {
            if let value = embed.rawData?[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }
}

private struct DevEmbedDisplayBlock<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(title)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("dev-preview-display-\(title)")

            content
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.spacing5)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
    }
}
#endif
