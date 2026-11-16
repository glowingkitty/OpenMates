// SlidesPresentRemoteModel — state machine of the slides presentation remote:
// follows the `slides_present_state` frames of the user's other devices and sends
// remote-origin states (Previous, Next, jump, notes). Encryption, decryption and the
// ordering of relayed states live in the Rust core (`slidesRemote*`); this type only
// builds the next state and tracks staleness. Speaker notes stay on this device.
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.present.remote-control, slides.present.remote-one-core

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/slides/SlidesPresentRemote.svelte
// TS:      frontend/packages/ui/src/components/embeds/slides/slidesPresentRemote.ts
// CSS:     frontend/packages/ui/src/components/embeds/slides/SlidesPresentRemote.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Combine
import Foundation

/// One relayed `slides_present_state` frame (ciphertext only).
struct SlidesRemoteFrame: Equatable, Sendable {
    let embedId: String
    let ciphertext: String
}

/// The core calls the remote needs; `CoreSlidesRemote` is the app's implementation.
@MainActor protocol SlidesRemoteCoreClient: AnyObject {
    var incoming: AnyPublisher<SlidesRemoteFrame, Never> { get }
    func encrypt(_ state: SlidesRemoteStateRecord) async throws -> String
    func decrypt(embedId: String, ciphertext: String) async throws -> SlidesRemoteStateRecord
    func send(embedId: String, ciphertext: String) async throws
    func accept(_ state: SlidesRemoteStateRecord) -> Bool
}

@MainActor final class SlidesPresentRemoteModel: ObservableObject {
    /// Seconds without a presenter state after which the presentation counts as ended.
    static let staleSeconds: TimeInterval = 25

    let embedId: String
    private let stepCounts: [Int]
    private let notesBySlide: [String]
    private let client: SlidesRemoteCoreClient
    @Published private(set) var state: SlidesRemoteStateRecord?
    @Published private(set) var notesVisible = false
    private var lastReceived: Date?
    private var subscription: AnyCancellable?

    init(embedId: String, deck: SlideDeckRecord?, client: SlidesRemoteCoreClient) {
        self.embedId = embedId
        self.client = client
        stepCounts = SlidesDeckNavigation(deck: deck).stepCounts
        notesBySlide = (deck?.slides ?? []).map(\.notes)
        subscription = client.incoming
            .filter { [embedId] in $0.embedId == embedId }
            .sink { [weak self] frame in
                Task { @MainActor in await self?.receive(frame.ciphertext) }
            }
    }

    var total: Int { stepCounts.count }
    var isPresenting: Bool { state?.presenting == true }
    var index: Int { Int(state?.index ?? 0) }
    var positionLabel: String { "\(index + 1) / \(total)" }
    var notes: String { index < notesBySlide.count ? notesBySlide[index] : "" }
    var canGoPrevious: Bool { isPresenting && (index > 0 || (state?.step ?? 0) > 0) }
    var canGoNext: Bool {
        guard isPresenting, index < total else { return false }
        return index < total - 1 || Int(state?.step ?? 0) < stepCounts[index]
    }

    /// Decrypts and applies one relayed frame; refused and out-of-order frames are dropped.
    func receive(_ ciphertext: String, now: Date = Date()) async {
        guard let state = try? await client.decrypt(embedId: embedId, ciphertext: ciphertext) else { return }
        apply(state, now: now)
    }

    func apply(_ incoming: SlidesRemoteStateRecord, now: Date = Date()) {
        guard incoming.embedId == embedId, client.accept(incoming) else { return }
        state = incoming
        lastReceived = now
    }

    /// Marks the presentation as ended when the presenter went silent.
    func expireIfStale(now: Date = Date()) {
        guard var current = state, current.presenting, let lastReceived,
              now.timeIntervalSince(lastReceived) > Self.staleSeconds else { return }
        current.presenting = false
        state = current
    }

    func next() async {
        guard canGoNext, let current = state else { return }
        if Int(current.step) < stepCounts[index] {
            await publish(index: current.index, step: current.step + 1)
        } else {
            await publish(index: current.index + 1, step: 0)
        }
    }

    func previous() async {
        guard canGoPrevious, let current = state else { return }
        if current.step > 0 {
            await publish(index: current.index, step: current.step - 1)
        } else {
            await publish(index: current.index - 1, step: UInt32(stepCounts[index - 1]))
        }
    }

    func jump(toSlide position: Int) async {
        guard isPresenting, position >= 1, position <= total else { return }
        await publish(index: UInt32(position - 1), step: 0)
    }

    func toggleNotes() { notesVisible.toggle() }

    private func publish(index: UInt32, step: UInt32) async {
        guard let current = state else { return }
        let next = SlidesRemoteStateRecord(
            embedId: embedId, sessionId: current.sessionId, seq: current.seq + 1, index: index,
            step: step, notesVisible: current.notesVisible, presenting: true, origin: .remote)
        do {
            let sealed = try await client.encrypt(next)
            try await client.send(embedId: embedId, ciphertext: sealed)
            apply(next)
        } catch {
            NativeDiagnostics.error("slides_remote_send_failed class=\(CoreSession.errorClass(error))", category: "core_bridge")
        }
    }
}
