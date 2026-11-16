// CoreSlidesRemote — the app's `SlidesRemoteCoreClient` over `CoreSession.shared`:
// the core encrypts, decrypts and orders `slides_present_state`; this file only
// moves the frame through the unowned-frame pass-through (`unownedSocketFrame`
// in, `sendUnownedFrame` out). Refusals arrive as `slides_present_state_rejected`.
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.present.remote-one-core

// ─── Web source ─────────────────────────────────────────────────────
// TS:      frontend/packages/ui/src/components/embeds/slides/slidesPresentRemote.ts
// ────────────────────────────────────────────────────────────────────

import Combine
import Foundation

@MainActor final class CoreSlidesRemote: SlidesRemoteCoreClient {
    private static var instance: CoreSlidesRemote?
    static let frameType = "slides_present_state"

    static func live() -> CoreSlidesRemote? {
        if let instance { return instance }
        guard let session = CoreSession.shared else { return nil }
        let created = CoreSlidesRemote(session: session)
        instance = created
        return created
    }

    private let session: CoreSession
    private let orderings = SlidesRemoteOrderings()
    private let frames = PassthroughSubject<SlidesRemoteFrame, Never>()
    private var subscription: AnyCancellable?
    var incoming: AnyPublisher<SlidesRemoteFrame, Never> { frames.eraseToAnyPublisher() }

    init(session: CoreSession) {
        self.session = session
        subscription = session.events.sink { [weak self] event in self?.apply(event) }
        Task { [session] in
            do {
                try await session.perform { core, _ in try await core.forwardUnownedFrames() }
            } catch {
                NativeDiagnostics.error("slides_remote_forward_failed class=\(CoreSession.errorClass(error))", category: "core_bridge")
            }
        }
    }

    func encrypt(_ state: SlidesRemoteStateRecord) async throws -> String {
        try await session.perform { core, _ in try await core.slidesRemoteEncrypt(state: state) }
    }

    func decrypt(embedId: String, ciphertext: String) async throws -> SlidesRemoteStateRecord {
        try await session.perform { core, _ in
            try await core.slidesRemoteDecrypt(embedId: embedId, ciphertext: ciphertext)
        }
    }

    func send(embedId: String, ciphertext: String) async throws {
        let payload = try JSONSerialization.data(withJSONObject: ["embed_id": embedId, "ciphertext": ciphertext])
        let json = String(decoding: payload, as: UTF8.self)
        try await session.perform { core, cancellation in
            try await core.sendUnownedFrame(
                eventType: Self.frameType, payloadJson: json, cancellation: cancellation)
        }
    }

    func accept(_ state: SlidesRemoteStateRecord) -> Bool { orderings.accept(state: state) }

    private func apply(_ event: ViewEventRecord) {
        guard case .unownedSocketFrame(let eventType, let payloadJson) = event, eventType == Self.frameType,
              let object = try? JSONSerialization.jsonObject(with: Data(payloadJson.utf8)) as? [String: Any],
              let embedId = object["embed_id"] as? String,
              let ciphertext = object["ciphertext"] as? String else { return }
        frames.send(SlidesRemoteFrame(embedId: embedId, ciphertext: ciphertext))
    }
}
