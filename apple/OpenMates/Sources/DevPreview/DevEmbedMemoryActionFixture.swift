// Synthetic encrypted memory transport; no real account, API, disk or reminders.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte
// CSS: .embed-header-cta-group, .embed-header-cta.secondary/destructive
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import SwiftUI
import CryptoKit

@MainActor
struct DevEmbedMemoryActionFixture: View {
    @StateObject private var service: SettingsMemoryService
    private let embed: EmbedRecord
    private let config: NativeEmbedMemoryConfig

    init(variant: String) {
        let raw: [String: Any] = ["title": "Public memory fixture", "id": "public-event", "url": "https://example.invalid/event"]
        let record = EmbedRecord(id: "public-memory-child", type: "events-event", status: .finished,
                                 data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil,
                                 appId: "events", skillId: "event", embedIds: nil, createdAt: nil)
        embed = record
        config = NativeEmbedMemoryConfig.config(for: record)!
        _service = StateObject(wrappedValue: DevEmbedMemoryTransport(failFirstSave: variant == "action-memory-error").service())
    }

    var body: some View {
        VStack(spacing: .spacing4) {
            EmbedFullscreenHeader(embed: embed,
                headerCTA: EmbedHeaderCTA(title: AppStrings.openOnProvider("Public provider"), accessibilityIdentifier: "external-provider-cta") {},
                secondaryHeaderCTA: AnyView(NativeEmbedMemoryButton(config: config, service: service)),
                viewportWidth: 320, responsiveViewportWidth: 320)
            Spacer(minLength: 0)
        }
        .frame(width: 320)
        .background(Color.grey0)
        .accessibilityIdentifier("dev-embed-memory-action-fixture")
    }
}

@MainActor
private final class DevEmbedMemoryTransport {
    private let key = SymmetricKey(size: .bits256)
    private let scope = UUID()
    private let server = ServerProfile.current()
    private var record: SettingsEncryptedMemoryRecord?
    private var failFirstSave: Bool
    init(failFirstSave: Bool) { self.failFirstSave = failFirstSave }

    func service() -> SettingsMemoryService {
        SettingsMemoryService(transport: { method, path, body, _ in
            if path.contains("metadata") {
                return Data("{\"apps\":{\"events\":{\"settings_and_memories\":[{\"id\":\"saved_events\",\"name\":\"Saved events\"}]}}}".utf8)
            }
            if method == .get {
                let data = try JSONEncoder().encode(self.record.map { [$0] } ?? [])
                return try JSONSerialization.data(withJSONObject: ["memories": JSONSerialization.jsonObject(with: data)])
            }
            // Deterministic delay exposes the actual service's pending state.
            try await Task.sleep(for: .seconds(2))
            if method == .delete { self.record = nil; return Data("{}".utf8) }
            if self.failFirstSave { self.failFirstSave = false; throw URLError(.notConnectedToInternet) }
            guard let body, let root = try JSONSerialization.jsonObject(with: body) as? [String: Any], let entry = root["entry"] else {
                throw SettingsMemoryServiceError.invalidPayload
            }
            self.record = try JSONDecoder().decode(SettingsEncryptedMemoryRecord.self, from: JSONSerialization.data(withJSONObject: entry))
            return Data("{}".utf8)
        }, keyLoader: { _ in self.key },
        environment: .init(currentAccountID: { "synthetic-memory-preview" }, scopeGeneration: { self.scope }, serverProfile: { self.server }),
        teamContext: { .init(epoch: 0, teamID: nil) }, observesSync: false, liveActivitySnapshot: { _ in })
    }
}
#endif
