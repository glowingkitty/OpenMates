// Web reference: .runtime/followups123/web-voice-reference362.json.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.privacy.first-call-warning
#if DEBUG && !os(watchOS)
import SwiftUI

/// Root may register only in its existing authenticated-independent Debug
/// preview router. Synthetic UI state: no microphone, socket, API or billing.
@MainActor
struct NativeVoiceCallControlsFixture: View {
    @StateObject private var coordinator: NativeVoiceCallAppCoordinator
    private let destination: NativeVoiceCallAppDestination
    private let chatLayout: Bool
    private let headerPill: Bool
    @StateObject private var presentation = NativeVoiceCallRootPresentation()
    @State private var pinned = false
    @State private var moreOpen = false
    @State private var returnedToChat = false
    init(consent: Bool = false, chatLayout: Bool = false, headerPill: Bool = false) {
        self.chatLayout = chatLayout
        self.headerPill = headerPill
        let driver = NativeVoiceCallFixtureDriver(consent: consent)
        destination = .existing(chatID: driver.scope.chatID)
        _coordinator = StateObject(wrappedValue: NativeVoiceCallAppCoordinator(driver: driver,
            accepted: { _, _ in }, restore: { _ in false }, artifacts: { _, _, _ in .unsupported }, usage: { _, _, _ in }))
    }
    var body: some View {
        Group {
            if headerPill { headerPillHarness }
            else if chatLayout { chatHarness }
            else { NativeVoiceCallOverlay(coordinator: coordinator, returnToChat: { _ in }) }
        }
        .task { await coordinator.start(destination) }
    }
    private static let headerHeight: CGFloat = 220
    private func strip(pinned: Bool, hosts: Bool) -> some View {
        NativeVoiceCallChatStripBody(coordinator: coordinator, presentation: presentation,
            chatID: coordinator.boundChatID ?? "", pinned: pinned, hosts: hosts,
            onMore: { moreOpen.toggle() }, onCloseChat: { moreOpen = false })
    }
    /// Chat header + scrollable transcript harness for the call-strip layout proof.
    /// Global header with the production brand slot while the bound chat is closed;
    /// the pill opens the chat, whose strip then takes over (web `showGlobalVoiceCall`).
    private var headerPillHarness: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                NativeVoiceCallHeaderBrandSlotBody(coordinator: coordinator, presentation: presentation,
                    onReturn: { _ in returnedToChat = true }) {
                    Text(AppStrings.openMatesName).font(.omH3.weight(.bold))
                        .foregroundStyle(LinearGradient.primary)
                        .accessibilityIdentifier("fixture-header-brand")
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing8).frame(height: 60)
            .background(Color.grey0).accessibilityElement(children: .contain)
            .accessibilityIdentifier("fixture-global-header")
            if returnedToChat { chatHarness } else { Color.grey10.frame(maxWidth: .infinity, maxHeight: .infinity) }
        }
        .overlay {
            NativeVoiceCallOverlay(coordinator: coordinator, returnToChat: { _ in returnedToChat = true },
                stripHostedInChat: coordinator.boundChatID.map {
                    presentation.stripHostedChatID == $0 || presentation.headerPillChatID == $0
                } ?? false)
        }
    }
    private var chatHarness: some View {
        let scroll = ScrollView {
            VStack(spacing: 0) {
                Text("Kitchen renovation").font(.omH3).foregroundStyle(.white)
                    .frame(maxWidth: .infinity).frame(height: Self.headerHeight)
                    .background(LinearGradient.primary).accessibilityIdentifier("chat-header-banner")
                if coordinator.showsStrip { strip(pinned: pinned, hosts: true) }
                VStack(alignment: .leading, spacing: .spacing4) {
                    ForEach(0..<30, id: \.self) { index in
                        Text("Message \(index + 1) about the kitchen plan").font(.omP)
                            .foregroundStyle(Color.fontPrimary)
                    }
                }.padding(.spacing4).frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        return Group {
            if #available(iOS 18.0, macOS 15.0, *) {
                scroll.onScrollGeometryChange(for: Bool.self) { geometry in
                    geometry.contentOffset.y + geometry.contentInsets.top >= Self.headerHeight
                } action: { _, value in pinned = value }
            } else { scroll }
        }
        .overlay(alignment: .top) {
            if pinned, coordinator.showsStrip {
                VStack(spacing: 0) {
                    strip(pinned: true, hosts: false)
                    if moreOpen { Text(AppStrings.nativeCall("more_actions")).font(.omSmall).accessibilityIdentifier("voice-call-more-menu") }
                }
            }
        }
    }
}

@MainActor
private final class NativeVoiceCallFixtureDriver: NativeVoiceCallAppDriving {
    let scope = NativeVoiceCallScope(accountID: "debug-fixture", profileID: "debug-fixture",
        workspaceGeneration: UUID(), chatID: UUID().uuidString, mateCategory: "general_knowledge")
    private let needsConsent: Bool
    private var consent: (@MainActor @Sendable () async -> Bool)?
    private var event: (@MainActor @Sendable (NativeVoiceCallEvent) async -> Void)?
    private var state = NativeVoiceCallSnapshot()
    init(consent: Bool) { needsConsent = consent }
    func bind(consent: @escaping @MainActor @Sendable () async -> Bool,
              event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void) {
        self.consent = consent; self.event = event
    }
    func start(_ destination: NativeVoiceCallAppDestination) async throws {
        if needsConsent, await consent?() != true { throw NativeVoiceCallError.consentRequired }
        state = .init(status: .live, scope: scope, callID: "debug-fixture", activeSeconds: 15)
        await event?(.state(state))
    }
    func sendText(_ text: String) async throws -> String { throw NativeVoiceCallError.unsupportedTransport }
    func setMuted(_ muted: Bool) async { state.muted = muted; await event?(.state(state)) }
    func hangup() async { state.status = .ended; await event?(.state(state)) }
    func invalidate() async { await hangup() }
    func snapshot() async -> NativeVoiceCallSnapshot { state }
    func respondToTool(_ frame: NativeVoiceCallFrame) async throws { throw NativeVoiceCallError.unsupportedTransport }
}
#endif
