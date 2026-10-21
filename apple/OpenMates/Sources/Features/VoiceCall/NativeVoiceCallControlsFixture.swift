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
    init(consent: Bool = false) {
        let driver = NativeVoiceCallFixtureDriver(consent: consent)
        destination = .existing(chatID: driver.scope.chatID)
        _coordinator = StateObject(wrappedValue: NativeVoiceCallAppCoordinator(driver: driver,
            accepted: { _, _ in }, restore: { _ in false }, artifacts: { _, _, _ in .unsupported }, usage: { _, _, _ in }))
    }
    var body: some View {
        NativeVoiceCallOverlay(coordinator: coordinator, returnToChat: { _ in })
            .task { await coordinator.start(destination) }
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
