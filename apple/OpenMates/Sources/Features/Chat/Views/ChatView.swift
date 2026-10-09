// Single chat view — message list with input field and streaming responses.
// Supports block-level markdown rendering (code blocks, tables, blockquotes),
// inline embed previews, and fullscreen embed sheets. Advertises the current
// chat for Handoff so users can continue on another Apple device.
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.draft-only.lifecycle
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.open.local-first-coherent, chat-navigation.empty-new-chat.excluded
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.layout.responsive-parity, message-input.recording.lifecycle, message-input.embeds.gated-send, message-input.send.ownership, message-input.privacy-context, message-input.suggestions.contextual
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.layout.responsive-history, chats.streaming.progressive-presentation, chats.rendering.assistant-document-convergence, chats.surface.semantic-parity
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.delivery.idempotent-visible, apple-notifications.action.routing-coherent

// ─── Web source ─────────────────────────────────────────────────────
// MessageBubble:
//   Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte
//            frontend/packages/ui/src/components/ReadOnlyMessage.svelte
//            frontend/packages/ui/src/components/embeds/SourceQuoteBlock.svelte
//            frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte
//   CSS:     frontend/packages/ui/src/styles/chat.css
//            .mate-message-content  { background:var(--color-grey-0); border-radius:13px;
//              filter:drop-shadow(0 4px 4px rgba(0,0,0,.25)); padding:12px }
//            .user-message-content  { background:var(--color-grey-blue); color:var(--color-grey-100) }
//            .user-message-content::before / .mate-message-content::before  (SVG tail)
//            speechbubble.svg       { viewBox: 0 0 7 11 → rendered 12×20pt }
//            SourceQuoteBlock.svelte .source-quote-block (semantic verified source)
//
// inputBar:
//   Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//   Swift:   MessageComposerView -> NativeComposerEditorView editable surface
//   CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//            .message-field { background-color:var(--color-grey-blue); border-radius:24px;
//              min-height:100px; padding:0 0 60px 0;
//              box-shadow:0 4px 12px rgba(0,0,0,0.08); /* no border, no focus ring */ }
//   CSS:     frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
//            .send-button { color:white; padding:spacing-4 spacing-8; border-radius:radius-8;
//              height:40px; font-weight:500 }
//            .action-buttons { position:absolute; bottom:1rem; left:1rem; right:1rem }
//
// Specification: specifications/features/rules/specification.yml — rules.transparency.applied-set
// Specification: specifications/features/chats/specification.yml — chats.direction.reviewed-correction
// Specification: specifications/features/focus-modes/specification.yml — focus-modes.project-authoring-click
// messageList:
//   Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//            frontend/packages/ui/src/components/ActiveChat.svelte
//            frontend/packages/ui/src/components/HeaderActionMenu.svelte
//   Action:  frontend/packages/ui/src/actions/headerOverlayControls.ts
//   CSS:     frontend/packages/ui/src/styles/chat.css
//            .chat-history-container { padding:10px; overflow-y:auto }
//            .chat-history-content { max-width:1000px; margin:0 auto }
//            .message-wrapper user/assistant alignment mirrors under [dir="rtl"]
//
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import Foundation
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// ChatBannerView and ChatBannerState are defined in ChatBannerView.swift

/// One immutable presentation snapshot per transcript evaluation. Rows share
/// the same user mappings and restored embed graph, including citation children.
/// Building these values inside ForEach repeats the whole-chat work per row.
struct ChatTranscriptDisplayProjection {
    let piiMappings: [PIIMapping]
    let embedRecords: [String: EmbedRecord]

    init(messages: [Message], embedRecords: [String: EmbedRecord], isPIIRevealed: Bool,
         restoreEmbed: (EmbedRecord, [PIIMapping]) -> EmbedRecord = {
             PIIDetector.restorePII(in: $0, mappings: $1)
         }) {
        let mappings = Self.cumulativeMappings(in: messages)
        piiMappings = mappings
        self.embedRecords = isPIIRevealed
            ? embedRecords.mapValues { restoreEmbed($0, mappings) }
            : embedRecords
    }

    func embeds(for message: Message) -> [EmbedRecord] {
        message.embedRefs?.compactMap { embedRecords[$0.id] } ?? []
    }

    static func cumulativeMappings(in messages: [Message]) -> [PIIMapping] {
        var indexByPlaceholder: [String: Int] = [:]
        var mappings: [PIIMapping] = []
        for message in messages where message.role == .user {
            for mapping in message.piiMappings ?? [] {
                if let index = indexByPlaceholder[mapping.placeholder] {
                    mappings[index] = mapping
                } else {
                    indexByPlaceholder[mapping.placeholder] = mappings.count
                    mappings.append(mapping)
                }
            }
        }
        // Preserve first appearance order while retaining the latest user value.
        // Dictionary iteration can reorder an unchanged row/environment input
        // every time streaming or layout reevaluates the transcript projection.
        return mappings
    }
}

private enum ChatScrollSentinelEdge: Hashable {
    case top
    case bottom
}

private enum ComposerOverlay: Equatable {
    case location
    case sketch
    case recording
}

struct ComposerDeferredEmbedSnapshot {
    let embeds: [ComposerPendingEmbed]

    init?(document: ComposerDocumentV1, resolvedEmbeds: [String: ComposerPendingEmbed]) {
        let nodeIDs = document.nodes.filter { $0.kind == "embed" }.map(\.id)
        let embeds = nodeIDs.compactMap { resolvedEmbeds[$0] }
        guard embeds.count == nodeIDs.count else { return nil }
        self.embeds = embeds
    }
}

private struct ComposerDeferredSendContext {
    let excludedPIIIds: Set<String>
    let excludedPIIOriginals: Set<String>
    let broadcastToSiblings: Bool
    let owner: ComposerModelSendOwnership
    var embedSnapshot: ComposerDeferredEmbedSnapshot?
}

private enum ComposerDeferredSendError: Error {
    case missingContext
    case missingEmbed
    case transportUnavailable
    case sendFailed
}

private struct ChatScrollSentinelPreferenceKey: PreferenceKey {
    static let defaultValue: [ChatScrollSentinelEdge: CGFloat] = [:]

    static func reduce(value: inout [ChatScrollSentinelEdge: CGFloat], nextValue: () -> [ChatScrollSentinelEdge: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private enum ChatMoreLeadingAlignment: AlignmentID {
    static func defaultValue(in dimensions: ViewDimensions) -> CGFloat {
        dimensions[.leading]
    }
}

private extension HorizontalAlignment {
    static let chatMoreLeading = HorizontalAlignment(ChatMoreLeadingAlignment.self)
}

private struct ChatVisibleMessagePreferenceKey: PreferenceKey {
    static let defaultValue: Set<String> = []

    static func reduce(value: inout Set<String>, nextValue: () -> Set<String>) {
        value.formUnion(nextValue())
    }
}

/// Only changes that affect transcript controls belong in the observable projection.
struct ChatScrollBoundaries: Equatable {
    let isAtTop: Bool
    let isAtBottom: Bool
    let overlapsBanner: Bool?
}

/// Retains exact geometry without invalidating ChatView on every scroll pixel.
/// SwiftUI compares the returned projection before invoking the geometry action.
final class ChatTranscriptScrollState {
    private(set) var contentOffsetY: CGFloat = 0

    func record(contentOffsetY: CGFloat, isAtBottom: Bool, bannerHeight: CGFloat) -> ChatScrollBoundaries {
        self.contentOffsetY = max(0, contentOffsetY)
        return ChatScrollBoundaries(isAtTop: self.contentOffsetY <= 8,
                                    isAtBottom: isAtBottom,
                                    overlapsBanner: bannerOverlap(bannerHeight: bannerHeight))
    }

    func bannerOverlap(bannerHeight: CGFloat) -> Bool? {
        guard bannerHeight > 0 else { return nil }
        return contentOffsetY < max(0, bannerHeight - 64)
    }

    func reset() {
        contentOffsetY = 0
    }
}

/// Current systems report scroll visibility directly; older systems project row
/// geometry into membership before publishing a preference. Neither path sends
/// per-pixel message-frame dictionaries back through the whole transcript.
private struct ChatMessageVisibilityTracking: ViewModifier {
    let messageId: String
    let viewportHeight: CGFloat

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(iOS 18.0, macOS 15.0, *) {
            content
        } else {
            content.background {
                GeometryReader { geometry in
                    let frame = geometry.frame(in: .named("chat-scroll"))
                    Color.clear.preference(key: ChatVisibleMessagePreferenceKey.self,
                        value: frame.maxY > 0 && frame.minY < viewportHeight ? [messageId] : [])
                }
            }
        }
    }
}

private struct ChatTranscriptScrollTracking: ViewModifier {
    let scrollState: ChatTranscriptScrollState
    let bannerHeight: CGFloat
    let viewportHeight: CGFloat
    let onBoundariesChanged: (ChatScrollBoundaries) -> Void
    let onVisibleMessagesChanged: (Set<String>) -> Void
    let onUserScroll: () -> Void

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(iOS 18.0, macOS 15.0, *) {
            content
                .onScrollPhaseChange { _, phase in
                    if phase == .interacting || phase == .decelerating { onUserScroll() }
                }
                .onScrollGeometryChange(for: ChatScrollBoundaries.self) { geometry in
                    let contentOffsetY = max(0, geometry.contentOffset.y + geometry.contentInsets.top)
                    return scrollState.record(contentOffsetY: contentOffsetY,
                        isAtBottom: geometry.contentSize.height + geometry.contentInsets.bottom
                            - geometry.contentOffset.y <= geometry.containerSize.height + 8,
                        bannerHeight: bannerHeight)
                } action: { _, boundaries in
                    onBoundariesChanged(boundaries)
                }
                // A tiny positive fraction includes even the edge of a very tall
                // answer, while excluding completely offscreen targets (zero).
                .onScrollTargetVisibilityChange(idType: String.self, threshold: 0.000001) { ids in
                    onVisibleMessagesChanged(Set(ids))
                }
        } else {
            content
                .onPreferenceChange(ChatScrollSentinelPreferenceKey.self) { values in
                    let contentOffsetY = max(0, -(values[.top] ?? 0))
                    onBoundariesChanged(scrollState.record(contentOffsetY: contentOffsetY,
                        isAtBottom: values[.bottom].map { $0 <= viewportHeight + 8 } ?? false,
                        bannerHeight: bannerHeight))
                }
                .onPreferenceChange(ChatVisibleMessagePreferenceKey.self, perform: onVisibleMessagesChanged)
        }
    }
}

enum ChatResponsiveLayoutPolicy {
    /// Web `ChatMessage.svelte`: assistant messages use `.mobile-stacked`
    /// when the measured chat container width is <= 500 px.
    private static let assistantStackedBreakpoint: CGFloat = 500
    /// Web `ActiveChat.svelte`: input-adjacent New chat label hides at
    /// `@container chat-side (max-width: 550px)`.
    static let inlineNewChatCompact: CGFloat = 550
    static let contentMaximumWidth: CGFloat = 1_000
    static let inlineCompactComposerHeight: CGFloat = 48

    static func stacksAssistantIdentity(containerWidth: CGFloat) -> Bool {
        containerWidth <= assistantStackedBreakpoint
    }
}

private enum ChatHistoryLayoutMetric {
    static let wideWindowMinimumWidth: CGFloat = 900
    static let streamingUpdateDebounceMilliseconds = 50
    static let streamingFinalizationDelayMilliseconds = 250
}

private enum ChatMessageLayoutMetric {
    /// Web `chat.css`: `.chat-message { gap: 6px; }`.
    static let rowGap: CGFloat = 6
    /// Web `chat.css`: `.mobile-stacked .mate-profile { margin-bottom: 8px; }`.
    static let stackedAvatarGap: CGFloat = 8
    /// Web `chat.css`: `.message-align-right { max-width: calc(100% - 100px); }`.
    static let userDesktopReserve: CGFloat = 100
    /// Web `chat.css`: `.message-align-right.mobile-compact { max-width: calc(100% - 20px); }`.
    static let userCompactReserve: CGFloat = 20
    /// Web `chat.css`: `.message-align-left { max-width: calc(100% - 70px); }`.
    static let assistantDesktopReserve: CGFloat = 70
}

enum ChatFollowUpTapPolicy {
    enum Action: Equatable {
        case requestAuthentication
        case continueInNewChat
        case sendInCurrentChat
    }

    static func action(isPublic: Bool, isAuthenticated: Bool) -> Action {
        guard isPublic else { return .sendInCurrentChat }
        return isAuthenticated ? .continueInNewChat : .requestAuthentication
    }
}

enum ChatGeneratedHeaderPolicy {
    static func shouldShowLoading(
        title: String?,
        titleVersion: Int?,
        hasMessages: Bool,
        isStreaming: Bool
    ) -> Bool {
        let normalizedTitle = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalizedTitle.isEmpty && (titleVersion ?? 0) == 0 && hasMessages && isStreaming
    }
}

enum ChatAssistantIdentityPolicy {
    static func explicitDisplayName(_ senderName: String?) -> String? {
        guard let name = senderName?.trimmingCharacters(in: .whitespacesAndNewlines),
              !name.isEmpty,
              !["assistant", "ai"].contains(name.lowercased()) else { return nil }
        return name
    }
}

/// Mirrors the web processing-text gradient sweep while preserving a static
/// readable color when Reduce Motion is enabled.
private struct ProcessingTextShimmer: ViewModifier {
    @State private var phase: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .foregroundStyle(
                reduceMotion
                    ? AnyShapeStyle(Color.grey60)
                    : AnyShapeStyle(
                        LinearGradient(
                            stops: [
                                .init(color: Color.grey60, location: 0),
                                .init(color: Color.grey60, location: 0.4),
                                .init(color: Color.grey40, location: 0.5),
                                .init(color: Color.grey60, location: 0.6),
                                .init(color: Color.grey60, location: 1)
                            ],
                            startPoint: UnitPoint(x: phase - 1, y: 0.5),
                            endPoint: UnitPoint(x: phase, y: 0.5)
                        )
                    )
            )
            .onAppear {
                guard !reduceMotion else { return }
                phase = 0
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    phase = 2
                }
            }
    }
}

/// Composer status follows the web's current-turn mate selection. A chat's
/// stored category can describe an earlier turn, so it is never used here.
@MainActor
enum ChatTypingPresentation {
    static func stageText(for lifecycle: ChatStreamingLifecycleState) -> String {
        switch lifecycle.phase {
        case .sending:
            return AppStrings.sendingMessage
        case .processing:
            if lifecycle.preprocessingStep == "model_selected" {
                if let mateName = lifecycle.selectedMateName, !mateName.isEmpty {
                    return AppStrings.mateIsTyping(mateName)
                }
                if let mate = CanonicalSettingsMateCatalog.mate(id: lifecycle.selectedMateCategory) {
                    return AppStrings.mateIsTyping(mate.name)
                }
            }
            return lifecycle.preprocessingStep
                .map(ProcessingDetailsView.ProcessingStep.stageLabel(for:))
                ?? AppStrings.selectingMateAndModel
        case .thinking:
            guard let mate = CanonicalSettingsMateCatalog.mate(id: lifecycle.selectedMateCategory) else {
                return AppStrings.thinkingHeaderStreaming
            }
            return AppStrings.mateIsThinking(mate.name)
        case .typing, .streaming:
            guard let mate = CanonicalSettingsMateCatalog.mate(id: lifecycle.selectedMateCategory) else {
                return AppStrings.selectingMateAndModel
            }
            return AppStrings.mateIsTyping(mate.name)
        case .queued:
            return lifecycle.queuedMessageText ?? AppStrings.messageQueued
        case .cancelling, .idle, .completed, .error:
            return AppStrings.aiResponding
        }
    }
}

/// Clear only the accepted snapshot, never edits made during an awaited send.
enum ComposerAcceptedSendSnapshotPolicy {
    static func shouldClear(accepted: Bool, submittedRevision: Int, currentRevision: Int,
                            submittedDocument: ComposerDocumentV1, currentDocument: ComposerDocumentV1) -> Bool {
        accepted && submittedRevision == currentRevision && submittedDocument == currentDocument
    }
}

struct ChatView: View {
    #if DEBUG
    var isolatedHistory = false
    #endif
    @StateObject private var modelHost = NativeComposerModelHost()
    let chatId: String
    var projectReviewOwnerID: UUID? = nil
    /// Optional gradient banner state. Provide `.loaded` for demo/example chats;
    /// omit (nil) for regular user chats where no banner should appear.
    var bannerState: ChatBannerState? = nil
    var bannerCreatedAt: Date? = nil
    /// Synced user chat data from the app shell. Public/example chats still load
    /// from PublicChatContent, so both paths share this one ChatView + ViewModel.
    var initialChat: Chat? = nil
    var initialMessages: [Message] = []
    /// The shell releases history loading after the opening slide completes.
    /// Header metadata is available immediately through initialChat.
    var historyPresentationReady = true
    var initialEmbeds: [EmbedRecord] = []
    var wsManager: WebSocketManager? = nil
    var chatStore: ChatStore? = nil
    var inputFocusRequest = 0
    var cameraCaptureRequest = 0
    var prepareComposerSearchMetadata: () async -> Void = {}
    var searchTarget: ChatSearchSelection? = nil
    var initialEmbedId: String? = nil
    /// Mirrors web `.chat-container.menu-open`; used by the banner header to
    /// collapse from viewport-responsive height to the fixed adjacent-panel height.
    var isSettingsOpen = false
    var onShareChat: (() -> Void)? = nil
    var onOpenForkSettings: ((NativeMessageForkContext) -> Void)? = nil
    var onOpenEmbedShareSettings: ((EmbedShareSettingsTarget) -> Void)? = nil
    var onOpenChatSettings: (() -> Void)? = nil
    var onCloseChat: (() -> Void)? = nil
    /// Navigation callbacks for prev/next chat arrows on the banner.
    var onPreviousChat: (() -> Void)? = nil
    var onNextChat: (() -> Void)? = nil
    /// Mirrors web `demoChatSelected`: embedded public chat cards ask the app shell
    /// to select and load a different bundled demo/example chat.
    var onOpenPublicChat: ((String) -> Void)? = nil
    /// Opens another user chat in the owning app shell.
    var onOpenChat: ((String) -> Void)? = nil
    /// Opens the new-chat surface in the owning app shell window.
    var onNewChat: (() -> Void)? = nil
    /// Opens the app-owned issue report settings pane with an optional prefill.
    var onReportIssue: ((ReportIssuePrefill) -> Void)? = nil
    /// Opens the selected mate/model detail in the app-owned settings panel.
    var onOpenMateSettings: ((String) -> Void)? = nil
    var onOpenModelSettings: ((String) -> Void)? = nil
    /// Sends the last visible message ID to the app shell for cross-device sync.
    var onScrollPositionChanged: ((String) -> Void)? = nil
    /// Reports decrypted, final messages that are actually in the visible transcript.
    var onFinalMessagesVisible: ((Set<String>) async -> Set<String>)? = nil
    /// Called after an external chat/embed deep link has opened the fullscreen embed route.
    var onInitialEmbedOpened: ((String) -> Void)? = nil

    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var handoffManager = HandoffManager()
    @StateObject private var piiPrivacySettingsStore = PIIPrivacySettingsStore.shared
    @StateObject private var enhancedPIIModelController = EnhancedPIIModelDownloadController.shared
    @StateObject private var enhancedPIIRecommendationStore = EnhancedPIIRecommendationStore.shared
    @StateObject private var composerSession = NativeComposerSession()
    @ObservedObject private var draftService = DraftService.shared
    @ObservedObject private var projectReviews = ProjectWorkspaceReviewRuntime.shared
    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.workspacePaneIsVisible) private var parentPaneVisible
    private var transcriptIsVisible: Bool { parentPaneVisible && (!showEmbedFullscreen || (chatWorkspaceWidth >= 1024 && !hideSplitChat)) }
    @State private var chatWorkspaceWidth: CGFloat = 0
    @State private var hideSplitChat = false
    @State private var loadedRouteID: String?
    @State private var selectedEmbed: EmbedRecord?
    @State private var sourceQuoteTarget: SourceQuoteTarget?
    @State private var fullscreenPreviousEmbeds: [EmbedRecord] = []
    @State private var showEmbedFullscreen = false
    @State private var openedInitialEmbedId: String?
    @State private var showReminder = false
    @State private var chatHeaderMoreOpen = false
    @State private var chatHeaderActionsOverlapBanner = true
    @State private var chatBannerHeight: CGFloat = 0
    @State private var transcriptScrollState = ChatTranscriptScrollState()
    @State private var isPIIRevealed = false
    @State private var showAttachmentMenu = false
    @State private var showCameraCapture = false
    @State private var composerOverlay: ComposerOverlay?
    @State private var isComposerExpanded = false
    @State private var micPermissionState: MicPermissionState = .unknown
    @State private var recordHintVisible = false
    @State private var recordDragOffsetX: CGFloat = 0
    @State private var recordAttemptActive = false
    @State private var recordStartedFromKeyboard = false
    @State private var recordStartTask: Task<Void, Never>?
    @State private var recordHintTask: Task<Void, Never>?
    @State private var recordingUploadTasks: [String: Task<Void, Never>] = [:]
    @State private var recordingTemporaryFiles: [String: URL] = [:]
    @State private var detectedPIIMatches: [PIIMatch] = []
    @State private var piiExclusions: Set<String> = []
    @StateObject private var piiDetectionCoordinator = ComposerPIIDetectionCoordinator()
    @ObservedObject private var piiDetectionService = EnhancedPIIDetectionService.shared
    @State private var piiExcludedValues = Set<String>()
    @State private var isVerifyingPIISend = false
    @State private var composerSearchRecentlyFocused = false
    @State private var composerSearchFocusTask: Task<Void, Never>?
    @State private var mentionQuery: String?
    @State private var actionMessage: Message?
    @ObservedObject private var messageHighlights = HighlightsManager.shared
    @State private var messageForkContext: NativeMessageForkContext?
    @State private var editingContextMessage: Message?
    @State private var preEditDraft: String?
    @State private var compressedMessageBoundary: Int?
    @State private var selectedMessageText: MessageTextSelectionSnapshot?
    @State private var selectionHideTask: Task<Void, Never>?
    @State private var nativeMessageSelectionTarget: MessageTextSelectionTarget?
    @State private var confirmingMessageDeletionID: String?
    @State private var highlightCommentID: String?
    @State private var highlightComment = ""
    @State private var explanationChatID: String?
    @State private var chatViewportHeight: CGFloat = 0
    @State private var chatContainerWidth: CGFloat = 0
    @State private var historyNavigationTask: Task<Void, Never>?
    @State private var historyNavigationID = UUID()
    @State private var completedSearchTargetID: String?
    @State private var userHasScrolledHistory = false
    @State private var isAtTop = true
    @State private var isAtBottom = false
    @State private var followsStreamingResponse = false
    @State private var hasRestoredInitialScroll = false
    @State private var isRestoringScroll = false
    @State private var handledInputFocusRequest = 0
    @State private var handledCameraCaptureRequest = 0
    @State private var lastReportedVisibleMessageId: String?
    @State private var latestVisibleMessageIds: Set<String> = []
    @State private var reportedVisibleReceiptIds: Set<String> = []
    @State private var pendingVisibleReceiptIds: Set<String> = []
    @State private var inFlightVisibleReceiptIds: Set<String> = []
    @State private var visibleReceiptAttemptID = UUID()
    @State private var assistantFeedbackMessageId: String?
    @State private var selectedAssistantRating: Int?
    @State private var assistantFeedbackSubmitted = false
    @State private var scrollPositionDebounceTask: Task<Void, Never>?
    @State private var streamingScrollTask: Task<Void, Never>?
    @State private var draftSaveTask: Task<Void, Never>?
    #if DEBUG
    @State private var attachmentDraftSavedRevision = -1
    #endif
    @State private var suppressNextDraftSave = false
    @State private var broadcastToSiblingSubChats = false
    @StateObject private var focusModeManager = FocusModeManager()
    @StateObject private var composerRecorder = VoiceRecorder()
    @State private var activeRecordingRealtimeSession: AudioRecordingRealtimeSession?
    @State private var recordingLiveTranscript = ""
    @State private var recordingRealtimeConnecting = false
    @StateObject private var pendingUploads = PendingUploadStore.shared
    @State private var composerEmbedLifecycle = ComposerEmbedLifecycle()
    @State private var composerPendingSendCoordinator = ComposerPendingSendCoordinator()
    @State private var deferredComposerSendContexts: [String: ComposerDeferredSendContext] = [:]
    @State private var deferredComposerSendNodeIDs: [String: Set<String>] = [:]
    @State private var composerSearchEmbedRecords: [String: EmbedRecord] = [:]
    @State private var resolvedComposerEmbeds: [String: ComposerPendingEmbed] = [:]
    @State private var deferredComposerSendRevisions: Set<Int> = []
    @State private var stopButtonPulsing = false
    @State private var deferredSocketConnectedEpoch = 0
    @State private var isInputFocused = false
    #if DEBUG
    @State private var composerSendFixturePhases: [String] = ["idle"]
    #endif
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.layoutDirection) private var layoutDirection
    @Environment(\.scenePhase) private var scenePhase

    private var messageText: String {
        get { composerSession.canonicalMarkdown }
        nonmutating set { composerSession.replaceMarkdown(newValue) }
    }

    private var composerHasEmbed: Bool {
        composerSession.controller.document.nodes.contains { node in
            node.kind == "embed" && node.status != AppleComposerEmbedLifecycleState.cancelled.rawValue
        }
    }

    /// True for demo/intro/legal chats that show "New chat" CTA instead of input field
    private var isDemoOrLegalChat: Bool {
        chatId.hasPrefix("demo-") || chatId.hasPrefix("legal-") || chatId.hasPrefix("announcements-")
    }

    private var isExampleChat: Bool {
        chatId.hasPrefix("example-")
    }

    private var latestAssistantMessageId: String? {
        viewModel.messages.last { message in
            message.role == .assistant && !(message.content ?? "").isEmpty
        }?.id
    }

    private var showAssistantFeedback: Bool {
        latestAssistantMessageId != nil && !viewModel.isStreaming
    }

    private var isStreamingPresentationActive: Bool {
        viewModel.isStreaming || isUITestStreamingPresentationEnabled
    }

    private var streamingStageText: String {
        ChatTypingPresentation.stageText(for: viewModel.streamingLifecycle)
    }

    var body: some View {
        #if DEBUG
        if isolatedHistory {
            GeometryReader { geometry in
                ZStack {
                    ChatEmbedWorkspace(embedOpen: showEmbedFullscreen, chatHidden: $hideSplitChat, onLayout: { width, transcriptWidth in
                        chatWorkspaceWidth = width; chatContainerWidth = transcriptWidth
                    }) {
                        messageList
                    } embed: {
                        if let embed = selectedEmbed { embedFullscreenSheet(for: embed) }
                    }
                    if let actionMessage { messageActionsOverlay(for: actionMessage) }
                }
                .onAppear { chatViewportHeight = geometry.size.height; chatContainerWidth = showEmbedFullscreen && geometry.size.width >= 1024 ? 400 : geometry.size.width }
                .onChange(of: geometry.size) { _, size in chatViewportHeight = size.height; chatContainerWidth = showEmbedFullscreen && size.width >= 1024 ? 400 : size.width }
            }.task(id: chatId) {
                if let initialChat { viewModel.seedIsolatedHistory(chat: initialChat, messages: initialMessages, embeds: initialEmbeds) }
            }
        } else { normalLifecycleBody }
        #else
        normalLifecycleBody
        #endif
    }

    private var normalLifecycleBody: some View {
        lifecycleChatView
            .onChange(of: transcriptIsVisible) { _, visible in
                if !visible {
                    scrollPositionDebounceTask?.cancel()
                    scrollPositionDebounceTask = nil
                    // A skipped pending write must not suppress the next real
                    // visible scroll observation after this pane is restored.
                    lastReportedVisibleMessageId = nil
                }
            }
            #if DEBUG
            .overlay(alignment: .topLeading) {
                if ProcessInfo.processInfo.arguments.contains("--ui-test-expose-chat-ids"), let chatStore {
                    ChatRecoveryStateProbe(
                        store: chatStore, chatId: chatId,
                        renderedMessages: viewModel.messages,
                        renderedEmbeds: viewModel.embedRecords
                    )
                }
            }
            #endif
    }

    private var baseChatView: some View {
        GeometryReader { geo in
            ZStack {
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-test-nav-draft-attachments") {
                    Text("nodes=\(composerSession.controller.document.nodes.filter { $0.kind == "embed" }.count);resolved=\(resolvedComposerEmbeds.count);cached=\(resolvedComposerEmbeds.values.filter { $0.localData != nil }.count);revision=\(composerSession.revision);saved=\(attachmentDraftSavedRevision)")
                        .font(.system(size: 1)).opacity(0.01).allowsHitTesting(false)
                        .accessibilityIdentifier("composer-draft-attachment-probe")
                }
                if ProcessInfo.processInfo.arguments.contains("--ui-test-window-drafts"),
                   ProcessInfo.processInfo.arguments.contains("--ui-test-nav-callback-diagnostics") {
                    Text("chat-id=\(chatId);loaded-route=\(loadedRouteID ?? "nil");length=\(composerSession.canonicalMarkdown.count);revision=\(composerSession.revision)")
                        .font(.system(size: 1)).opacity(0.01).allowsHitTesting(false)
                        .accessibilityIdentifier("chat-draft-restore-probe")
                }
                Color.clear
                    .accessibilityElement()
                    .accessibilityLabel(AppStrings.chat)
                    .accessibilityIdentifier("chat-view-\(chatId)")
                    .allowsHitTesting(false)
                #endif

                ChatEmbedWorkspace(embedOpen: showEmbedFullscreen, chatHidden: $hideSplitChat, onLayout: { width, transcriptWidth in
                        chatWorkspaceWidth = width; chatContainerWidth = transcriptWidth
                    }) {
                VStack(spacing: 0) {
                    VStack(spacing: 0) {
                        if let chat = presentedChat, !isDraftOnlyChat(chat), bannerState == nil {
                            if effectiveBannerState == nil {
                                chatTopBar
                            }
                        }

                        if IncognitoChatSession.isIncognitoChatId(chatId) {
                            incognitoSessionBanner
                        }

                        AssistantSpeechPlayerHostView(chatID: chatId, viewportWidth: chatContainerWidth)

                        messageList
                            .simultaneousGesture(
                                TapGesture().onEnded {
                                    dismissInputIfNeeded()
                                }
                            )

                        subChatLifecyclePanel

                        returnToParentButton

                        if isStreamingPresentationActive {
                            streamingBanner
                        }

                    }
                    .workspacePromptBackground(active: isInputFocused || isComposerExpanded,
                        identifier: "chat-composer-workspace-backdrop",
                        activeOpacity: !displayedChatMessages.isEmpty || (presentedChat?.messagesV ?? 0) > 0 ? 0.35 : 0,
                        onDismiss: dismissInputIfNeeded)

                    // Web: intro/legal chats show a full-width "New chat" CTA instead of the input field
                    Group {
                        if isDemoOrLegalChat {
                            newChatCTA
                        } else if isExampleChat || !displayedChatMessages.isEmpty || (presentedChat?.messagesV ?? 0) > 0 {
                            exampleChatInputRow
                        } else {
                            inputBar
                        }
                    }
                    .overlay(alignment: .top) {
                        FocusModePill(focusModeManager: focusModeManager) { _ in
                            Task { await viewModel.deactivateActiveFocusMode() }
                        }
                        .padding(.horizontal, 12)
                        .offset(y: -30)
                    }
                    .padding(.top, focusModeManager.activeFocusMode == nil ? 0 : 15)
                }
                .background(Color.grey20)
                } embed: {
                    if let embed = selectedEmbed { embedFullscreenSheet(for: embed) }
                }


                if showReminder {
                    customOverlay(title: AppStrings.setReminder, isPresented: $showReminder) {
                        ReminderCreationView(chatId: chatId)
                    }
                }


                if let actionMessage {
                    messageActionsOverlay(for: actionMessage)
                } else if let selection = selectedMessageText,
                          let message = displayedChatMessages.first(where: { $0.id == selection.messageID }) {
                    MessageSelectionDismissBackdrop(selection: selection, onDismiss: dismissMessageTextSelection)
                    MessageSelectionToolbar(canExplain: messageSelectionPolicy(for: message).canExplain,
                        canHighlight: messageSelectionPolicy(for: message).canHighlight,
                        onCopy: { copyMessage(message) },
                        onMore: { actionMessage = message },
                        onHighlight: { commitMessageHighlight(selection, comment: false) },
                        onComment: { commitMessageHighlight(selection, comment: true) },
                        onExplain: { explainSelectedText(selection, message: message) })
                        .frame(width: min(340, max(1, geo.size.width - 16)))
                        .position(selectionToolbarPosition(selection, geometry: geo))
                }
                if let id = highlightCommentID {
                    Color.black.opacity(0.28).ignoresSafeArea().onTapGesture { highlightCommentID = nil }
                    MessageHighlightCommentEditor(comment: $highlightComment, onSave: {
                        let comment = highlightComment
                        Task { do { try await messageHighlights.updateComment(id: id, comment: comment); highlightCommentID = nil }
                            catch { ToastManager.shared.show(AppStrings.error, type: .error) } }
                    }, onCancel: { highlightCommentID = nil }).frame(maxWidth: 340)
                }
                if let id = explanationChatID {
                    VStack { Spacer(); Button(AppStrings.localized("chats.explain_in_new_chat.open_action.text")) {
                        explanationChatID = nil; onOpenChat?(id)
                    }.buttonStyle(OMSecondaryButtonStyle()).accessibilityIdentifier("message-explanation-open") }
                    .padding(.spacing6)
                }
            }
            .onAppear {
                chatViewportHeight = geo.size.height
                chatContainerWidth = showEmbedFullscreen && geo.size.width >= 1024 ? 400 : geo.size.width
            }
            .onChange(of: geo.size.height) { _, height in
                chatViewportHeight = height
            }
            .onChange(of: geo.size.width) { _, width in
                chatContainerWidth = showEmbedFullscreen && width >= 1024 ? 400 : width
            }
        }
    }

    private func receiveCompressionCheckpoint(_ note: Notification) {
        guard let receipt = ChatCompressionNotificationReceipt(note) else { return }
        let socket = wsManager ?? AppSessionCoordinator.shared.webSocketManager
        let expectedChatID = chatId
        let expectedTransport = socket.transportGeneration
        guard receipt.matches(scope: OfflineStore.shared.scopeGeneration, transport: expectedTransport) else { return }
        Task { @MainActor in
            guard let fields = try? await receipt.fields(),
                  chatId == expectedChatID,
                  socket.transportGeneration == expectedTransport,
                  receipt.matches(scope: OfflineStore.shared.scopeGeneration, transport: socket.transportGeneration),
                  RememberMessageDraft.latestBoundary(fields.fields, chatID: expectedChatID) != nil,
                  let boundary = OfflineStore.shared.compressionBoundary(chatID: expectedChatID) else { return }
            compressedMessageBoundary = max(compressedMessageBoundary ?? boundary, boundary)
        }
    }

    private var decoratedChatView: some View {
        baseChatView
        .task(id: messageSelectionRuntimeIdentity) {
            selectedMessageText = nil; nativeMessageSelectionTarget = nil; actionMessage = nil; highlightCommentID = nil; explanationChatID = nil
            await messageHighlights.configure(messageSelectionRuntime)
            await messageHighlights.flush()
        }
        .overlay {
            OMSheet(isPresented: Binding(get: { messageForkContext != nil }, set: { if !$0 { messageForkContext = nil } }),
                title: AppStrings.localized("chats.fork.title.text")) {
                if let context = messageForkContext { NativeMessageForkPanel(context: context, onClose: { messageForkContext = nil }) }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsSyncEvent)) { note in
            receiveCompressionCheckpoint(note)
        }
        .onReceive(NotificationCenter.default.publisher(for: .compressionCheckpointPersisted)) { note in
            receiveCompressionCheckpoint(note)
        }
        .onReceive(NotificationCenter.default.publisher(for: .chatKeyMaterialAvailable)) { _ in
            Task { await messageHighlights.restore() }
        }
        .onReceive((wsManager ?? AppSessionCoordinator.shared.webSocketManager).$connectionState) { state in
            if state == .connected { Task { await messageHighlights.flush() } }
        }
        .onChange(of: actionMessage?.id) { _, _ in confirmingMessageDeletionID = nil }
        .onChange(of: chatId) { _, _ in selectedMessageText = nil; nativeMessageSelectionTarget = nil; actionMessage = nil; highlightCommentID = nil; explanationChatID = nil; editingContextMessage = nil; preEditDraft = nil; compressedMessageBoundary = nil; selectionHideTask?.cancel() }
        .onDisappear { selectionHideTask?.cancel() }
        .overlay {
            if viewModel.streamingLifecycle.isActive {
                ChatProcessingRing()
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
        }
        .chatKeyboardShortcuts(
            onStopStreaming: { viewModel.stopStreaming() },
            onToggleIncognito: {
                // Incognito toggle is posted as a notification — handled by MainAppView
                // which owns the IncognitoManager instance
                NotificationCenter.default.post(name: .toggleIncognito, object: nil)
            }
        )
        .environment(\.embedShareSettingsAction, onOpenEmbedShareSettings.map { EmbedShareSettingsAction(open: $0) })
        .onKeyPress(.init("m"), phases: .down) { press in
            handleKeyboardRecordShortcut(press)
        }
        .onKeyPress(.return, phases: .down) { press in
            handleKeyboardRecordEnter(press)
        }
        .onKeyPress(.escape, phases: .down) { _ in
            handleKeyboardRecordEscape()
        }
        #if os(iOS)
        .fullScreenCover(isPresented: $showCameraCapture) {
            CameraCaptureView(
                onCapture: { data, filename in
                    showCameraCapture = false
                    enqueueAttachmentUpload(data: data, filename: filename)
                },
                onCancel: { showCameraCapture = false }
            )
            .ignoresSafeArea()
        }
        #endif
    }

    private var lifecycleChatView: some View {
        AnyView(lifecycleWithoutFocusView)
        .onChange(of: activeFocusId) { _, focusId in
            handleActiveFocusChange(focusId)
        }
    }

    // Keep lifecycle modifiers in the same order while giving Swift smaller
    // expressions to type-check. Each property retains its concrete view type.
    private var appearanceLifecycleChatView: some View {
        decoratedChatView
        .onAppear(perform: handleInitialAppear)
        .onChange(of: isInputFocused) { _, focused in
            if focused, authManager.state == .authenticated,
               !IncognitoChatSession.isIncognitoChatId(chatId), !WelcomeScreenState.isPublicChat(chatId) {
                OfflineAIModelPack.shared.offerIfNeeded()
            }
        }
        .onChange(of: inputFocusRequest) { _, _ in
            if let mention = SettingsComposerHandoff.consume() {
                messageText = SettingsComposerHandoff.appending(mention: mention, to: messageText)
            }
            handleInputFocusRequestChange()
        }
        .onChange(of: cameraCaptureRequest) { _, _ in
            handleCameraCaptureRequestChange()
        }
        .task(id: "\(chatId):\(historyPresentationReady)") {
            guard historyPresentationReady else { return }
            await handleChatTask()
        }
        .task(id: authManager.currentUser?.id) {
            // Account preferences must not hold up the selected chat's local
            // header or history while their independent request completes.
            await ApplePrivacySettingsService.shared.load()
        }
        .task(id: modelHost.savedContext(chatID: chatId)) {
            await modelHost.activate(modelHost.savedContext(chatID: chatId))
        }
        .onDisappear(perform: handleChatLifecycleDisappear)
        .onChange(of: viewModel.forkedChatId) {
            handleForkedChatChange()
        }
    }

    private var syncLifecycleChatView: some View {
        appearanceLifecycleChatView
        .onChange(of: latestAssistantMessageId) { _, newMessageId in
            guard assistantFeedbackMessageId != newMessageId else { return }
            assistantFeedbackMessageId = newMessageId
            selectedAssistantRating = nil
            assistantFeedbackSubmitted = false
        }
        .onChange(of: initialMessageSyncSignature) { _, _ in
            Task {
                await viewModel.applySynced(chat: initialChat, messages: initialMessages, embeds: initialEmbeds)
                await catchUpNotificationCompletion()
            }
        }
        .onReceive(PushNotificationManager.shared.$completionCatchUpIntent) { intent in
            guard intent?.chatID == chatId else { return }
            Task { @MainActor in await catchUpNotificationCompletion() }
        }
        .onChange(of: initialEmbedSyncSignature) { _, _ in
            Task {
                await viewModel.applySyncedEmbeds(initialEmbeds)
                openInitialEmbedIfReady()
            }
        }
        .onChange(of: initialEmbedId) { _, _ in
            openedInitialEmbedId = nil
            openInitialEmbedIfReady()
        }
        .onChange(of: embedRecordIdsSignature) { _, _ in
            openInitialEmbedIfReady()
        }
    }

    private var lifecycleWithoutFocusView: some View {
        syncLifecycleChatView
        .onChange(of: messageText) { _, newValue in
            updatePIIMatches(for: newValue)
            updateMentionQuery(for: newValue)
        }
        .onChange(of: composerSession.revision) { _, _ in
            if suppressNextDraftSave {
                suppressNextDraftSave = false
            } else {
                scheduleEncryptedDraftSave()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .composerDraftDidChange)) { notification in
            guard notification.userInfo?["chatId"] as? String == chatId,
                  notification.userInfo?["scopeGeneration"] as? UUID == OfflineStore.shared.scopeGeneration else { return }
            if closeRemovedDraftIfNeeded(notification) { return }
            guard notification.userInfo?["reloadComposer"] as? Bool != false else { return }
            Task {
                await applyInboundDraft()
                // A remote deletion clears the restored document first. Recheck
                // the live revision/content before leaving the deleted route.
                _ = closeRemovedDraftIfNeeded(notification)
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { flushEncryptedDraft() }
            else {
                visibleReceiptAttemptID = UUID()
                inFlightVisibleReceiptIds = []
                reportFinalVisibleMessages(latestVisibleMessageIds)
            }
        }
        .onReceive(Timer.publish(every: 25, on: .main, in: .common).autoconnect()) { _ in
            reportFinalVisibleMessages(latestVisibleMessageIds)
        }
        .onDisappear(perform: handleDisappear)
        .onChange(of: piiPrivacySettingsStore.settings) { _, _ in
            updatePIIMatches(for: messageText)
        }
        .onAppear { updatePIIMatches(for: messageText) }
        .onChange(of: scenePhase) { _, phase in
            updatePIIMatches(for: messageText)
            if phase == .active { Task {
                await retryDeferredComposerSendsAfterReconnect()
                await catchUpNotificationCompletion(renewAttempts: true)
            } }
        }
        .onChange(of: parentPaneVisible) { _, visible in
            updatePIIMatches(for: messageText)
            if visible { Task { await retryDeferredComposerSendsAfterReconnect() } }
        }
        .onChange(of: chatId) { _, _ in resetComposerPIIDetection(); updatePIIMatches(for: messageText) }
        .onChange(of: authManager.currentUser?.id) { _, _ in resetComposerPIIDetection(); updatePIIMatches(for: messageText) }
        .onReceive(piiDetectionCoordinator.$publication) { applyPIIPublication($0) }
        .onDisappear { resetComposerPIIDetection() }
        .onReceive(NotificationCenter.default.publisher(for: .pendingDeferredSendRequested)) { notification in
            handleComposerDeferredSend(notification)
        }
        .onReceive((wsManager ?? AppSessionCoordinator.shared.webSocketManager).$connectionState) { state in
            guard state == .connected else { return }
            visibleReceiptAttemptID = UUID()
            inFlightVisibleReceiptIds = []
            reportFinalVisibleMessages(latestVisibleMessageIds)
            deferredSocketConnectedEpoch += 1
            Task { @MainActor in
                await retryDeferredComposerSendsAfterReconnect()
                await catchUpNotificationCompletion(renewAttempts: true)
            }
        }
    }

    private var initialMessageSyncSignature: String {
        [
            initialChat?.id ?? "",
            initialChat?.updatedAt ?? "",
            initialChat?.displayTitle ?? "",
            initialChat?.category ?? "",
            initialChat?.icon ?? "",
            initialChat?.chatSummary ?? "",
            String(chatStore?.chat(for: chatId)?.messagesV ?? initialChat?.messagesV ?? 0),
            String(chatStore?.contentRevision(for: chatId) ?? 0),
            String(initialMessages.count),
            initialMessages.last?.id ?? ""
        ].joined(separator: "|")
    }

    private var initialEmbedSyncSignature: String {
        ChatEmbedSyncSignature.make(chatId: initialChat?.id, embeds: initialEmbeds)
    }

    private var embedRecordIdsSignature: String {
        viewModel.embedRecords.keys.sorted().joined(separator: "|")
    }

    private var activeFocusId: String? {
        viewModel.chat?.activeFocusId
    }

    private func handleDisappear() {
        draftSaveTask?.cancel()
        flushEncryptedDraft()
    }

    private func handleInitialAppear() {
        applyUITestRecordingOverlayIfNeeded()
        applyInputFocusRequestIfNeeded()
        applyCameraCaptureRequestIfNeeded()
    }

    private func handleInputFocusRequestChange() {
        if inputFocusRequest == 0 {
            handledInputFocusRequest = 0
            isInputFocused = false
        }
        applyInputFocusRequestIfNeeded()
    }

    private func handleCameraCaptureRequestChange() {
        applyCameraCaptureRequestIfNeeded()
    }

    private func catchUpNotificationCompletion(renewAttempts: Bool = false) async {
        let notifications = PushNotificationManager.shared
        guard historyPresentationReady, let intent = notifications.completionCatchUpIntent(for: chatId),
              intent.chatID == chatId, intent.isCurrent else { return }
        if await viewModel.refreshNotificationCompletion(intent, renewAttempts: renewAttempts), intent.isCurrent {
            notifications.finishCompletionCatchUp(intent.id)
        }
    }

    private func handleChatTask() async {
        if let loadedRouteID, loadedRouteID != chatId {
            // ChatView retains its identity across selection; overlays belong to
            // the old chat, while transcript restoration belongs to each record.
            fullscreenPreviousEmbeds = []
            sourceQuoteTarget = nil
            selectedEmbed = nil
            showEmbedFullscreen = false
            hideSplitChat = false
            openedInitialEmbedId = nil
            if inputFocusRequest == 0 { isInputFocused = false }
            cancelRecordAttempt()
        }
        loadedRouteID = chatId
        draftSaveTask?.cancel()
        await invalidateDeferredComposerSends()
        resetComposerForChatLoad()
        isPIIRevealed = false
        viewModel.configure(wsManager: wsManager, chatStore: chatStore)
        await viewModel.loadChat(id: chatId, initialChat: initialChat, initialMessages: initialMessages, initialEmbeds: initialEmbeds)
        await catchUpNotificationCompletion()
        openInitialEmbedIfReady()
        await restoreEncryptedDraft()
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-seed-pending-composer-embed") {
            if let embed = viewModel.seedUITestPendingComposerEmbed() {
                insertResolvedUITestEmbed(embed)
            }
        }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-seed-recording-raw-pending") {
            seedUITestRecordingRawPending()
        }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay") {
            micPermissionState = .granted
            composerOverlay = .recording
            isInputFocused = false
        }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-chat-mic-granted") {
            micPermissionState = .granted
        }
        #endif
        handoffManager.advertiseChatViewing(
            chatId: chatId,
            chatTitle: viewModel.chat?.displayTitle
        )
        UnreadMessagesStore.shared.resynchronizeBadge()
    }

    #if DEBUG
    private func seedUITestRecordingRawPending() {
        let nodeID = "composer:embed:ui-test-recording-raw"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "recording",
                title: "recording-ui-test.m4a"
            )
            try composerSession.updateEmbed(
                nodeID: nodeID,
                status: AppleComposerEmbedLifecycleState.transcribing.rawValue
            )
            try composerSession.updatePendingEmbedTitle(
                nodeID: nodeID,
                title: "Raw realtime transcript"
            )
            try composerSession.updateEmbed(
                nodeID: nodeID,
                status: AppleComposerEmbedLifecycleState.correcting.rawValue
            )
            isInputFocused = true
            Task { @MainActor in
                // Leave the realtime transcript visible long enough for the UI test
                // process to attach after app launch, then model correction in place.
                try? await Task.sleep(for: .seconds(8))
                guard composerSession.controller.document.nodes.contains(where: { $0.id == nodeID }) else { return }
                try? composerSession.updatePendingEmbedTitle(
                    nodeID: nodeID,
                    title: "Corrected realtime transcript"
                )
                try? composerSession.resolveEmbed(
                    nodeID: nodeID,
                    durableEmbedID: "ui-test-recording-server",
                    referenceType: "audio-recording",
                    status: AppleComposerEmbedLifecycleState.finished.rawValue
                )
            }
        } catch {
            NativeDiagnostics.error(
                "Recording pending transcript fixture failed: \(type(of: error))",
                category: "apple_composer"
            )
        }
    }
    #endif

    private func resetComposerForChatLoad() {
        guard !composerSession.canonicalMarkdown.isEmpty || !composerSession.controller.document.nodes.isEmpty else {
            return
        }
        suppressNextDraftSave = true
        composerSession.clear()
        resolvedComposerEmbeds.removeAll()
        composerEmbedLifecycle = .init()
    }

    private func handleChatLifecycleDisappear() {
        recordStartTask?.cancel()
        recordStartTask = nil
        composerRecorder.cancelRecording()
        cancelRealtimeRecording()
        composerOverlay = nil
        recordAttemptActive = false
        recordStartedFromKeyboard = false
        modelHost.deactivate()
        scrollPositionDebounceTask?.cancel()
        handoffManager.stopAdvertising()
        Task { await invalidateDeferredComposerSends() }
    }

    private func handleForkedChatChange() {
        guard let newChatID = viewModel.forkedChatId else { return }
        let scope = OfflineStore.shared.scopeGeneration, server = ServerProfile.current()
        let ownerID = authManager.currentUser?.id
        Task { @MainActor in
            guard let ownerID, ownerID == (await AuthManager.currentUserId()),
                  viewModel.forkedChatId == newChatID, scope == OfflineStore.shared.scopeGeneration,
                  server == ServerProfile.current() else { return }
            // Switch only after the fork is stored, retaining the readable Team
            // source and its key throughout payload preparation and acknowledgement.
            await TeamWorkspaceContext.shared.selectTeam(nil)
            let currentOwner = await AuthManager.currentUserId()
            guard ownerID == currentOwner, scope == OfflineStore.shared.scopeGeneration,
                  server == ServerProfile.current(), TeamWorkspaceContext.shared.snapshot.teamID == nil,
                  viewModel.forkedChatId == newChatID,
                  let url = URL(string: "openmates://chat/\(newChatID)") else { return }
            NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
            if viewModel.forkedChatId == newChatID { viewModel.forkedChatId = nil }
        }
    }

    private func handleActiveFocusChange(_ focusId: String?) {
        guard let focusId, !focusId.isEmpty else {
            focusModeManager.deactivate()
            return
        }
        guard let focus = FocusModeManager.FocusModeInfo.resolve(focusId) else {
            focusModeManager.deactivate()
            return
        }
        focusModeManager.activate(focus)
    }

    /// The shell already owns decrypted metadata when a recent chat is selected.
    /// Use it on the first frame, before key/window loading starts, and never
    /// borrow a previous route's model state.
    private var presentedChat: Chat? {
        if let chat = viewModel.chat, chat.id == chatId { return chat }
        return initialChat?.id == chatId ? initialChat : nil
    }

    private var initialContentIsLoading: Bool {
        (loadedRouteID != chatId || viewModel.isLoading) && displayedChatMessages.isEmpty
    }

    private var effectiveBannerState: ChatBannerState? {
        // An unsent draft is editor state, not generated chat identity.
        if let chat = presentedChat, isDraftOnlyChat(chat) { return nil }
        if let bannerState {
            if case .draftOnly = bannerState { return nil }
            return bannerState
        }
        guard let chat = presentedChat else { return nil }
        return ChatBannerPresentation.generatedOrProvisionalState(
            title: chat.title,
            provisionalTitle: chat.title?.isEmpty == false ? nil : firstUserMessageProvisionalTitle,
            category: chat.category,
            summary: chat.chatSummary,
            shouldShowLoading: ChatGeneratedHeaderPolicy.shouldShowLoading(
                title: chat.title,
                titleVersion: chat.titleV,
                hasMessages: !displayedChatMessages.isEmpty,
                isStreaming: viewModel.isStreaming
            )
        )
    }

    private var firstUserMessageProvisionalTitle: String? {
        guard let content = displayedChatMessages.first(where: { $0.role == .user })?.content,
              let text = ChatSendPipeline.provisionalTitleSource(content: content, composerEmbeds: [],
                  embedTypesByID: displayedEmbedRecords.mapValues(\.type)) else {
            return nil
        }
        // Audio-only and file-only messages await generated metadata; an embed
        // reference or filename is not a meaningful chat title.
        return ChatHeaderPresentation.provisionalTitle(from: text)
    }

    private var effectiveBannerCreatedAt: Date? {
        bannerCreatedAt ?? presentedChat?.createdDate ?? presentedChat?.updatedDate
    }

    private var displayedChatMessages: [Message] {
        #if DEBUG
        if isUITestChatHistoryFullParityEnabled {
            return Self.chatHistoryFullParityMessages
        }
        #endif
        return viewModel.chat?.id == chatId ? viewModel.messages : []
    }

    private func isDraftOnlyChat(_ chat: Chat) -> Bool {
        return (chat.messagesV ?? 0) == 0 && displayedChatMessages.isEmpty
            && (chat.hasNonEmptyDraft == true || (chat.draftV ?? 0) > 0 || draftPreview(for: chat) != nil)
    }

    private func draftPreview(for chat: Chat) -> String? {
        let preview = draftService.draftPreview(chatId: chat.id)?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let preview, !preview.isEmpty else { return nil }
        return preview
    }

    // MARK: - Embed fullscreen helper

    private var chatTopBar: some View {
        HStack(spacing: .spacing3) {
            ChatHeaderView(
                chat: presentedChat,
                titleOverride: nil,
                provisionalTitle: presentedChat?.title?.isEmpty == false ? nil : firstUserMessageProvisionalTitle,
                isLoading: initialContentIsLoading || viewModel.isLoading
            )

            Spacer()

            if showEmbedFullscreen && chatWorkspaceWidth >= 1024 { splitChatHideAction }
            if chatHasPIIMappings {
                chatFloatingAction(
                    icon: isPIIRevealed ? "hidden" : "visible",
                    label: isPIIRevealed ? AppStrings.piiHide : AppStrings.piiShow,
                    accessibilityIdentifier: "chat-pii-toggle"
                ) {
                    isPIIRevealed.toggle()
                }
            }
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
        .accessibilityIdentifier("active-chat-header")
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.grey20)
                .frame(height: 1)
        }
    }

    private var chatHasPIIMappings: Bool {
        viewModel.messages.contains { ($0.piiMappings?.isEmpty == false) || ($0.encryptedPIIMappings?.isEmpty == false) }
    }

    private var cumulativePIIMappings: [PIIMapping] {
        ChatTranscriptDisplayProjection.cumulativeMappings(in: viewModel.messages)
    }

    private var displayedEmbedRecords: [String: EmbedRecord] {
        let records = composerSearchEmbedRecords.merging(viewModel.embedRecords) { _, current in current }
        guard isPIIRevealed else { return records }
        let mappings = cumulativePIIMappings
        return records.mapValues { PIIDetector.restorePII(in: $0, mappings: mappings) }
    }

    private func displayEmbed(_ embed: EmbedRecord) -> EmbedRecord {
        guard isPIIRevealed else { return embed }
        return PIIDetector.restorePII(in: embed, mappings: cumulativePIIMappings)
    }

    private func displayedEmbeds(for message: Message) -> [EmbedRecord] {
        viewModel.embeds(for: message).map(displayEmbed)
    }

    private var incognitoSessionBanner: some View {
        HStack(spacing: .spacing3) {
            Icon("hidden", size: 14)
                .accessibilityHidden(true)
            Text(AppStrings.incognitoModeActive)
                .font(.omXs)
                .fontWeight(.medium)
            Spacer()
        }
        .foregroundStyle(Color.fontButton)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey80)
        .accessibilityElement(children: .combine)
        .help(Text(AppStrings.incognitoModeActive))
        .accessibilityLabel(AppStrings.incognitoModeActive)
        .accessibilityIdentifier("incognito-mode-banner")
    }

    private func customOverlay<Content: View>(
        title: String,
        isPresented: Binding<Bool>,
        showHeader: Bool = true,
        @ViewBuilder content: () -> Content
    ) -> some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture {
                    isPresented.wrappedValue = false
                }

            VStack(spacing: 0) {
                if showHeader {
                    HStack {
                        Text(title)
                            .font(.omH3)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                        Spacer()
                        OMIconButton(icon: "close", label: AppStrings.close, size: 34) {
                            isPresented.wrappedValue = false
                        }
                    }
                    .padding(.spacing6)
                }

                content()
            }
            .frame(maxWidth: 760, maxHeight: 760)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .padding(.spacing8)
        }
    }

    @ViewBuilder
    private func embedFullscreenSheet(for embed: EmbedRecord) -> some View {
        let displayedSelectedEmbed = displayEmbed(viewModel.embedRecords[embed.id] ?? embed)
        let matchingMessage = viewModel.messages.first { msg in
            msg.embedRefs?.contains(where: { $0.id == embed.id }) == true
        }
        let fallbackMessage = matchingMessage ?? viewModel.messages.last
        let messageEmbeds: [EmbedRecord] = if let msg = fallbackMessage {
            displayedEmbeds(for: msg)
        } else {
            []
        }
        let fullscreenEmbeds = EmbedGrouper.fullscreenNavigationEmbeds(
            selected: displayedSelectedEmbed, messageEmbeds: messageEmbeds,
            allRecords: displayedEmbedRecords,
            parent: fullscreenPreviousEmbeds.last.map(displayEmbed)
        )
        EmbedFullscreenContainer(
            embeds: fullscreenEmbeds,
            initialEmbedId: displayedSelectedEmbed.id,
            allEmbedRecords: displayedEmbedRecords,
            chatId: chatId,
            hasPIIMappings: !cumulativePIIMappings.isEmpty,
            piiMappings: cumulativePIIMappings,
            isPIIRevealed: isPIIRevealed,
            onTogglePII: { isPIIRevealed.toggle() },
            onOpenEmbed: { child, parent in
                openChildEmbedFullscreen(child, from: parent)
            },
            onClose: {
                closeEmbedFullscreenRoute()
            },
            onOpenShareSettings: { onOpenEmbedShareSettings?($0) },
            isSidePanel: chatWorkspaceWidth >= 1024,
            responsiveViewportWidth: chatWorkspaceWidth > 0 ? chatWorkspaceWidth : nil,
            showChat: chatWorkspaceWidth >= 1024 && hideSplitChat,
            onShowChat: { hideSplitChat = false },
            onReportEmbedIssue: onReportIssue.map { callback in { _ in callback(.init(title: "", category: "bug")) } },
            highlightQuoteText: sourceQuoteTarget?.embedID == displayedSelectedEmbed.id ? sourceQuoteTarget?.text : nil
        )
    }

    private func openEmbedFullscreen(_ embed: EmbedRecord, quote: String? = nil) {
        sourceQuoteTarget = quote.map { SourceQuoteTarget(embedID: embed.id, text: $0) }
        // Do not let a suspended page discard this overlay's parent/sibling
        // graph or restore the background scroll after the embed opens.
        viewModel.cancelHistoryWindowNavigation()
        historyNavigationTask?.cancel()
        historyNavigationTask = nil
        historyNavigationID = UUID()
        userHasScrolledHistory = false
        isRestoringScroll = false
        fullscreenPreviousEmbeds = []
        selectedEmbed = embed
        showEmbedFullscreen = true
        // Search parents can finish before their encrypted result children are
        // decoded locally. Retry the scoped graph load when the user opens the
        // result so fullscreen does not remain on a stale empty snapshot.
        Task { @MainActor in
            await viewModel.loadEmbeds(for: viewModel.messages.map(\.id))
            guard showEmbedFullscreen, selectedEmbed?.id == embed.id else { return }
            selectedEmbed = viewModel.embedRecords[embed.id] ?? embed
        }
    }

    private func openInitialEmbedIfReady() {
        guard let initialEmbedId,
              openedInitialEmbedId != initialEmbedId,
              let embed = viewModel.embedRecords[initialEmbedId] else { return }
        openedInitialEmbedId = initialEmbedId
        openEmbedFullscreen(embed)
        onInitialEmbedOpened?(initialEmbedId)
    }

    private func openChildEmbedFullscreen(_ child: EmbedRecord, from parent: EmbedRecord) {
        sourceQuoteTarget = nil
        if fullscreenPreviousEmbeds.last?.id != parent.id {
            fullscreenPreviousEmbeds.append(parent)
        }
        selectedEmbed = child
        showEmbedFullscreen = true
    }

    private func closeEmbedFullscreenRoute() {
        sourceQuoteTarget = nil
        if let previous = fullscreenPreviousEmbeds.popLast() {
            selectedEmbed = previous
            showEmbedFullscreen = true
            return
        }

        hideSplitChat = false
        selectedEmbed = nil
        showEmbedFullscreen = false
    }

    // MARK: - Message list

    private func resetTranscriptScrollGeometry() {
        transcriptScrollState.reset()
        isAtTop = true
        isAtBottom = false
        // The banner can stay mounted with the same height across a reset.
        // Preserve its measurement: onGeometryChange need not republish it.
        chatHeaderActionsOverlapBanner = transcriptScrollState.bannerOverlap(bannerHeight: chatBannerHeight) ?? true
    }

    private func updateChatHeaderBannerOverlap(_ overlap: Bool?) {
        guard let overlaps = overlap else { return }
        guard overlaps != chatHeaderActionsOverlapBanner else { return }
        if reduceMotion {
            chatHeaderActionsOverlapBanner = overlaps
        } else {
            withAnimation(.easeInOut(duration: 0.2)) {
                chatHeaderActionsOverlapBanner = overlaps
            }
        }
    }

    private var messageList: some View {
        GeometryReader { scrollGeo in
            let displayProjection = ChatTranscriptDisplayProjection(
                messages: viewModel.messages, embedRecords: viewModel.embedRecords,
                isPIIRevealed: isPIIRevealed)
            ScrollViewReader { proxy in
                ZStack {
                    ScrollView {
                        VStack(spacing: 0) {
                            scrollSentinel(id: "scroll-top", edge: .top)

                            // Gradient banner — shown for demo/example chats (ChatHeader.svelte equivalent)
                            if let banner = effectiveBannerState {
                                ChatBannerView(
                                    state: banner,
                                    createdAt: effectiveBannerCreatedAt,
                                    isExampleChat: chatId.hasPrefix("example-"),
                                    isIntroChat: false,
                                    teaserVideoURL: nil,
                                    fullVideoURL: nil,
                                    iconName: publicChatIconName(for: chatId) ?? presentedChat?.icon,
                                    isSettingsOpen: isSettingsOpen,
                                    viewportHeight: chatViewportHeight,
                                    onPrevious: onPreviousChat,
                                    onNext: onNextChat
                                )
                                    .id("banner")
                                    .onGeometryChange(for: CGFloat.self) { geometry in
                                        geometry.size.height
                                    } action: { height in
                                        guard height != chatBannerHeight else { return }
                                        chatBannerHeight = height
                                        updateChatHeaderBannerOverlap(transcriptScrollState.bannerOverlap(bannerHeight: height))
                                    }
                            }

                            // The initial history window is capped by the model.
                            // Realize that window with stable measured heights:
                            // lazy placement repeatedly invalidates its estimated
                            // extent when scrolling past tall markdown answers.
                            VStack(spacing: .spacing4) {
                                if initialContentIsLoading {
                                    ProgressView()
                                        .padding(.vertical, .spacing8)
                                        .frame(maxWidth: .infinity)
                                        .accessibilityIdentifier("chat-initial-content-loading")
                                }
                                // Load older messages button at the top
                                if viewModel.hasOlderMessages {
                                    Button {
                                        navigateHistory(.older, retaining: viewModel.messages.first?.id,
                                                        anchor: .top, proxy: proxy)
                                    } label: {
                                        HStack(spacing: .spacing2) {
                                            if viewModel.isLoadingOlder {
                                                ProgressView()
                                                    .scaleEffect(0.7)
                                            } else {
                                                Icon("up", size: 12)
                                            }
                                            Text(AppStrings.loadEarlierMessages)
                                                .font(.omXs)
                                        }
                                        .foregroundStyle(Color.fontSecondary)
                                        .padding(.vertical, .spacing3)
                                        .frame(maxWidth: .infinity)
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(viewModel.isLoadingOlder)
                                    .accessibilityIdentifier("load-older-messages")
                                    .id("load-older")
                                }

                                #if DEBUG
                                if isUITestChatHistoryAudioParityEnabled {
                                    chatHistoryAudioParityFixture(containerWidth: scrollGeo.size.width)
                                }
                                #endif

                                ForEach(displayedChatMessages) { message in
                                    MessageBubble(
                                        message: message,
                                        chatId: chatId,
                                        appId: viewModel.chat?.category ?? viewModel.chat?.appId,
                                        embeds: displayProjection.embeds(for: message),
                                        allEmbedRecords: displayProjection.embedRecords,
                                        streamingContent: viewModel.isStreamingMessage(message.id) ? viewModel.streamingContent : nil,
                                        thinkingContent: thinkingContent(for: message),
                                        isThinkingStreaming: isThinkingStreaming(for: message),
                                        piiMappings: displayProjection.piiMappings,
                                        isPIIRevealed: isPIIRevealed,
                                        containerWidth: scrollGeo.size.width,
                                        isSearchTarget: searchTarget?.messageId == message.id,
                                        searchHighlightQuery: searchTarget?.messageId == message.id ? searchTarget?.query : nil,
                                        onEmbedTap: { embed in
                                            openEmbedFullscreen(embed)
                                        },
                                        onOpenPublicChat: onOpenPublicChat,
                                        subChatStore: chatStore,
                                        subChatProgress: viewModel.subChatProgress,
                                        completedSubChatIDs: viewModel.completedSubChatIDs,
                                        onOpenSubChat: onOpenChat,
                                        onInteractiveQuestionSubmit: { content in
                                            Task { await viewModel.sendMessage(content) }
                                        },
                                        onOpenMateSettings: onOpenMateSettings,
                                        onOpenModelSettings: onOpenModelSettings,
                                        onSpeak: canSpeakAssistantMessage(message) ? {
                                            speakAssistantMessage(message)
                                        } : nil,
                                        onShowActions: {
                                            actionMessage = message
                                        },
                                        accessibilityIdentifier: chatHistoryFixtureIdentifier(for: message)
                                    )
                                    .id(message.id)
                                    .environment(\.embedChatID, chatId)
                                    .environment(\.messageTextSelection, messageSelectionContext(for: message))
                                    .environment(\.sourceQuoteOpenAction, { embed, quote in
                                        openEmbedFullscreen(embed, quote: quote)
                                    })
                                    .environment(\.embedPIIMappings, displayProjection.piiMappings)
                                    .environment(\.embedPIIRevealed, isPIIRevealed)
                                    .modifier(ChatMessageVisibilityTracking(
                                        messageId: message.id, viewportHeight: scrollGeo.size.height))
                                }

                                #if DEBUG
                                if isUITestChatHistoryFullParityEnabled {
                                    Color.clear
                                        .frame(height: 1)
                                        .accessibilityElement()
                                        .accessibilityLabel(AppStrings.chat)
                                        .accessibilityIdentifier("chat-history-final-content")
                                }
                                #endif

                                if let accountID = authManager.currentUser?.id, let ownerID = projectReviewOwnerID {
                                    ProjectWorkspaceReviewTranscriptView(runtime: projectReviews,
                                        chatID: chatId, accountID: accountID, ownerID: ownerID)
                                        .id("project-review-cards")
                                }

                                if viewModel.hasNewerMessages {
                                    Button {
                                        navigateHistory(.newer, retaining: viewModel.messages.last?.id,
                                                        anchor: .bottom, proxy: proxy)
                                    } label: {
                                        HStack(spacing: .spacing2) {
                                            Text(AppStrings.next).font(.omXs)
                                            Icon("dropdown", size: 12)
                                        }
                                        .foregroundStyle(Color.fontSecondary)
                                        .padding(.vertical, .spacing3)
                                        .frame(maxWidth: .infinity)
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(viewModel.isLoadingOlder)
                                    .accessibilityIdentifier("load-newer-messages")
                                    .id("load-newer")
                                }

                                if !viewModel.hasNewerMessages && showAssistantFeedback {
                                    AssistantResponseFeedbackView(
                                        selectedRating: $selectedAssistantRating,
                                        submitted: assistantFeedbackSubmitted,
                                        onSubmit: handleAssistantFeedbackSubmit,
                                        onRequestFeature: {
                                            onReportIssue?(.featureRequest())
                                        }
                                    )
                                    .padding(.leading, ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: scrollGeo.size.width) ? 0 : 75)
                                    .padding(.trailing, ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: scrollGeo.size.width) ? 0 : 20)
                                    .id("assistant-response-feedback")
                                }

                                if !viewModel.isLoading && !viewModel.hasNewerMessages && !viewModel.followUpSuggestions.isEmpty && !viewModel.isStreaming {
                                    FollowUpSuggestions(
                                        suggestions: viewModel.followUpSuggestions,
                                        compact: scrollGeo.size.width <= 500
                                    ) { suggestion in
                                        handleFollowUpSuggestionTap(suggestion)
                                    }
                                    .accessibilityIdentifier("follow-up-suggestions")
                                    .id("follow-up-suggestions")
                                }
                            }
                            .scrollTargetLayout()
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing4)
                            // Cap message area width on iPad/Mac, centered
                            .frame(maxWidth: ChatResponsiveLayoutPolicy.contentMaximumWidth)
                            .frame(maxWidth: .infinity)
                            // Own the transcript identifier; do not let VStack
                            // propagate it over user/assistant row identifiers.
                            .accessibilityElement(children: .contain)
                            .accessibilityIdentifier("chat-history-content")
                            #if DEBUG
                            .accessibilityValue(isUITestHistoryWindowMetricsEnabled
                                ? viewModel.historyWindowAccessibilityValue : "")
                            #endif

                            scrollSentinel(id: "scroll-bottom", edge: .bottom)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .coordinateSpace(name: "chat-scroll")
                    .contentShape(Rectangle())
                    .accessibilityIdentifier("chat-history-container")
                    .scrollDismissesKeyboard(.interactively)
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 4).onChanged { value in
                            if !userHasScrolledHistory { userHasScrolledHistory = true }
                            stopFollowingStreamingResponse()
                            // Also handles dragging past an already-reached edge;
                            // the geometry callback handles wheel/trackpad scrolling.
                            if value.translation.height > 4 && isAtTop {
                                pageHistoryAtBoundary(isTop: true, proxy: proxy)
                            } else if value.translation.height < -4 && isAtBottom {
                                pageHistoryAtBoundary(isTop: false, proxy: proxy)
                            }
                        }
                    )
                    // Keyboard dismissal observes transcript taps without
                    // consuming the open action of an inline embed button.
                    .simultaneousGesture(
                        TapGesture().onEnded {
                            dismissInputIfNeeded()
                        }
                    )
                    .modifier(ChatTranscriptScrollTracking(
                        scrollState: transcriptScrollState,
                        bannerHeight: chatBannerHeight,
                        viewportHeight: scrollGeo.size.height,
                        onBoundariesChanged: { boundaries in
                            let reachedTop = !isAtTop && boundaries.isAtTop
                            let reachedBottom = !isAtBottom && boundaries.isAtBottom
                            updateChatHeaderBannerOverlap(boundaries.overlapsBanner)
                            if isAtTop != boundaries.isAtTop { isAtTop = boundaries.isAtTop }
                            if isAtBottom != boundaries.isAtBottom { isAtBottom = boundaries.isAtBottom }
                            if reachedTop { pageHistoryAtBoundary(isTop: true, proxy: proxy) }
                            else if reachedBottom { pageHistoryAtBoundary(isTop: false, proxy: proxy) }
                        },
                        onVisibleMessagesChanged: trackVisibleMessage,
                        onUserScroll: {
                            if !userHasScrolledHistory { userHasScrolledHistory = true }
                            stopFollowingStreamingResponse()
                        }))

                    if !viewModel.messages.isEmpty && (!isAtTop || viewModel.hasOlderMessages) {
                        scrollNavButton(isTop: true) {
                            navigateHistory(.oldest, retaining: nil, anchor: .top, proxy: proxy)
                        }
                        .padding(.top, 18)
                        .frame(maxHeight: .infinity, alignment: .top)
                    }

                    if !viewModel.messages.isEmpty && (!isAtBottom || viewModel.hasNewerMessages) {
                        scrollNavButton(isTop: false) {
                            navigateHistory(.latest, retaining: nil, anchor: .bottom, proxy: proxy)
                        }
                        .frame(maxHeight: .infinity, alignment: .bottom)
                    }

                    if effectiveBannerState != nil {
                        chatFloatingActions
                            .padding(.top, .spacing4)
                            .padding(.horizontal, .spacing6)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    }

                    #if DEBUG
                    if isUITestChatHistoryFullParityEnabled {
                        chatHistoryLayoutMetricsProbe(containerSize: scrollGeo.size)
                    }
                    #endif
                }
                .onAppear {
                    resetTranscriptScrollGeometry()
                    resetScrollRestoration()
                    proxy.scrollTo("scroll-top", anchor: .top)
                }
                .onChange(of: chatId) { _, _ in
                    chatHeaderMoreOpen = false
                    resetTranscriptScrollGeometry()
                    resetScrollRestoration()
                    proxy.scrollTo("scroll-top", anchor: .top)
                }
                .onChange(of: authManager.currentUser?.id) { _, _ in
                    resetTranscriptScrollGeometry()
                    resetScrollRestoration()
                }
                .onChange(of: viewModel.messages.map(\.id)) { _, _ in
                    restoreInitialScrollIfNeeded(proxy: proxy)
                    scrollToSearchTargetIfNeeded(proxy: proxy)
                    scrollToStreamingResponseIfNeeded(proxy: proxy)
                }
                .onChange(of: viewModel.streamingContent) { _, _ in
                    scrollToStreamingResponseIfNeeded(proxy: proxy)
                }
                .onChange(of: viewModel.isStreaming) { wasStreaming, isStreaming in
                    if wasStreaming && !isStreaming {
                        Task { @MainActor in
                            await Task.yield()
                            reportFinalVisibleMessages(latestVisibleMessageIds)
                        }
                    }
                    if !wasStreaming, isStreaming {
                        followsStreamingResponse = !viewModel.hasNewerMessages
                            && (displayedChatMessages.last?.role == .user || isAtBottom)
                        scrollToStreamingResponseIfNeeded(proxy: proxy)
                        return
                    }
                    guard wasStreaming, !isStreaming, followsStreamingResponse else { return }
                    finalizeStreamingResponseScroll(proxy: proxy)
                }
                .onChange(of: viewModel.followUpSuggestions) { _, suggestions in
                    guard !viewModel.hasNewerMessages, !isRestoringScroll,
                          !suggestions.isEmpty, followsStreamingResponse || isAtBottom else { return }
                    Task { @MainActor in
                        await Task.yield()
                        withAnimation(.easeInOut(duration: 0.25)) {
                            proxy.scrollTo("scroll-bottom", anchor: .bottom)
                        }
                    }
                }
                .onChange(of: searchTarget) { _, _ in
                    completedSearchTargetID = nil
                    scrollToSearchTargetIfNeeded(proxy: proxy)
                }
                .onDisappear {
                    historyNavigationTask?.cancel()
                    historyNavigationID = UUID()
                    scrollPositionDebounceTask?.cancel()
                }
            }
        }
    }

    #if DEBUG
    private var isUITestHistoryWindowMetricsEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-history-window-metrics")
            || ProcessInfo.processInfo.environment["UI_TEST_HISTORY_WINDOW_METRICS"] == "1"
    }

    private var isUITestChatHistoryFullParityEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-chat-history-full-parity")
            || ProcessInfo.processInfo.environment["UI_TEST_CHAT_HISTORY_FULL_PARITY"] == "1"
    }

    private var isUITestChatHistoryAudioParityEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-chat-history-audio-parity")
            || ProcessInfo.processInfo.environment["UI_TEST_CHAT_HISTORY_AUDIO_PARITY"] == "1"
    }

    private var isUITestStreamingPresentationEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-streaming-presentation")
            || ProcessInfo.processInfo.environment["UI_TEST_STREAMING_PRESENTATION"] == "1"
    }

    private func chatHistoryLayoutMetricsProbe(containerSize: CGSize) -> some View {
        let transcriptWidth = min(containerSize.width, ChatResponsiveLayoutPolicy.contentMaximumWidth)
        let mobileBanner = containerSize.width <= 730
        let minimumBannerHeight: CGFloat = mobileBanner ? 230 : 240
        let bannerHeight = max(minimumBannerHeight, chatViewportHeight * 0.35)
        let direction = layoutDirection == .rightToLeft ? "rtl" : "ltr"
        let windowMode = containerSize.width < ChatHistoryLayoutMetric.wideWindowMinimumWidth ? "narrow" : "wide"
        let metrics = [
            "viewport-width=\(Int(containerSize.width.rounded()))",
            "transcript-width=\(Int(transcriptWidth.rounded()))",
            "banner-width=\(Int(containerSize.width.rounded()))",
            "banner-height=\(Int(bannerHeight.rounded()))",
            "composer-safe-area-clearance=0",
            "layout-direction=\(direction)",
            "window-mode=\(windowMode)",
            "accessibility-order=banner,user,assistant,composer"
        ].joined(separator: "; ")

        return Color.clear
            .frame(width: 1, height: 1)
            .accessibilityElement()
            .accessibilityLabel(metrics)
            .accessibilityIdentifier("chat-history-layout-metrics")
            .allowsHitTesting(false)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private static var chatHistoryUserBubbleFixtureText: String {
        switch ProcessInfo.processInfo.environment["UI_TEST_USER_BUBBLE_VARIANT"] {
        case "short": return "Short reply"
        case "wrapped": return String(repeating: "A saved user paragraph wraps naturally and keeps every line at the leading edge. ", count: 4)
        case "newlines": return "First explicit line is longer\nShort line\nThird line"
        default: return "Synthetic user history fixture"
        }
    }

    private static let chatHistoryFullParityMessages = [
        Message(
            id: "ui-test-history-user",
            chatId: "ui-test-chat-history",
            role: .user,
            content: chatHistoryUserBubbleFixtureText,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        ),
        Message(
            id: "ui-test-history-assistant",
            chatId: "ui-test-chat-history",
            role: .assistant,
            content: """
            Synthetic assistant history fixture with an independently readable link: https://example.invalid/history

            This public fixture intentionally includes enough deterministic transcript content to scroll the banner fully past the fixed header actions. That lets the UI contract exercise both the banner-overlay and standard control styles instead of stopping at a non-scrollable initial layout.

            The additional paragraph also keeps the final composer-clearance and keyboard-dismissal checks representative of a normal conversation whose history extends beyond one viewport.

            A longer answer is common when a mate explains its sources, summarizes several findings, and gives the reader useful next steps. Keeping that shape in the fixture makes a swipe move through actual message content while the header controls remain fixed over the transcript viewport.

            Once the gradient banner has moved above those controls, their translucent white treatment should switch to the standard gradient icon and neutral background. Scrolling back to the beginning should restore the overlay treatment because the controls again intersect the banner.
            """,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:01Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: nil,
            modelName: "Synthetic Model",
            senderName: "Synthetic Mate",
            category: "research"
        )
    ]

    private func chatHistoryAudioParityFixture(containerWidth: CGFloat) -> some View {
        let records = Self.chatHistoryAudioParityRecords
        let recordLookup = EmbedRecord.dictionaryById(records, context: "chatView.audioParityFixture")
        return VStack(alignment: .leading, spacing: .spacing4) {
            MessageBubble(
                message: Self.chatHistorySourceQuoteMessage,
                chatId: chatId,
                appId: "web",
                embeds: [Self.chatHistorySourceRecord],
                allEmbedRecords: recordLookup,
                streamingContent: nil,
                thinkingContent: nil,
                isThinkingStreaming: false,
                piiMappings: [],
                isPIIRevealed: false,
                containerWidth: containerWidth,
                isSearchTarget: false,
                searchHighlightQuery: nil,
                onEmbedTap: { _ in },
                onOpenPublicChat: nil,
                onInteractiveQuestionSubmit: nil,
                onShowActions: nil
            )

            MessageBubble(
                message: Self.chatHistorySystemMessage,
                chatId: chatId,
                appId: nil,
                embeds: [],
                allEmbedRecords: recordLookup,
                streamingContent: nil,
                thinkingContent: nil,
                isThinkingStreaming: false,
                piiMappings: [],
                isPIIRevealed: false,
                containerWidth: containerWidth,
                isSearchTarget: false,
                searchHighlightQuery: nil,
                onEmbedTap: { _ in },
                onOpenPublicChat: nil,
                onInteractiveQuestionSubmit: nil,
                onShowActions: nil
            )

            MessageBubble(
                message: Self.chatHistorySentAudioMessage,
                chatId: chatId,
                appId: "audio",
                embeds: [Self.chatHistoryFinishedAudio],
                allEmbedRecords: recordLookup,
                streamingContent: nil,
                thinkingContent: nil,
                isThinkingStreaming: false,
                piiMappings: [],
                isPIIRevealed: false,
                containerWidth: containerWidth,
                isSearchTarget: false,
                searchHighlightQuery: nil,
                onEmbedTap: { openEmbedFullscreen($0) },
                onOpenPublicChat: nil,
                onInteractiveQuestionSubmit: nil,
                onShowActions: nil,
                accessibilityIdentifier: "chat-history-sent-audio-message"
            )

            ForEach([Self.chatHistoryProcessingAudio, Self.chatHistoryErrorAudio]) { record in
                EmbedPreviewCard(embed: record, allEmbedRecords: recordLookup) {
                    guard record.status == .finished else { return }
                    openEmbedFullscreen(record)
                }
                .frame(maxWidth: .infinity)
                .frame(height: 220)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-history-audio-parity-fixture")
    }

    private static var chatHistorySentAudioMessage: Message {
        let content: String
        switch ProcessInfo.processInfo.environment["UI_TEST_AUDIO_MESSAGE_CONTENT"] {
        case "whitespace": content = " \n\t "
        case "mixed": content = "Synthetic audio introduction\n\n[[embed:synthetic-finished-audio]]\n\nSynthetic audio conclusion"
        default: content = " \n[[embed:synthetic-finished-audio]]\n "
        }
        return Message(
            id: "ui-test-sent-audio-message", chatId: "ui-test-chat-history",
            role: .user, content: content, encryptedContent: nil,
            createdAt: "2026-01-01T00:00:02Z", updatedAt: nil,
            appId: "audio", isStreaming: false,
            embedRefs: [EmbedRef(id: "synthetic-finished-audio", type: "recording", status: "finished", data: nil)]
        )
    }

    private static let chatHistorySourceQuoteMessage = Message(
        id: "ui-test-source-message",
        chatId: "ui-test-chat-history",
        role: .assistant,
        content: "Synthetic ordered introduction\n\n> [Verified synthetic source quote](embed:synthetic-source)",
        encryptedContent: nil,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: nil,
        appId: "web",
        isStreaming: false,
        embedRefs: [EmbedRef(id: "synthetic-source", type: "web-website", status: "finished", data: nil)],
        modelName: "Synthetic Model",
        senderName: "Synthetic Mate",
        category: "research"
    )

    private static let chatHistorySystemMessage = Message(
        id: "ui-test-system-message",
        chatId: "ui-test-chat-history",
        role: .system,
        content: "Synthetic system notice",
        encryptedContent: nil,
        createdAt: "2026-01-01T00:00:01Z",
        updatedAt: nil,
        appId: nil,
        isStreaming: false,
        embedRefs: nil
    )

    private static let chatHistorySourceRecord = chatHistoryAudioRecord(
        id: "synthetic-source-record",
        type: "web-website",
        appId: "web",
        data: [
            "embed_ref": "synthetic-source",
            "source": "example.invalid",
            "url": "https://example.invalid/source"
        ]
    )

    private static let chatHistoryFinishedAudio = chatHistoryAudioRecord(
        id: "synthetic-finished-audio",
        data: [
            "status": "finished",
            "duration": "0:42",
            "transcript": "Synthetic corrected transcript for sent audio parity.",
            "transcript_original": "Synthetic original transcript for sent audio parity.",
            "transcript_corrected": "Synthetic corrected transcript for sent audio parity.",
            "use_corrected": true,
            "model": "Synthetic Voxtral",
            "preview_audio_url": "https://example.invalid/synthetic-audio.m4a"
        ]
    )

    private static let chatHistoryProcessingAudio = chatHistoryAudioRecord(
        id: "synthetic-processing-audio",
        status: .processing,
        data: ["status": "transcribing", "model": "Synthetic Voxtral"]
    )

    private static let chatHistoryErrorAudio = chatHistoryAudioRecord(
        id: "synthetic-error-audio",
        status: .error,
        data: ["status": "error", "upload_error": "Audio unavailable"]
    )

    private static let chatHistoryAudioParityRecords = [
        chatHistorySourceRecord,
        chatHistoryFinishedAudio,
        chatHistoryProcessingAudio,
        chatHistoryErrorAudio
    ]

    private static func chatHistoryAudioRecord(
        id: String,
        type: String = EmbedType.recording.rawValue,
        status: EmbedStatus = .finished,
        appId: String = "audio",
        data: [String: Any]
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(data.mapValues(AnyCodable.init)),
            parentEmbedId: nil,
            appId: appId,
            skillId: type == EmbedType.recording.rawValue ? "transcribe" : nil,
            embedIds: nil,
            createdAt: "2026-01-01T00:00:00Z"
        )
    }
    #endif

    #if !DEBUG
    private var isUITestStreamingPresentationEnabled: Bool { false }
    #endif

    private func thinkingContent(for message: Message) -> String? {
        #if DEBUG
        if isUITestStreamingPresentationEnabled,
           message.id == "ui-test-history-assistant" {
            return Array(repeating: "**Bounded thinking detail**", count: 24)
                .joined(separator: "\n\n")
        }
        #endif
        return message.id == viewModel.streamingLifecycle.messageId
            ? viewModel.streamingLifecycle.thinkingContent
            : message.thinkingContent
    }

    private func isThinkingStreaming(for message: Message) -> Bool {
        #if DEBUG
        if isUITestStreamingPresentationEnabled,
           message.id == "ui-test-history-assistant" {
            return true
        }
        #endif
        return message.id == viewModel.streamingLifecycle.messageId
            && viewModel.streamingLifecycle.isThinkingStreaming
    }

    private func chatHistoryFixtureIdentifier(for message: Message) -> String? {
        #if DEBUG
        if isUITestHistoryWindowMetricsEnabled { return "chat-history-message-" + message.id }
        guard isUITestChatHistoryFullParityEnabled else { return nil }
        if message.id == "ui-test-history-user" { return "chat-history-fixture-user" }
        if message.id == "ui-test-history-assistant" { return "chat-history-fixture-assistant" }
        #endif
        return nil
    }

    private func scrollToSearchTargetIfNeeded(proxy: ScrollViewProxy) {
        guard let targetMessageId = searchTarget?.messageId,
              completedSearchTargetID != targetMessageId, !viewModel.isLoading,
              !viewModel.messages.isEmpty else { return }
        completedSearchTargetID = targetMessageId
        navigateHistory(.message(targetMessageId), retaining: targetMessageId,
                        anchor: UnitPoint(x: 0.5, y: 0.18), proxy: proxy)
    }

    private func pageHistoryAtBoundary(isTop: Bool, proxy: ScrollViewProxy) {
        guard !showEmbedFullscreen, userHasScrolledHistory, hasRestoredInitialScroll,
              !isRestoringScroll, !viewModel.isLoadingOlder,
              !followsStreamingResponse else { return }
        if isTop && viewModel.hasOlderMessages {
            navigateHistory(.older, retaining: viewModel.messages.first?.id, anchor: .top, proxy: proxy)
        } else if !isTop && viewModel.hasNewerMessages {
            navigateHistory(.newer, retaining: viewModel.messages.last?.id, anchor: .bottom, proxy: proxy)
        }
    }

    /// Keep the overlap only after the model commits its replacement window.
    /// One retained task and generation guard prevent an old chat/page from
    /// moving the new transcript or persisting its temporary scroll position.
    private func navigateHistory(_ destination: ChatHistoryWindowDestination, retaining anchorMessageID: String?,
                                 anchor: UnitPoint, proxy: ScrollViewProxy) {
        stopFollowingStreamingResponse()
        historyNavigationTask?.cancel()
        scrollPositionDebounceTask?.cancel()
        let navigationID = UUID()
        historyNavigationID = navigationID
        userHasScrolledHistory = false
        isRestoringScroll = true
        let requestedChatID = chatId
        let scope = OfflineStore.shared.scopeGeneration
        let previousRevision = viewModel.historyWindowRevision
        let page = viewModel.loadMessageWindow(destination)
        let requestGeneration = viewModel.windowRequestGeneration
        historyNavigationTask = Task { @MainActor in
            defer {
                if historyNavigationID == navigationID {
                    isRestoringScroll = false
                    historyNavigationTask = nil
                }
            }
            if let page { await page.value }
            await Task.yield()
            guard !Task.isCancelled, historyNavigationID == navigationID,
                  chatId == requestedChatID, viewModel.chat?.id == requestedChatID,
                  viewModel.windowRequestGeneration == requestGeneration,
                  OfflineStore.shared.scopeGeneration == scope,
                  page == nil || viewModel.historyWindowRevision != previousRevision else { return }
            let target: String
            if let anchorMessageID, viewModel.messages.contains(where: { $0.id == anchorMessageID }) {
                target = anchorMessageID
            } else {
                switch destination {
                case .oldest: target = "scroll-top"
                case .latest: target = "scroll-bottom"
                default: return // A removed/missing target must not jump elsewhere.
                }
            }
            // Intentionally no animated extent transition while rows are replaced.
            proxy.scrollTo(target, anchor: anchor)
            try? await Task.sleep(nanoseconds: 120_000_000)
        }
    }

    private func scrollToStreamingResponseIfNeeded(proxy: ScrollViewProxy) {
        guard followsStreamingResponse, !viewModel.hasNewerMessages, !isRestoringScroll else { return }
        streamingScrollTask?.cancel()
        streamingScrollTask = Task { @MainActor in
            try? await Task.sleep(
                for: .milliseconds(ChatHistoryLayoutMetric.streamingUpdateDebounceMilliseconds)
            )
            guard !Task.isCancelled, followsStreamingResponse, !viewModel.hasNewerMessages,
                  !isRestoringScroll else { return }
            proxy.scrollTo("scroll-bottom", anchor: .bottom)
        }
    }

    private func finalizeStreamingResponseScroll(proxy: ScrollViewProxy) {
        streamingScrollTask?.cancel()
        streamingScrollTask = Task { @MainActor in
            await Task.yield()
            guard !Task.isCancelled, followsStreamingResponse, !viewModel.hasNewerMessages,
                  !isRestoringScroll else { return }
            proxy.scrollTo("scroll-bottom", anchor: .bottom)
            try? await Task.sleep(
                for: .milliseconds(ChatHistoryLayoutMetric.streamingFinalizationDelayMilliseconds)
            )
            guard !Task.isCancelled, followsStreamingResponse, !viewModel.hasNewerMessages,
                  !isRestoringScroll else { return }
            proxy.scrollTo("scroll-bottom", anchor: .bottom)
            followsStreamingResponse = false
        }
    }

    private func stopFollowingStreamingResponse() {
        streamingScrollTask?.cancel()
        streamingScrollTask = nil
        followsStreamingResponse = false
    }

    private func scrollSentinel(id: String, edge: ChatScrollSentinelEdge) -> some View {
        Group {
            if #available(iOS 18.0, macOS 15.0, *) {
                Color.clear
            } else {
                GeometryReader { geo in
                    Color.clear.preference(
                        key: ChatScrollSentinelPreferenceKey.self,
                        value: [edge: edge == .top
                            ? geo.frame(in: .named("chat-scroll")).minY
                            : geo.frame(in: .named("chat-scroll")).maxY
                        ]
                    )
                }
            }
        }
        .frame(height: 1)
        .id(id)
    }

    private func resetScrollRestoration() {
        historyNavigationTask?.cancel()
        historyNavigationTask = nil
        historyNavigationID = UUID()
        completedSearchTargetID = nil
        userHasScrolledHistory = false
        hasRestoredInitialScroll = false
        isRestoringScroll = true
        lastReportedVisibleMessageId = nil
        latestVisibleMessageIds = []
        reportedVisibleReceiptIds = []
        pendingVisibleReceiptIds = []
        inFlightVisibleReceiptIds = []
        visibleReceiptAttemptID = UUID()
        scrollPositionDebounceTask?.cancel()
        scrollPositionDebounceTask = nil
        stopFollowingStreamingResponse()
    }

    private func handleAssistantFeedbackSubmit() {
        guard let selectedAssistantRating else { return }
        assistantFeedbackSubmitted = true

        if selectedAssistantRating <= 3 {
            onReportIssue?(.assistantResponseQuality())
        }
    }

    private func restoreInitialScrollIfNeeded(proxy: ScrollViewProxy) {
        guard !hasRestoredInitialScroll, !viewModel.messages.isEmpty else { return }
        hasRestoredInitialScroll = true
        isRestoringScroll = true

        let targetId = viewModel.chat?.lastVisibleMessageId
        let hasTargetMessage = targetId.map { id in viewModel.messages.contains { $0.id == id } } ?? false

        #if DEBUG
        let shouldKeepTopAligned = isUITestChatHistoryAudioParityEnabled || bannerState != nil || isDemoOrLegalChat
        #else
        let shouldKeepTopAligned = bannerState != nil || isDemoOrLegalChat
        #endif

        if shouldKeepTopAligned {
            proxy.scrollTo("scroll-top", anchor: .top)
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=publicTop messages=\(viewModel.messages.count)")
        } else if let targetId, hasTargetMessage {
            proxy.scrollTo(targetId, anchor: UnitPoint(x: 0.5, y: 0.12))
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=saved message=\(targetId.prefix(8)) messages=\(viewModel.messages.count)")
        } else {
            proxy.scrollTo("scroll-top", anchor: .top)
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=noSavedTop messages=\(viewModel.messages.count)")
        }

        let navigationID = historyNavigationID
        let requestedChatID = chatId
        historyNavigationTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 120_000_000)
            guard !Task.isCancelled, historyNavigationID == navigationID,
                  chatId == requestedChatID else { return }
            isRestoringScroll = false
            historyNavigationTask = nil
        }
    }

    private func trackVisibleMessage(_ visibleIds: Set<String>) {
        latestVisibleMessageIds = visibleIds
        reportFinalVisibleMessages(visibleIds)
        guard transcriptIsVisible, !isRestoringScroll, onScrollPositionChanged != nil, !viewModel.messages.isEmpty else { return }
        guard let lastVisibleId = viewModel.messages.last(where: { visibleIds.contains($0.id) })?.id,
              lastVisibleId != lastReportedVisibleMessageId else { return }

        lastReportedVisibleMessageId = lastVisibleId
        let requestedChatID = chatId
        let navigationID = historyNavigationID
        let scope = OfflineStore.shared.scopeGeneration
        scrollPositionDebounceTask?.cancel()
        scrollPositionDebounceTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !Task.isCancelled, transcriptIsVisible, !isRestoringScroll, chatId == requestedChatID,
                  historyNavigationID == navigationID, OfflineStore.shared.scopeGeneration == scope,
                  viewModel.messages.contains(where: { $0.id == lastVisibleId }) else { return }
            onScrollPositionChanged?(lastVisibleId)
            NativeSyncPerfLog.info("phase=chatScrollPositionSend chat=\(chatId.prefix(8)) message=\(lastVisibleId.prefix(8))")
        }
    }

    private func reportFinalVisibleMessages(_ visibleIds: Set<String>) {
        guard transcriptIsVisible, !isRestoringScroll, scenePhase == .active,
              let onFinalMessagesVisible else { return }
        #if os(macOS)
        guard NSApp.isActive else { return }
        #endif
        let finalIds = Set(viewModel.messages.filter {
            visibleIds.contains($0.id) && ($0.role == .assistant || $0.role == .user)
                && $0.isStreaming != true && !viewModel.isStreamingMessage($0.id)
        }.map(\.id))
        pendingVisibleReceiptIds.formUnion(finalIds.subtracting(reportedVisibleReceiptIds))
        let toSend = pendingVisibleReceiptIds.intersection(finalIds)
            .subtracting(reportedVisibleReceiptIds)
            .subtracting(inFlightVisibleReceiptIds)
        guard !toSend.isEmpty else { return }
        pendingVisibleReceiptIds.subtract(toSend)
        inFlightVisibleReceiptIds.formUnion(toSend)
        let requestedChatID = chatId
        let navigationID = historyNavigationID
        let scope = OfflineStore.shared.scopeGeneration
        let attemptID = visibleReceiptAttemptID
        let profile = ServerProfile.current()
        let team = TeamWorkspaceContext.shared.snapshot
        let accountID = authManager.currentUser?.id
        let deletion = OfflineStore.shared.chatDeletionVersion(requestedChatID)
        Task { @MainActor in
            let confirmed = await onFinalMessagesVisible(toSend)
            let acknowledged = confirmed.intersection(toSend)
            guard chatId == requestedChatID, historyNavigationID == navigationID,
                  OfflineStore.shared.scopeGeneration == scope,
                  visibleReceiptAttemptID == attemptID, ServerProfile.current() == profile,
                  authManager.currentUser?.id == accountID, TeamWorkspaceContext.shared.isCurrent(team),
                  OfflineStore.shared.chatDeletionVersion(requestedChatID) == deletion else { return }
            inFlightVisibleReceiptIds.subtract(toSend)
            reportedVisibleReceiptIds.formUnion(acknowledged)
            pendingVisibleReceiptIds.formUnion(toSend.subtracting(acknowledged)
                .subtracting(reportedVisibleReceiptIds))
            if let accountID, viewModel.chat?.teamId == team.teamID, !acknowledged.isEmpty {
                let aliases = viewModel.messages.filter { acknowledged.contains($0.id) }
                    .compactMap(\.serverMessageId)
                await PushNotificationManager.shared.removeAcknowledgedChatNotifications(
                    chatID: requestedChatID, messageIDs: acknowledged.union(aliases),
                    accountID: accountID, profile: profile, scope: scope, team: team, deletion: deletion)
            }
        }
    }

    private func scrollNavButton(isTop: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing2) {
                Icon("dropdown", size: 12)
                    .rotationEffect(isTop ? .degrees(180) : .degrees(0))
                if !isTop && viewModel.newerMessageCount > 0 {
                    Text("\(viewModel.newerMessageCount)")
                        .font(.omXs)
                        .monospacedDigit()
                }
            }
            .foregroundStyle(Color.grey60)
            .frame(width: 120, height: 36)
            .contentShape(RoundedRectangle(cornerRadius: 18))
        }
        .buttonStyle(.plain)
        .opacity(0.7)
        .help(Text(isTop ? AppStrings.scrollToTop : AppStrings.scrollToBottom))
        .accessibilityLabel(isTop ? AppStrings.scrollToTop : AppStrings.scrollToBottom)
        .accessibilityIdentifier(isTop ? "scroll-to-top-button" : "scroll-to-bottom-button")
        .accessibilityValue(!isTop && viewModel.newerMessageCount > 0 ? "\(viewModel.newerMessageCount)" : "")
    }

    private var chatFloatingActions: some View {
        ZStack(alignment: Alignment(horizontal: .chatMoreLeading, vertical: .top)) {
            HStack(spacing: .spacing2) {
                chatFloatingAction(
                    icon: "bug",
                    label: AppStrings.settingsReportIssue,
                    accessibilityIdentifier: "report-issue-button",
                    showsLabel: chatContainerWidth >= 640
                ) {
                    onReportIssue?(.assistantResponseQuality())
                }

                if chatContainerWidth >= 460, onShareChat != nil {
                    chatFloatingAction(icon: "share", label: AppStrings.share, accessibilityIdentifier: "chat-share-button") {
                        onShareChat?()
                    }
                }

                chatMoreTrigger
                    .alignmentGuide(.chatMoreLeading) { dimensions in dimensions[.leading] }
                    .zIndex(chatHeaderMoreOpen ? 2 : 0)

                Spacer(minLength: .spacing6)

                if showEmbedFullscreen && chatWorkspaceWidth >= 1024 {
                    splitChatHideAction
                } else {
                    chatFloatingAction(icon: "close", label: AppStrings.close, accessibilityIdentifier: "chat-close-button") {
                        onCloseChat?()
                    }
                }
            }

            if chatHeaderMoreOpen {
                chatHeaderMoreActions
                    .alignmentGuide(.chatMoreLeading) { dimensions in dimensions[.leading] }
                    .offset(y: 52)
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .topLeading)))
                    .zIndex(3)
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-top-actions")
        .accessibilityValue(chatHeaderActionsOverlapBanner ? "banner-overlay" : "standard")
    }

    private var chatHeaderMoreActions: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if chatContainerWidth < 460, onShareChat != nil {
                chatFloatingMenuAction(icon: "share", label: AppStrings.share, identifier: "chat-more-share-button") {
                    chatHeaderMoreOpen = false
                    onShareChat?()
                }
            }
            if let onOpenChatSettings {
                chatFloatingMenuAction(icon: "settings", label: AppStrings.settings, identifier: "chat-details-button") {
                    chatHeaderMoreOpen = false
                    onOpenChatSettings()
                }
            }
            chatFloatingMenuAction(icon: "reminder", label: AppStrings.setReminder, identifier: "chat-reminders-button") {
                chatHeaderMoreOpen = false
                showReminder = true
            }
        }
        .fixedSize(horizontal: true, vertical: false)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-more-actions")
    }

    private var splitChatHideAction: some View {
        chatFloatingAction(icon: "close", label: AppStrings.close, accessibilityIdentifier: "workspace-hide-chat") {
            hideSplitChat = true
        }
    }

    private var chatMoreTrigger: some View {
        let label = LocalizationManager.shared.text("common.more_actions")
        return NativeHeaderActionPill(icon: "more", label: label,
            overlapsHeader: chatHeaderActionsOverlapBanner,
            accessibilityIdentifier: "chat-more-button") {
            chatHeaderMoreOpen.toggle()
        }
        .contentShape(Circle())
    }

    private func chatFloatingAction(
        icon: String,
        label: String,
        accessibilityIdentifier: String? = nil,
        showsLabel: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        NativeHeaderActionPill(icon: icon, label: label, showsLabel: showsLabel,
            overlapsHeader: chatHeaderActionsOverlapBanner,
            accessibilityIdentifier: accessibilityIdentifier ?? "chat-floating-action-\(icon)", action: action)
    }

    private func chatFloatingMenuAction(
        icon: String,
        label: String,
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        NativeHeaderMenuActionPill(icon: icon, label: label,
            accessibilityIdentifier: identifier, action: action)
    }

    // MARK: - Streaming banner

    private var messageSelectionRuntime: MessageHighlightRuntimeScope? {
        guard authManager.state == .authenticated, let accountID = authManager.currentUser?.id else { return nil }
        return .init(accountID: accountID, scope: OfflineStore.shared.scopeGeneration, server: ServerProfile.current(), team: TeamWorkspaceContext.shared.snapshot)
    }
    private var messageSelectionRuntimeIdentity: String {
        (authManager.currentUser?.id ?? "") + "|" + OfflineStore.shared.scopeGeneration.uuidString + "|" + String(TeamWorkspaceContext.shared.snapshot.epoch)
    }
    private func messageSelectionPolicy(for message: Message) -> MessageSelectionActionPolicy {
        .init(authenticated: authManager.state == .authenticated,
              readOnly: isDemoOrLegalChat || isExampleChat || presentedChat?.isSharedByOthers == true,
              incognito: IncognitoChatSession.isIncognitoChatId(chatId), assistant: message.role == .assistant,
              streaming: message.isStreaming == true || viewModel.isStreamingMessage(message.id))
    }
    private var canMutateMessageHistory: Bool {
        authManager.state == .authenticated && !isDemoOrLegalChat && !isExampleChat
            && presentedChat?.isSharedByOthers != true && presentedChat?.teamId == nil
            && TeamWorkspaceContext.shared.snapshot.teamID == nil
            && !IncognitoChatSession.isIncognitoChatId(chatId) && !viewModel.isStreaming
    }
    private var canForkReadableMessageHistory: Bool {
        guard authManager.state == .authenticated, !isDemoOrLegalChat, !isExampleChat,
              !IncognitoChatSession.isIncognitoChatId(chatId), !viewModel.isStreaming else { return false }
        if let teamID = presentedChat?.teamId { return TeamWorkspaceContext.shared.snapshot.teamID == teamID && ChatKeyManager.shared.hasKey(for: chatId) }
        return presentedChat?.isSharedByOthers != true && TeamWorkspaceContext.shared.snapshot.teamID == nil
    }
    private func beginEditingMessage(_ message: Message) {
        guard canMutateMessageHistory, message.role == .user else { return }
        if editingContextMessage == nil { preEditDraft = messageText }
        editingContextMessage = message; messageText = message.content ?? ""
        selectedMessageText = nil; actionMessage = nil; isInputFocused = true
    }
    private func cancelMessageEdit() {
        messageText = preEditDraft ?? ""; editingContextMessage = nil; preEditDraft = nil
    }
    private func rememberMessage(_ message: Message) {
        guard messageSelectionPolicy(for: message).canHighlight,
              RememberMessageDraft.isForgotten(message, messages: displayedChatMessages,
                checkpoint: compressedMessageBoundary ?? OfflineStore.shared.compressionBoundary(chatID: chatId)) else { return }
        messageText = RememberMessageDraft.append(message.content ?? "", to: messageText)
        selectedMessageText = nil; actionMessage = nil; isInputFocused = true
    }
    private func messageSelectionContext(for message: Message) -> MessageTextSelectionContext? {
        #if DEBUG
        if isolatedHistory { return nil }
        #endif
        return .init(messageID: message.id, highlights: messageHighlights.anchors(chatID: chatId, messageID: message.id),
              onSelectTarget: { nativeMessageSelectionTarget = $0 },
              onSelection: { selection in receiveMessageTextSelection(selection, messageID: message.id) },
              onContextMenu: { selection in selectionHideTask?.cancel(); selectedMessageText = selection; actionMessage = message })
    }
    private func dismissMessageTextSelection() {
        selectionHideTask?.cancel()
        selectedMessageText = nil
        actionMessage = nil
        nativeMessageSelectionTarget?.dismiss()
        nativeMessageSelectionTarget = nil
    }
    private func receiveMessageTextSelection(_ selection: MessageTextSelectionSnapshot?, messageID: String) {
        selectionHideTask?.cancel()
        if let selection { selectedMessageText = selection; return }
        guard selectedMessageText?.messageID == messageID, actionMessage == nil else { return }
        selectionHideTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled, actionMessage == nil else { return }
            selectedMessageText = nil
        }
    }
    private func selectionToolbarPosition(_ selection: MessageTextSelectionSnapshot, geometry: GeometryProxy) -> CGPoint {
        let origin = geometry.frame(in: .global).origin, rect = selection.anchorRect
        let halfWidth = min(340, max(1, geometry.size.width - 16)) / 2
        let x = min(max(halfWidth + 8, (rect?.midX ?? origin.x + geometry.size.width / 2) - origin.x), geometry.size.width - halfWidth - 8)
        let top = (rect?.minY ?? origin.y + 80) - origin.y
        let y = top >= 56 ? top - 28 : (rect?.maxY ?? origin.y + 40) - origin.y + 28
        return .init(x: x, y: min(max(28, y), max(28, geometry.size.height - 28)))
    }
    private func commitMessageHighlight(_ selection: MessageTextSelectionSnapshot, comment: Bool) {
        guard let message = displayedChatMessages.first(where: { $0.id == selection.messageID }), messageSelectionPolicy(for: message).canHighlight else { return }
        selectionHideTask?.cancel(); selectedMessageText = nil; actionMessage = nil
        let runtime = messageSelectionRuntime, source = chatId
        Task {
            do {
                let id = try await messageHighlights.add(chatID: source, messageID: selection.messageID, anchor: selection.anchor)
                guard messageSelectionRuntime == runtime, chatId == source else { return }
                if comment { highlightComment = ""; highlightCommentID = id }
            } catch { ToastManager.shared.show(AppStrings.error, type: .error) }
        }
    }
    private func explainSelectedText(_ selection: MessageTextSelectionSnapshot, message: Message) {
        guard selection.messageID == message.id, messageSelectionPolicy(for: message).canExplain, !selection.explanationTerm.isEmpty else { return }
        let prompt = LocalizationManager.shared.text("chats.explain_in_new_chat.prompt", replacements: ["term": selection.explanationTerm])
        let runtime = messageSelectionRuntime, source = chatId
        selectionHideTask?.cancel(); selectedMessageText = nil; actionMessage = nil
        Task {
            do {
                let result = try await BackgroundChatSender().send(.init(content: prompt, destination: nil))
                guard messageSelectionRuntime == runtime, chatId == source else { return }
                explanationChatID = result.chatId
                ToastManager.shared.show(AppStrings.localized("chats.explain_in_new_chat.started_title.text"), type: .info)
            } catch { ToastManager.shared.show(AppStrings.localized("chats.explain_in_new_chat.failed.text"), type: .error) }
        }
    }
    private func copyMessageLink(_ message: Message) {
        var components = URLComponents(url: ServerProfile.current().webBaseURL, resolvingAgainstBaseURL: false)
        components?.fragment = "chat-id=\(chatId)&message-id=\(message.id)"
        guard let link = components?.url?.absoluteString else { return }
        #if os(iOS)
        UIPasteboard.general.string = link
        #else
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(link, forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.copied, type: .success)
    }

    private func messageActionsOverlay(for message: Message) -> some View {
        ZStack {
            Color.black.opacity(0.28)
                .ignoresSafeArea()
                .onTapGesture(perform: dismissMessageTextSelection)

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(message.role == .user ? "You" : "OpenMates")
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .padding(.horizontal, .spacing4)
                    .padding(.top, .spacing3)

                messageActionRow(icon: "copy", title: AppStrings.copyMessage) {
                    copyMessage(message)
                    actionMessage = nil
                }
                .accessibilityIdentifier("message-action-copy")
                #if os(iOS)
                if nativeMessageSelectionTarget?.messageID == message.id {
                    messageActionRow(icon: "copy", title: AppStrings.localized("chats.context_menu.select.text")) {
                        nativeMessageSelectionTarget?.select(); actionMessage = nil
                    }.accessibilityIdentifier("message-action-select")
                }
                #endif
                if authManager.state == .authenticated && !messageSelectionPolicy(for: message).readOnly {
                    messageActionRow(icon: "link", title: AppStrings.localized("enter_message.press_and_hold_menu.copy_link.text")) {
                        copyMessageLink(message); actionMessage = nil
                    }.accessibilityIdentifier("message-action-copy-link")
                }
                if let selection = selectedMessageText, selection.messageID == message.id,
                   messageSelectionPolicy(for: message).canHighlight {
                    messageActionRow(icon: "quote", title: AppStrings.localized("chats.context_menu.highlight.text")) {
                        commitMessageHighlight(selection, comment: false)
                    }.accessibilityIdentifier("chat-context-highlight")
                    messageActionRow(icon: "quote", title: AppStrings.localized("chats.context_menu.highlight_and_comment.text")) {
                        commitMessageHighlight(selection, comment: true)
                    }.accessibilityIdentifier("chat-context-highlight-and-comment")
                    if messageSelectionPolicy(for: message).canExplain {
                        messageActionRow(icon: "planning", title: AppStrings.localized("chats.context_menu.explain_in_new_chat.text")) {
                            explainSelectedText(selection, message: message)
                        }.accessibilityIdentifier("chat-context-explain-new-chat")
                    }
                }

                if canMutateMessageHistory && message.role == .user {
                    messageActionRow(icon: "edit", title: AppStrings.localized("chats.context_menu.edit.text")) {
                        beginEditingMessage(message)
                    }.accessibilityIdentifier("message-action-edit")
                }
                if messageSelectionPolicy(for: message).canHighlight,
                   RememberMessageDraft.isForgotten(message, messages: displayedChatMessages,
                    checkpoint: compressedMessageBoundary ?? OfflineStore.shared.compressionBoundary(chatID: chatId)) {
                    messageActionRow(icon: "planning", title: AppStrings.localized("chats.context_menu.remember.text")) {
                        rememberMessage(message)
                    }.accessibilityIdentifier("message-action-remember")
                }
                if canSpeakAssistantMessage(message) {
                    messageActionRow(icon: "assistant-speech-audio", title: LocalizationManager.shared.text("chat.assistant_speech.speak_response")) {
                        actionMessage = nil
                        speakAssistantMessage(message)
                    }.accessibilityIdentifier("message-action-speak")
                }

                if canForkReadableMessageHistory {
                    messageActionRow(icon: "copy", title: AppStrings.forkConversation) {
                        actionMessage = nil
                        Task {
                            do {
                                let context = try await viewModel.prepareForkContext(message.id)
                                if let onOpenForkSettings { onOpenForkSettings(context) } else { messageForkContext = context }
                            } catch { ToastManager.shared.show(AppStrings.error, type: .error) }
                        }
                    }.accessibilityIdentifier("message-action-fork")
                }
                if canMutateMessageHistory {
                    if displayedChatMessages.first?.id != message.id {
                        messageActionRow(icon: "delete", title: confirmingMessageDeletionID == message.id
                            ? AppStrings.localized("chats.context_menu.confirm.text") : AppStrings.deleteMessage, isDestructive: true) {
                            guard confirmingMessageDeletionID == message.id else { confirmingMessageDeletionID = message.id; return }
                            Task { await viewModel.deleteMessage(message.id) }; actionMessage = nil
                        }.accessibilityIdentifier("message-action-delete")
                    }
                }

            }
            .padding(.spacing4)
            .frame(minWidth: 140, maxWidth: 260)
            .background(Color.greyBlue)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .shadow(color: .black.opacity(0.22), radius: 16, x: 0, y: 8)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("message-actions-menu")
        }
    }

    private func messageActionRow(
        icon: String,
        title: String,
        isDestructive: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing3) {
                Icon(icon, size: 17)
                    .foregroundStyle(isDestructive ? Color.error : Color.grey100)
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(isDestructive ? Color.error : Color.grey100)
                Spacer()
            }
            .frame(minHeight: 44)
            .padding(.horizontal, .spacing8)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .contentShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
    }

    private func canSpeakAssistantMessage(_ message: Message) -> Bool {
        guard message.role == .assistant, !viewModel.isStreamingMessage(message.id),
              message.isStreaming != true, !IncognitoChatSession.isIncognitoChatId(chatId) else { return false }
        if isDemoOrLegalChat || isExampleChat {
            return !PublicAssistantSpeechManifest.segments(chatID: chatId, nativeMessageID: message.id).isEmpty
        }
        return authManager.state == .authenticated
    }
    private func speakAssistantMessage(_ message: Message) {
        guard canSpeakAssistantMessage(message) else { return }
        if isDemoOrLegalChat || isExampleChat {
            let fixtures = PublicAssistantSpeechManifest.segments(chatID: chatId, nativeMessageID: message.id)
            Task { await AssistantSpeechAppRuntime.shared.playPublicExample(chatID: chatId, messageID: message.id, fixtures: fixtures) }
        } else {
            Task {
                await AssistantSpeechAppRuntime.shared.controller(for: chatId).request(
                    messageID: message.id, markdown: message.content ?? "",
                    mateName: message.senderName ?? "OpenMates", mateCategory: message.category ?? "default")
            }
        }
    }

    private func copyMessage(_ message: Message) {
        let content = selectedMessageText?.messageID == message.id ? selectedMessageText!.copyText : message.content ?? ""
        #if os(iOS)
        UIPasteboard.general.string = content
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(content, forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.copied, type: .success)
    }

    private var streamingBanner: some View {
        Text(streamingStageText)
            .font(.omP)
            .fontWeight(.medium)
            .italic()
            .modifier(ProcessingTextShimmer())
            .frame(maxWidth: .infinity)
            .padding(.horizontal, .spacing8)
            .padding(.bottom, .spacing3)
            .background(
                LinearGradient(
                    colors: [.clear, Color.grey20, Color.grey20],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .accessibilityElement(children: .combine)
            .accessibilityLabel(streamingStageText)
            .accessibilityIdentifier("streaming-banner")
    }

    private var composerStopButton: some View {
        Button {
            viewModel.stopStreaming()
        } label: {
            Icon("stop_processing", size: 28)
                .foregroundStyle(Color.error)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
                .opacity(stopButtonPulsing ? 0.55 : 1)
        }
        .buttonStyle(.plain)
        .help(Text(AppStrings.stopResponse))
        .accessibilityLabel(AppStrings.stopResponse)
        .accessibilityIdentifier("stop-processing-button")
        .onAppear {
            guard !reduceMotion else { return }
            stopButtonPulsing = false
            withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                stopButtonPulsing = true
            }
        }
        .onDisappear { stopButtonPulsing = false }
    }

    // MARK: - New chat CTA (replaces input for demo/intro/legal chats)

    private var newChatCTA: some View {
        Button {
            openNewChat()
        } label: {
            HStack(spacing: .spacing3) {
                Icon("create", size: 18)
                    .foregroundStyle(Color.fontButton)
                Text(AppStrings.newChat)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontButton)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .background(Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("new-chat-button")
        .frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
    }

    // MARK: - Input bar

    private var exampleChatInputRow: some View {
        let composerOpen = isInputFocused || isComposerExpanded
        return VStack(spacing: composerOpen ? .spacing3 : 0) {
            HStack(alignment: .bottom, spacing: composerOpen ? 0 : .spacing3) {
                newChatInlineButton
                    .frame(
                        width: composerOpen ? 0 : (useCompactInlineNewChat ? ChatResponsiveLayoutPolicy.inlineCompactComposerHeight : nil),
                        height: ChatResponsiveLayoutPolicy.inlineCompactComposerHeight
                    )
                    .opacity(composerOpen ? 0 : 1)
                    .clipped()
                    // Clipping bounds drawing only. Bound interaction to this
                    // inline button so adjacent native-editor taps stay editing
                    // taps, including at the leading edge of the compact field.
                    .contentShape(Rectangle())
                    .disabled(composerOpen)
                    .allowsHitTesting(!composerOpen)
                    .accessibilityHidden(composerOpen)

                inputField(
                    compact: !composerOpen && messageText.isEmpty,
                    placeholder: AppStrings.typeFollowup,
                    expandedMinHeight: MessageComposerMetric.expandedMinHeight
                )
            }

            if isInputFocused || isComposerExpanded {
                inputDismissButton
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: ChatResponsiveLayoutPolicy.contentMaximumWidth)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .animation(.easeInOut(duration: 0.25), value: isInputFocused)
    }

    private func insertComposerSearchEmbed(_ result: ComposerEmbedSearchResult) {
        let nodeID = "composer:search:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.controller.setSelection(NSRange(location: composerSession.controller.attributedString.length, length: 0))
            try composerSession.insertPendingEmbed(nodeID: nodeID, embedType: result.nodeType, title: result.title)
            let lifecycle = composerEmbedLifecycle.register(nodeId: nodeID)
            resolveComposerEmbed(nodeID: nodeID, generation: lifecycle.generation, embed: result.pendingReference)
            for record in result.relatedRecords { composerSearchEmbedRecords[record.id] = record }
            composerSearchEmbedRecords[result.id] = result.record
            try composerSession.configureEmbedActions(nodeID: nodeID,
                onOpen: { _ in openEmbedFullscreen(result.record) }, onRetry: { _ in },
                onRemove: { _ in resolvedComposerEmbeds.removeValue(forKey: nodeID) })
            isInputFocused = true
        } catch {
            NativeDiagnostics.error("Composer search reference insertion failed: \(type(of: error))", category: "apple_composer")
        }
    }

    private var inputBar: some View {
        VStack(spacing: .spacing3) {
            if let chatStore, (isInputFocused || composerSearchRecentlyFocused), composerOverlay == nil, !isComposerExpanded,
               !composerHasEmbed, !IncognitoChatSession.isIncognitoChatId(chatId) {
                ComposerSearchSuggestionsHost(store: chatStore,
                    text: ComposerPIIDecorations.visibleText(document: composerSession.controller.document),
                    authenticated: authManager.state == .authenticated, accountID: authManager.currentUser?.id,
                    currentChatID: chatId, prepareMetadata: prepareComposerSearchMetadata,
                    onOpenChat: { id in (onOpenChat ?? onOpenPublicChat)?(id) },
                    onSelectEmbed: insertComposerSearchEmbed)
            }
            subChatBroadcastToggle.frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
            inputField(compact: false, placeholder: AppStrings.typeMessage)
            if isInputFocused || isComposerExpanded { inputDismissButton }
        }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .onChange(of: isInputFocused) { _, focused in
                composerSearchFocusTask?.cancel()
                if focused { composerSearchRecentlyFocused = true }
                else {
                    composerSearchFocusTask = Task { @MainActor in
                        try? await Task.sleep(for: .seconds(3))
                        guard !Task.isCancelled else { return }
                        composerSearchRecentlyFocused = false
                    }
                }
            }
            .onDisappear { composerSearchFocusTask?.cancel(); composerSearchRecentlyFocused = false }
    }

    @ViewBuilder
    private var subChatLifecyclePanel: some View {
        if let request = viewModel.subChatApprovalRequest {
            subChatApprovalCard(request)
        } else if let progress = viewModel.subChatProgress {
            subChatProgressBar(progress)
        }
    }

    @ViewBuilder
    private var returnToParentButton: some View {
        if let parentId = viewModel.chat?.parentId {
            Button {
                onOpenChat?(parentId)
            } label: {
                HStack(spacing: .spacing4) {
                    Icon("arrow-left", size: 14)
                        .foregroundStyle(Color.buttonPrimary)
                    Text(LocalizationManager.shared.text("chat.sub_chats.return_to_parent"))
                        .font(.omXs)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing3)
                .background(Color.grey0)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("return-to-parent-button")
        }
    }

    private func subChatApprovalCard(_ request: SubChatApprovalRequest) -> some View {
        let count = request.subChats?.count ?? 0
        return VStack(alignment: .leading, spacing: .spacing5) {
            Text(LocalizationManager.shared.text("chat.sub_chats.confirmation_title", replacements: ["count": String(count)]))
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
            Text(LocalizationManager.shared.text(
                "chat.sub_chats.confirmation_description",
                replacements: [
                    "auto": String(request.maxAutoSubChats ?? 0),
                    "max": String(request.maxDirectSubChats ?? count)
                ]
            ))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            subChatPromptPreview(request.subChats ?? [])
            HStack(spacing: .spacing4) {
                subChatActionButton(
                    title: LocalizationManager.shared.text("chat.sub_chats.start_all", replacements: ["count": String(count)]),
                    primary: true,
                    identifier: "sub-chat-approve-button"
                ) {
                    Task { await viewModel.approveSubChatRequest() }
                }
                subChatActionButton(
                    title: AppStrings.cancel,
                    primary: false,
                    identifier: "sub-chat-cancel-button"
                ) {
                    Task { await viewModel.cancelSubChatRequest() }
                }
            }
        }
        .padding(.spacing8)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .padding(.horizontal, .spacing8)
        .padding(.bottom, .spacing4)
        .accessibilityIdentifier("sub-chat-approval-card")
    }

    private func subChatPromptPreview(_ subChats: [SpawnedSubChat]) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(subChats.prefix(3)) { child in
                Text(child.title ?? child.prompt)
                    .font(.omXs)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
            }
        }
    }

    private func subChatActionButton(title: String, primary: Bool, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(primary ? Color.fontButton : Color.fontPrimary)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing4)
                .background(primary ? Color.buttonPrimary : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func subChatProgressBar(_ progress: SubChatProgress) -> some View {
        HStack(spacing: .spacing5) {
            Text(subChatProgressLabel(progress))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            Spacer()
            Button {
                Task { await viewModel.stopSubChats() }
            } label: {
                Text(LocalizationManager.shared.text("chat.sub_chats.stop_queue"))
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing3)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("sub-chat-stop-button")
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing4)
        .background(Color.grey0)
        .accessibilityIdentifier("sub-chat-progress-bar")
    }

    @ViewBuilder
    private var subChatBroadcastToggle: some View {
        if viewModel.chat?.isSubChat == true {
            Button {
                broadcastToSiblingSubChats.toggle()
            } label: {
                HStack(spacing: .spacing4) {
                    if broadcastToSiblingSubChats {
                        Icon("select", size: 14)
                            .foregroundStyle(Color.buttonPrimary)
                    } else {
                        Circle()
                            .stroke(Color.fontTertiary, lineWidth: 1.5)
                            .frame(width: 14, height: 14)
                    }
                    Text(LocalizationManager.shared.text("chat.sub_chats.broadcast_to_siblings"))
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("sub-chat-broadcast-toggle")
        }
    }

    private func subChatProgressLabel(_ progress: SubChatProgress) -> String {
        if progress.status == "stopping" {
            return LocalizationManager.shared.text("chat.sub_chats.progress_stopping")
        }
        return LocalizationManager.shared.text(
            "chat.sub_chats.progress_label",
            replacements: [
                "completed": String(progress.completed ?? 0),
                "total": String(progress.total ?? 0)
            ]
        )
    }

    private var fallbackFullscreenComposerHeight: CGFloat {
        #if canImport(UIKit)
        return UIScreen.main.bounds.height * 0.65
        #elseif canImport(AppKit)
        return (NSScreen.main?.visibleFrame.height ?? MessageComposerMetric.expandedMaxHeight) * 0.65
        #else
        return MessageComposerMetric.expandedMaxHeight
        #endif
    }

    private func inputField(compact: Bool, placeholder: String, expandedMinHeight: CGFloat = 100) -> some View {
        let overlayActive = composerOverlay != nil || isUITestRecordingOverlayForced
        let activePIIMatches = detectedPIIMatches.filter { !piiExclusions.contains($0.id) && !piiExcludedValues.contains($0.value) }
        let maximumViewportFieldHeight = max(0, chatViewportHeight - MessageComposerMetric.expandedTopReservedHeight)
        let recordingOverlayActive = composerOverlay == .recording || isUITestRecordingOverlayForced
        let overlayHeight = recordingOverlayActive
            ? ComposerRecordingOverlay.recordingPanelHeight
            : min(400, maximumViewportFieldHeight)
        return VStack(spacing: .spacing2) {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-composer-send"), chatId == "dev-chat-opening-large" {
                Text(viewModel.error == nil ? "ready" : "rejected")
                    .font(.omMicro)
                    .accessibilityIdentifier("composer-send-fixture-outcome")
                    .accessibilityValue(composerSendFixtureDiagnostic)
                if ProcessInfo.processInfo.arguments.contains("--ui-test-composer-processing-recovery") {
                    Button {
                        Task { @MainActor in await viewModel.recoverIsolatedProcessingFixture() }
                    } label: {
                        Text("Recover synthetic processing")
                            .font(.omMicro)
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("composer-processing-recover")
                    .accessibilityValue(viewModel.composerProcessingRecoveryReceipt)
                }
            }
            #endif
            if editingContextMessage != nil {
                HStack {
                    Text(AppStrings.localized("chats.edit_banner.editing.text")).font(.omSmall)
                    Spacer()
                    Button(AppStrings.cancel, action: cancelMessageEdit).buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("message-edit-cancel")
                }.padding(.horizontal, .spacing4).accessibilityIdentifier("message-edit-banner")
            }
            MessageComposerView(
                session: composerSession,
                isFocused: $isInputFocused,
                compact: compact && !overlayActive,
                placeholder: placeholder,
                expandedMinHeight: isComposerExpanded
                    // Web mapped fullscreen fills the chat card, keeping an
                    // outside gutter. Native also reserves the Cancel row.
                    // The 65% policy is only an unmeasured-container fallback.
                    ? (chatViewportHeight > 0 ? maximumViewportFieldHeight
                        : max(expandedMinHeight, fallbackFullscreenComposerHeight))
                    : (overlayActive ? overlayHeight : expandedMinHeight),
                maxWidth: MessageComposerMetric.mainAppMaxWidth,
                accessibilityHint: AppStrings.typeMessage,
                isComposerEditable: deferredComposerSendContexts.isEmpty,
                piiDecorations: ComposerPIIDecorations.nativeDecorations(
                    matches: activePIIMatches,
                    visibleText: composerSession.controller.attributedString.string
                ),
                onExcludePII: { id in excludeComposerPII(id) },
                onSubmit: sendMessage,
                inlineFieldContent: nil,
                idleFieldContent: compact && !overlayActive ? idleFieldControls : nil
            ) {
                if isVerifyingPIISend {
                    ProgressView(AppStrings.enhancedPIIModelVerifying).font(.omXs)
                        .accessibilityIdentifier("composer-pii-verifying")
                }
                PIIWarningBanner(matches: activePIIMatches) {
                    piiExclusions.formUnion(detectedPIIMatches.map(\.id)); piiExcludedValues.formUnion(detectedPIIMatches.map(\.value))
                }

                if enhancedPIIModelController.isDownloadConfigured,
                   enhancedPIIRecommendationStore.shouldRecommend(
                       regexMatches: activePIIMatches,
                       modelStatus: enhancedPIIModelController.status
                   ) {
                    EnhancedPIIModelSuggestionBanner(
                        onDownload: { Task { await enhancedPIIModelController.performPrimaryAction() } },
                        onDismiss: { enhancedPIIRecommendationStore.dismiss() }
                    )
                }

                PIIHighlightStrip(matches: activePIIMatches) { match in
                    excludeComposerPII(match.id)
                }

                if let chatId = viewModel.chat?.id {
                    UploadProgressBar(uploads: pendingUploads.uploadsForChat(chatId))
                }
                if let mentionQuery {
                    MentionDropdownView(
                        query: mentionQuery,
                        onSelect: insertMention,
                        onDismiss: { self.mentionQuery = nil }
                    )
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, .spacing5)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            } overlayContent: {
                if let overlay = composerOverlayView() {
                    overlay
                }
            } actionButtons: {
                GeometryReader { actionGeometry in
                    ComposerAttachmentActionRow(viewportWidth: actionGeometry.size.width,
                        onDrawing: {
                            #if os(iOS)
                            withAnimation(.easeInOut(duration: 0.2)) { composerOverlay = .sketch; isInputFocused = false }
                            #else
                            ToastManager.shared.show(AppStrings.sketchAction, type: .info)
                            #endif
                        },
                        onLocation: { withAnimation(.easeInOut(duration: 0.2)) { composerOverlay = .location; isInputFocused = false } },
                        onCamera: {
                            #if os(iOS)
                            showCameraCapture = true
                            #endif
                        }, onFiles: { showAttachmentMenu = true },
                        model: { NativeComposerModelHostView(host: modelHost, viewportWidth: actionGeometry.size.width) }, speech: { ComposerSpeechHostView(chatID: chatId, supported: !IncognitoChatSession.isIncognitoChatId(chatId)) }, record: { recordActionControls }, submit: {
                if isStreamingPresentationActive {
                    composerStopButton
                } else if !messageText.isEmpty || viewModel.hasPendingComposerEmbeds || composerHasEmbed {
                    MessageComposerSendButton(
                        title: AppStrings.sendAction,
                        disabled: isVerifyingPIISend || (messageText.isEmpty && !viewModel.hasPendingComposerEmbeds && !composerHasEmbed),
                        accessibilityLabel: AppStrings.sendMessage,
                        action: sendMessage
                    )
                    .accessibilityHint(AppStrings.typeMessage)
                    #if os(macOS)
                    .keyboardShortcut(.return, modifiers: .command)
                    #endif
                }
                        })
                        .background {
                            AttachmentPicker(isPresented: $showAttachmentMenu,
                                onImageSelected: { data, name in enqueueAttachmentUpload(data: data, filename: name) },
                                onFileSelected: { data, name in enqueueAttachmentUpload(data: data, filename: name) }, externalFilesOnly: true)
                        }
                }.frame(height: 56)

            }
            .environment(\.composerFieldMaximumHeight, chatViewportHeight > 0 ? maximumViewportFieldHeight : nil)
            .environment(\.composerFullscreen, isComposerExpanded)
            .environment(\.composerFullscreenControlHandler,
                ComposerFullscreenControlHandler(isEnabled: !overlayActive, action: {
                    isComposerExpanded.toggle()
                    isInputFocused = false
                }))

            if let queuedMessageText = viewModel.streamingLifecycle.queuedMessageText {
                Text(queuedMessageText)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing2)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .padding(.horizontal, .spacing5)
                    .accessibilityIdentifier("queued-message-indicator")
            }

            if let recordPermissionHintText {
                Text(recordPermissionHintText)
                    .font(.omXs)
                    .foregroundStyle(micPermissionState == .denied ? Color.error : Color.fontTertiary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.horizontal, .spacing5)
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
    }

    private func composerOverlayView() -> AnyView? {
        #if DEBUG
        if composerOverlay == nil, isUITestRecordingOverlayForced {
            return recordingOverlayView()
        }
        #endif
        guard let composerOverlay else { return nil }
        switch composerOverlay {
        case .location:
            return AnyView(
                ComposerLocationOverlay(
                    isFullscreen: $isComposerExpanded,
                    onShare: insertSharedLocation,
                    onCancel: { self.composerOverlay = nil }
                )
            )
        case .sketch:
            #if os(iOS)
            return AnyView(
                SketchComposerOverlay(
                    isFullscreen: $isComposerExpanded,
                    onSave: { data, filename in
                        self.composerOverlay = nil
                        enqueueAttachmentUpload(data: data, filename: filename)
                    },
                    onCancel: { self.composerOverlay = nil }
                )
            )
            #else
            return nil
            #endif
        case .recording:
            return recordingOverlayView()
        }
    }

    private func recordingOverlayView() -> AnyView {
        AnyView(
            ComposerRecordingOverlay(
                recorder: composerRecorder,
                dragOffsetX: recordDragOffsetX,
                startedFromKeyboard: recordStartedFromKeyboard,
                liveTranscript: recordingLiveTranscript,
                isRealtimeConnecting: recordingRealtimeConnecting,
                onStop: { url in
                    let duration = composerRecorder.duration
                    let uploadContext = finishRealtimeRecording(duration: duration)
                    self.composerOverlay = nil
                    self.recordAttemptActive = false
                    self.recordStartedFromKeyboard = false
                    self.recordDragOffsetX = 0
                    dismissChatKeyboardForRecording(afterCurrentGesture: true)
                    enqueueRecordingUpload(
                        url: url,
                        duration: duration,
                        waveform: uploadContext.waveform,
                        realtimeResult: uploadContext.realtimeResult,
                        realtimeSession: uploadContext.realtimeSession
                    )
                },
                onCancel: {
                    composerRecorder.cancelRecording()
                    cancelRealtimeRecording()
                    self.composerOverlay = nil
                    self.recordAttemptActive = false
                    self.recordStartedFromKeyboard = false
                    self.recordDragOffsetX = 0
                    dismissChatKeyboardForRecording(afterCurrentGesture: true)
                },
                onFailure: {
                    composerRecorder.cancelRecording()
                    cancelRealtimeRecording()
                    self.composerOverlay = nil
                    self.recordAttemptActive = false
                    self.recordStartedFromKeyboard = false
                    self.recordDragOffsetX = 0
                    dismissChatKeyboardForRecording(afterCurrentGesture: true)
                    showRecordHint(duration: 0)
                }
            )
        )
    }

    private var isUITestRecordingOverlayForced: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay")
            || ProcessInfo.processInfo.arguments.contains("--ui-test-force-keyboard-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_RECORDING_OVERLAY"] == "1"
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_KEYBOARD_RECORDING_OVERLAY"] == "1"
        #else
        return false
        #endif
    }

    private var isUITestKeyboardRecordingOverlayForced: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("--ui-test-force-keyboard-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_KEYBOARD_RECORDING_OVERLAY"] == "1"
        #else
        return false
        #endif
    }

    private func applyUITestRecordingOverlayIfNeeded() {
        #if DEBUG
        guard isUITestRecordingOverlayForced else { return }
        micPermissionState = .granted
        recordStartedFromKeyboard = isUITestKeyboardRecordingOverlayForced
        composerOverlay = .recording
        isInputFocused = false
        #endif
    }

    private var newChatInlineButton: some View {
        Button {
            openNewChat()
        } label: {
            HStack(spacing: .spacing4) {
                Icon("create", size: 20)
                    .foregroundStyle(Color.fontButton)
                if !useCompactInlineNewChat {
                    Text(AppStrings.newChat)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontButton)
                }
            }
            .frame(width: useCompactInlineNewChat ? 48 : nil, height: 48)
            .padding(.horizontal, useCompactInlineNewChat ? 0 : .spacing8)
            .background(Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .help(Text(AppStrings.newChat))
        .accessibilityLabel(AppStrings.newChat)
        .accessibilityIdentifier("new-chat-button")
    }

    private func enqueueAttachmentUpload(data: Data, filename: String) {
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: composerEmbedType(for: filename),
                title: filename,
                localPreviewData: data
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in
                    Task { @MainActor in retryAttachmentUpload(nodeID: nodeID, data: data, filename: filename) }
                },
                onRemove: { durableID in handleComposerEmbedRemoval(nodeID: nodeID, durableID: durableID) }
            )
            guard transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .uploading
            ) != nil else { return }
        } catch {
            NativeDiagnostics.error("Composer attachment insertion failed: \(type(of: error))", category: "apple_composer")
            return
        }

        guard let generation = composerEmbedLifecycle.record(nodeId: nodeID)?.generation else { return }
        Task { @MainActor in
            guard let embed = await viewModel.uploadAttachment(
                data: data,
                filename: filename,
                trackingId: nodeID
            ) else {
                _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
                return
            }
            resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
        }
    }

    private func insertSharedLocation(_ selection: ComposerLocationSelection) {
        let embed = selection.makePendingEmbed()
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "maps",
                title: selection.name
            )
            try composerSession.resolveEmbed(
                nodeID: nodeID,
                durableEmbedID: embed.id,
                referenceType: embed.referenceType,
                status: AppleComposerEmbedLifecycleState.finished.rawValue,
                embedRecord: embed.record
            )
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in },
                onRemove: { _ in resolvedComposerEmbeds.removeValue(forKey: nodeID) }
            )
            resolvedComposerEmbeds[nodeID] = embed
            composerOverlay = nil
        } catch {
            NativeDiagnostics.error(
                "Composer location insertion failed: \(type(of: error))",
                category: "apple_composer"
            )
        }
    }

    private func retryAttachmentUpload(nodeID: String, data: Data, filename: String) {
        guard let generation = retryComposerEmbed(nodeID: nodeID, to: .uploading) else { return }
        Task { @MainActor in
            guard let embed = await viewModel.uploadAttachment(
                data: data,
                filename: filename,
                trackingId: nodeID
            ) else {
                _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
                return
            }
            resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
        }
    }

    private func enqueueRecordingUpload(
        url: URL,
        duration: TimeInterval,
        waveform: AudioRecordingWaveform? = nil,
        realtimeResult: AudioRecordingRealtimeResultProvider? = nil,
        realtimeSession: AudioRecordingRealtimeSession? = nil
    ) {
        let uploadChatID = chatId
        let uploadScope = AudioRecordingUploadScope.capture()
        let localTranscription = realtimeSession?.usesLocalTranscription == true
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        recordingTemporaryFiles[nodeID] = url
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "recording",
                title: AppStrings.audioRecording,
                localPreviewData: try? Data(contentsOf: url)
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in
                    guard uploadScope.isCurrent, chatId == uploadChatID else { return }
                    recordingUploadTasks[nodeID] = Task { @MainActor in
                        await retryRecordingUpload(nodeID: nodeID, url: url, duration: duration, waveform: waveform, realtimeResult: realtimeResult,
                            localTranscription: localTranscription)
                        recordingUploadTasks[nodeID] = nil
                    }
                },
                onRemove: { durableID in handleComposerEmbedRemoval(nodeID: nodeID, durableID: durableID) }
            )
            guard transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .uploading
            ) != nil,
            transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .transcribing
            ) != nil else {
                removeRecordingTemporaryFile(nodeID: nodeID)
                return
            }
        } catch {
            removeRecordingTemporaryFile(nodeID: nodeID)
            NativeDiagnostics.error("Composer recording insertion failed: \(type(of: error))", category: "apple_composer")
            return
        }

        guard let generation = composerEmbedLifecycle.record(nodeId: nodeID)?.generation else {
            removeRecordingTemporaryFile(nodeID: nodeID)
            return
        }
        realtimeSession?.observeRawTranscript { transcript in
            guard uploadScope.isCurrent, chatId == uploadChatID,
                  transitionComposerEmbed(
                nodeID: nodeID,
                generation: generation,
                to: .correcting
            ) != nil else { return }
            try? composerSession.updatePendingEmbedTitle(nodeID: nodeID, title: transcript)
        }
        recordingUploadTasks[nodeID] = Task { @MainActor in
            let embed = await viewModel.uploadRecording(
                url: url,
                duration: duration,
                waveform: waveform,
                realtimeResult: realtimeResult,
                localTranscription: localTranscription,
                trackingId: nodeID
            )
            recordingUploadTasks[nodeID] = nil
            guard !Task.isCancelled, uploadScope.isCurrent, chatId == uploadChatID else {
                if let embed { viewModel.removePendingComposerEmbed(id: embed.id) }
                removeRecordingTemporaryFile(nodeID: nodeID)
                return
            }
            guard let embed else {
                _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
                return
            }
            try? composerSession.updatePendingEmbedTitle(
                nodeID: nodeID,
                title: embed.textPreview.flatMap { $0.isEmpty ? nil : $0 } ?? AppStrings.audioRecording
            )
            resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
            removeRecordingTemporaryFile(nodeID: nodeID)
        }
    }

    private func retryRecordingUpload(nodeID: String, url: URL, duration: TimeInterval,
                                      waveform: AudioRecordingWaveform? = nil,
                                      realtimeResult: AudioRecordingRealtimeResultProvider? = nil,
                                      localTranscription: Bool = false) async {
        let uploadChatID = chatId
        let uploadScope = AudioRecordingUploadScope.capture()
        guard let generation = retryComposerEmbed(nodeID: nodeID, to: .transcribing) else { return }
        guard let embed = await viewModel.uploadRecording(
            url: url,
            duration: duration,
            waveform: waveform,
            realtimeResult: realtimeResult,
            localTranscription: localTranscription,
            trackingId: nodeID
        ) else {
            _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
            return
        }
        guard uploadScope.isCurrent, chatId == uploadChatID, !Task.isCancelled else {
            viewModel.removePendingComposerEmbed(id: embed.id)
            return
        }
        resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
        removeRecordingTemporaryFile(nodeID: nodeID)
    }

    private func resolveComposerEmbed(nodeID: String, generation: Int, embed: ComposerPendingEmbed) {
        if let current = composerEmbedLifecycle.record(nodeId: nodeID),
           (current.generation != generation || current.state == .cancelled) {
            // The service may have registered a stale result before this callback.
            // Remove it from the send boundary without recreating the visible atom.
            viewModel.removePendingComposerEmbed(id: embed.id)
            return
        }
        let state = AppleComposerEmbedLifecycleState(rawValue: embed.status) ?? .finished
        guard transitionComposerEmbed(
            nodeID: nodeID,
            generation: generation,
            to: state,
            durableEmbedID: embed.id
        ) != nil else { return }
        do {
            try composerSession.resolveEmbed(
                nodeID: nodeID,
                durableEmbedID: embed.id,
                referenceType: embed.referenceType,
                status: state.rawValue,
                embedRecord: embed.record,
                localPreviewData: embed.localData
            )
            resolvedComposerEmbeds[nodeID] = embed
        } catch {
            NativeDiagnostics.error("Composer attachment resolution failed: \(type(of: error))", category: "apple_composer")
        }
    }

    @discardableResult
    private func transitionComposerEmbed(
        nodeID: String,
        generation: Int,
        to state: AppleComposerEmbedLifecycleState,
        durableEmbedID: String? = nil
    ) -> ComposerEmbedLifecycleRecord? {
        guard case .applied(let record) = composerEmbedLifecycle.transition(
            nodeId: nodeID,
            generation: generation,
            to: state,
            durableEmbedId: durableEmbedID
        ) else { return nil }
        do {
            try composerSession.updateEmbed(nodeID: nodeID, status: state.rawValue)
        } catch {
            NativeDiagnostics.error("Composer embed lifecycle update failed: \(type(of: error))", category: "apple_composer")
            return nil
        }
        reportComposerEmbedState(record)
        return record
    }

    private func retryComposerEmbed(
        nodeID: String,
        to state: AppleComposerEmbedLifecycleState
    ) -> Int? {
        guard let current = composerEmbedLifecycle.record(nodeId: nodeID),
              case .applied(let record) = composerEmbedLifecycle.retry(
                  nodeId: nodeID,
                  generation: current.generation,
                  to: state
              ) else { return nil }
        do {
            try composerSession.updateEmbed(nodeID: nodeID, status: state.rawValue)
        } catch {
            NativeDiagnostics.error("Composer embed retry update failed: \(type(of: error))", category: "apple_composer")
            return nil
        }
        let requestIDs = Array(deferredComposerSendContexts.keys)
        Task { @MainActor in
            for requestID in requestIDs {
                await composerPendingSendCoordinator.replaceBlockerGeneration(
                    requestId: requestID,
                    nodeId: nodeID,
                    generation: record.generation
                )
            }
            await composerPendingSendCoordinator.updateNode(
                nodeId: record.nodeId,
                generation: record.generation,
                state: record.state
            )
            await resumeDeferredComposerSends()
        }
        return record.generation
    }

    private func handleComposerEmbedRemoval(nodeID: String, durableID: String) {
        recordingUploadTasks.removeValue(forKey: nodeID)?.cancel()
        removeRecordingTemporaryFile(nodeID: nodeID)
        PendingUploadStore.shared.cancelUpload(id: nodeID)
        if let current = composerEmbedLifecycle.record(nodeId: nodeID),
           case .applied(let record) = composerEmbedLifecycle.remove(
               nodeId: nodeID,
               generation: current.generation
           ) {
            reportComposerEmbedState(record)
        }
        viewModel.removePendingComposerEmbed(id: durableID)
        Task { await invalidateDeferredComposerSends() }
    }

    private func removeRecordingTemporaryFile(nodeID: String) {
        guard let url = recordingTemporaryFiles.removeValue(forKey: nodeID) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    private func reportComposerEmbedState(_ record: ComposerEmbedLifecycleRecord) {
        Task { @MainActor in
            await composerPendingSendCoordinator.updateNode(
                nodeId: record.nodeId,
                generation: record.generation,
                state: record.state
            )
            await resumeDeferredComposerSends()
        }
    }

    private func queueDeferredComposerSend(document: ComposerDocumentV1) {
        guard let destinationID = viewModel.chat?.id,
              !deferredComposerSendRevisions.contains(composerSession.revision) else { return }
        let blockers = composerBlockers(in: document)
        guard !blockers.isEmpty else { return }
        let blockerNodeIDs = Set(blockers.map(\.nodeId))
        guard !deferredComposerSendNodeIDs.values.contains(where: { !$0.isDisjoint(with: blockerNodeIDs) }) else {
            return
        }

        let requestID = UUID().uuidString.lowercased()
        let snapshot = ComposerSendSnapshot(
            requestId: requestID,
            messageId: UUID().uuidString.lowercased(),
            destinationId: destinationID,
            documentRevision: composerSession.revision,
            document: document,
            blockers: blockers
        )
        deferredComposerSendRevisions.insert(snapshot.documentRevision)
        deferredComposerSendContexts[requestID] = ComposerDeferredSendContext(
            excludedPIIIds: piiExclusions,
            excludedPIIOriginals: excludedPIIOriginals(in: document, excludedIds: piiExclusions),
            broadcastToSiblings: broadcastToSiblingSubChats,
            owner: ComposerModelSendOwnership(
                server: ServerProfile.current().apiBaseURL.absoluteString,
                accountGeneration: OfflineStore.shared.scopeGeneration,
                chatID: destinationID
            )
        )
        deferredComposerSendNodeIDs[requestID] = Set(document.nodes.map(\.id))
        viewModel.error = nil

        Task { @MainActor in
            guard await composerPendingSendCoordinator.enqueue(snapshot) else {
                deferredComposerSendRevisions.remove(snapshot.documentRevision)
                deferredComposerSendContexts.removeValue(forKey: requestID)
                deferredComposerSendNodeIDs.removeValue(forKey: requestID)
                return
            }
            await resumeDeferredComposerSends()
        }
    }

    private func composerBlockers(in document: ComposerDocumentV1) -> [ComposerEmbedBlocker] {
        document.nodes.compactMap { node in
            guard node.kind == "embed",
                  let status = node.status,
                  let state = AppleComposerEmbedLifecycleState(rawValue: status),
                  ComposerEmbedLifecycle.isBlocking(state) else { return nil }
            let record = composerEmbedLifecycle.record(nodeId: node.id)
                ?? composerEmbedLifecycle.register(nodeId: node.id, state: state)
            reportComposerEmbedState(record)
            return ComposerEmbedBlocker(nodeId: node.id, generation: record.generation)
        }
    }

    private func resumeDeferredComposerSends() async {
        guard piiComposerForeground else { return }
        let connectedEpoch = deferredSocketConnectedEpoch
        await composerPendingSendCoordinator.resumeReady { snapshot in
            try await dispatchDeferredComposerSend(snapshot)
        }
        // A reconnect can finish while the coordinator still marks a send as
        // dispatching. Its retry call then sees no failed entry yet. Once that
        // in-flight dispatch settles, retry any failure from this transition.
        if deferredSocketConnectedEpoch != connectedEpoch, viewModel.isSendTransportReady {
            for requestID in Array(deferredComposerSendContexts.keys) {
                _ = await composerPendingSendCoordinator.retryFailed(requestId: requestID)
            }
            await composerPendingSendCoordinator.resumeReady { snapshot in
                try await dispatchDeferredComposerSend(snapshot)
            }
        }
    }

    private func retryDeferredComposerSendIfNeeded() -> Bool {
        guard !deferredComposerSendContexts.isEmpty else { return false }
        Task { @MainActor in
            await retryDeferredComposerSendsAfterReconnect()
        }
        return true
    }

    @MainActor
    private func retryDeferredComposerSendsAfterReconnect() async {
        guard viewModel.isSendTransportReady, piiComposerForeground else { return }
        for requestID in Array(deferredComposerSendContexts.keys) {
            _ = await composerPendingSendCoordinator.retryFailed(requestId: requestID)
        }
        await resumeDeferredComposerSends()
    }

    @MainActor
    private func dispatchDeferredComposerSend(_ snapshot: ComposerSendSnapshot) async throws {
        guard var context = deferredComposerSendContexts[snapshot.requestId] else {
            throw ComposerDeferredSendError.missingContext
        }
        guard context.owner.matches(
            server: ServerProfile.current().apiBaseURL.absoluteString,
            accountGeneration: OfflineStore.shared.scopeGeneration,
            chatID: viewModel.chat?.id
        ) else { throw ComposerDeferredSendError.missingContext }
        guard viewModel.isSendTransportReady else { throw ComposerDeferredSendError.transportUnavailable }
        let snapshotNodeIDs = deferredComposerSendNodeIDs[snapshot.requestId] ?? []
        if context.embedSnapshot == nil {
            guard let embedSnapshot = ComposerDeferredEmbedSnapshot(
                document: snapshot.document,
                resolvedEmbeds: resolvedComposerEmbeds
            ) else { throw ComposerDeferredSendError.missingEmbed }
            context.embedSnapshot = embedSnapshot
            deferredComposerSendContexts[snapshot.requestId] = context
        }
        let embeds = context.embedSnapshot?.embeds ?? []
        let excludedOriginals = context.excludedPIIOriginals
        let rewriteMappings = PIIDetector.mergePIIMappings(cumulativePIIMappings + embeds.flatMap(\.piiMappings))
        let rewrite = ComposerPIIDecorations.rewriteKnownPIIPlaceholders(
            document: snapshot.document,
            mappings: rewriteMappings,
            excludedOriginals: excludedOriginals
        )
        let sendOptions = piiPrivacySettingsStore.detectionOptions()
        let redaction = await piiDetectionCoordinator.verifiedRedaction(
            document: rewrite.document, excludedIds: context.excludedPIIIds,
            excludedOriginals: excludedOriginals, options: sendOptions,
            context: ComposerPIIContext(server: context.owner.server,
                accountGeneration: context.owner.accountGeneration, routeID: context.owner.chatID))
        guard context.owner.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
            accountGeneration: OfflineStore.shared.scopeGeneration, chatID: viewModel.chat?.id),
            sendOptions == piiPrivacySettingsStore.detectionOptions(), piiComposerForeground else { throw CancellationError() }
        let markdown = try ComposerMarkdownAdapter.serialize(redaction.document)
        let piiMappings = PIIDetector.mergePIIMappings(rewrite.appliedMappings + redaction.mappings)
        viewModel.error = nil
        let accepted = await viewModel.sendMessage(
            markdown,
            piiMappings: piiMappings,
            excludedPIIOriginals: excludedOriginals,
            broadcastToSiblings: context.broadcastToSiblings,
            composerEmbeds: embeds,
            messageId: snapshot.messageId
        )
        guard accepted, viewModel.error == nil else { throw ComposerDeferredSendError.sendFailed }

        // Delivery has already succeeded. A local editor cleanup failure must not
        // turn this into a network retry with the same accepted message.
        do {
            try composerSession.removeSentSnapshotNodes(snapshot.document)
        } catch {
            NativeDiagnostics.error("Composer sent snapshot cleanup failed: \(type(of: error))", category: "apple_composer")
        }
        if composerSession.canonicalMarkdown.isEmpty { dismissAcceptedComposer() }
        detectedPIIMatches = []
        piiExclusions = []
        piiExcludedValues = []
        mentionQuery = nil
        deferredComposerSendRevisions.remove(snapshot.documentRevision)
        deferredComposerSendContexts.removeValue(forKey: snapshot.requestId)
        deferredComposerSendNodeIDs.removeValue(forKey: snapshot.requestId)
        for nodeID in snapshotNodeIDs {
            resolvedComposerEmbeds.removeValue(forKey: nodeID)
        }
        try? await DraftService.shared.clearDraft(chatId: snapshot.destinationId)
    }

    @MainActor
    private func invalidateDeferredComposerSends() async {
        deferredComposerSendContexts.removeAll()
        deferredComposerSendNodeIDs.removeAll()
        resolvedComposerEmbeds.removeAll()
        deferredComposerSendRevisions.removeAll()
        await composerPendingSendCoordinator.invalidateAllForTermination()
    }

    #if DEBUG
    private func insertResolvedUITestEmbed(_ embed: ComposerPendingEmbed) {
        let nodeID = "composer:embed:ui-test"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "image",
                title: embed.filename,
                localPreviewData: embed.localData
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            resolveComposerEmbed(nodeID: nodeID, generation: record.generation, embed: embed)
        } catch {
            NativeDiagnostics.error("Composer UI fixture insertion failed: \(type(of: error))", category: "apple_composer")
        }
    }
    #endif

    private func composerEmbedType(for filename: String) -> String {
        switch URL(fileURLWithPath: filename).pathExtension.lowercased() {
        case "jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "svg": return "image"
        case "pdf": return "pdf"
        case "m4a", "mp4", "webm", "ogg", "mp3", "wav", "aac": return "recording"
        default: return "docs-doc"
        }
    }

    private var useCompactInlineNewChat: Bool {
        if chatContainerWidth > 0 {
            return chatContainerWidth <= ChatResponsiveLayoutPolicy.inlineNewChatCompact
        }
        return sizeClass == .compact
    }

    private func openNewChat() {
        if let onNewChat {
            onNewChat()
        } else {
            NotificationCenter.default.post(name: .newChat, object: nil)
        }
    }

    private var inputDismissButton: some View {
        Button {
            flushEncryptedDraft()
            dismissInputIfNeeded()
        } label: {
            ComposerDismissLabel(title: messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("chat-composer-cancel")
        .help(Text(messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft))
        .accessibilityLabel(messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft)
    }

    private var recordActionControls: some View {
        HStack(spacing: .spacing4) {
            if recordHintVisible && micPermissionState == .granted {
                Text(AppStrings.pressAndHoldToRecord)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontTertiary)
                    .lineLimit(1)
                    .transition(.opacity)
                    .accessibilityIdentifier("press-hold-label")
            }

            recordGestureButton
        }
    }

    private var recordGestureButton: some View {
        Button(action: { startRecordFromControlIfNeeded() }) {
            Icon("recordaudio", size: 25)
                .foregroundStyle(recordAttemptActive ? AnyShapeStyle(Color.error) : AnyShapeStyle(LinearGradient.primary))
                .frame(width: 25, height: 25)
        }
            .buttonStyle(.plain)
            .contentShape(Circle())
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        handleRecordGestureChanged(value)
                    }
                    .onEnded { _ in }
            )
            .help(Text(AppStrings.recordAudio))
            .accessibilityLabel(AppStrings.recordAudio)
            .accessibilityIdentifier("record-audio-button")
    }

    // Match the web example-chat composer before the field is focused.
    // Spec: specifications/features/message-input/specification.yml (message-input.actions.visibility).
    private var idleFieldControls: AnyView {
        AnyView(ComposerIdleFieldControls {
            if isStreamingPresentationActive {
                composerStopButton
            } else {
                recordGestureButton
            }
        })
    }

    private var recordPermissionHintText: String? {
        if micPermissionState == .denied {
            return AppStrings.microphoneBlocked
        }
        if recordHintVisible && micPermissionState != .granted {
            return AppStrings.allowMicrophoneAccess
        }
        return nil
    }

    private func dismissInputIfNeeded() {
        guard isInputFocused || isComposerExpanded else { return }
        isInputFocused = false
        isComposerExpanded = false
        showAttachmentMenu = false
    }

    private func handleRecordGestureChanged(_ value: DragGesture.Value) {
        startRecordFromControlIfNeeded(startLocation: value.startLocation)
    }

    private func startRecordFromControlIfNeeded(startLocation: CGPoint = .zero) {
        guard !recordAttemptActive, composerOverlay != .recording else { return }
        beginRecordAttempt(startLocation: startLocation)
    }

    private func prepareRealtimeRecording() {
        recordingLiveTranscript = ""
        recordingRealtimeConnecting = false
        composerRecorder.setPCMHandler(nil)
        guard authManager.state == .authenticated else {
            activeRecordingRealtimeSession = nil
            return
        }
        let session = AudioRecordingRealtimeSession()
        activeRecordingRealtimeSession = session
        session.begin(authManager: authManager, chatID: chatId) { transcript, isConnecting in
            guard activeRecordingRealtimeSession === session else { return }
            recordingLiveTranscript = transcript
            recordingRealtimeConnecting = isConnecting
        }
        composerRecorder.setPCMHandler { [weak session] samples, sampleRate in
            session?.append(samples: samples, sampleRate: sampleRate)
        }
    }

    private func finishRealtimeRecording(
        duration: TimeInterval
    ) -> (
        waveform: AudioRecordingWaveform?,
        realtimeResult: AudioRecordingRealtimeResultProvider?,
        realtimeSession: AudioRecordingRealtimeSession?
    ) {
        let waveform = composerRecorder.recordingWaveform(duration: duration)
        composerRecorder.setPCMHandler(nil)
        guard let session = activeRecordingRealtimeSession else {
            return (waveform, nil, nil)
        }
        session.finish()
        activeRecordingRealtimeSession = nil
        recordingLiveTranscript = ""
        recordingRealtimeConnecting = false
        let provider: AudioRecordingRealtimeResultProvider = { [session] in
            await session.awaitResult()
        }
        return (waveform, provider, session)
    }

    private func cancelRealtimeRecording() {
        composerRecorder.setPCMHandler(nil)
        guard let session = activeRecordingRealtimeSession else { return }
        activeRecordingRealtimeSession = nil
        recordingLiveTranscript = ""
        recordingRealtimeConnecting = false
        Task { await session.cancel() }
    }

    private func beginRecordAttempt(startLocation _: CGPoint) {
        dismissChatKeyboardForRecording()
        recordStartedFromKeyboard = false
        recordAttemptActive = true
        recordDragOffsetX = 0
        recordStartTask?.cancel()

        if micPermissionState == .denied {
            showRecordHint()
            return
        }

        if micPermissionState == .unknown {
            Task { @MainActor in
                let granted = await composerRecorder.requestPermission()
                micPermissionState = granted ? .granted : .denied
                if granted && recordAttemptActive {
                    beginRecordAttempt(startLocation: .zero)
                } else {
                    recordAttemptActive = false
                    showRecordHint(duration: granted ? 2500 : 0)
                }
            }
            return
        }

        prepareRealtimeRecording()
        composerRecorder.startRecording()
        guard composerRecorder.error == nil else {
            cancelRealtimeRecording()
            micPermissionState = .denied
            recordAttemptActive = false
            showRecordHint(duration: 0)
            return
        }
        withAnimation(.easeInOut(duration: 0.15)) {
            composerOverlay = .recording
            isInputFocused = false
        }
        dismissChatKeyboardForRecording(afterCurrentGesture: true)
    }

    private func finishRecordAttempt() {
        recordStartTask?.cancel()
        recordStartTask = nil

        if composerOverlay == .recording, let url = composerRecorder.stopRecording() {
            let duration = composerRecorder.duration
            let uploadContext = finishRealtimeRecording(duration: duration)
            composerOverlay = nil
            recordAttemptActive = false
            recordStartedFromKeyboard = false
            recordDragOffsetX = 0
            dismissChatKeyboardForRecording(afterCurrentGesture: true)
            enqueueRecordingUpload(
                url: url,
                duration: duration,
                waveform: uploadContext.waveform,
                realtimeResult: uploadContext.realtimeResult,
                realtimeSession: uploadContext.realtimeSession
            )
            return
        }

        if recordAttemptActive && micPermissionState == .granted {
            showRecordHint()
        }
        recordAttemptActive = false
        recordStartedFromKeyboard = false
        recordDragOffsetX = 0
        dismissChatKeyboardForRecording(afterCurrentGesture: true)
    }

    private func cancelRecordAttempt() {
        recordStartTask?.cancel()
        recordStartTask = nil
        composerRecorder.cancelRecording()
        cancelRealtimeRecording()
        composerOverlay = nil
        recordAttemptActive = false
        recordStartedFromKeyboard = false
        recordDragOffsetX = 0
        dismissChatKeyboardForRecording(afterCurrentGesture: true)
    }

    private func beginKeyboardRecordAttempt() {
        dismissChatKeyboardForRecording()
        recordStartedFromKeyboard = true
        recordAttemptActive = true
        recordDragOffsetX = 0
        recordStartTask?.cancel()

        if micPermissionState == .denied {
            showRecordHint()
            return
        }

        if micPermissionState == .unknown {
            Task { @MainActor in
                let granted = await composerRecorder.requestPermission()
                micPermissionState = granted ? .granted : .denied
                if granted && recordAttemptActive {
                    beginKeyboardRecordAttempt()
                } else {
                    recordAttemptActive = false
                    recordStartedFromKeyboard = false
                    showRecordHint(duration: granted ? 2500 : 0)
                }
            }
            return
        }

        prepareRealtimeRecording()
        composerRecorder.startRecording()
        guard composerRecorder.error == nil else {
            micPermissionState = .denied
            recordAttemptActive = false
            recordStartedFromKeyboard = false
            showRecordHint(duration: 0)
            return
        }
        withAnimation(.easeInOut(duration: 0.15)) {
            composerOverlay = .recording
            isInputFocused = false
        }
        dismissChatKeyboardForRecording(afterCurrentGesture: true)
    }

    private func dismissChatKeyboardForRecording(afterCurrentGesture: Bool = false) {
        isInputFocused = false
        #if os(iOS)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
        #endif
        guard afterCurrentGesture else { return }
        Task { @MainActor in
            await Task.yield()
            isInputFocused = false
            #if os(iOS)
            UIApplication.shared.sendAction(
                #selector(UIResponder.resignFirstResponder),
                to: nil,
                from: nil,
                for: nil
            )
            #endif
        }
    }

    private func handleKeyboardRecordShortcut(_ press: KeyPress) -> KeyPress.Result {
        guard press.modifiers == [.command, .shift] || press.modifiers == [.control, .shift] else { return .ignored }
        guard recordStartedFromKeyboard else {
            beginKeyboardRecordAttempt()
            return .handled
        }
        finishRecordAttempt()
        return .handled
    }

    private func handleKeyboardRecordEnter(_ press: KeyPress) -> KeyPress.Result {
        guard press.modifiers.isEmpty, recordStartedFromKeyboard else { return .ignored }
        finishRecordAttempt()
        return .handled
    }

    private func handleKeyboardRecordEscape() -> KeyPress.Result {
        guard recordStartedFromKeyboard else { return .ignored }
        cancelRecordAttempt()
        return .handled
    }

    private func showRecordHint(duration: Int = 2500) {
        recordHintVisible = true
        recordHintTask?.cancel()
        guard duration > 0 else { return }
        recordHintTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(duration))
            guard !Task.isCancelled else { return }
            recordHintVisible = false
        }
    }

    #if DEBUG
    // Synthetic-fixture-only phases/booleans: no text, account, key or server data.
    // No timers or layout probes; only actual dispatch transitions publish state.
    private func recordComposerSendFixturePhase(_ phase: String) {
        guard chatId == "dev-chat-opening-large",
              ProcessInfo.processInfo.arguments.contains("--ui-test-composer-send"),
              composerSendFixturePhases.last != phase else { return }
        composerSendFixturePhases = Array((composerSendFixturePhases + [phase]).suffix(20))
    }
    private var composerSendFixtureDiagnostic: String {
        "phases=\(composerSendFixturePhases.joined(separator: ","));foreground=\(piiComposerForeground);sceneActive=\(scenePhase == .active);paneVisible=\(parentPaneVisible);public=\(isDemoOrLegalChat || isExampleChat);verifying=\(isVerifyingPIISend);focused=\(isInputFocused);modelReady=\(modelHost.controller?.isReady == true);chatReady=\(viewModel.chat?.id == chatId)"
    }
    #endif

    private func sendMessage() {
        #if DEBUG
        recordComposerSendFixturePhase("entered")
        #endif
        guard !isVerifyingPIISend else {
            #if DEBUG
            recordComposerSendFixturePhase("blocked-verifying")
            #endif
            return
        }
        guard !retryDeferredComposerSendIfNeeded() else {
            #if DEBUG
            recordComposerSendFixturePhase("deferred-retry")
            #endif
            return
        }
        let document = composerSession.controller.document
        let documentRevision = composerSession.revision
        let decision = ComposerSubmitPolicy.decision(
            document: document,
            platform: .desktop,
            trigger: .sendButton,
            modifiers: [],
            markedTextRange: nil,
            conversionInFlight: false
        )
        if case .deferred = decision {
            #if DEBUG
            recordComposerSendFixturePhase("deferred-document")
            #endif
            queueDeferredComposerSend(document: document)
            return
        }
        guard decision == .submit else {
            #if DEBUG
            recordComposerSendFixturePhase("blocked-submit-policy")
            #endif
            return
        }
        isVerifyingPIISend = true
        #if DEBUG
        recordComposerSendFixturePhase("scheduled")
        #endif
        let owner = piiComposerContext
        let options = piiPrivacySettingsStore.detectionOptions()
        let exclusions = piiExclusions
        let originals = excludedPIIOriginals(in: document, excludedIds: exclusions)
        Task { @MainActor in
            await sendVerifiedComposerMessage(document: document, documentRevision: documentRevision, owner: owner, options: options,
                                              exclusions: exclusions, excludedOriginals: originals)
            if piiComposerContext == owner { isVerifyingPIISend = false }
        }
    }

    private func sendVerifiedComposerMessage(document: ComposerDocumentV1, documentRevision: Int, owner: ComposerPIIContext,
        options: PIIDetectionOptions, exclusions: Set<String>, excludedOriginals: Set<String>) async {
        guard owner == piiComposerContext, piiComposerForeground else {
            #if DEBUG
            recordComposerSendFixturePhase("blocked-foreground-context")
            #endif
            return
        }
        #if DEBUG
        recordComposerSendFixturePhase("verification-begin")
        #endif

        let redaction: ComposerDocumentPIIRedactionResult
        let text: String
        let documentNodeIDs = document.nodes.filter { $0.kind == "embed" }.map(\.id)
        let composerEmbeds = documentNodeIDs.compactMap { resolvedComposerEmbeds[$0] }
        let rewriteMappings = PIIDetector.mergePIIMappings(cumulativePIIMappings + composerEmbeds.flatMap(\.piiMappings))
        let piiMappings: [PIIMapping]
        do {
            let rewrite = ComposerPIIDecorations.rewriteKnownPIIPlaceholders(
                document: document,
                mappings: rewriteMappings,
                excludedOriginals: excludedOriginals
            )
            #if DEBUG
            recordComposerSendFixturePhase("verification-await")
            #endif
            redaction = await piiDetectionCoordinator.verifiedRedaction(
                document: rewrite.document, excludedIds: exclusions,
                excludedOriginals: excludedOriginals, options: options, context: owner)
            #if DEBUG
            recordComposerSendFixturePhase("verification-returned")
            #endif
            text = try ComposerMarkdownAdapter.serialize(redaction.document)
            piiMappings = PIIDetector.mergePIIMappings(rewrite.appliedMappings + redaction.mappings)
        } catch {
            #if DEBUG
            recordComposerSendFixturePhase("serialization-failed")
            #endif
            NativeDiagnostics.error(
                "Composer send serialization failed: \(type(of: error))",
                category: "apple_composer"
            )
            viewModel.error = AppStrings.error
            return
        }
        guard viewModel.chat?.id == chatId, owner == piiComposerContext,
              options == piiPrivacySettingsStore.detectionOptions(), piiComposerForeground else {
            #if DEBUG
            recordComposerSendFixturePhase("blocked-post-verification")
            #endif
            return
        }
        let editingID = editingContextMessage?.id
        let sendingOwner = ComposerModelSendOwnership(server: ServerProfile.current().apiBaseURL.absoluteString,
            accountGeneration: OfflineStore.shared.scopeGeneration, chatID: chatId)
        let routingGeneration = modelHost.sendGeneration
        let dispatchFence = ComposerPIIDispatchFence(context: owner, options: options)
        // Keep the original composer and encrypted draft through preparation.
        // Clearing here would autosave an empty draft and delete a draft-only
        // chat before the pipeline can durably retain/insert its user message.
        followsStreamingResponse = true
        viewModel.error = nil

        // Await dispatch so the outer PII submit gate remains held throughout.
        let routedText: String
        do {
            NativeDiagnostics.event("composer_send_model_routing", category: "apple_composer")
            #if DEBUG
            recordComposerSendFixturePhase("routing-await")
            #endif
            routedText = try await modelHost.textForSend(text, expectedGeneration: routingGeneration)
            guard sendingOwner.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
                accountGeneration: OfflineStore.shared.scopeGeneration, chatID: viewModel.chat?.id) else {
                #if DEBUG
                recordComposerSendFixturePhase("blocked-routing-ownership")
                #endif
                return
            }
        }
        catch {
            #if DEBUG
            recordComposerSendFixturePhase("routing-failed")
            #endif
            guard sendingOwner.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
                accountGeneration: OfflineStore.shared.scopeGeneration, chatID: viewModel.chat?.id) else {
                #if DEBUG
                recordComposerSendFixturePhase("blocked-routing-ownership")
                #endif
                return
            }
            viewModel.error = LocalizationManager.shared.text("enter_message.model_selector.unavailable_reset")
            return
        }
        guard dispatchFence.permits(currentContext: piiComposerContext,
            currentOptions: piiPrivacySettingsStore.detectionOptions(),
            foreground: piiComposerForeground, cancelled: Task.isCancelled) else {
            #if DEBUG
            recordComposerSendFixturePhase("blocked-dispatch-fence")
            #endif
            guard owner == piiComposerContext else { return }
            stopFollowingStreamingResponse()
            return
        }
        NativeDiagnostics.event("composer_send_pipeline_begin", category: "apple_composer")
        #if DEBUG
        recordComposerSendFixturePhase("pipeline-await")
        #endif
        let accepted = await viewModel.sendMessage(
            routedText,
            piiMappings: piiMappings,
            excludedPIIOriginals: excludedOriginals,
            broadcastToSiblings: broadcastToSiblingSubChats,
            composerEmbeds: composerEmbeds.isEmpty ? nil : composerEmbeds,
            editingMessageID: editingID
        )
        #if DEBUG
        recordComposerSendFixturePhase("pipeline-returned")
        #endif
        NativeDiagnostics.event("composer_send_pipeline_finished", category: "apple_composer",
            flags: ["accepted": accepted, "has_error": viewModel.error != nil])
        guard sendingOwner.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
            accountGeneration: OfflineStore.shared.scopeGeneration, chatID: viewModel.chat?.id) else { return }
        if !accepted || viewModel.error != nil {
            #if DEBUG
            recordComposerSendFixturePhase("rejected")
            #endif
            stopFollowingStreamingResponse()
            if let editingID, !viewModel.containsMessageForEdit(editingID), editingContextMessage?.id == editingID {
                // The suffix was accepted before a send failure. Preserve
                // the replacement draft for an ordinary encrypted retry.
                editingContextMessage = nil; preEditDraft = nil
            }
        } else {
            // A later draft belongs to the next send. Do not dismiss its
            // selection or keyboard when the previous dispatch completes.
            let clearsSnapshot = ComposerAcceptedSendSnapshotPolicy.shouldClear(
                accepted: accepted, submittedRevision: documentRevision, currentRevision: composerSession.revision,
                submittedDocument: document, currentDocument: composerSession.controller.document)
            if clearsSnapshot {
                #if DEBUG
                recordComposerSendFixturePhase("accepted-clear")
                #endif
                draftSaveTask?.cancel()
                suppressNextDraftSave = true
                messageText = ""; detectedPIIMatches = []; piiExclusions = []; piiExcludedValues = []; mentionQuery = nil
                dismissAcceptedComposer()
            }
            if editingContextMessage?.id == editingID { editingContextMessage = nil; preEditDraft = nil }
            let retainedNodeIDs = Set(composerSession.controller.document.nodes.map(\.id))
            for nodeID in documentNodeIDs where !retainedNodeIDs.contains(nodeID) {
                resolvedComposerEmbeds.removeValue(forKey: nodeID)
            }
            if clearsSnapshot { try? await DraftService.shared.clearDraft(chatId: sendingOwner.chatID) }
        }
    }

    private func dismissAcceptedComposer() {
        isComposerExpanded = false
        isInputFocused = false
        composerSearchFocusTask?.cancel()
        composerSearchRecentlyFocused = false
        try? composerSession.controller.setSelection(NSRange(location: 0, length: 0))
        // The production editor's focus binding resigns its UIKit/AppKit first
        // responder. Clear both expansion and focus so the compact surface wins.
    }

    private func handleFollowUpSuggestionTap(_ suggestion: String) {
        let isPublic = isDemoOrLegalChat || isExampleChat
        switch ChatFollowUpTapPolicy.action(
            isPublic: isPublic,
            isAuthenticated: authManager.state == .authenticated
        ) {
        case .requestAuthentication:
            NotificationCenter.default.post(name: .openAuth, object: nil)
        case .continueInNewChat:
            continuePublicChat(with: suggestion)
        case .sendInCurrentChat:
            messageText = suggestion
            sendMessage()
        }
    }

    private func continuePublicChat(with content: String) {
        guard let wsManager, let chatStore else { return }
        let now = ChatSendPipeline.isoString(from: Date())
        let chat = Chat(
            id: UUID().uuidString.lowercased(),
            title: nil,
            lastMessageAt: nil,
            createdAt: now,
            updatedAt: now,
            isArchived: false,
            isPinned: false,
            appId: nil,
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0,
            draftV: 0
        )

        Task { @MainActor in
            do {
                let result = try await ChatSendPipeline().sendUserMessage(
                    content: content,
                    in: chat,
                    existingMessages: [],
                    wsManager: wsManager,
                    chatStore: chatStore,
                    waitForRemoteSend: false
                )
                onOpenChat?(result.chat.id)
            } catch {
                viewModel.error = error.localizedDescription
            }
        }
    }

    private func restoreEncryptedDraft() async {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        let requestedChatID = chatId
        let scope = OfflineStore.shared.scopeGeneration
        let revision = composerSession.revision
        do {
            if let draft = try await DraftService.shared.loadDraft(chatId: requestedChatID),
               requestedChatID == chatId, loadedRouteID == requestedChatID,
               scope == OfflineStore.shared.scopeGeneration, revision == composerSession.revision,
               composerSession.canonicalMarkdown.isEmpty {
                suppressNextDraftSave = true
                composerSession.replaceMarkdown(draft.canonicalMarkdown)
                hydrateEncryptedDraftAttachments(draft.attachments)
            }
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning("Encrypted composer draft restore failed: \(type(of: error))", category: "apple_composer")
        }
    }

    private func closeRemovedDraftIfNeeded(_ notification: Notification) -> Bool {
        guard ChatSelectionSyncPolicy.shouldCloseRemovedDraft(
            selectedChatId: chatId, eventChatId: notification.userInfo?["chatId"] as? String,
            eventScope: notification.userInfo?["scopeGeneration"] as? UUID,
            currentScope: OfflineStore.shared.scopeGeneration,
            chatRemoved: notification.userInfo?["chatRemoved"] as? Bool == true,
            hasComposerContent: !composerSession.canonicalMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || composerHasEmbed || viewModel.hasPendingComposerEmbeds || recordAttemptActive,
            hasMessages: !viewModel.messages.isEmpty || viewModel.isStreaming
                || chatStore?.chat(for: chatId) != nil || !(chatStore?.messages(for: chatId).isEmpty ?? true)
        ) else { return false }
        onCloseChat?()
        return true
    }

    private func applyInboundDraft() async {
        let requestedChatID = chatId
        let revision = composerSession.revision
        let scopeGeneration = OfflineStore.shared.scopeGeneration
        do {
            let draft = try await DraftService.shared.loadDraft(chatId: requestedChatID)
            let markdown = draft?.canonicalMarkdown ?? ""
            guard requestedChatID == chatId, loadedRouteID == requestedChatID,
                  revision == composerSession.revision,
                  scopeGeneration == OfflineStore.shared.scopeGeneration else { return }
            if markdown != composerSession.canonicalMarkdown {
                suppressNextDraftSave = true
                composerSession.replaceMarkdown(markdown)
                resolvedComposerEmbeds.removeAll()
                composerEmbedLifecycle = .init()
            }
            hydrateEncryptedDraftAttachments(draft?.attachments ?? [])
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning("Inbound composer draft refresh failed: \(type(of: error))", category: "draft_sync")
        }
    }

    private func hydrateEncryptedDraftAttachments(_ attachments: [ComposerDraftAttachment]) {
        let records = Dictionary(attachments.map { ($0.embedRecord.id, $0) }, uniquingKeysWith: { first, _ in first })
        for node in composerSession.controller.document.nodes where node.kind == "embed" {
            guard let reference = node.contentRef, reference.hasPrefix("embed:"),
                  let attachment = records[String(reference.dropFirst(6))],
                  let embed = Self.restoredComposerDraftEmbed(attachment) else { continue }
            let state = AppleComposerEmbedLifecycleState(rawValue: node.status ?? "finished") ?? .finished
            _ = composerEmbedLifecycle.register(nodeId: node.id, state: state)
            resolvedComposerEmbeds[node.id] = embed
            try? composerSession.controller.configureEmbedPreview(id: node.id,
                embedRecord: attachment.embedRecord, localPreviewData: attachment.localData)
            try? composerSession.configureEmbedActions(nodeID: node.id, onOpen: { _ in }, onRetry: { _ in },
                onRemove: { _ in
                    resolvedComposerEmbeds.removeValue(forKey: node.id)
                    handleComposerEmbedRemoval(nodeID: node.id, durableID: embed.id)
                })
        }
    }

    static func restoredComposerDraftEmbed(_ attachment: ComposerDraftAttachment) -> ComposerPendingEmbed? {
        let record = attachment.embedRecord
        if record.type == "audio-recording" {
            guard let embed = ComposerPendingEmbed.restoredRecording(from: record) else { return nil }
            return ComposerPendingEmbed(id: embed.id, type: embed.type, referenceType: embed.referenceType,
                status: embed.status, content: embed.content, textPreview: embed.textPreview, record: embed.record,
                localData: attachment.localData, filename: embed.filename,
                size: attachment.localData?.count ?? embed.size, piiMappings: embed.piiMappings)
        }
        guard let raw = record.rawData, JSONSerialization.isValidJSONObject(raw.mapValues(\.value)),
              let data = try? JSONSerialization.data(withJSONObject: raw.mapValues(\.value), options: [.sortedKeys]),
              let content = String(data: data, encoding: .utf8) else { return nil }
        return ComposerPendingEmbed(id: record.id, type: record.type,
            referenceType: raw["type"]?.value as? String ?? (record.type == "images-image" ? "image" : "file"),
            status: record.status.rawValue, content: content, textPreview: raw["title"]?.value as? String,
            record: record, localData: attachment.localData,
            filename: raw["filename"]?.value as? String ?? record.id,
            size: attachment.localData?.count ?? 0, piiMappings: [])
    }

    static func draftAttachmentSnapshot(document: ComposerDocumentV1,
        resolved: [String: ComposerPendingEmbed]) -> [ComposerDraftAttachment]? {
        let nodes = document.nodes.filter { $0.kind == "embed" }
        let embeds = nodes.compactMap { resolved[$0.id] }
        // Preserve the encrypted prior payload until every restored node has a
        // real snapshot. Removing all embed nodes deliberately saves an empty set.
        guard embeds.count == nodes.count else { return nil }
        return embeds.map { ComposerDraftAttachment(embedRecord: $0.record, localData: $0.localData) }
    }

    private func scheduleEncryptedDraftSave() {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        draftSaveTask?.cancel()
        let markdown = composerSession.canonicalMarkdown
        let revision = composerSession.revision
        let draftVersion = viewModel.chat?.draftV ?? 0
        draftSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            await saveEncryptedDraft(markdown: markdown, revision: revision, draftVersion: draftVersion)
        }
    }

    private func flushEncryptedDraft() {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        draftSaveTask?.cancel()
        let markdown = composerSession.canonicalMarkdown
        let revision = composerSession.revision
        let draftVersion = viewModel.chat?.draftV ?? 0
        Task { @MainActor in
            await saveEncryptedDraft(markdown: markdown, revision: revision, draftVersion: draftVersion)
        }
    }

    private func saveEncryptedDraft(markdown: String, revision: Int, draftVersion: Int) async {
        do {
            guard revision == composerSession.revision else { return }
            try await DraftService.shared.saveDraft(
                canonicalMarkdown: markdown,
                preview: String(markdown.prefix(160)),
                chatId: chatId,
                revision: revision,
                draftVersion: draftVersion,
                attachments: Self.draftAttachmentSnapshot(document: composerSession.controller.document,
                    resolved: resolvedComposerEmbeds)
            )
            #if DEBUG
            attachmentDraftSavedRevision = revision
            #endif
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning("Encrypted composer draft save failed: \(type(of: error))", category: "apple_composer")
        }
    }

    private func applyInputFocusRequestIfNeeded() {
        guard inputFocusRequest > 0, handledInputFocusRequest != inputFocusRequest else { return }
        handledInputFocusRequest = inputFocusRequest
        Task { @MainActor in
            await Task.yield()
            isInputFocused = true
        }
    }

    private func applyCameraCaptureRequestIfNeeded() {
        guard cameraCaptureRequest > 0, handledCameraCaptureRequest != cameraCaptureRequest else { return }
        handledCameraCaptureRequest = cameraCaptureRequest
        #if os(iOS)
        Task { @MainActor in
            await Task.yield()
            showCameraCapture = true
        }
        #endif
    }

    private func handleComposerDeferredSend(_ notification: Notification) {
        guard let routeThroughComposer = notification.userInfo?["dispatchThroughActiveComposer"] as? Bool,
              routeThroughComposer,
              let deferredChatId = notification.userInfo?["chatId"] as? String,
              deferredChatId == viewModel.chat?.id,
              let content = notification.userInfo?["content"] as? String else { return }
        let piiMappings = notification.userInfo?["piiMappings"] as? [PIIMapping] ?? []
        Task {
            await viewModel.sendMessage(
                content,
                piiMappings: piiMappings,
                broadcastToSiblings: broadcastToSiblingSubChats
            )
        }
    }

    private var piiComposerContext: ComposerPIIContext {
        .init(server: ServerProfile.current().apiBaseURL.absoluteString,
              accountGeneration: OfflineStore.shared.scopeGeneration, routeID: chatId)
    }
    private var piiComposerForeground: Bool {
        scenePhase == .active && parentPaneVisible && !isDemoOrLegalChat && !isExampleChat
    }
    private func updatePIIMatches(for _: String) {
        let visible = ComposerPIIDecorations.visibleText(document: composerSession.controller.document)
        piiExcludedValues = piiExcludedValues.filter { visible.contains($0) }
        piiDetectionCoordinator.submit(text: visible, options: piiPrivacySettingsStore.detectionOptions(),
            context: piiComposerContext, enabled: piiPrivacySettingsStore.settings.masterEnabled,
            foreground: piiComposerForeground)
    }
    private func applyPIIPublication(_ publication: ComposerPIIDetectionPublication?) {
        guard let publication else { detectedPIIMatches = []; return }
        guard piiComposerForeground, publication.snapshot.context == piiComposerContext,
              publication.snapshot.options == piiPrivacySettingsStore.detectionOptions(),
              publication.snapshot.text == ComposerPIIDecorations.visibleText(document: composerSession.controller.document) else { return }
        detectedPIIMatches = publication.result.matches
        piiExclusions = Set(detectedPIIMatches.filter { piiExcludedValues.contains($0.value) }.map(\.id))
    }
    private func excludeComposerPII(_ id: String) {
        guard let match = detectedPIIMatches.first(where: { $0.id == id }) else { return }
        piiExclusions.insert(id); piiExcludedValues.insert(match.value)
    }
    private func resetComposerPIIDetection() {
        piiDetectionCoordinator.invalidate(); detectedPIIMatches = []; piiExclusions = []; piiExcludedValues = []
        isVerifyingPIISend = false
    }
    private func excludedPIIOriginals(in document: ComposerDocumentV1, excludedIds: Set<String>) -> Set<String> {
        let visible = ComposerPIIDecorations.visibleText(document: document)
        let matches = PIIDetector.detect(in: visible, options: piiPrivacySettingsStore.detectionOptions())
        return Set((matches + detectedPIIMatches).filter { excludedIds.contains($0.id) && visible.contains($0.value) }.map(\.value))
            .union(piiExcludedValues.filter { visible.contains($0) })
    }

    private func updateMentionQuery(for text: String) {
        mentionQuery = extractMentionQuery(from: text)
    }

    private func extractMentionQuery(from text: String) -> String? {
        guard let atIndex = text.lastIndex(of: "@") else { return nil }
        if atIndex != text.startIndex {
            let previousIndex = text.index(before: atIndex)
            let previousCharacter = text[previousIndex]
            guard previousCharacter == " " || previousCharacter == "\n" || previousCharacter == "\t" else {
                return nil
            }
        }
        let queryStart = text.index(after: atIndex)
        let query = String(text[queryStart...])
        guard !query.contains(" "), !query.contains("\n"), !query.contains("\t") else { return nil }
        return query
    }

    private func insertMention(_ item: MentionItem) {
        guard let atIndex = messageText.lastIndex(of: "@") else {
            messageText += messageText.isEmpty ? "\(item.mentionSyntax) " : " \(item.mentionSyntax) "
            mentionQuery = nil
            return
        }
        messageText.replaceSubrange(atIndex..<messageText.endIndex, with: "\(item.mentionSyntax) ")
        mentionQuery = nil
        isInputFocused = true
    }

    private func publicChatIconName(for chatId: String) -> String? {
        switch chatId {
        case "example-beautiful-single-page-html":
            return "code"
        case "demo-who-develops-openmates":
            return "user"
        case "announcements-introducing-openmates-v09":
            return "megaphone"
        case "legal-privacy":
            return "shield-check"
        case "legal-terms":
            return "file-text"
        case "legal-imprint":
            return "building"
        case "example-gigantic-airplanes", "example-flights-berlin-bangkok":
            return "plane"
        case "example-artemis-ii-mission":
            return "rocket"
        case "example-eu-chat-control-law":
            return "shield"
        case "example-creativity-drawing-meetups-berlin":
            return "pencil"
        default:
            return nil
        }
    }
}

/// Same-ID embed transitions are ordinary during app-skill streaming. Hash the
/// complete render/persistence revision so SwiftUI observes processing→finished
/// and version refreshes without retaining plaintext in view state.
enum ChatEmbedSyncSignature {
    static func make(chatId: String?, embeds: [EmbedRecord]) -> String {
        var hasher = SHA256()
        update(&hasher, chatId ?? "")
        for embed in embeds.sorted(by: { $0.id < $1.id }) {
            for value in [
                embed.id, embed.type, embed.status.rawValue,
                embed.parentEmbedId ?? "", embed.appId ?? "", embed.skillId ?? "",
                embed.embedIds ?? "", embed.hashedChatId ?? "", embed.hashedMessageId ?? "",
                embed.hashedUserId ?? "", embed.versionNumber.map(String.init) ?? "",
                embed.contentHash ?? "", embed.createdAt ?? "",
                embed.encryptedContent ?? "", embed.encryptedType ?? "",
                embed.encryptedTextPreview ?? "",
            ] {
                update(&hasher, value)
            }
            if let rawData = embed.rawData,
               JSONSerialization.isValidJSONObject(rawData.mapValues(\.value)),
               let data = try? JSONSerialization.data(
                   withJSONObject: rawData.mapValues(\.value),
                   options: [.sortedKeys]
               ) {
                hasher.update(data: data)
            }
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func update(_ hasher: inout SHA256, _ value: String) {
        hasher.update(data: Data(value.utf8))
        hasher.update(data: Data([0]))
    }
}

private struct ChatProcessingRing: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @State private var rotation = 0.0

    private var gradient: AngularGradient {
        AngularGradient(
            colors: [
                .chatRainbowRed,
                .chatRainbowOrange,
                .chatRainbowYellow,
                .chatRainbowGreen,
                .chatRainbowCyan,
                .chatRainbowPurple,
                .chatRainbowRed
            ],
            center: .center,
            angle: .degrees(rotation)
        )
    }

    var body: some View {
        RoundedRectangle(cornerRadius: 17)
            .strokeBorder(gradient, lineWidth: 2)
            .blur(radius: 1.5)
            .shadow(color: Color.chatRainbowPurple.opacity(colorScheme == .dark ? 0.70 : 0.42), radius: 9)
            .shadow(color: Color.chatRainbowCyan.opacity(colorScheme == .dark ? 0.55 : 0.32), radius: 5)
            .padding(1)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.linear(duration: 3).repeatForever(autoreverses: false)) {
                    rotation = 360
                }
            }
    }
}

private struct AssistantResponseFeedbackView: View {
    @Binding var selectedRating: Int?
    let submitted: Bool
    let onSubmit: () -> Void
    let onRequestFeature: () -> Void

    private let ratings = [1, 2, 3, 4, 5]

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if submitted {
                Text(AppStrings.assistantFeedbackThanks)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("assistant-feedback-thanks")
            } else {
                HStack(alignment: .center, spacing: .spacing3) {
                    Text(AppStrings.assistantFeedbackRateLabel)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)

                    HStack(spacing: .spacing1) {
                        ForEach(ratings, id: \.self) { rating in
                            Button {
                                selectedRating = rating
                            } label: {
                                Text(verbatim: "★")
                                    .font(.omP)
                                    .foregroundStyle(starColor(for: rating))
                            }
                            .buttonStyle(.plain)
                            .help(Text(AppStrings.assistantFeedbackStarLabel(count: rating)))
                            .accessibilityLabel(AppStrings.assistantFeedbackStarLabel(count: rating))
                            .accessibilityIdentifier("assistant-feedback-star-\(rating)")
                        }
                    }

                    if selectedRating != nil {
                        Button(action: onSubmit) {
                            Text(submitLabel)
                                .font(.omXs.weight(.semibold))
                                .foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing4)
                                .padding(.vertical, .spacing2)
                                .background(Color.buttonPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("assistant-feedback-submit")
                    }
                }
            }

            Button(action: onRequestFeature) {
                Text(AppStrings.requestFeature)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("chat-history-request-feature")
        }
        .padding(.top, .spacing2)
        .accessibilityIdentifier("assistant-response-feedback")
    }

    private var submitLabel: String {
        guard let selectedRating, selectedRating <= 3 else {
            return AppStrings.assistantFeedbackSubmit
        }
        return AppStrings.settingsReportIssue
    }

    private func starColor(for rating: Int) -> Color {
        guard let selectedRating, rating <= selectedRating else {
            return Color.grey50
        }
        return Color.buttonPrimary
    }
}

// MARK: - Message bubble with embed support

enum ChatMessageAccessibilityPolicy {
    static func semanticLabel(
        content: String,
        thinkingContent: String?,
        embedTypes: [String],
        fallback: String
    ) -> String {
        let text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            return text
        }
        if let thinkingContent {
            let thinkingText = thinkingContent.trimmingCharacters(in: .whitespacesAndNewlines)
            if !thinkingText.isEmpty {
                return thinkingText
            }
        }
        let embedNames = embedTypes.compactMap { EmbedType.normalized(rawValue: $0)?.displayName }
        if !embedNames.isEmpty {
            return embedNames.joined(separator: ", ")
        }
        return fallback
    }
}

enum ChatMessageStreamingRenderPolicy {
    static func visibleContent(_ content: String) -> String {
        let lines = content.components(separatedBy: "\n")
        var visibleLines: [String] = []
        var index = 0

        while index < lines.count {
            let trimmed = lines[index].trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("```") else {
                visibleLines.append(lines[index])
                index += 1
                continue
            }

            let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
            var endIndex = index + 1
            while endIndex < lines.count,
                  !lines[endIndex].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                endIndex += 1
            }

            let isClosed = endIndex < lines.count
            let body = lines[(index + 1)..<min(endIndex, lines.count)].joined(separator: "\n")
            if isInternalProtocolFence(language: language, body: body, isClosed: isClosed) {
                index = isClosed ? endIndex + 1 : lines.count
                continue
            }

            let finalIndex = isClosed ? endIndex : lines.count - 1
            visibleLines.append(contentsOf: lines[index...finalIndex])
            index = finalIndex + 1
        }

        return visibleLines.joined(separator: "\n")
    }

    static func isInternalProtocolFence(language: String, body: String, isClosed: Bool) -> Bool {
        if language == "interactive_response" || language == "interactive_question" {
            return true
        }
        guard language == "json" || language == "json_embed" else { return false }
        guard isClosed else {
            return language == "json_embed"
                || (body.contains("\"app_skill_use\"") && body.contains("\"embed_id\""))
                || body.contains("\"sub_chat_batch\"")
        }
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false
        }
        return language == "json_embed"
            || (object["type"] != nil && object["embed_id"] != nil)
    }
}

struct ImportedAssistantProvider: Equatable {
    let category: String
    let displayNameKey: String
    let iconName: String

    @MainActor
    var displayName: String { AppStrings.localized(displayNameKey) }

    static func resolve(category: String?, isOfficialOpenMatesChat: Bool = false) -> Self? {
        guard !isOfficialOpenMatesChat else { return nil }
        switch category {
        case "openmates": return Self(category: "openmates", displayNameKey: "settings.account.import_source_openmates", iconName: "openmates")
        case "chatgpt": return Self(category: "chatgpt", displayNameKey: "settings.account.import_source_chatgpt", iconName: "openai")
        case "claude": return Self(category: "claude", displayNameKey: "settings.account.import_source_claude", iconName: "claude")
        case "gemini": return Self(category: "gemini", displayNameKey: "settings.account.import_source_gemini", iconName: "google")
        case "opencode": return Self(category: "opencode", displayNameKey: "settings.account.import_source_opencode", iconName: "coding")
        case "other": return Self(category: "other", displayNameKey: "settings.account.import_source_other_assistant_name", iconName: "ai")
        default: return nil
        }
    }
}

/// Immutable inputs shared by every branch of one message body evaluation.
/// Rebuilt from current row inputs so late embed hydration and PII reveal remain synchronous.
struct ChatMessageRenderPresentation {
    let displayContent: String
    let progressiveContent: String
    let stableRenderDocument: ChatHistoryRenderDocument?
    let agentContextEvent: AgentContextEvent?
    let topLevelAppSkillEmbeds: [EmbedRecord]
    let hiddenInlineEmbedIds: Set<String>

    init(
        message: Message,
        streamingContent: String?,
        piiMappings: [PIIMapping],
        isPIIRevealed: Bool,
        embeds: [EmbedRecord],
        allEmbedRecords: [String: EmbedRecord],
        streamingFilter: (String) -> String = ChatMessageStreamingRenderPolicy.visibleContent,
        parentResolver: ([EmbedRecord], [String: EmbedRecord], String) -> [EmbedRecord] = ChatMessageRenderPresentation.resolveParents
    ) {
        let raw = streamingContent ?? message.content ?? ""
        let visible = streamingContent == nil ? raw : streamingFilter(raw)
        if isPIIRevealed && !piiMappings.isEmpty {
            displayContent = PIIDetector.restorePII(in: visible, mappings: piiMappings)
            // Progressive parsing needs the original protocol-bearing stream.
            progressiveContent = visible == raw
                ? displayContent : PIIDetector.restorePII(in: raw, mappings: piiMappings)
        } else {
            displayContent = visible
            progressiveContent = raw
        }
        if streamingContent == nil, !isPIIRevealed,
           let document = message.renderDocumentForDisplay,
           !document.blocks.contains(where: { $0.kind == .interactiveQuestion || $0.kind == .demoGroup }) {
            stableRenderDocument = document
        } else {
            stableRenderDocument = nil
        }
        agentContextEvent = message.role == .system ? AgentContextEvent.parse(displayContent) : nil
        topLevelAppSkillEmbeds = message.role == .assistant
            ? parentResolver(embeds, allEmbedRecords, displayContent) : []
        hiddenInlineEmbedIds = Set(topLevelAppSkillEmbeds.map(\.id))
    }

    static func resolveParents(
        _ embeds: [EmbedRecord], _ allEmbedRecords: [String: EmbedRecord], _ displayContent: String
    ) -> [EmbedRecord] {
        let directParents = embeds.filter { $0.isAppSkillUse }
        if !directParents.isEmpty { return directParents }
        return EmbedRecord.deduplicatedById(
            Array(allEmbedRecords.values), context: "chatView.topLevelAppSkillEmbeds"
        ).filter { $0.isAppSkillUse && displayContent.contains($0.id) }
    }
}

// Web .message-align-right keeps the bubble intrinsic until its available
// transcript lane is exhausted. Paragraphs retain their own leading alignment.
private struct UserMessageTextLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let content = subviews.first else { return .zero }
        let ideal = content.sizeThatFits(.unspecified)
        let available = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? ideal.width
        let width = min(ideal.width, available)
        return content.sizeThatFits(ProposedViewSize(width: width, height: nil))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin, anchor: .topLeading,
            proposal: ProposedViewSize(width: bounds.width, height: bounds.height))
    }
}

struct MessageBubble: View {
    let message: Message
    let chatId: String
    let appId: String?
    let embeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let streamingContent: String?
    let thinkingContent: String?
    let isThinkingStreaming: Bool
    let piiMappings: [PIIMapping]
    let isPIIRevealed: Bool
    let containerWidth: CGFloat
    let isSearchTarget: Bool
    let searchHighlightQuery: String?
    let onEmbedTap: (EmbedRecord) -> Void
    let onOpenPublicChat: ((String) -> Void)?
    var subChatStore: ChatStore? = nil
    var subChatProgress: SubChatProgress? = nil
    var completedSubChatIDs: Set<String> = []
    var onOpenSubChat: ((String) -> Void)? = nil
    let onInteractiveQuestionSubmit: ((String) -> Void)?
    var onOpenMateSettings: ((String) -> Void)? = nil
    var onOpenModelSettings: ((String) -> Void)? = nil
    var onSpeak: (() -> Void)? = nil
    let onShowActions: (() -> Void)?
    var accessibilityIdentifier: String? = nil
    /// Recipient transcripts use an ephemeral scope instead of the owner's cache scope.
    var renderScopeID: String? = nil
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.messageTextSelection) private var selectionContext

    var isUser: Bool { message.role == .user }
    private var isSystem: Bool { message.role == .system }
    /// Web: ≤500px uses stacked layout (avatar above message).
    private var useStackedLayout: Bool {
        if containerWidth > 0 {
            return ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: containerWidth)
        }
        return sizeClass == .compact
    }
    private var assistantCategory: String? { message.category ?? message.appId ?? appId }
    private var importedProvider: ImportedAssistantProvider? {
        ImportedAssistantProvider.resolve(
            category: assistantCategory,
            isOfficialOpenMatesChat: isOpenMatesOfficial
        )
    }
    private var resolvedAccessibilityIdentifier: String {
        accessibilityIdentifier ?? (isUser ? "message-user" : (isSystem ? "message-system" : "message-assistant"))
    }

    private var phaseNoticeUnavailableText: String {
        AppStrings.localized("common.detail_load_error")
            .replacingOccurrences(of: "{item}", with: AppStrings.localized("focus_phases.phases"))
    }

    private func semanticAccessibilityLabel(_ presentation: ChatMessageRenderPresentation) -> String {
        if isSystem, FocusPhaseEvent.isTypedPayload(presentation.displayContent) {
            if let event = FocusPhaseEvent.parse(presentation.displayContent) {
                let prefix = AppStrings.localized(event.direction == "backward" ? "focus_phases.returned" : "focus_phases.switched")
                return prefix + " " + event.phaseTitle
            }
            return phaseNoticeUnavailableText
        }
        return ChatMessageAccessibilityPolicy.semanticLabel(
            content: presentation.displayContent,
            thinkingContent: thinkingContent,
            embedTypes: embeds.map(\.type),
            fallback: resolvedAccessibilityIdentifier
        )
    }

    @ViewBuilder
    private func assistantMarkdownContent(_ presentation: ChatMessageRenderPresentation) -> some View {
        RichMarkdownView(
            content: presentation.displayContent,
            renderDocument: presentation.stableRenderDocument,
            progressiveRequest: progressiveMarkdownRequest(presentation),
            isUserMessage: false,
            onOpenPublicChat: onOpenPublicChat,
            parentChatID: chatId,
            messageCreatedAt: message.createdAt,
            viewportWidth: containerWidth,
            subChatStore: subChatStore,
            onOpenSubChat: onOpenSubChat,
            subChatProgress: subChatProgress,
            completedSubChatIDs: completedSubChatIDs,
            embedLookup: EmbedRecord.dictionaryById(embeds, context: "chatView.richMarkdown"),
            allEmbedRecords: allEmbedRecords,
            hiddenEmbedIds: presentation.hiddenInlineEmbedIds,
            onEmbedTap: onEmbedTap,
            onInteractiveQuestionSubmit: viewAllowsInteractiveQuestionSubmit ? onInteractiveQuestionSubmit : nil,
            searchHighlightQuery: searchHighlightQuery
        )
    }

    private func progressiveMarkdownRequest(_ presentation: ChatMessageRenderPresentation) -> ProgressiveMarkdownRequest {
        ProgressiveMarkdownRequest(
            identity: ProgressiveMarkdownIdentity(scopeID: renderScopeID ?? OfflineStore.shared.scopeGeneration.uuidString,
                chatID: chatId, messageID: message.id),
            content: presentation.progressiveContent, isStreaming: streamingContent != nil,
            renderDocument: presentation.stableRenderDocument, embedRefs: message.embedRefs ?? [])
    }

    #if DEBUG
    private func parityRenderManifestValue(_ presentation: ChatMessageRenderPresentation) -> String {
        let contentHash = Self.stableHash(Self.normalizedText(presentation.displayContent))
        let blockCounts = parityBlockCounts(from: presentation.stableRenderDocument, content: presentation.displayContent)
        let payload: [String: Any] = [
            "schema_version": 1,
            "role": message.role.rawValue,
            "content_hash": contentHash,
            "text_length": Self.normalizedText(presentation.displayContent).count,
            "block_counts": blockCounts,
            "embed_count": embeds.count,
            "has_thinking": thinkingContent?.isEmpty == false,
            "has_sender_name": !isUser && !isSystem,
            "is_streaming": streamingContent != nil
        ]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }

    private func parityBlockCounts(from document: ChatHistoryRenderDocument?, content: String) -> [String: Int] {
        guard let document else {
            return [
                "paragraph": content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0 : 1,
                "heading": 0,
                "code_block": 0,
                "blockquote": 0,
                "list": 0,
                "table": 0,
                "source_quote": 0,
                "embed_group": embeds.isEmpty ? 0 : embeds.count,
                "interactive_question": 0
            ]
        }

        var counts: [String: Int] = [
            "paragraph": 0,
            "heading": 0,
            "code_block": 0,
            "blockquote": 0,
            "list": 0,
            "table": 0,
            "source_quote": 0,
            "embed_group": 0,
            "interactive_question": 0
        ]
        for block in document.blocks {
            switch block.kind {
            case .paragraph:
                counts["paragraph", default: 0] += 1
            case .heading:
                counts["heading", default: 0] += 1
            case .codeBlock:
                counts["code_block", default: 0] += 1
            case .blockquote:
                counts["blockquote", default: 0] += 1
            case .unorderedList, .orderedList:
                counts["list", default: 0] += 1
            case .table:
                counts["table", default: 0] += 1
            case .sourceQuote:
                counts["source_quote", default: 0] += 1
            case .embedGroup:
                counts["embed_group", default: 0] += max(1, block.embedReferences.count)
            case .resultsView, .subChatBatch:
                counts["embed_group", default: 0] += 1
            case .interactiveQuestion, .interactiveQuestionFallback:
                counts["interactive_question", default: 0] += 1
            case .horizontalRule, .hiddenProtocol, .demoGroup:
                break
            }
        }
        return counts
    }

    private static func normalizedText(_ value: String) -> String {
        value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    private static func stableHash(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
    }
    #endif

    private var viewAllowsInteractiveQuestionSubmit: Bool {
        !isUser && streamingContent == nil
    }

    // MARK: - Assistant avatar with AI badge

    private static let openMatesOfficialChatIds: Set<String> = [
        "demo-who-develops-openmates",
        "announcements-introducing-openmates-v09",
        "legal-privacy",
        "legal-terms",
        "legal-imprint"
    ]

    /// True for openmates_official chats — shows OpenMates favicon, hides AI badge.
    private var isOpenMatesOfficial: Bool {
        Self.openMatesOfficialChatIds.contains(chatId)
    }

    /// Gradient for the avatar — openmates_official and default "ai" use .primary (blue/purple).
    private var avatarGradient: LinearGradient {
        if isOpenMatesOfficial { return .primary }
        return (assistantCategory == nil || assistantCategory == "ai") ? .primary : AppIconView.gradient(forAppId: assistantCategory!)
    }

    // Web: .mate-profile = 60px; .mate-profile-small-mobile (≤500px container) = 25px
    private var avatarSize: CGFloat { useStackedLayout ? 25 : 60 }
    private var avatarIconSize: CGFloat { useStackedLayout ? 12 : 30 }
    // Web: AI badge — normal: 24/16px, small-mobile: 12/8px
    private var badgeSize: CGFloat { useStackedLayout ? 12 : 24 }
    private var badgeIconSize: CGFloat { useStackedLayout ? 8 : 16 }

    private var assistantAvatar: some View {
        Group {
            if isOpenMatesOfficial {
                // Web: .mate-profile.openmates_official — favicon as background-image,
                // background-size:contain, border-radius:50%, no AI badge.
                // Use the PNG brand asset because Xcode distorts this colorful SVG.
                Image("openmates-brand")
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFill()
                    .frame(width: avatarSize, height: avatarSize)
                    .clipShape(Circle())
            } else if let importedProvider {
                Circle()
                    .fill(avatarGradient)
                    .frame(width: avatarSize, height: avatarSize)
                    .overlay {
                        Icon(importedProvider.iconName, size: avatarIconSize)
                            .foregroundStyle(.white)
                    }
                    .accessibilityIdentifier("imported-provider-profile")
            } else {
                assistantCategoryAvatar
                    .overlay(alignment: .bottomTrailing) {
                        Circle()
                            .fill(Color.grey0)
                            .frame(width: badgeSize, height: badgeSize)
                            .overlay {
                                Icon("ai", size: badgeIconSize)
                                    .foregroundStyle(LinearGradient.primary)
                            }
                            .shadow(color: .black.opacity(0.10), radius: 2, x: 0, y: 1)
                    }
            }
        }
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
    }

    @ViewBuilder
    private var assistantCategoryAvatar: some View {
        if let assistantCategory, let image = categoryProfileImage(for: assistantCategory) {
            image
                .renderingMode(.original)
                .resizable()
                .scaledToFill()
                .frame(width: avatarSize, height: avatarSize)
                .clipShape(Circle())
        } else {
            Circle()
                .fill(avatarGradient)
                .frame(width: avatarSize, height: avatarSize)
                .overlay {
                    Icon(AppIconView.iconName(forAppId: assistantCategory ?? "ai"), size: avatarIconSize)
                        .foregroundStyle(.white)
                }
        }
    }

    private func categoryProfileImage(for category: String) -> Image? {
        guard CategoryMapping.isKnownCategory(category) else { return nil }
        #if os(iOS)
        let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg")
        guard let path, let image = UIImage(contentsOfFile: path) else { return nil }
        return Image(uiImage: image)
        #elseif os(macOS)
        let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg")
        guard let path, let image = NSImage(contentsOfFile: path) else { return nil }
        return Image(nsImage: image)
        #endif
    }

    private var assistantDisplayName: String {
        if let senderName = ChatAssistantIdentityPolicy.explicitDisplayName(message.senderName) {
            return senderName
        }
        if isOpenMatesOfficial {
            return AppStrings.openMatesName
        }
        if let importedProvider {
            return importedProvider.displayName
        }
        guard let assistantCategory else {
            return AppStrings.openMatesName
        }
        let key = "mates.\(assistantCategory)"
        let localized = AppStrings.localized(key)
        return localized == key ? AppStrings.openMatesName : localized
    }

    private func assistantIdentity(_ placement: AssistantMessageIdentityView.Placement) -> AssistantMessageIdentityView {
        AssistantMessageIdentityView(
            placement: placement,
            displayName: assistantDisplayName,
            category: assistantCategory,
            modelName: message.modelName,
            onOpenMateSettings: onOpenMateSettings,
            onOpenModelSettings: onOpenModelSettings
        )
    }

    private func userBubble(_ presentation: ChatMessageRenderPresentation) -> some View {
        // Stable semantic blocks distinguish text from recording references without
        // parsing markdown again during SwiftUI layout. Mixed text keeps its renderer.
        let referenceOnly = presentation.stableRenderDocument?.blocks.allSatisfy {
            $0.kind == .embedGroup || $0.kind == .hiddenProtocol
        } == true
        let hasVisibleText = !presentation.displayContent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !(referenceOnly && !embeds.isEmpty)
        let hasThinking = !(thinkingContent?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        let recordingOnly = !embeds.isEmpty && embeds.allSatisfy { EmbedType.normalized(rawValue: $0.type) == .recording }
        return VStack(alignment: .trailing, spacing: .spacing3) {
            if hasVisibleText || hasThinking {
                UserMessageTextLayout {
                    RichMarkdownView(
                        content: presentation.displayContent,
                        renderDocument: presentation.stableRenderDocument,
                        isUserMessage: true,
                        allEmbedRecords: allEmbedRecords,
                        onEmbedTap: onEmbedTap,
                        searchHighlightQuery: searchHighlightQuery
                    )
                    .multilineTextAlignment(.leading)
                }
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing6)
                    .background(Color.greyBlue)
                    .clipShape(RoundedRectangle(cornerRadius: 13))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .overlay(alignment: .bottomTrailing) {
                        SpeechTailView(side: .trailing, color: Color.greyBlue)
                    }
                    .searchTargetOutline(isSearchTarget)
                    .modifier(MessageActionsHoldModifier(nativeSelection: selectionContext != nil, action: onShowActions))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("user-message-content")
            } else if !embeds.isEmpty {
                VStack(alignment: .trailing, spacing: .spacing3) {
                    ForEach(EmbedGrouper.groupForInlineDisplay(embeds)) { group in
                        GroupedEmbedView(group: group, allEmbedRecords: allEmbedRecords) { embed in
                            onEmbedTap(embed)
                        }
                    }
                }
                // Compact recording previews already have a 300pt product width.
                // Bound their expanding overlay to that width before bubble padding.
                .frame(width: recordingOnly ? 300 : nil, alignment: .trailing)
                .padding(.spacing6)
                .background(Color.greyBlue)
                .clipShape(RoundedRectangle(cornerRadius: 13))
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("user-embed-only-bubble")
                .overlay(alignment: .bottomTrailing) {
                    SpeechTailView(side: .trailing, color: Color.greyBlue)
                }
                .searchTargetOutline(isSearchTarget)
                .onLongPressGesture {
                    onShowActions?()
                }
            }
        }
        // Like the assistant tail anchor, keep the row and its bubble as separate
        // accessibility containers. SwiftUI otherwise reuses its only child
        // container and replaces the compact bubble identifier with the row's.
        .overlay(alignment: .bottomTrailing) {
            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityIdentifier("message-user-tail")
        }
    }

    private func assistantContent(_ presentation: ChatMessageRenderPresentation) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if !presentation.displayContent.isEmpty || thinkingContent?.isEmpty == false || !presentation.topLevelAppSkillEmbeds.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        HStack(spacing: .spacing2) {
                            assistantIdentity(.mateName)
                            if let onSpeak, message.isStreaming != true {
                                AssistantMessageSpeakButton(action: onSpeak)
                            }
                        }

                        if let thinkingContent, !thinkingContent.isEmpty {
                            ThinkingSectionView(
                                content: thinkingContent,
                                isStreaming: isThinkingStreaming
                            )
                            .accessibilityIdentifier("thinking-section")
                        }

                        if !presentation.topLevelAppSkillEmbeds.isEmpty {
                            VStack(alignment: .leading, spacing: .spacing3) {
                                Text("\(presentation.topLevelAppSkillEmbeds.count) app skill\(presentation.topLevelAppSkillEmbeds.count == 1 ? "" : "s") used:")
                                    .font(.omXs)
                                    .fontWeight(.bold)
                                    .foregroundStyle(Color.fontTertiary)

                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: .spacing3) {
                                        ForEach(Array(presentation.topLevelAppSkillEmbeds.reversed())) { embed in
                                            EmbedPreviewCard(embed: embed, allEmbedRecords: allEmbedRecords) {
                                                onEmbedTap(embed)
                                            }
                                            .frame(width: 300, height: 200)
                                        }
                                    }
                                }
                                .frame(height: 200)
                            }
                            .padding(.bottom, .spacing2)
                        }

                        if !presentation.displayContent.isEmpty {
                            assistantMarkdownContent(presentation)
                        }
                    }
                    .foregroundStyle(Color.grey100)
                    .padding(.spacing6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: 13))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .overlay(alignment: .topLeading) {
                        SpeechTailView(side: useStackedLayout ? .top : .leading, color: Color.grey0)
                    }
                    .searchTargetOutline(isSearchTarget)
                    .modifier(MessageActionsHoldModifier(nativeSelection: selectionContext != nil, action: onShowActions))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("assistant-message-content")

                    assistantIdentity(.modelAttribution)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottomLeading) {
            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityIdentifier("message-assistant-tail")
        }
    }

    private func systemContent(_ presentation: ChatMessageRenderPresentation) -> some View {
        Group {
            if let event = presentation.agentContextEvent {
                AgentContextNoticeView(event: event, onAuthoring: subChatStore.map { store in
                    { recommendation in
                        guard recommendation.chatID == chatId else { throw ProjectsWorkspaceError.invalidContext }
                        try await NativeProjectAuthoringClient.shared.start(recommendation, messages: store.messages(for: chatId))
                    }
                })
            } else if let event = FocusPhaseEvent.parse(presentation.displayContent) {
                FocusPhaseNoticeView(event: event)
            } else if FocusPhaseEvent.isTypedPayload(presentation.displayContent) {
                Text(phaseNoticeUnavailableText)
                    .accessibilityIdentifier("focus-phase-notice-unavailable")
            } else {
                RichMarkdownView(
                    content: presentation.displayContent,
                    renderDocument: presentation.stableRenderDocument,
            isUserMessage: false,
            embedLookup: EmbedRecord.dictionaryById(embeds, context: "chatView.systemMarkdown"),
            allEmbedRecords: allEmbedRecords,
            onEmbedTap: onEmbedTap,
            searchHighlightQuery: searchHighlightQuery
        ) }
        }
        .font(.omSmall)
        .foregroundStyle(Color.fontSecondary)
        .padding(.horizontal, .spacing6)
        .padding(.vertical, .spacing4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10)
        .overlay {
            RoundedRectangle(cornerRadius: .radius4)
                .stroke(Color.grey30, lineWidth: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .searchTargetOutline(isSearchTarget)
        .accessibilityIdentifier("chat-history-system-message")
    }

    var body: some View {
        let presentation = ChatMessageRenderPresentation(
            message: message, streamingContent: streamingContent,
            piiMappings: piiMappings, isPIIRevealed: isPIIRevealed,
            embeds: embeds, allEmbedRecords: allEmbedRecords
        )
        Group {
            if isUser {
                // User message: right-aligned, spacer on left
                HStack(alignment: .top, spacing: ChatMessageLayoutMetric.rowGap) {
                    Spacer(
                        minLength: useStackedLayout
                            ? ChatMessageLayoutMetric.userCompactReserve
                            : ChatMessageLayoutMetric.userDesktopReserve
                    )
                    userBubble(presentation)
                }
            } else if isSystem {
                systemContent(presentation)
            } else {
                // Change only layout at the web breakpoint. Conditional stack
                // branches destroyed the mounted markdown/citation state when
                // resizing from a desktop width to a phone width.
                let layout = useStackedLayout
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: ChatMessageLayoutMetric.stackedAvatarGap))
                    : AnyLayout(HStackLayout(alignment: .top, spacing: ChatMessageLayoutMetric.rowGap))
                layout {
                    assistantAvatar
                    assistantContent(presentation)
                        .padding(.trailing, useStackedLayout ? 0 : ChatMessageLayoutMetric.assistantDesktopReserve)
                }
            }
        }
        // Restored history is already complete. Realizing a row during scrolling
        // must not start an animation transaction over its entire markdown tree.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(resolvedAccessibilityIdentifier)
        .accessibilityLabel(semanticAccessibilityLabel(presentation))
        #if DEBUG
        .accessibilityValue(parityRenderManifestValue(presentation))
        #endif
    }
}

private extension View {
    func searchTargetOutline(_ isActive: Bool) -> some View {
        overlay {
            if isActive {
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.buttonPrimary, lineWidth: 2)
                    .padding(-4)
                    .allowsHitTesting(false)
            }
        }
    }
}

// MARK: - Speech bubble tail overlay

private enum BubbleTailSide { case leading, trailing, top }

/// Renders the triangular speech tail as an overlay, positioned to extend
/// beyond the bubble's clipped edge. Uses the SVG curve shape.
private struct SpeechTailView: View {
    let side: BubbleTailSide
    let color: Color
    @Environment(\.layoutDirection) private var layoutDirection

    /// Tail dimensions matching web CSS (12×20px)
    private let tailWidth: CGFloat = 12
    private let tailHeight: CGFloat = 20

    var body: some View {
        Canvas { context, _ in
            // Draw the SVG path: M0 9.926c0 .992 3.191 1.814 7 0V0C5.093 4.893 0 8.933 0 9.926z
            // Scaled from 7×11 viewBox to 12×20pt
            let sx = tailWidth / 7.0
            let sy = tailHeight / 11.0

            var path = Path()
            path.move(to: CGPoint(x: 0, y: 9.926 * sy))
            // First curve: c0 .992 3.191 1.814 7 0
            path.addCurve(
                to: CGPoint(x: 7 * sx, y: 9.926 * sy),
                control1: CGPoint(x: 0, y: (9.926 + 0.992) * sy),
                control2: CGPoint(x: 3.191 * sx, y: (9.926 + 1.814) * sy)
            )
            // V0 — line to top
            path.addLine(to: CGPoint(x: 7 * sx, y: 0))
            // C5.093 4.893 0 8.933 0 9.926
            path.addCurve(
                to: CGPoint(x: 0, y: 9.926 * sy),
                control1: CGPoint(x: 5.093 * sx, y: 4.893 * sy),
                control2: CGPoint(x: 0, y: 8.933 * sy)
            )
            path.closeSubpath()

            context.fill(path, with: .color(color))
        }
        .frame(width: tailWidth, height: tailHeight)
        .scaleEffect(x: shouldFlipHorizontally ? -1 : 1, y: 1)
        .rotationEffect(side == .top ? .degrees(90) : .degrees(0))
        .offset(
            x: tailOffsetX,
            y: tailOffsetY
        )
        .allowsHitTesting(false)
    }

    private var tailOffsetX: CGFloat {
        let direction: CGFloat = layoutDirection == .rightToLeft ? -1 : 1
        switch side {
        case .leading: return -tailWidth * direction
        case .trailing: return tailWidth * direction
        case .top: return 20
        }
    }

    private var shouldFlipHorizontally: Bool {
        guard side != .top else { return false }
        return (side == .trailing) != (layoutDirection == .rightToLeft)
    }

    private var tailOffsetY: CGFloat {
        switch side {
        case .leading: return 20
        case .trailing: return -10
        case .top: return -16
        }
    }
}

// MarkdownText and IsUserMessage environment removed — replaced by
// RichMarkdownView / InlineMarkdownText in RichMarkdownRenderer.swift

#if DEBUG
/// Counts only, enabled explicitly by the real-account test. The test still
/// asserts rendered user/assistant text; this additional evidence distinguishes
/// a cached reply from the server-acknowledged encrypted completion.
private struct ChatRecoveryStateProbe: View {
    @ObservedObject var store: ChatStore
    let chatId: String
    let renderedMessages: [Message]
    let renderedEmbeds: [String: EmbedRecord]

    var body: some View {
        let pending = store.pendingAssistantRecoveryMessageIds(in: chatId).count
        let version = store.chat(for: chatId)?.messagesV ?? 0
        let encrypted = store.messages(for: chatId).filter {
            $0.role == .assistant && !($0.encryptedContent?.isEmpty ?? true)
        }.count
        let storeRefs = store.messages(for: chatId).flatMap { $0.embedRefs ?? [] }.count
        let renderedRefs = renderedMessages.flatMap { $0.embedRefs ?? [] }
        let viewRefs = renderedRefs.count
        let matchingRefs = renderedRefs.filter { renderedEmbeds[$0.id] != nil }.count
        let audioEmbeds = renderedEmbeds.values.filter { $0.type.contains("audio") }.count
        let hydratedEmbeds = renderedEmbeds.values.filter { $0.rawData != nil }.count
        let storeEmbeds = store.embeds(for: chatId).count
        Color.clear
            .frame(width: 1, height: 1)
            .accessibilityElement()
            .accessibilityLabel("Chat recovery state")
            .accessibilityValue(
                "pending=\(pending);version=\(version);encrypted=\(encrypted);" +
                "storeRefs=\(storeRefs);viewRefs=\(viewRefs);matchedRefs=\(matchingRefs);" +
                "storeEmbeds=\(storeEmbeds);viewEmbeds=\(renderedEmbeds.count);" +
                "audioEmbeds=\(audioEmbeds);hydratedEmbeds=\(hydratedEmbeds)"
            )
            .accessibilityIdentifier("chat-recovery-state")
            .allowsHitTesting(false)
    }
}
#endif
