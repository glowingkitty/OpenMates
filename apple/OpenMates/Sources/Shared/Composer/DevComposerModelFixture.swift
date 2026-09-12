#if DEBUG
import SwiftUI

struct DevComposerModelFixture: View {
    @StateObject private var controller: ComposerModelPreferenceController
    @State private var error: String?
    private let catalog = try? NativeModelCatalog.load(bundle: .main)
    init() {
        let catalog = try? NativeModelCatalog.load(bundle: .main)
        let routing = catalog?.routing(health: nil) ?? ModelRoutingCatalog(entries: [])
        let service = ChatModelPreferenceService(adapters: FixtureModelNoPersistence(), catalog: { routing }, notify: { _ in })
        _controller = StateObject(wrappedValue: ComposerModelPreferenceController(service: service, catalog: { routing }))
    }
    var body: some View {
        GeometryReader { proxy in
            if let catalog {
                VStack {
                    NativeComposerModelSelector(catalog: catalog, routing: catalog.routing(health: nil), selection: controller.selection,
                        ready: controller.isReady, viewportWidth: proxy.size.width, onSelect: { selected in
                            let routing = catalog.routing(health: nil)
                            guard selected == "auto" || routing.usable(selected) else { error = AppStrings.error; return }
                            Task { await controller.selectVisible(selected) }
                        }, onOpenDetails: { _ in error = LocalizationManager.shared.text("common.details") })
                    Text(controller.selection).accessibilityIdentifier("dev-model-selection")
                    Text(catalog.routing(health: nil).prefix(selection: controller.selection, text: "Fixture request"))
                        .accessibilityIdentifier("dev-model-routed-text")
                    if let error { Text(error) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else { Text(AppStrings.error).accessibilityIdentifier("dev-model-catalog-error") }
        }.task { try? await controller.activate(.draft(server: "fixture", userID: "fixture", draftID: "fixture-draft")) }
    }
}
@MainActor private final class FixtureModelNoPersistence: ModelPreferenceAdapters {
    func encryptFormatD(_ plaintext: String, scope: ModelPreferenceScope) async throws -> String { throw ModelPreferenceFailure.staleContext }
    func decryptFormatD(_ ciphertext: String, scope: ModelPreferenceScope) async throws -> String { throw ModelPreferenceFailure.staleContext }
    func localRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { throw ModelPreferenceFailure.staleContext }
    func localWrite(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws { throw ModelPreferenceFailure.staleContext }
    func localWriteIfNewer(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference { throw ModelPreferenceFailure.staleContext }
    func remoteRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { throw ModelPreferenceFailure.staleContext }
    func compareAndSet(_ record: EncryptedModelPreference, expected: Int, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { throw ModelPreferenceFailure.staleContext }
}
#endif
