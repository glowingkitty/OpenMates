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
                }
                Spacer(minLength: 0)
            }

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

            DevEmbedDisplayBlock(title: "Preview - Compact") {
                EmbedPreviewCard(embed: skill.primaryEmbed, allEmbedRecords: skill.allRecords) {}
            }

            DevEmbedDisplayBlock(title: "Preview - Large") {
                EmbedPreviewCard(
                    embed: skill.primaryEmbed,
                    allEmbedRecords: skill.allRecords,
                    variant: .large
                ) {}
                .frame(maxWidth: 640)
            }

            if !skill.childEmbeds.isEmpty {
                DevEmbedDisplayBlock(title: "Group - Small") {
                    GroupedEmbedView(
                        group: EmbedGroup(
                            id: "\(skill.id)-group",
                            type: EmbedType(rawValue: skill.childEmbeds[0].type) ?? .webWebsite,
                            embeds: skill.childEmbeds,
                            isAppSkillUse: false
                        ),
                        allEmbedRecords: skill.allRecords
                    ) { _ in }
                }
            }

            DevEmbedDisplayBlock(title: "Fullscreen") {
                EmbedFullscreenView(
                    embed: skill.primaryEmbed,
                    childEmbeds: skill.childEmbeds,
                    allEmbedRecords: skill.allRecords
                )
                .frame(height: 620)
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
