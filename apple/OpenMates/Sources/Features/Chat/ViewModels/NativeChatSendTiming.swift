// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation, chats.surface.semantic-parity
// Privacy-safe monotonic send instrumentation. Identifiers stay in memory only;
// logs contain a fresh local attempt token, fixed phase names and durations.
import Foundation
import SwiftUI
import Combine
#if os(iOS)
import UIKit
#endif

struct NativeChatSendTimingBinding: Equatable {
    let chatID: String
    let userMessageID: String?
    let responseID: String
    let category: String?
}

@MainActor
final class NativeChatSendTiming: ObservableObject {
    static let shared = NativeChatSendTiming()
    struct Attempt {
        let token: UUID
        let started: TimeInterval
        let scope: UUID
        let actionUnixMilliseconds: Double
        var messageID: String?
        var responseID: String?
        var category: String?
        var incomingTaskID: String?
        var incomingCategory: String?
        var incomingReceivedAt: TimeInterval?
        var marks: [String: TimeInterval] = [:]
    }
    private var attempts: [String: Attempt] = [:]
    @Published private(set) var revision = 0
    var debugProbeEnabled: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("--ui-test-send-mate-timing")
        #else
        false
        #endif
    }

    @discardableResult
    func beginAction(chatID: String, startedAt: TimeInterval = NativeSyncPerfLog.now()) -> UUID {
        let token = UUID()
        attempts = attempts.filter { NativeSyncPerfLog.now() - $0.value.started < 180 }
        attempts[chatID] = Attempt(token: token, started: startedAt, scope: OfflineStore.shared.scopeGeneration,
            actionUnixMilliseconds: (Date().timeIntervalSince1970 - (NativeSyncPerfLog.now() - startedAt)) * 1000)
        mark(chatID: chatID, phase: "action")
        return token
    }

    func cancel(chatID: String, token: UUID) {
        guard attempts[chatID]?.token == token else { return }
        mark(chatID: chatID, phase: "cancelled")
        attempts.removeValue(forKey: chatID)
        revision &+= 1
    }

    func bind(chatID: String, messageID: String) {
        guard var attempt = current(chatID), attempt.messageID == nil || attempt.messageID == messageID else { return }
        attempt.messageID = messageID
        attempts[chatID] = attempt
        mark(chatID: chatID, messageID: messageID, phase: "pipelineBound")
    }

    func mark(chatID: String, messageID: String? = nil, phase: String) {
        guard var attempt = current(chatID), messageID == nil || attempt.messageID == messageID else { return }
        let now = NativeSyncPerfLog.now()
        guard attempt.marks[phase] == nil else { return }
        attempt.marks[phase] = now
        attempts[chatID] = attempt
        let elapsed = (now - attempt.started) * 1000
        NativeSyncPerfLog.info("phase=chatSendTiming attempt=\(attempt.token.uuidString) stage=\(phase) elapsedMs=\(String(format: "%.3f", elapsed))")
        if phase == "action" || phase == "selectedMateFrameOpportunity" { revision &+= 1 }
    }

    // The ordered socket dispatcher calls this before actor dispatch or replay
    // buffering. A receipt becomes publishable only after the UI reducer accepts
    // the same user turn and category; it never creates presentation state.
    func serverEventReceived(_ event: StreamingClient.StreamEvent, chatID: String) {
        guard var attempt = current(chatID), let messageID = attempt.messageID else { return }
        let category: String?
        switch event {
        case .taskInitiated(let eventChatID, let taskID, let userMessageID):
            guard eventChatID == chatID else { return }
            attempt.incomingTaskID = userMessageID == messageID ? taskID : nil
            attempts[chatID] = attempt
            return
        case .preprocessingStep(let eventChatID, let step, let data):
            guard eventChatID == chatID, step == "mate_selected", attempt.incomingTaskID != nil else { return }
            category = data?["mate_category"] as? String
        case .typingStarted(let eventChatID, _, let metadata):
            guard eventChatID == chatID,
                  metadata?.userMessageId == messageID || (metadata?.userMessageId == nil && attempt.incomingTaskID != nil) else { return }
            category = metadata?.category
        case .chunk(let eventChatID, _, _, _, _, let userMessageID, let mateCategory, _, _):
            guard eventChatID == chatID,
                  userMessageID == messageID || (userMessageID == nil && attempt.incomingTaskID != nil) else { return }
            category = mateCategory
        default: return
        }
        guard let category, !category.isEmpty else { return }
        if attempt.incomingCategory != category || attempt.incomingReceivedAt == nil {
            attempt.incomingCategory = category
            attempt.incomingReceivedAt = NativeSyncPerfLog.now()
        }
        attempts[chatID] = attempt
    }

    // Called only after the production lifecycle reducer accepts the server event.
    func acceptedMate(lifecycle: ChatStreamingLifecycleState, receivedAt: TimeInterval) {
        guard let chatID = lifecycle.chatId, var attempt = current(chatID),
              let messageID = attempt.messageID, lifecycle.userMessageId == messageID,
              let responseID = lifecycle.messageId ?? lifecycle.taskId,
              let category = lifecycle.selectedMateCategory, !category.isEmpty else { return }
        let identityChanged = attempt.responseID != responseID || attempt.category != category
        attempt.responseID = responseID
        attempt.category = category
        if attempt.marks["mateEventReceived"] == nil, attempt.incomingCategory == category,
           let incomingAt = attempt.incomingReceivedAt {
            attempt.marks["mateEventReceived"] = incomingAt
            NativeSyncPerfLog.info("phase=chatSendTiming attempt=\(attempt.token.uuidString) stage=mateEventReceived elapsedMs=\(String(format: "%.3f", (incomingAt - attempt.started) * 1000))")
        }
        if attempt.marks["mateEventConsumed"] == nil { attempt.marks["mateEventConsumed"] = receivedAt }
        attempts[chatID] = attempt
        mark(chatID: chatID, messageID: messageID, phase: "mateReducerApplied")
        if identityChanged { revision &+= 1 }
    }

    func matchingToken(_ binding: NativeChatSendTimingBinding) -> UUID? {
        guard let attempt = current(binding.chatID), let messageID = attempt.messageID,
              binding.userMessageID == messageID, binding.responseID == attempt.responseID,
              binding.category == attempt.category, attempt.marks["mateReducerApplied"] != nil else { return nil }
        return attempt.token
    }

    func awaitingFrame(_ binding: NativeChatSendTimingBinding) -> Bool {
        matchingToken(binding) != nil && current(binding.chatID)?.marks["selectedMateFrameOpportunity"] == nil
    }

    func frameOpportunity(_ binding: NativeChatSendTimingBinding, token: UUID) {
        guard matchingToken(binding) == token else { return }
        mark(chatID: binding.chatID, phase: "selectedMateFrameOpportunity")
    }

    func probeValue(_ binding: NativeChatSendTimingBinding) -> String {
        guard debugProbeEnabled, let token = matchingToken(binding), let attempt = current(binding.chatID) else { return "" }
        let fields = ["mateEventReceived", "mateEventConsumed", "mateReducerApplied", "selectedMateFrameOpportunity"].compactMap { stage -> String? in
            guard let timestamp = attempt.marks[stage] else { return nil }
            return "\(stage)=\((timestamp - attempt.started) * 1000)"
        }
        return (["attempt=\(token.uuidString)", "actionUnixMs=\(String(format: "%.3f", attempt.actionUnixMilliseconds))"] + fields).joined(separator: ";")
    }

    private func current(_ chatID: String) -> Attempt? {
        guard let attempt = attempts[chatID], attempt.scope == OfflineStore.shared.scopeGeneration,
              NativeSyncPerfLog.now() - attempt.started < 180 else { return nil }
        return attempt
    }
}

// This observes an attached, nonempty identity inside the window and then a
// display-link opportunity. It is not a GPU/display presentation timestamp;
// recorded frames and an actual visible identity remain required proof.
struct NativeChatSendTimingModifier: ViewModifier {
    let binding: NativeChatSendTimingBinding?
    @ObservedObject private var timing = NativeChatSendTiming.shared
    func body(content: Content) -> some View {
        #if os(iOS)
        if let binding {
            content.background {
                if timing.matchingToken(binding) != nil { NativeSelectedMateFrameProbe(binding: binding) }
            }
                .modifier(NativeChatSendTimingAccessibility(binding: binding))
        } else { content }
        #else
        content
        #endif
    }
}

private struct NativeChatSendTimingAccessibility: ViewModifier {
    let binding: NativeChatSendTimingBinding
    @ObservedObject private var timing = NativeChatSendTiming.shared
    func body(content: Content) -> some View {
        if timing.debugProbeEnabled { content.accessibilityValue(timing.probeValue(binding)) }
        else { content }
    }
}

#if os(iOS)
private struct NativeSelectedMateFrameProbe: UIViewRepresentable {
    let binding: NativeChatSendTimingBinding
    func makeUIView(context: Context) -> Probe { Probe() }
    func updateUIView(_ view: Probe, context: Context) { view.binding = binding; view.schedule() }
    static func dismantleUIView(_ uiView: Probe, coordinator: ()) { uiView.stop() }
    @MainActor final class Probe: UIView {
        var binding: NativeChatSendTimingBinding?
        private var link: CADisplayLink?
        private var scheduledToken: UUID?
        override func didMoveToWindow() { super.didMoveToWindow(); schedule() }
        override func layoutSubviews() { super.layoutSubviews(); schedule() }
        func schedule() {
            guard let binding, NativeChatSendTiming.shared.awaitingFrame(binding),
                  let token = NativeChatSendTiming.shared.matchingToken(binding),
                  let window, !isHidden, alpha > 0, !bounds.isEmpty,
                  !convert(bounds, to: window).intersection(window.bounds).isEmpty else { return }
            guard link == nil else { return }
            scheduledToken = token
            let link = CADisplayLink(target: self, selector: #selector(frame(_:)))
            self.link = link
            link.add(to: .main, forMode: .common)
        }
        @objc private func frame(_ link: CADisplayLink) {
            defer { stop() }
            guard let binding, let scheduledToken, let window, !window.isHidden,
                  !isHidden, alpha > 0, !bounds.isEmpty,
                  !convert(bounds, to: window).intersection(window.bounds).isEmpty else { return }
            NativeChatSendTiming.shared.frameOpportunity(binding, token: scheduledToken)
        }
        func stop() { link?.invalidate(); link = nil; scheduledToken = nil }
    }
}
#endif
