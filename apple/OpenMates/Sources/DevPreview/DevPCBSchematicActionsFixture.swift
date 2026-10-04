// Deterministic owner-authorized PCB controls; no provider runs or private source uploads.
// Web: electronics/PcbSchematicEmbedFullscreen.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
#if DEBUG
import SwiftUI

@MainActor
private final class DevPCBFixtureState: ObservableObject {
    @Published var requests: [String] = []
    let variant: String
    init(variant: String) { self.variant = variant }
    var transport: NativePCBTransport {
        NativePCBTransport(request: { [self] method, path, body in
            requests.append("\(method.rawValue)|\(path)|\(body.flatMap { String(data: $0, encoding: .utf8) } ?? "")")
            if variant == "action-pcb-delayed" { try await Task.sleep(nanoseconds: 500_000_000) }
            if path.contains("/artifacts/") { return Data("(kicad_pcb (version 20240108))".utf8) }
            let failed = variant == "action-pcb-failed"
            return try JSONSerialization.data(withJSONObject: [
                "compile_id": "public-compile", "status": failed ? "failed" : "succeeded",
                "logs": failed ? "Public compile failed" : "Public compile completed",
                "error": failed ? "Public compiler error" : NSNull(),
                "artifact_manifest": ["files": failed ? [] : [["id": "public-board", "name": "public-board.kicad_pcb", "type": "kicad"]]]
            ])
        }, validate: { try Task.checkCancellation() })
    }
}
struct DevPCBSchematicActionsFixture: View {
    let variant: String
    @StateObject private var state: DevPCBFixtureState
    init(variant: String = "action-pcb") {
        self.variant = variant
        _state = StateObject(wrappedValue: DevPCBFixtureState(variant: variant))
    }
    private var embed: EmbedRecord {
        EmbedRecord(id: "public-pcb", type: "electronics-pcb-schematic", status: .finished,
            data: .raw(["code": .init("module PublicBoard:\n    pass"), "language": .init("atopile")]),
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
    }
    var body: some View {
        ZStack(alignment: .bottomLeading) {
            EmbedFullscreenContainer(embeds: [embed], initialEmbedId: embed.id, allEmbedRecords: [embed.id: embed], chatId: nil,
                responsiveViewportWidth: 390)
                .environment(\.nativePCBTransport, state.transport)
                .environment(\.recipientMediaContext, recipient)
            Text(" ").font(.omTiny).foregroundStyle(Color.clear).frame(width: 1, height: 1)
                .allowsHitTesting(false).accessibilityLabel(state.requests.joined(separator: "\n"))
                .accessibilityIdentifier("pcb-fixture-requests")
        }
        .accessibilityIdentifier("dev-pcb-actions-fixture")
    }
    private var recipient: RecipientMediaContext? {
        guard variant == "action-pcb-recipient" else { return nil }
        return try? RecipientMediaContext(linkURL: URL(string: "https://app.dev.openmates.org/share/chat/public-pcb#key=abc")!,
            requestLoader: { _ in throw URLError(.unsupportedURL) })
    }
}
#endif
