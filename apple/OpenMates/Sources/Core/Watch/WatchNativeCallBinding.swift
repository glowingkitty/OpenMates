// Watch projection of the shared immutable native call controller.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.typed-input
import Foundation

@MainActor
enum WatchNativeCallBinding {
    /// Root provides canonical chat preparation/confirmation and the genuine
    /// physical Watch eligibility result. An accountless fixture cannot opt in.
    static func install(adapter: WatchCallActionAdapter, controller: NativeVoiceCallController,
                        physicalRouteVerified: Bool,
                        prepareScope: @escaping @MainActor (WatchChatRequestContext, String) async throws -> NativeVoiceCallScope) {
        adapter.configure(projection: .init(phase: physicalRouteVerified ? .ready : .unavailable,
            physicalRouteVerified: physicalRouteVerified), start: { context, chatID in
                try context.check()
                guard physicalRouteVerified, let accountID = context.accountID else { throw NativeVoiceCallError.callUnavailable }
                let scope = try await prepareScope(context, chatID)
                try context.check()
                guard scope.accountID == accountID, scope.chatID == chatID else { throw NativeVoiceCallError.scopeChanged }
                try await controller.start(scope: scope)
            }, sendText: { text in
                try await controller.sendText(text)
            }, setMuted: { await controller.setMuted($0) }, hangup: { await controller.hangup() }, invalidate: { await controller.invalidateScope() })
    }

    /// Call this from the controller's .state event on MainActor. Transcript and
    /// tool events retain the shared encrypted persistence/continuation owner.
    static func update(adapter: WatchCallActionAdapter, snapshot: NativeVoiceCallSnapshot,
                       physicalRouteVerified: Bool) {
        let phase: WatchCallActionProjection.Phase
        switch snapshot.status {
        case .idle: phase = physicalRouteVerified ? .ready : .unavailable
        case .connecting: phase = .connecting
        case .live: phase = .live
        case .ended: phase = .ended
        case .failed: phase = .failed
        }
        adapter.update(.init(phase: phase, chatID: snapshot.scope?.chatID,
            callID: snapshot.callID, scopeGeneration: snapshot.scope?.workspaceGeneration,
            muted: snapshot.muted, activeSeconds: snapshot.activeSeconds, physicalRouteVerified: physicalRouteVerified))
    }
}
