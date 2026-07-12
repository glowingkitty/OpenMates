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
import CryptoKit
import SwiftUI

struct DevPreviewRootView: View {
    let configuration: DevPreviewLaunchConfiguration
    @StateObject private var previewAuthManager = AuthManager()

    var body: some View {
        switch configuration.surface {
        case .chatOpening:
            DevChatOpeningPreviewView()
        case .chatOpeningRecording:
            DevChatOpeningPreviewView(forceRecordingOverlay: true)
        case .chatShare:
            DevChatSharePreviewView()
        case .embedShare:
            DevEmbedSharePreviewView()
        case .quickCapture:
            #if os(macOS)
            MacMenuBarQuickCaptureView()
                .environmentObject(previewAuthManager)
                .frame(width: 430)
            #else
            DevQuickCaptureAttachmentPreviewView()
            #endif
        case .composerEmbeds:
            DevNativeComposerEmbedGalleryView()
        case .composerDraftEdit:
            DevMessageEditFixtureView()
        case .embeds:
            DevEmbedPreviewGalleryView(initialApp: configuration.appSlug)
        }
    }
}

struct DevNativeComposerEmbedGalleryView: View {
    private let registry = AppleComposerRendererRegistry.shared
    private let actions = AppleComposerEmbedActions(
        onOpen: { _ in },
        onRetry: { _ in },
        onRemove: { _ in }
    )

    var body: some View {
        ScrollView {
            LazyVStack(spacing: .spacing10) {
                lifecycleShowcase
                ForEach(registry.registeredTypes, id: \.self) { embedType in
                    if let descriptor = registry.descriptor(for: embedType) {
                        AppleComposerEmbedPreview(
                            descriptor: descriptor,
                            node: fixtureNode(embedType: embedType, state: state(for: embedType)),
                            lifecycle: state(for: embedType),
                            embedRecord: nil,
                            allEmbedRecords: [:],
                            actions: actions
                        )
                    }
                }
            }
            .padding(.spacing12)
        }
        .background(Color.grey0)
        .accessibilityIdentifier("dev-native-composer-embed-gallery")
        .accessibilityValue("\(registry.registeredTypes.count)")
    }

    private var lifecycleShowcase: some View {
        Group {
            if let descriptor = registry.descriptor(for: "recording") {
                ForEach(AppleComposerEmbedLifecycleState.allCases, id: \.self) { state in
                    AppleComposerEmbedPreview(
                        descriptor: descriptor,
                        node: fixtureNode(embedType: "recording", state: state),
                        lifecycle: state,
                        embedRecord: nil,
                        allEmbedRecords: [:],
                        actions: actions
                    )
                }
            }
        }
    }

    private func state(for embedType: String) -> AppleComposerEmbedLifecycleState {
        switch embedType {
        case "app-skill-use": .draft
        case "electronics-pcb-schematic": .error
        case "fitness-location": .uploading
        case "code-repo-group": .cancelled
        default: .finished
        }
    }

    private func fixtureNode(
        embedType: String,
        state: AppleComposerEmbedLifecycleState
    ) -> ComposerNodeV1 {
        ComposerNodeV1.embed(
            id: "composer:fixture:\(embedType):\(state.rawValue)",
            embedType: embedType,
            canonicalSource: "```json\n{}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(
                title: EmbedType.normalized(rawValue: embedType)?.displayName
                    ?? AppStrings.uploadProgressProcessing,
                mediaKind: embedType
            )
        ).updatingStatus(state.rawValue)
    }
}

#if !os(macOS)
struct DevQuickCaptureAttachmentPreviewView: View {
    @State private var selectedTab = "chats"
    @StateObject private var composerSession = NativeComposerSession()
    @State private var inputFocused = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            HStack(spacing: .spacing4) {
                tabButton("chats")
                tabButton("projects")
                tabButton("plans")
                tabButton("tasks")
                tabButton("workflows")
            }
            if selectedTab == "chats" {
                chatsPreview
            } else {
                Text("Quick capture for \(selectedTab) is coming later.")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.spacing8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: 24))
                    .accessibilityIdentifier("quick-capture-placeholder-\(selectedTab)")
            }
        }
        .padding(.spacing8)
        .background(Color.grey0)
    }

    private var chatsPreview: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            HStack(spacing: .spacing4) {
                Text("New Chat")
                Text("UI Test Chat")
            }
            .font(.omXs.weight(.semibold))
            .foregroundStyle(Color.fontPrimary)
            .accessibilityIdentifier("quick-capture-recent-chats")

            VStack(spacing: 0) {
                MessageComposerView(
                    session: composerSession,
                    isFocused: $inputFocused,
                    compact: false,
                    placeholder: AppStrings.whatDoYouNeedHelpWith,
                    maxWidth: nil,
                    onSubmit: {}
                ) {
                    HStack(spacing: .spacing6) {
                        MessageComposerActionIcon(
                            icon: "recordaudio",
                            label: AppStrings.recordAudio,
                            identifier: "quick-capture-record-audio-button"
                        ) {}
                        Spacer()
                        MessageComposerSendButton(title: AppStrings.sendAction) {}
                            .accessibilityIdentifier("quick-capture-send-button")
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.bottom, .spacing6)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("quick-capture-composer")

            Text("Shared fixture.pdf")
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("quick-capture-pending-attachments")
            Text("Success")
                .font(.omMicro.weight(.semibold))
                .foregroundStyle(Color.buttonPrimary)
                .accessibilityIdentifier("quick-capture-status-list")
        }
    }

    private func tabButton(_ id: String) -> some View {
        Button(id.capitalized) {
            selectedTab = id
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("quick-capture-tab-\(id)")
    }
}
#endif

struct DevChatSharePreviewView: View {
    private let context = AppleShareContext(
        contentType: .chat,
        id: "ui-test-chat-share",
        title: "Share preview chat",
        summary: "Synthetic chat share preview",
        key: SymmetricKey(data: Data(repeating: 0, count: 32)),
        chatId: "ui-test-chat-share"
    )

    var body: some View {
        AppleSharePanel(context: context, onClose: {}, onGenerated: { _, _, _ in })
            .accessibilityIdentifier("chat-share-preview")
    }
}

struct DevEmbedSharePreviewView: View {
    private let context = AppleShareContext(
        contentType: .embed,
        id: "ui-test-embed-share",
        title: "Web search",
        summary: "Synthetic embed share preview",
        key: SymmetricKey(data: Data(repeating: 1, count: 32)),
        chatId: "ui-test-chat-share"
    )

    var body: some View {
        ShareEmbedView(context: context, onClose: {}, onGenerated: { _, _, _ in })
            .accessibilityIdentifier("embed-share-preview")
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
            HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                Text(selectedApp.title)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Text(skillCountLabel)
                    .font(.omMicro)
                    .foregroundStyle(Color.fontTertiary)
                    .accessibilityIdentifier("dev-preview-route")
            }
        }
        .padding(.horizontal, .spacing8)
        .padding(.top, .spacing8)
        .padding(.bottom, .spacing3)
        .background(Color.grey0)
    }

    private var skillCountLabel: String {
        let count = DevEmbedPreviewFixtures.skills(for: selectedApp).count
        return count == 1 ? "1 skill" : "\(count) skills"
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
