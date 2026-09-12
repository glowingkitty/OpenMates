import SwiftUI
import Combine

@MainActor final class NativeComposerModelHost: ObservableObject {
    @Published var catalog: NativeModelCatalog?
    @Published var error: String?
    @Published var details: NativeModelCatalog.Model?
    @Published private(set) var controller: ComposerModelPreferenceController?
    private var lifecycle = Set<AnyCancellable>()
    private var observation: AnyCancellable?
    private var activationGeneration = UUID()
    private var healthTask: Task<Void, Never>?
    private let runtime = AppSessionCoordinator.shared.modelPreferences
    init() {
        do {
            guard let catalog = NativeModelCatalogRuntime.shared.catalog else { throw NativeModelCatalog.Failure.invalidCatalog }
            self.catalog = catalog
            let service = ChatModelPreferenceService(adapters: runtime.makeAdapters(),
                catalog: { NativeModelCatalogRuntime.shared.routing },
                notify: { [weak self] key in self?.error = LocalizationManager.shared.text(key) })
            let controller = ComposerModelPreferenceController(service: service,
                catalog: { NativeModelCatalogRuntime.shared.routing })
            controller.bind(runtime: runtime)
            self.controller = controller
            observation = controller.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
            AppSessionCoordinator.shared.webSocketManager.$connectionState.sink { [weak controller] state in
                if state == .connected { Task { @MainActor in try? await controller?.reconnect() } }
            }.store(in: &lifecycle)
            // The app runtime owns the authenticated socket/account. Never create
            // a second AuthManager or rely on a nonexistent global auth singleton.
            runtime.$ownershipRevision.dropFirst().sink { [weak self] _ in self?.deactivate() }
                .store(in: &lifecycle)
        } catch { self.error = LocalizationManager.shared.text("login.cant_connect_to_server") }
    }
    func deactivate() {
        activationGeneration = UUID()
        healthTask?.cancel(); healthTask = nil
        controller?.invalidate()
        details = nil; error = nil
        objectWillChange.send()
    }
    func activate(_ context: ComposerModelPreferenceController.Context?) async {
        guard !Task.isCancelled else { return }
        guard let context else { deactivate(); return }
        let profile = ServerProfile.current()
        if let user = context.userID {
            guard let owner = runtime.connection, owner.userID == user,
                  owner.server == context.server, owner.server == profile.apiBaseURL.absoluteString else { return }
        } else if runtime.connection != nil { return }
        let token = UUID(); activationGeneration = token
        NativeModelCatalogRuntime.shared.activatePreferences(server: profile.apiBaseURL.absoluteString, user: context.userID)
        // Public health is advisory and uses web's unknown/usable fallback. It
        // refreshes separately; it must never hold input activation or sending.
        healthTask?.cancel()
        healthTask = Task { await NativeModelCatalogRuntime.shared.refresh(profile: profile) }
        do {
            try Task.checkCancellation()
            try await controller?.activate(context)
            guard activationGeneration == token, !Task.isCancelled else { return }
            error = nil
        } catch {
            guard activationGeneration == token, !Task.isCancelled else { return }
            self.error = LocalizationManager.shared.text("login.cant_connect_to_server")
        }
    }
    var sendGeneration: UUID { activationGeneration }
    func textForSend(_ text: String, expectedGeneration: UUID? = nil) async throws -> String {
        let token = expectedGeneration ?? activationGeneration
        guard token == activationGeneration, let controller else { throw ModelPreferenceFailure.staleContext }
        let result = try await controller.textForSend(text)
        guard token == activationGeneration, !Task.isCancelled else { throw ModelPreferenceFailure.staleContext }
        return result
    }
    func savedContext(chatID: String) -> ComposerModelPreferenceController.Context {
        let server = ServerProfile.current().apiBaseURL.absoluteString
        guard let connection = runtime.connection, connection.server == server else { return .guest(sessionID: chatID) }
        if IncognitoChatSession.isIncognitoChatId(chatID) { return .incognito(server: server, userID: connection.userID, chatID: chatID) }
        return .saved(.init(server: server, userID: connection.userID, chatID: chatID))
    }
}

struct NativeComposerModelHostView: View {
    @ObservedObject private var modelCatalog = NativeModelCatalogRuntime.shared
    @ObservedObject var host: NativeComposerModelHost
    let viewportWidth: CGFloat
    var body: some View {
        if let catalog = host.catalog, let controller = host.controller {
            VStack(alignment: .leading) {
                NativeComposerModelSelector(catalog: catalog, routing: modelCatalog.routing, selection: controller.selection,
                    ready: controller.isReady, viewportWidth: viewportWidth,
                    onSelect: { value in Task { await controller.selectVisible(value) } }, onOpenDetails: { host.details = $0 })
                if let error = controller.visibleError ?? host.error {
                    Button(error) { Task { await controller.retryVisible() } }.foregroundStyle(Color.error)
                        .accessibilityIdentifier("composer-model-retry")
                }
            }
            .overlay(alignment: .bottomLeading) {
                if let model = host.details {
                    NativeComposerModelDetails(model: model, onClose: { host.details = nil })
                        .frame(width: min(440, max(300, viewportWidth - 24)), height: 520)
                        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 20))
                        .shadow(color: .black.opacity(0.15), radius: 16, x: 0, y: 4)
                        .offset(y: -48).zIndex(30)
                }
            }
        } else if let error = host.error { Text(error).foregroundStyle(Color.error) }
    }
}
