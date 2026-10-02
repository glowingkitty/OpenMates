// Debug-only native embed preview gallery for simulator visual QA.
// Reproduces the web /dev/preview/embeds pages with real SwiftUI renderers.
// Xcode MCP can launch this surface, capture screenshots, and compare it with
// Playwright screenshots from the Svelte preview pages.
// This file is compiled in Debug builds only.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/embeds/[app=embedApp]/+page.svelte
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
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var previewAuthManager = AuthManager()

    var body: some View {
        Group {
            if let error = configuration.error {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text("Preview configuration error").font(.omH4)
                    Text(error).font(.omSmall)
                }
                .padding(.spacing8)
                .accessibilityIdentifier("dev-preview-error")
            } else {
                previewContent
            }
        }
        .frame(width: configuration.width.map(CGFloat.init), height: configuration.height.map(CGFloat.init))
        .preferredColorScheme(previewColorScheme)
        .transformEnvironment(\.colorScheme) { scheme in
            if let previewColorScheme { scheme = previewColorScheme }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey0.ignoresSafeArea())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("dev-preview-root")
        .accessibilityValue(runtimeState)
    }

    private var previewColorScheme: ColorScheme? {
        switch configuration.theme {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    // Observable runtime facts, not a hard-coded "isolated" label. Tests use
    // these to catch accidental account startup behind synthetic component UI.
    private var runtimeState: String {
        let auth = authManager.state == .initializing ? "not-started" : "started"
        let store = OfflineStore.shared.activeScopeId == nil ? "detached" : "attached"
        let socket = AppSessionCoordinator.shared.webSocketManager.connectionState == .disconnected ? "disconnected" : "active"
        return "auth=\(auth);store=\(store);socket=\(socket)"
    }

    @ViewBuilder
    private var previewContent: some View {
        switch configuration.surface {
        case .component:
            DevComponentPreviewView(configuration: configuration)
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
                .overlay { ToastOverlay() }
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
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement()
                    .accessibilityIdentifier("dev-native-composer-embed-gallery")
                    .accessibilityValue("\(registry.registeredTypes.count)")

                lifecycleShowcase
                ForEach(registry.registeredTypes, id: \.self) { embedType in
                    if let descriptor = registry.descriptor(for: embedType) {
                        AppleComposerEmbedPreview(
                            descriptor: descriptor,
                            node: fixtureNode(embedType: embedType, state: state(for: embedType)),
                            lifecycle: state(for: embedType),
                            embedRecord: fixtureRecord(embedType: embedType, state: state(for: embedType)),
                            allEmbedRecords: [:],
                            actions: actions
                        )
                    }
                }
            }
            .padding(.spacing12)
        }
        .background(Color.grey0)
    }

    private var lifecycleShowcase: some View {
        Group {
            if let descriptor = registry.descriptor(for: "recording") {
                ForEach(AppleComposerEmbedLifecycleState.allCases, id: \.self) { state in
                    AppleComposerEmbedPreview(
                        descriptor: descriptor,
                        node: fixtureNode(embedType: "recording", state: state),
                        lifecycle: state,
                        embedRecord: fixtureRecord(embedType: "recording", state: state),
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

    private func fixtureRecord(
        embedType: String,
        state: AppleComposerEmbedLifecycleState
    ) -> EmbedRecord? {
        guard embedType == "recording" else { return nil }
        let status: EmbedStatus = switch state {
        case .finished: .finished
        case .error: .error
        case .cancelled: .cancelled
        default: .processing
        }
        return EmbedRecord(
            id: "composer:fixture:\(embedType):\(state.rawValue)",
            type: embedType,
            status: status,
            data: .raw([
                "title": AnyCodable("Native voice note"),
                "duration": AnyCodable(42.0),
                "transcript_original": AnyCodable("Live transcript from the native recording fixture."),
                "transcript_corrected": AnyCodable("Corrected transcript from the native recording fixture."),
                "use_corrected": AnyCodable(state == .finished),
                "model": AnyCodable("voxtral-mini-transcribe-realtime-2602"),
                "waveform": AnyCodable([
                    "version": 1,
                    "kind": "rms-envelope",
                    "samples": [18, 44, 80, 34, 100, 62, 28]
                ] as [String: Any])
            ]),
            parentEmbedId: nil,
            appId: "audio",
            skillId: "transcribe",
            embedIds: nil,
            createdAt: "2026-09-23T09:00:00Z"
        )
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
        AppleSharePanel(context: context, onClose: {}, onGenerated: { _, _, _ in }, onStopSharing: nil)
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
    @State private var isPreviewPIIRevealed = false

    private var previewPIIMappings: [PIIMapping] {
        guard ProcessInfo.processInfo.arguments.contains("--dev-pii-embed-preview") else { return [] }
        return [PIIMapping(placeholder: "[HTML_NAME]", original: "OpenMates preview", type: "name")]
    }

    @Environment(\.colorScheme) private var colorScheme
    @State private var galleryColorScheme: ColorScheme?
    @State private var openedSkill: DevEmbedPreviewSkill?
    @State private var openedQuote: String?
    @State private var canonicalFullscreenOpen = true

    private var canonicalRequest: DevEmbedPreviewRequest? {
        DevEmbedPreviewRequest.parse(arguments: ProcessInfo.processInfo.arguments)
    }

    init(initialApp: DevEmbedPreviewApp) {
        _selectedApp = State(initialValue: initialApp)
    }

    var body: some View {
        Group {
            if ProcessInfo.processInfo.arguments.contains("--dev-owner-pii-navigation-preview") {
                DevEmbedOwnerPIINavigationPreviewView()
            } else if ProcessInfo.processInfo.arguments.contains("--dev-youtube-search-route-preview"),
                      let skill = DevEmbedPreviewFixtures.skills(for: .web).first(where: { $0.id == "web-search-youtube" }) {
                DevEmbedFullscreenRouteHarness(skill: skill)
                    .padding(.spacing8)
            } else if ProcessInfo.processInfo.arguments.contains("--dev-health-search-route-preview"),
                      let skill = DevEmbedPreviewFixtures.fullscreenSkill(forRegistryKey: EmbedType.healthSearch.rawValue) {
                DevEmbedFullscreenRouteHarness(skill: skill)
                    .padding(.spacing8)
            } else if let request = canonicalRequest {
                canonicalSurface(request)
            } else {
                VStack(spacing: 0) {
                    header
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: .spacing12) {
                            ForEach(DevEmbedPreviewFixtures.skills(for: selectedApp)) { skill in
                                DevEmbedPreviewSkillSection(skill: skill) { open($0, quote: $1) }
                            }
                        }
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing8)
                    }
                    .background(Color.grey0)
                }
                .accessibilityIdentifier("dev-embed-preview-gallery")
            }
        }
        .background(Color.grey0.ignoresSafeArea())
        .preferredColorScheme(galleryColorScheme)
        .transformEnvironment(\.colorScheme) { scheme in
            if let galleryColorScheme { scheme = galleryColorScheme }
        }
        .transformEnvironment(\.layoutDirection) { direction in
            if let request = canonicalRequest {
                direction = request.direction == .rtl ? .rightToLeft : .leftToRight
            }
        }
        .overlay {
            if let openedSkill {
                EmbedFullscreenContainer(
                    embeds: [openedSkill.primaryEmbed], initialEmbedId: openedSkill.primaryEmbed.id,
                    allEmbedRecords: openedSkill.allRecords, chatId: nil,
                    onClose: { self.openedSkill = nil; openedQuote = nil },
                    highlightQuoteText: openedQuote
                )
                .accessibilityIdentifier("dev-embed-opened-fullscreen")
            }
        }
        .environment(\.embedChatID,
                     ProcessInfo.processInfo.arguments.contains("--dev-code-run-output-preview")
                        ? "dev-embed-preview-chat" : nil)
        .onAppear {
            if ProcessInfo.processInfo.arguments.contains("--dev-code-run-output-preview") {
                CodeRunOutputStore.shared.seedPreviewOutput(
                    chatId: "dev-embed-preview-chat", embedId: "preview-code-1",
                    output: "Preparing sandbox\nRendered index.html\nRun complete\n"
                )
            }
        }
    }

    @ViewBuilder
    private func canonicalSurface(_ request: DevEmbedPreviewRequest) -> some View {
        if let skill = DevEmbedPreviewFixtures.fixture(for: request) {
            Group {
                switch request.surface {
                case .preview:
                    if request.registryKey == EmbedType.focusModeActivation.rawValue {
                        FocusModeRenderer(data: skill.primaryEmbed.rawData, mode: .preview)
                            .frame(maxWidth: 326)
                    } else {
                        EmbedPreviewCard(embed: skill.primaryEmbed, allEmbedRecords: skill.allRecords, variant: .compact) {
                            open(skill)
                        }
                        .frame(width: 300, height: 200)
                    }
                case .fullscreen:
                    if canonicalFullscreenOpen {
                        EmbedFullscreenContainer(
                            embeds: [skill.primaryEmbed], initialEmbedId: skill.primaryEmbed.id,
                            allEmbedRecords: skill.allRecords,
                            chatId: ProcessInfo.processInfo.arguments.contains("--dev-code-run-output-preview")
                                ? "dev-embed-preview-chat" : nil,
                            hasPIIMappings: !previewPIIMappings.isEmpty, piiMappings: previewPIIMappings,
                            isPIIRevealed: isPreviewPIIRevealed,
                            onTogglePII: { isPreviewPIIRevealed.toggle() },
                            onClose: { canonicalFullscreenOpen = false }
                        )
                    } else {
                        Button("Reopen fullscreen embed") { canonicalFullscreenOpen = true }
                            .accessibilityIdentifier("dev-embed-fullscreen-dismissed")
                    }
                case .inline:
                    DevEmbedInlineLinkBlock(skill: skill) { open(skill) }
                        .padding(.spacing10)
                case .quote:
                    DevEmbedQuoteBlock(skill: skill) { quote in open(skill, quote: quote) }
                        .padding(.spacing10)
                case .groupSmall:
                    if let base = DevEmbedPreviewFixtures.skill(forRegistryKey: request.registryKey) {
                        DevEmbedSmallGroup(variants: DevEmbedPreviewFixtures.dataVariants(for: base)) { open($0) }
                    }
                case .groupLarge:
                    if let base = DevEmbedPreviewFixtures.skill(forRegistryKey: request.registryKey) {
                        DevEmbedLargeGroup(variants: DevEmbedPreviewFixtures.dataVariants(for: base), initialVariant: request.variant) { open($0) }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .overlay(alignment: .topLeading) {
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement()
                    .accessibilityIdentifier("dev-embed-canonical-\(request.surface.rawValue)")
                    .accessibilityValue("\(request.registryKey)|\(request.variant)")
                    .offset(x: 8)
            }
        } else {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text("Missing native registry fixture or unsupported state").font(.omH4)
                Text("\(request.registryKey)|\(request.surface.rawValue)|\(request.variant)").font(.omSmall)
            }
            .padding(.spacing8)
            .accessibilityIdentifier("dev-embed-registry-missing")
            .accessibilityValue(request.registryKey)
        }
    }

    private func open(_ skill: DevEmbedPreviewSkill, quote: String? = nil) {
        openedQuote = quote
        openedSkill = skill
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                Text(selectedApp.title)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                Button {
                    galleryColorScheme = (galleryColorScheme ?? colorScheme) == .dark ? .light : .dark
                } label: {
                    Icon("darkmode", size: .iconSizeSm)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("theme-toggle-btn")
                .accessibilityLabel("Toggle theme")
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

/// Two embeds intentionally reuse one placeholder so the navigation test can
/// prove owner-only mappings never cross from the previous selection.
private struct DevEmbedOwnerPIINavigationPreviewView: View {
    private let chatId = "dev-embed-preview-chat"
    private let firstID = "preview-owner-pii-a"
    private let secondID = "preview-owner-pii-b"

    private var embeds: [EmbedRecord] {
        [makeEmbed(id: firstID), makeEmbed(id: secondID)]
    }

    var body: some View {
        VStack(spacing: .spacing4) {
            Button("Load second embed mapping") {
                OwnerEmbedPIIStore.shared.seedPreviewMappings(
                    chatId: chatId, embedId: secondID,
                    mappings: [PIIMapping(placeholder: "[COUNTERPARTY_1]", original: "Owner B", type: "COUNTERPARTY")]
                )
            }
            .accessibilityIdentifier("dev-owner-pii-load-b")

            EmbedFullscreenContainer(
                embeds: embeds,
                initialEmbedId: firstID,
                allEmbedRecords: EmbedRecord.dictionaryById(embeds, context: "devOwnerPIINavigation"),
                chatId: chatId,
                isPIIRevealed: true
            )
        }
        .onAppear {
            OwnerEmbedPIIStore.shared.seedPreviewMappings(
                chatId: chatId, embedId: firstID,
                mappings: [PIIMapping(placeholder: "[COUNTERPARTY_1]", original: "Owner A", type: "COUNTERPARTY")]
            )
        }
    }

    private func makeEmbed(id: String) -> EmbedRecord {
        EmbedRecord(
            id: id, type: EmbedType.codeCode.rawValue, status: .finished,
            data: .raw([
                "code": AnyCodable("let counterparty = \"[COUNTERPARTY_1]\""),
                "language": AnyCodable("swift"),
                "filename": AnyCodable("owner.swift")
            ]),
            parentEmbedId: nil, appId: "code", skillId: "code",
            embedIds: nil, createdAt: nil
        )
    }
}

private struct DevEmbedPreviewSkillSection: View {
    let skill: DevEmbedPreviewSkill
    let onOpen: (DevEmbedPreviewSkill, String?) -> Void
    private let previewVariants: [DevEmbedPreviewVariant]
    private let fullscreenVariants: [DevEmbedPreviewVariant]
    private let showsLargeGroup: Bool
    @State private var selectedTemplate = "default"
    @State private var fullscreenVariant = "default"

    init(skill: DevEmbedPreviewSkill, onOpen: @escaping (DevEmbedPreviewSkill, String?) -> Void) {
        self.skill = skill
        self.onOpen = onOpen
        previewVariants = DevEmbedPreviewFixtures.variants(for: skill)
        let fullscreen = DevEmbedPreviewFixtures.fullscreenSkill(forRegistryKey: skill.primaryEmbed.type) ?? skill
        fullscreenVariants = DevEmbedPreviewFixtures.dataVariants(for: fullscreen, fullscreen: true)
        showsLargeGroup = DevEmbedPreviewFixtures.supportsLargeGroup(skill)
    }

    private var activeTemplate: DevEmbedPreviewSkill {
        previewVariants.first { $0.name == selectedTemplate }?.skill ?? skill
    }
    private var smallVariants: [DevEmbedPreviewVariant] {
        previewVariants.filter(\.isDataVariant).map {
            $0.name == "default" ? DevEmbedPreviewVariant(name: "default", skill: activeTemplate) : $0
        }
    }
    private var activeFullscreen: DevEmbedPreviewSkill {
        fullscreenVariants.first { $0.name == fullscreenVariant }?.skill ?? skill
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing12) {
            HStack(spacing: .spacing3) {
                AppIconView(appId: skill.primaryEmbed.appId ?? "web", size: 28)
                Text(skill.label).font(.omH4).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            }
            .accessibilityIdentifier("dev-preview-skill-\(skill.id)")
            .accessibilityValue(skill.primaryEmbed.type)

            Color.clear.frame(width: 1, height: 1).accessibilityElement()
                .accessibilityIdentifier("dev-preview-registry-key-\(skill.primaryEmbed.type)")

            DevEmbedTemplateControls(variants: previewVariants.filter { $0.name != "mobile" },
                                     selection: $selectedTemplate, identifier: "dev-embed-template")
                .accessibilityValue(selectedTemplate)
                .accessibilityIdentifier("dev-preview-active-template")

            DevEmbedDisplayBlock(title: "INLINE LINK") {
                DevEmbedInlineLinkBlock(skill: skill) { open(activeTemplate) }
            }
            DevEmbedDisplayBlock(title: "QUOTE BLOCK") {
                DevEmbedQuoteBlock(skill: skill) { quote in open(activeTemplate, quote: quote) }
            }
            DevEmbedDisplayBlock(title: "GROUP — SMALL", flush: true) {
                DevEmbedSmallGroup(variants: smallVariants) { open($0) }
            }
            if showsLargeGroup {
                DevEmbedDisplayBlock(title: "GROUP — LARGE", flush: true) {
                    DevEmbedLargeGroup(variants: previewVariants.filter(\.isDataVariant)) { open($0) }
                }
            }
            DevEmbedDisplayBlock(title: "FULLSCREEN CLIPPED INLINE", flush: true) {
                VStack(spacing: 0) {
                    if fullscreenVariants.count > 1 {
                        DevEmbedTemplateControls(variants: fullscreenVariants, selection: $fullscreenVariant,
                                                 identifier: "dev-embed-fullscreen-variant")
                            .padding(.spacing5)
                    }
                    EmbedFullscreenContainer(
                        embeds: fullscreenVariants.map { $0.skill.primaryEmbed },
                        initialEmbedId: activeFullscreen.primaryEmbed.id,
                        allEmbedRecords: fullscreenVariants.reduce(into: [:]) { $0.merge($1.skill.allRecords) { _, new in new } },
                        chatId: nil
                    )
                    .id(fullscreenVariant)
                    .frame(height: 560)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .overlay {
                        RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1)
                    }
                }
            }
            if !skill.childEmbeds.isEmpty {
                DevEmbedDisplayBlock(title: "FULLSCREEN ROUTE HARNESS", flush: true) {
                    DevEmbedFullscreenRouteHarness(skill: skill)
                }
            }
        }
        .frame(maxWidth: 930, alignment: .leading)

    }

    private func open(_ skill: DevEmbedPreviewSkill, quote: String? = nil) {
        onOpen(skill, quote)
    }
}

/// The showcase groups compare data variants of one renderer, not parent/child records.
private struct DevEmbedSmallGroup: View {
    let variants: [DevEmbedPreviewVariant]
    let onOpen: (DevEmbedPreviewSkill) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            HStack(alignment: .top, spacing: .spacing6) {
                ForEach(variants) { variant in
                    VStack(spacing: .spacing3) {
                        Text(variant.name.uppercased()).font(.omTiny.weight(.semibold))
                            .foregroundStyle(Color.fontTertiary)
                        EmbedPreviewCard(embed: variant.skill.primaryEmbed, allEmbedRecords: variant.skill.allRecords) {
                            onOpen(variant.skill)
                        }
                        .frame(width: 300, height: 200)
                    }
                    .accessibilityIdentifier("dev-embed-small-variant-\(variant.name)")
                }
            }
            .padding(.bottom, .spacing4)
        }
        .padding(.vertical, .spacing6)
        .padding(.horizontal, .spacing8)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .overlay { RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1) }
        .accessibilityIdentifier("dev-embed-group-small")
        .accessibilityValue(variants.map(\.name).joined(separator: "|"))
    }
}

private struct DevEmbedLargeGroup: View {
    let variants: [DevEmbedPreviewVariant]
    let onOpen: (DevEmbedPreviewSkill) -> Void
    @State private var selectedIndex: Int

    init(variants: [DevEmbedPreviewVariant], initialVariant: String = "default", onOpen: @escaping (DevEmbedPreviewSkill) -> Void) {
        self.variants = variants
        self.onOpen = onOpen
        _selectedIndex = State(initialValue: variants.firstIndex { $0.name == initialVariant } ?? 0)
    }

    var body: some View {
        if !variants.isEmpty {
            let variant = variants[min(selectedIndex, variants.count - 1)]
            VStack(spacing: 0) {
                HStack(spacing: .spacing6) {
                    arrow(previous: true) { selectedIndex = (selectedIndex - 1 + variants.count) % variants.count }
                    Text("\(variant.name)  \(selectedIndex + 1) / \(variants.count)")
                        .font(.omXs.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("dev-embed-large-active-variant")
                    arrow(previous: false) { selectedIndex = (selectedIndex + 1) % variants.count }
                }
                .padding(.bottom, .spacing6)
                GeometryReader { geometry in
                    EmbedPreviewCard(embed: variant.skill.primaryEmbed, allEmbedRecords: variant.skill.allRecords,
                                     variant: geometry.size.width > 400 ? .large : .compact) {
                        onOpen(variant.skill)
                    }
                    .frame(maxWidth: .infinity)
                }
                .frame(height: 425)
                .overlay { RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1) }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-embed-group-large")
            .accessibilityValue(variant.name)
        }
    }

    private func arrow(previous: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon("back", size: .iconSizeXs).scaleEffect(x: previous ? 1 : -1, y: 1)
                .padding(.vertical, .spacing2).padding(.horizontal, .spacing6)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
                .overlay { RoundedRectangle(cornerRadius: .radius2).stroke(Color.grey30, lineWidth: 1) }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(previous ? AppStrings.previousInspiration : AppStrings.nextInspiration)
        .accessibilityIdentifier(previous ? "dev-embed-large-previous" : "dev-embed-large-next")
    }
}

private struct DevEmbedFullscreenRouteHarness: View {
    let skill: DevEmbedPreviewSkill
    @State private var activeEmbed: EmbedRecord?
    @State private var previousEmbeds: [EmbedRecord] = []

    init(skill: DevEmbedPreviewSkill) {
        self.skill = skill
        _activeEmbed = State(initialValue: skill.primaryEmbed)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(activeRouteLabel)
                .font(.omMicro.weight(.semibold))
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("dev-embed-active-route")

            if let activeEmbed, activeEmbed.id == skill.primaryEmbed.id, let firstChild = skill.childEmbeds.first {
                Button("Open first child from parent fullscreen") {
                    openChild(firstChild, from: activeEmbed)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("dev-embed-route-open-first-child")
            }

            if let activeEmbed {
                EmbedFullscreenContainer(
                    embeds: [activeEmbed],
                    initialEmbedId: activeEmbed.id,
                    allEmbedRecords: skill.allRecords,
                    chatId: nil,
                    onOpenEmbed: { child, parent in
                        openChild(child, from: parent)
                    },
                    onClose: closeRoute
                )
                .frame(height: 560)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .overlay {
                    RoundedRectangle(cornerRadius: .radius8)
                        .stroke(Color.grey30, lineWidth: 1)
                }
            } else {
                Button("Reset fullscreen route") {
                    previousEmbeds = []
                    activeEmbed = skill.primaryEmbed
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("dev-embed-route-reset")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("dev-embed-fullscreen-route-harness")
    }

    private var activeRouteLabel: String {
        "Active embed: \(activeEmbed?.id ?? "none")"
    }

    private func openChild(_ child: EmbedRecord, from parent: EmbedRecord) {
        if previousEmbeds.last?.id != parent.id {
            previousEmbeds.append(parent)
        }
        activeEmbed = child
    }

    private func closeRoute() {
        if let previous = previousEmbeds.popLast() {
            activeEmbed = previous
        } else {
            activeEmbed = nil
        }
    }
}

private struct DevEmbedTemplateControls: View {
    let variants: [DevEmbedPreviewVariant]
    @Binding var selection: String
    let identifier: String

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing3) {
                ForEach(variants) { variant in
                    Button { selection = variant.name } label: {
                        Text(variant.name == "default" ? "Default" : variant.name)
                            .font(.omXxs)
                            .foregroundStyle(selection == variant.name ? Color.fontButton : Color.fontPrimary)
                            .padding(.horizontal, .spacing5).padding(.vertical, .spacing2)
                            .background(selection == variant.name ? AppGradientPalette.colors(for: "primary").start : Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius1))
                            .overlay { RoundedRectangle(cornerRadius: .radius1).stroke(Color.grey30, lineWidth: 1) }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("\(identifier)-\(variant.name)")
                    .accessibilityAddTraits(selection == variant.name ? [.isSelected] : [])
                }
            }
        }
    }
}

/// Web showcase-specific presentation. Production chat uses InlineMarkdownText;
/// this route compares the deployed fake-inline illustration and opens real embeds.
private struct DevEmbedInlineLinkBlock: View {
    let skill: DevEmbedPreviewSkill
    let onOpen: () -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 3) {
                Text("The assistant found")
                link
                Text("for you.")
            }
            .fixedSize(horizontal: true, vertical: false)
            VStack(alignment: .leading, spacing: 3) {
                Text("The assistant found")
                HStack(spacing: 3) { link; Text("for you.") }
            }
        }
        // /dev/preview .dt-body--inline, .fake-link-text: 0.9375rem (15px).
        .font(.custom("Lexend Deca", size: 15))
        .foregroundStyle(Color.fontPrimary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("dev-embed-inline")
    }

    private var link: some View {
        Button(action: onOpen) {
            HStack(spacing: 5) {
                AppIconView(appId: skill.primaryEmbed.appId ?? "web", size: .iconSizeSm)
                Text(DevEmbedPreviewFixtures.inlineText(for: skill))
                    .fontWeight(.medium).foregroundStyle(AppGradientPalette.colors(for: "primary").start)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("dev-embed-inline-open")
    }
}

/// Match the deployed showcase illustration while forwarding source quote text
/// to the production fullscreen highlight/scroll pipeline on open.
private struct DevEmbedQuoteBlock: View {
    let skill: DevEmbedPreviewSkill
    let onOpen: (String) -> Void

    var body: some View {
        let quote = DevEmbedPreviewFixtures.quoteText(for: skill)
        Button { onOpen(quote) } label: {
            VStack(alignment: .leading, spacing: .spacing4) {
                // /dev/preview .fake-quote-text: 15px, line-height 1.6.
                Text(quote).font(.custom("Lexend Deca", size: 15)).italic()
                    .foregroundStyle(Color.fontPrimary).lineSpacing(5)
                    .multilineTextAlignment(.leading)
                HStack(spacing: .spacing3) {
                    AppIconView(appId: skill.primaryEmbed.appId ?? "web", size: 18)
                    Text(skill.primaryEmbed.appId ?? "web").font(.omXxs).foregroundStyle(Color.fontTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, .spacing5).padding(.horizontal, .spacing8)
            .background(Color.grey0)
            .overlay(alignment: .leading) {
                Rectangle().fill(AppGradientPalette.colors(for: skill.primaryEmbed.appId ?? "web").start).frame(width: 3)
            }
            .clipShape(UnevenRoundedRectangle(topLeadingRadius: 0, bottomLeadingRadius: 0,
                                            bottomTrailingRadius: .radius3, topTrailingRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("dev-embed-quote-open")
    }
}

private struct DevEmbedDisplayBlock<Content: View>: View {
    let title: String
    var flush = false
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
                .padding(flush ? .spacing0 : .spacing10)
                .background(flush ? Color.clear : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .overlay {
                    if !flush { RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1) }
                }
        }
    }
}
#endif
