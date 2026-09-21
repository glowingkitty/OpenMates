// Debug-only, account-independent hosts for production Apple UI components.
// Fixtures and all editable state live in this view tree; no chat store, auth
// session, draft repository, upload service, or send pipeline is constructed.
// Recreating the configuration identity resets local interactions predictably.
// The bare canvas exposes its last local action through accessibility for tests.
//
// Web sources: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//              frontend/packages/ui/src/components/ChatHeader.svelte
//              frontend/packages/ui/src/components/ChatMessage.svelte
//              frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//              frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
// Exact bare comparison URLs are in DevPreviewComponentRegistry.

#if DEBUG
import SwiftUI

struct DevComponentPreviewView: View {
    let configuration: DevPreviewLaunchConfiguration

    var body: some View {
        Group {
            if let error = configuration.error ?? fixtureError {
                Text(error)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing8)
                    .accessibilityIdentifier("dev-preview-error")
            } else {
                DevComponentPreviewCanvas(configuration: configuration)
                    .id(configuration)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey0.ignoresSafeArea())
        // Production actions (for example Copy) keep their real user feedback
        // in the isolated host as well as in MainAppView.
        .overlay(alignment: .top) { ToastOverlay() }
    }

    private var fixtureError: String? {
        guard let component = configuration.component else { return "Select a component preview." }
        let allowedKeys: Set<String>
        switch component {
        case .login, .signup, .history, .sidebar, .welcome: allowedKeys = []
        case .composer: allowedKeys = ["text", "placeholder"]
        case .chatHeader: allowedKeys = ["title", "summary", "appId"]
        case .message: allowedKeys = configuration.variant.hasPrefix("streaming") ? [] : ["content", "thinkingContent"]
        case .embedPreview, .embedFullscreen:
            allowedKeys = []
            guard configuration.appSlug == .web else {
                return "Isolated embed interaction currently supports the web fixture only."
            }
        default:
            return "This component does not yet have an isolated preview host."
        }
        guard configuration.props.keys.allSatisfy(allowedKeys.contains) else {
            return "Unsupported prop for this component. Supported props: \(allowedKeys.sorted().joined(separator: ", "))."
        }
        guard configuration.props.values.allSatisfy({ $0.string != nil }) else {
            return "This component's fixture props must be strings."
        }
        return nil
    }
}

private struct DevComponentPreviewCanvas: View {
    let configuration: DevPreviewLaunchConfiguration
    @State private var lastAction = "ready"
    @State private var embedRoute: [EmbedRecord] = []
    @State private var headerIndex = 0
    @State private var standaloneFullscreenMinimized = false
    @State private var standaloneParent: EmbedRecord?
    @State private var insertedFixtureResult = false
    @State private var removedSecondFixtureResult = false

    private var skill: DevEmbedPreviewSkill {
        // This curated fixture is complete in memory. Other gallery families can
        // contain service-backed media/actions and require separate isolation.
        DevEmbedPreviewFixtures.skills(for: configuration.variant == "actions-code" ? .code : .web)[0]
    }

    private var primaryEmbed: EmbedRecord {
        let source = skill.primaryEmbed
        let status = EmbedStatus(rawValue: configuration.variant) ?? .finished
        var data = source.rawData ?? [:]
        data["result_count"] = AnyCodable(fixtureChildren.count)
        return EmbedRecord(id: source.id, type: source.type, status: status, data: .raw(data),
                           parentEmbedId: source.parentEmbedId, appId: source.appId,
                           skillId: source.skillId, embedIds: fixtureChildren.map(\.id).joined(separator: "|"),
                           createdAt: source.createdAt)
    }

    private var fixtureChildren: [EmbedRecord] {
        var result = skill.childEmbeds.filter { !removedSecondFixtureResult || $0.id != "preview-web-search-result-2" }
        if insertedFixtureResult, let template = skill.childEmbeds.first {
            var data = template.rawData ?? [:]
            data["title"] = AnyCodable("Earlier hydrated result")
            result.insert(EmbedRecord(id: "preview-web-search-result-inserted", type: template.type,
                status: template.status, data: .raw(data), parentEmbedId: primaryFixtureID,
                appId: template.appId, skillId: template.skillId, embedIds: nil, createdAt: template.createdAt), at: 0)
        }
        return result
    }

    private var primaryFixtureID: String { skill.primaryEmbed.id }

    // The web withNavigation variant means peer parent embeds, not a parent
    // followed by its own results. Local peers make the actions observable.
    private var parentNavigationEmbeds: [EmbedRecord] {
        guard configuration.variant == "withNavigation" else { return [primaryEmbed] }
        func peer(_ suffix: String, query: String) -> EmbedRecord {
            let source = primaryEmbed
            var data = source.rawData ?? [:]
            data["query"] = AnyCodable(query)
            return EmbedRecord(id: source.id + suffix, type: source.type, status: source.status,
                data: .raw(data), parentEmbedId: nil, appId: source.appId, skillId: source.skillId,
                embedIds: source.embedIds, createdAt: source.createdAt)
        }
        return [peer("-previous", query: "Previous search fixture"), primaryEmbed,
                peer("-next", query: "Next search fixture")]
    }

    private var fixtureRecords: [String: EmbedRecord] {
        Dictionary((parentNavigationEmbeds + fixtureChildren).map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                component(viewport: proxy.size)
                    .frame(maxWidth: .infinity, maxHeight: .infinity,
                           alignment: configuration.component == .chatHeader ? .top : .center)
                    .allowsHitTesting(embedRoute.isEmpty)
                    .accessibilityHidden(!embedRoute.isEmpty)
                if let active = embedRoute.last {
                    fullscreen(active)
                        .id(active.id)
                        .background(Color.grey0)
                }
                if ProcessInfo.processInfo.arguments.contains("--ui-test-embed-navigation-mutations") {
                    VStack {
                        Spacer()
                        HStack {
                            Button("Insert fixture result") { insertedFixtureResult = true }
                                .accessibilityIdentifier("dev-preview-insert-result")
                            Button("Remove fixture result 2") { removedSecondFixtureResult = true }
                                .accessibilityIdentifier("dev-preview-remove-result-2")
                        }
                        .buttonStyle(.bordered)
                        .padding(8)
                        .background(Color.grey0)
                    }
                }
                // A separate leaf survives SwiftUI collapsing the root/canvas
                // containers into one accessibility element. It changes no
                // visible chrome and cannot intercept component interactions.
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement()
                    .accessibilityLabel(lastAction)
                    .accessibilityIdentifier("dev-preview-local-action")
                    .allowsHitTesting(false)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            }
            .environment(\.openURL, OpenURLAction { _ in
                lastAction = "external-link-intercepted"
                return .handled
            })
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-component-preview-\(configuration.component?.rawValue ?? "unknown")")
            .accessibilityValue(lastAction)
        }
    }

    @ViewBuilder
    private func component(viewport: CGSize) -> some View {
        switch configuration.component {
        case .sidebar:
            DevSidebarComponentFixture(variant: configuration.variant)
        case .history:
            DevHistoryComponentFixture(workspace: configuration.variant == "workspace")
        case .welcome:
            DevWelcomeComponentFixture(empty: configuration.variant == "empty", onAction: { lastAction = $0 })
        case .login, .signup:
            DevAuthFormFixture(configuration: configuration)
        case .composer where configuration.variant == "model":
            DevComposerModelFixture()
        case .composer:
            DevComposerComponentFixture(configuration: configuration, onAction: { lastAction = $0 })
                .padding(.horizontal, viewport.width > 730 ? 32 : 16)
        case .chatHeader:
            ChatBannerView(state: bannerState,
                           createdAt: Date(timeIntervalSince1970: 1_783_684_800),
                           viewportHeight: viewport.height,
                           onPrevious: { headerIndex -= 1; lastAction = "previous-chat" },
                           onNext: { headerIndex += 1; lastAction = "next-chat" })
        case .message:
            if configuration.variant.hasPrefix("streaming") {
                DevProgressiveMessageFixture(variant: configuration.variant)
            } else {
            ScrollView {
                MessageBubble(message: message, chatId: message.chatId, appId: "code",
                              embeds: configuration.variant == "citations" ? Array(fixtureRecords.values) : [],
                              allEmbedRecords: fixtureRecords, streamingContent: nil,
                              thinkingContent: message.thinkingContent, isThinkingStreaming: false,
                              piiMappings: [], isPIIRevealed: false, containerWidth: viewport.width,
                              isSearchTarget: false, searchHighlightQuery: nil,
                              onEmbedTap: { open($0) },
                              onOpenPublicChat: { _ in lastAction = "public-chat-intercepted" },
                              onInteractiveQuestionSubmit: { _ in lastAction = "question-submitted-locally" },
                              onShowActions: { lastAction = "message-actions-requested" })
                    .padding(.spacing5)
            }
            }
        case .embedPreview:
            EmbedPreviewCard(embed: primaryEmbed, allEmbedRecords: fixtureRecords) { open(primaryEmbed) }
        case .embedFullscreen:
            if standaloneFullscreenMinimized {
                EmbedPreviewCard(embed: primaryEmbed, allEmbedRecords: fixtureRecords) { open(primaryEmbed) }
            } else {
                fullscreen(standaloneParent ?? primaryEmbed)
            }
        default:
            EmptyView()
        }
    }

    private var bannerState: ChatBannerState {
        switch configuration.variant {
        case "loading": return .loading
        case "incognito": return .incognito
        case "draft": return .draftOnly(preview: configuration.props["title"]?.string ?? "Plan a weekend in Berlin")
        default:
            let defaultTitle = configuration.variant == "long-title"
                ? "A detailed weekend guide to Berlin with restaurants, museums, parks, and places to explore"
                : "A weekend in Berlin"
            let title = configuration.props["title"]?.string ?? defaultTitle
            return .loaded(title: headerIndex == 0 ? title : "\(title) (\(headerIndex))",
                           appId: configuration.props["appId"]?.string ?? "travel",
                           summary: configuration.props["summary"]?.string ?? "Restaurants, museums, and a relaxed itinerary.")
        }
    }

    private var message: Message {
        let variant = configuration.variant
        let role: MessageRole = variant == "default" || variant == "user" ? .user : .assistant
        let defaultContent: String
        switch variant {
        case "default", "user":
            defaultContent = "Can you help me understand how Svelte 5 runes work? I want to migrate my app from Svelte 4."
        case "thinking":
            defaultContent = "Based on my analysis, the best approach would be to start by converting your reactive declarations first."
        case "citations":
            defaultContent = "Here are some places to start: [Berlin restaurants](embed:\(skill.childEmbeds[0].id)).\n\n[[embed:\(primaryEmbed.id)]]"
        default:
            defaultContent = "Svelte 5 runes are a new reactivity system that replaces the old `$:` reactive declarations.\n\n- **$state()** — Declares reactive state variables\n- **$derived()** — Creates computed values that update automatically\n- **$effect()** — Runs side effects when dependencies change\n- **$props()** — Declares component props\n\nThe migration is incremental — your existing Svelte 4 code will continue to work in compatibility mode."
        }
        let thinking = configuration.props["thinkingContent"]?.string ?? (variant == "thinking"
            ? "The user wants to migrate from Svelte 4 to Svelte 5. I should explain the key differences and provide a step-by-step migration approach. The most important change is the runes system."
            : nil)
        return Message(id: "preview-message", chatId: "preview-chat", role: role,
                       content: configuration.props["content"]?.string ?? defaultContent,
                       encryptedContent: nil, createdAt: "2026-07-09T12:00:00Z", updatedAt: nil,
                       appId: "code", isStreaming: false, embedRefs: nil,
                       modelName: role == .assistant ? "claude-sonnet-4-20250514" : nil,
                       thinkingContent: thinking)
    }

    private func fullscreen(_ active: EmbedRecord) -> some View {
        let resolvedActive = fixtureRecords[active.id] ?? active
        let siblings = EmbedGrouper.fullscreenNavigationEmbeds(
            selected: resolvedActive,
            messageEmbeds: configuration.variant == "withNavigation" ? parentNavigationEmbeds : [active],
            allRecords: fixtureRecords,
            parent: embedRoute.dropLast().last ?? (configuration.component == .embedFullscreen ? standaloneParent : nil)
        )
        return EmbedFullscreenContainer(embeds: siblings, initialEmbedId: active.id,
                                        allEmbedRecords: fixtureRecords, chatId: nil,
                                        onOpenEmbed: { child, parent in openChild(child, from: parent) },
                                        onClose: closeEmbed)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-preview-embed-fullscreen")
            .accessibilityValue(active.id)
    }

    private func open(_ embed: EmbedRecord) {
        embedRoute.append(embed)
        lastAction = "opened-\(embed.id)"
    }

    private func openChild(_ child: EmbedRecord, from parent: EmbedRecord) {
        if embedRoute.isEmpty && configuration.component == .embedFullscreen {
            standaloneParent = parent
        } else if !embedRoute.isEmpty {
            // The container may have navigated to a peer since this route was
            // opened. Minimize must restore that actual parent, not its seed.
            embedRoute[embedRoute.count - 1] = parent
        }
        open(child)
    }

    private func closeEmbed() {
        if !embedRoute.isEmpty {
            embedRoute.removeLast()
        } else {
            standaloneFullscreenMinimized = true
        }
        lastAction = "embed-minimized"
    }
}

private struct DevComposerComponentFixture: View {
    let configuration: DevPreviewLaunchConfiguration
    let onAction: (String) -> Void
    @StateObject private var session: NativeComposerSession
    @State private var focused: Bool
    @State private var fixtureError: String?
    @State private var attachmentInstalled = false
    @State private var drawingOpen = false
    @State private var drawingFullscreen = false
    @State private var localDrawing: Data?

    init(configuration: DevPreviewLaunchConfiguration, onAction: @escaping (String) -> Void) {
        self.configuration = configuration
        self.onAction = onAction
        let text = configuration.props["text"]?.string
            ?? (configuration.variant == "filled" ? "Help me plan a weekend in Berlin." : "")
        _session = StateObject(wrappedValue: NativeComposerSession(canonicalMarkdown: text))
        _focused = State(initialValue: configuration.variant == "focused")
    }

    private var compact: Bool {
        configuration.variant == "default" && !focused && session.canonicalMarkdown.isEmpty
    }

    var body: some View {
        VStack {
            MessageComposerView(session: session, isFocused: $focused, compact: compact,
                                placeholder: configuration.props["placeholder"]?.string ?? AppStrings.whatDoYouNeedHelpWith,
                                compactHeight: 64, compactCornerRadius: 32,
                                showActionButtonsWhenCompact: false, maxWidth: nil,
                                isComposerEditable: configuration.variant != "disabled",
                                onSubmit: submit, preFieldContent: { EmptyView() },
                                overlayContent: {
                    #if os(iOS)
                    if drawingOpen {
                        SketchComposerOverlay(isFullscreen: $drawingFullscreen, onSave: saveDrawing,
                                              onCancel: { drawingOpen = false })
                            .accessibilityIdentifier("dev-preview-drawing-overlay")
                    }
                    #endif
                }) {
                ComposerAttachmentActionRow(viewportWidth: 390,
                    onDrawing: { drawingOpen = true; focused = false },
                    onLocation: { fixtureError = AppStrings.shareLocation },
                    onCamera: { fixtureError = AppStrings.takePhoto },
                    onFiles: addAttachment,
                    model: { EmptyView() }, speech: { EmptyView() }, record: { EmptyView() },
                    submit: { MessageComposerSendButton(title: AppStrings.sendAction,
                        disabled: session.canonicalMarkdown.isEmpty, action: submit) })
            }

            if let fixtureError {
                Text(fixtureError).accessibilityIdentifier("dev-preview-action-error")
            }
        }
        .onAppear {
            if configuration.variant == "attachment" && !attachmentInstalled { addAttachment() }
        }
    }

    private func saveDrawing(_ data: Data, _ filename: String) {
        guard !data.isEmpty else { return }
        drawingOpen = false
        localDrawing = data
        do {
            try session.insertPendingEmbed(nodeID: "preview-drawing", embedType: "image", title: filename)
            try session.configureEmbedActions(nodeID: "preview-drawing", onOpen: { _ in drawingOpen = true },
                onRetry: { _ in }, onRemove: { _ in localDrawing = nil; onAction("drawing-removed") })
            onAction("drawing-attached-locally")
        } catch { fixtureError = "Unable to attach local drawing." }
    }

    private func addAttachment() {
        let id = "preview-composer-attachment"
        guard !session.controller.document.nodes.contains(where: { $0.id == id }) else { return }
        do {
            let record = DevEmbedPreviewFixtures.skills(for: .web)[0].primaryEmbed
            try session.insertPendingEmbed(nodeID: id, embedType: "app-skill-use", title: "Search")
            try session.resolveEmbed(nodeID: id, durableEmbedID: record.id, referenceType: "app-skill-use",
                                     status: "finished", embedRecord: record)
            try session.configureEmbedActions(nodeID: id,
                                              onOpen: { _ in onAction("attachment-opened-locally") },
                                              onRetry: { _ in onAction("attachment-retried-locally") },
                                              onRemove: { _ in onAction("attachment-removed") })
            attachmentInstalled = true
            onAction("attachment-added")
        } catch {
            fixtureError = "The local attachment fixture could not be created."
        }
    }

    private func submit() {
        guard configuration.variant != "disabled", !session.canonicalMarkdown.isEmpty else { return }
        session.clear()
        focused = false
        onAction("submitted-locally")
    }
}
#endif
