// Recipient-owned encrypted sharing view. It never mounts the owner ChatView,
// ChatViewModel, composer, account task services or owner embed fullscreen.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/apps/web_app/src/routes/share/chat/[chatId]/+page.svelte
//         frontend/packages/ui/src/components/ChatHeader.svelte
//         frontend/packages/ui/src/components/ChatHistory.svelte
//         frontend/packages/ui/src/components/ChatMessage.svelte
//         frontend/packages/ui/src/components/ActiveChat.svelte
//         frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/chats/ChatSettingsPage.svelte
// CSS: gate loading/password/error containers; history message-wrapper;
//      ActiveChat read-only-indicator. Captured 390pt web fixture, 2026-10-01.
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls,
//             chat-share-settings.shell-navigation, chat-share-settings.generated-link-controls

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

@MainActor
struct SharedChatRecipientView: View {
    let url: URL
    @StateObject private var model: SharedChatRecipientModel
    var onClose: () -> Void = {}
    // Preview fixtures supply a local action; production submits only to the
    // recipient service, with no auth/account state or password retention.
    var onPasswordSubmit: ((String) -> Void)? = nil
    private let loadOnAppear: Bool
    private let recipientMediaRequestLoader: RecipientMediaTransport.RequestLoader?
    @State private var password = ""
    @State private var showSettings = false
    @State private var settingsTab: ChatSettingsTab = .plan
    @State private var planning = SharedChatRecipientPlanningSnapshot.empty
    @State private var planningLoaded = false
    @State private var recipientMediaContext: RecipientMediaContext?
    @State private var embedPath: [EmbedRecord] = []
    @State private var embedSiblings: [EmbedRecord] = []
    @State private var hideSplitChat = false
    @State private var transcriptWidth: CGFloat = 0
    @State private var viewportHeight: CGFloat = 0
    @State private var spinning = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(url: URL, onClose: @escaping () -> Void = {}) {
        self.url = url
        self.onClose = onClose
        loadOnAppear = true
        recipientMediaRequestLoader = nil
        _model = StateObject(wrappedValue: SharedChatRecipientModel())
    }

    init(url: URL, model: SharedChatRecipientModel, onClose: @escaping () -> Void = {},
         onPasswordSubmit: ((String) -> Void)? = nil,
         recipientMediaRequestLoader: RecipientMediaTransport.RequestLoader? = nil) {
        self.url = url
        self.onClose = onClose
        self.onPasswordSubmit = onPasswordSubmit
        self.recipientMediaRequestLoader = recipientMediaRequestLoader
        loadOnAppear = false
        _model = StateObject(wrappedValue: model)
    }

    private var planningIdentity: String {
        "\(model.presentationScopeID):\(model.context?.chat.id ?? "")"
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                if let context = model.context,
                   recipientMediaContext?.namespace == model.presentationScopeID {
                    ready(context, width: geometry.size.width)
                    if showSettings {
                        ChatSettingsView(chat: context.chat, messages: context.messages,
                                         embeds: Array(context.embeds.values), accountID: nil,
                                         isSharedViewer: true, originalShareURL: context.originalURL,
                                         recipientPlanning: planning,
                                         recipientMediaContext: recipientMediaContext,
                                         onBack: { showSettings = false },
                                         onOpenFile: { embed in showSettings = false; openEmbed(embed) },
                                         initialTab: settingsTab)
                            .id(planningLoaded)
                            .accessibilityIdentifier("shared-recipient-settings")
                    }
                } else {
                    gate
                    OMIconButton(icon: "close", label: AppStrings.close, action: close)
                        .padding(.spacing6)
                        .accessibilityIdentifier("shared-recipient-close")
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .onAppear { viewportHeight = geometry.size.height }
            .onChange(of: geometry.size.height) { _, height in viewportHeight = height }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("shared-recipient-view")
        .environment(\.embedChatID, nil)
        .environment(\.recipientMediaContext, recipientMediaContext)
        .task(id: url) {
            guard loadOnAppear else { return }
            await model.open(url).value
        }
        .task(id: planningIdentity) {
            password = ""
            showSettings = false
            embedPath = []
            embedSiblings = []
            planning = .empty
            planningLoaded = false
            recipientMediaContext?.cancel()
            recipientMediaContext = nil
            let scope = model.presentationScopeID
            guard let context = model.context else { return }
            let chatID = context.chat.id
            recipientMediaContext = try? RecipientMediaContext(linkURL: context.originalURL, namespace: scope, isCurrent: { [weak model] in
                guard let model, model.presentationScopeID == scope,
                      model.context?.chat.id == chatID, case .ready = model.state else { return false }
                return true
            }, requestLoader: recipientMediaRequestLoader)
            guard recipientMediaContext != nil else { return }
            let snapshot = (try? await SharedChatRecipientPlanningSnapshot.load(context: context)) ?? .empty
            guard !Task.isCancelled, scope == model.presentationScopeID,
                  model.context?.chat.id == context.chat.id else { return }
            planning = snapshot
            planningLoaded = true
        }
        .onDisappear { clearPresentation(); model.cancel() }
    }

    private func ready(_ context: SharedChatRecipientContext, width: CGFloat) -> some View {
        ChatEmbedWorkspace(embedOpen: !embedPath.isEmpty, chatHidden: $hideSplitChat,
                           onLayout: { _, chatWidth in transcriptWidth = chatWidth }) {
            transcript(context, width: transcriptWidth > 0 ? transcriptWidth : width)
        } embed: {
            if let selected = embedPath.last {
                fullscreen(context, embed: context.embeds[selected.id] ?? selected)
            }
        }
    }

    private func transcript(_ context: SharedChatRecipientContext, width: CGFloat) -> some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(spacing: 0) {
                    ZStack(alignment: .topTrailing) {
                        ChatBannerView(state: .loaded(title: context.chat.title ?? AppStrings.newChat,
                                                      appId: context.chat.category ?? "general_knowledge",
                                                      summary: context.chat.chatSummary),
                                       createdAt: context.chat.createdDate, iconName: context.chat.icon,
                                       viewportHeight: viewportHeight)
                            .overlay(alignment: .bottom) {
                                Text(AppStrings.sharedRecipientBadge).font(.omXxs)
                                    .foregroundStyle(Color.fontButton)
                                    .padding(.horizontal, .spacing4).padding(.vertical, .spacing1)
                                    .background(Color.grey0.opacity(0.16), in: Capsule())
                                    .padding(.bottom, .spacing8)
                                    .accessibilityIdentifier("shared-chat-badge")
                            }
                        HStack(spacing: .spacing3) {
                            OMIconButton(icon: "share", label: AppStrings.shareChat) { openSettings(.share) }
                                .accessibilityIdentifier("shared-recipient-share")
                            OMIconButton(icon: "settings", label: AppStrings.settings) { openSettings(.plan) }
                                .accessibilityIdentifier("shared-recipient-open-settings")
                            OMIconButton(icon: "close", label: AppStrings.close, action: close)
                                .accessibilityIdentifier("shared-recipient-close")
                        }.padding(.spacing6)
                    }
                    VStack(spacing: .spacing5) {
                        if context.hasMoreBefore {
                            Button { model.loadEarlier() } label: {
                                Text(model.isLoadingEarlier ? AppStrings.loading : AppStrings.sharedRecipientOlder)
                                    .font(.omSmall).foregroundStyle(Color.fontPrimary)
                                    .padding(.vertical, .spacing6).frame(maxWidth: .infinity)
                            }.buttonStyle(.plain).disabled(model.isLoadingEarlier)
                                .accessibilityIdentifier("shared-recipient-load-earlier")
                        }
                        ForEach(context.messages) { message in
                            MessageBubble(message: message, chatId: context.chat.id, appId: message.appId,
                                          embeds: message.embedRefs?.compactMap { context.embeds[$0.id] } ?? [],
                                          allEmbedRecords: context.embeds, streamingContent: nil,
                                          thinkingContent: message.thinkingContent, isThinkingStreaming: false,
                                          piiMappings: [], isPIIRevealed: false, containerWidth: width,
                                          isSearchTarget: message.id == context.targetMessageID, searchHighlightQuery: nil,
                                          onEmbedTap: openEmbed, onOpenPublicChat: nil,
                                          onInteractiveQuestionSubmit: nil, onShowActions: nil,
                                          accessibilityIdentifier: "shared-recipient-message-\(message.id)",
                                          renderScopeID: model.presentationScopeID)
                                .id(message.id)
                                .environment(\.sourceQuoteOpenAction, { embed, _ in openEmbed(embed) })
                                .padding(.vertical, CGFloat.spacing5 / 2) // ChatHistory: 5pt row margin.
                        }
                        readonlyNotice
                    }
                    .frame(maxWidth: 1000) // ChatHistory .chat-history-content max-width.
                    .padding(.spacing5)
                    .frame(maxWidth: .infinity)
                }
            }
            .background(Color.grey0)
            .accessibilityIdentifier("shared-recipient-transcript")
            .task(id: context.targetMessageID) {
                if let target = context.targetMessageID, context.messages.contains(where: { $0.id == target }) {
                    await Task.yield()
                    guard !Task.isCancelled else { return }
                    scroll.scrollTo(target, anchor: .center)
                }
            }
        }
    }

    private var readonlyNotice: some View {
        VStack(spacing: .spacing12) {
            Text(AppStrings.sharedRecipientLockSymbol)
                // ActiveChat .read-only-icon computed font-size:36px, no matching generated font.
                .font(.custom("Lexend Deca", size: 36)).opacity(0.7)
            Text(AppStrings.sharedRecipientReadonly).font(.omSmall)
                .lineSpacing(dynamicTypeSize.isAccessibilitySize ? 2 : Self.readonlyLineSpacing)
                .foregroundStyle(Color.grey70).multilineTextAlignment(.center).frame(maxWidth: 500)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing12).padding(.horizontal, .spacing8)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay(RoundedRectangle(cornerRadius: .radius3).stroke(Color.grey30, lineWidth: 1))
        .padding(.bottom, .spacing12)
        .accessibilityIdentifier("shared-recipient-readonly")
    }

    @ViewBuilder private var gate: some View {
        ScrollView {
            VStack(spacing: 0) {
                Spacer(minLength: .spacing10)
                VStack(spacing: 0) {
                    switch model.state {
                    case .idle, .loading, .ready:
                        Image("openmates").renderingMode(.original).resizable().scaledToFit().frame(width: 96, height: 96)
                            .padding(.bottom, 18) // Route .openmates-logo margin-bottom.
                        gateDetail(AppStrings.sharedRecipientDecrypting)
                        ZStack {
                            Circle().stroke(Color.grey20, lineWidth: .spacing2)
                            Circle().trim(from: 0, to: 0.25).stroke(Color.buttonPrimary, lineWidth: .spacing2)
                                .rotationEffect(.degrees(spinning ? 360 : 0))
                        }.frame(width: .spacing24, height: .spacing24)
                            .onAppear { if !reduceMotion { withAnimation(.linear(duration: 1).repeatForever(autoreverses: false)) { spinning = true } } }
                            .accessibilityLabel(AppStrings.sharedRecipientDecrypting)
                            .accessibilityIdentifier("shared-recipient-loading")
                    case .passwordRequired, .failed(.invalidPassword):
                        gateSymbol(AppStrings.sharedRecipientLockSymbol)
                        gateTitle(AppStrings.sharedRecipientPasswordTitle)
                        gateDetail(AppStrings.sharedRecipientPasswordDetail)
                        passwordForm
                    case .failed(let error):
                        gateSymbol(AppStrings.sharedRecipientWarningSymbol)
                        gateTitle(AppStrings.sharedRecipientUnavailableTitle)
                        gateDetail(error == .expired ? AppStrings.sharedRecipientExpired : error == .shortLinkDisabled ? AppStrings.sharedRecipientShortDisabled : AppStrings.sharedRecipientUnavailableDetail)
                        gateButton(AppStrings.back, identifier: "shared-recipient-error-close", action: close)
                    }
                }
                .padding(.spacing20).frame(maxWidth: 500)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 2)
                Spacer(minLength: .spacing10)
            }
            .frame(maxWidth: .infinity).frame(minHeight: max(0, viewportHeight - .spacing20))
            .padding(.spacing10)
        }.background(Color.grey5).accessibilityIdentifier("shared-recipient-gate")
    }

    private func gateSymbol(_ value: String) -> some View {
        Text(value).font(.custom("Lexend Deca", size: 64)) // Route icon:64px/84px line box.
            .frame(height: 84).padding(.bottom, .spacing10)
    }
    private func gateTitle(_ value: String) -> some View {
        Text(value).font(.custom("Lexend Deca", size: 24).weight(.heavy)) // Route h1:24px/30px; no generated24pt font.
            .foregroundStyle(Color.grey100).multilineTextAlignment(.center).padding(.bottom, .spacing6)
    }
    private func gateDetail(_ value: String) -> some View {
        Text(value).font(.omP).foregroundStyle(Color.grey70).multilineTextAlignment(.center)
            .padding(.bottom, 18) // Route p margin-bottom:18px.
    }
    private var passwordForm: some View {
        VStack(spacing: .spacing6) {
            SecureField(AppStrings.sharedRecipientPasswordPlaceholder, text: $password)
                .textFieldStyle(.plain).font(.omP).padding(.spacing6)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .overlay(RoundedRectangle(cornerRadius: .radius3).stroke(passwordInvalid ? Color.error : Color.grey30, lineWidth: 2))
                .accessibilityLabel(AppStrings.sharedRecipientPasswordPlaceholder)
                .accessibilityIdentifier("shared-chat-password-input")
                .onSubmit(submitPassword)
                .onChange(of: password) { _, value in if value.count > 10 { password = String(value.prefix(10)) } }
            if passwordInvalid {
                Text(AppStrings.sharedRecipientInvalidPassword).font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("shared-chat-password-error")
            }
            gateButton(AppStrings.sharedRecipientAccess, identifier: "shared-chat-password-submit", action: submitPassword)
                .disabled(password.isEmpty && onPasswordSubmit == nil)
        }.padding(.top, .spacing12)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("shared-chat-password-form")
    }
    private var passwordInvalid: Bool { if case .failed(.invalidPassword) = model.state { return true }; return false }
    private func gateButton(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.omP.weight(.medium)).foregroundStyle(Color.fontButton)
                .padding(.horizontal, .spacing12)
                .frame(maxWidth: .infinity).frame(height: 41)
                .background(Color.buttonPrimary, in: RoundedRectangle(cornerRadius: .radius3))
        }.buttonStyle(.plain).accessibilityIdentifier(identifier)
    }

    private func fullscreen(_ context: SharedChatRecipientContext, embed: EmbedRecord) -> some View {
        let siblings = embedSiblings
        return VStack(spacing: 0) {
            HStack(spacing: .spacing3) {
                OMIconButton(icon: "back", label: AppStrings.back) { closeEmbed() }
                    .accessibilityIdentifier("shared-recipient-embed-back")
                Text(SharedChatRecipientEmbedNavigation.title(of: embed)).font(.omSmall.weight(.semibold)).lineLimit(1)
                Spacer(minLength: 0)
                if siblings.count > 1 {
                    OMIconButton(icon: "back", label: AppStrings.back) { moveEmbed(-1, siblings: siblings) }
                        .disabled(SharedChatRecipientEmbedNavigation.moved(from: embed.id, by: -1, in: siblings) == nil)
                        .accessibilityIdentifier("shared-recipient-embed-previous")
                    OMIconButton(icon: "back", label: AppStrings.next) { moveEmbed(1, siblings: siblings) }
                        .rotationEffect(.degrees(180))
                        .disabled(SharedChatRecipientEmbedNavigation.moved(from: embed.id, by: 1, in: siblings) == nil)
                        .accessibilityIdentifier("shared-recipient-embed-next")
                }
                OMIconButton(icon: "close", label: AppStrings.close) { embedPath = [] }
                    .accessibilityIdentifier("shared-recipient-embed-close")
            }.padding(.spacing6).background(Color.grey0)
            ScrollView {
                if embed.type == "image" {
                    // Recipient images are decorative renderer content: native
                    // preview/export is fenced off. Expose the actual content
                    // bounds and filename without announcing an owner action.
                    embedContent(context, embed: embed)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(SharedChatRecipientEmbedNavigation.title(of: embed))
                        .accessibilityIdentifier("shared-recipient-image-content")
                } else {
                    embedContent(context, embed: embed)
                }
            }
        }.background(Color.grey0).environment(\.embedChatID, nil)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("shared-recipient-embed-fullscreen")
    }

    private func embedContent(_ context: SharedChatRecipientContext, embed: EmbedRecord) -> some View {
        EmbedContentView(embed: embed, mode: .fullscreen, allEmbedRecords: context.embeds,
                         codePreviewActive: false, codeRunViewModel: nil, chatId: nil,
                         hasPIIMappings: false, piiMappings: [], isPIIRevealed: false,
                         onOpenEmbed: openChildEmbed)
            .id(SharedChatRecipientEmbedNavigation.renderIdentity(scopeID: model.presentationScopeID, embedID: embed.id))
            .frame(maxWidth: .infinity, alignment: .topLeading).padding(.spacing6)
    }

    private func openSettings(_ tab: ChatSettingsTab) { settingsTab = tab; showSettings = true }
    private func openEmbed(_ embed: EmbedRecord) {
        embedPath = [embed]
        embedSiblings = SharedChatRecipientEmbedNavigation.siblings(of: embed, in: model.context?.embeds ?? [:])
        hideSplitChat = false
    }
    private func openChildEmbed(_ embed: EmbedRecord) {
        embedPath.append(embed)
        embedSiblings = SharedChatRecipientEmbedNavigation.siblings(of: embed, in: model.context?.embeds ?? [:])
    }
    private func closeEmbed() {
        if embedPath.count > 1 {
            embedPath.removeLast()
            if let parent = embedPath.last { embedSiblings = SharedChatRecipientEmbedNavigation.siblings(of: parent, in: model.context?.embeds ?? [:]) }
        } else { embedPath = []; embedSiblings = [] }
    }
    private func moveEmbed(_ direction: Int, siblings: [EmbedRecord]) {
        guard let current = embedPath.last, let next = SharedChatRecipientEmbedNavigation.moved(from: current.id, by: direction, in: siblings) else { return }
        embedPath[embedPath.count - 1] = next
    }
    private func submitPassword() {
        guard !password.isEmpty || onPasswordSubmit != nil else { return }
        let submitted = password
        password = ""
        if let onPasswordSubmit { onPasswordSubmit(submitted) }
        else { model.open(url, password: submitted) }
    }
    private func clearPresentation() {
        recipientMediaContext?.cancel(); recipientMediaContext = nil
        password = ""; planning = .empty; planningLoaded = false; embedPath = []; embedSiblings = []; showSettings = false
    }
    private func close() { clearPresentation(); model.cancel(); onClose() }

    // Match CSS 14px/21px without adding 7px to the native font's own line height.
    private static let readonlyLineSpacing: CGFloat = {
        #if os(iOS)
        let natural = UIFont(name: "LexendDeca-Regular", size: 14)?.lineHeight ?? 17
        #elseif os(macOS)
        let font = NSFont(name: "LexendDeca-Regular", size: 14) ?? NSFont.systemFont(ofSize: 14)
        let natural = font.ascender - font.descender + font.leading
        #else
        let natural: CGFloat = 17
        #endif
        return max(0, 21 - natural)
    }()
}
