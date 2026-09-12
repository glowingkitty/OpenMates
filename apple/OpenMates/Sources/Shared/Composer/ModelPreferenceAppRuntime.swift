import Foundation
import Combine
import CryptoKit

@MainActor final class ModelPreferenceAppRuntime: ObservableObject {
    @Published private(set) var ownershipRevision = UUID()
    private let socket: WebSocketManager
    private let store: ChatStore
    private var account: (server: String, user: String)?
    private let mutations = ModelPreferenceMutationCoordinator()
    private let repository: ModelPreferenceEncryptedRepository
    lazy var transport = ModelPreferenceSocketTransport(socket: socket, current: { [weak self] in self?.connection })
    lazy var inbound = ModelPreferenceInboundCoordinator(repository: repository, current: { [weak self] in self?.connection }, ownsChat: { [weak self] in self?.store.chat(for: $0) != nil })
    var connection: ModelPreferenceConnection? {
        guard let account else { return nil }
        return .init(server: account.server, userID: account.user, socketGeneration: socket.modelPreferenceSocketGeneration)
    }
    init(socket: WebSocketManager, store: ChatStore, directory: URL) {
        self.socket = socket; self.store = store
        repository = ModelPreferenceEncryptedRepository(directory: directory)
    }
    func activate(server: String, user: String) {
        let changed = account?.server != server || account?.user != user
        if changed { inbound.clearAccount() }
        account = (server, user)
        if changed { ownershipRevision = UUID() }
        socket.modelPreferenceInbound = { [weak self] type, fields, generation in
            do { try self?.inbound.receive(type: type, fields: fields, generation: generation) }
            catch { NativeDiagnostics.warning("Model preference inbound record rejected", category: "sync") }
        }
    }
    func stop() {
        account = nil; inbound.clearAccount(); socket.modelPreferenceInbound = nil
        NativeModelCatalogRuntime.shared.activatePreferences(server: ServerProfile.current().apiBaseURL.absoluteString, user: nil)
        ownershipRevision = UUID()
    }
    func metadataChanged() {
        do { try inbound.ownershipDidChange() }
        catch { NativeDiagnostics.warning("Model preference queued record rejected", category: "sync") }
    }
    func makeAdapters() -> ModelPreferenceNativeAdapters {
        ModelPreferenceNativeAdapters(repository: repository, mutation: { [mutations] scope, operation in
            try await mutations.perform(scope, operation: operation)
        }, currentConnection: { [weak self] in self?.connection },
            request: { [weak self] connection, type, payload, events, timeout in
                guard let self else { throw ModelPreferenceFailure.staleContext }
                return try await self.transport.request(connection, type: type, payload: payload, events: events, timeout: timeout)
            }, masterKey: { [weak self] scope in
                guard let self, let before = self.connection, before.server == scope.server, before.userID == scope.userID else { throw ModelPreferenceFailure.staleContext }
                guard let key = try await CryptoManager.shared.loadMasterKey(for: scope.userID) else { throw ModelPreferenceFailure.invalidPayload }
                guard self.connection == before else { throw ModelPreferenceFailure.staleContext }
                return key
            })
    }
    // Active composer owns/unsubscribes token; filter account AND chat before
    // delivery, then service generation guards protect its asynchronous decrypt.
    func subscribe(scope: ModelPreferenceScope, service: ChatModelPreferenceService, onChange: @escaping () -> Void = {}) -> UUID {
        inbound.subscribe { receivedScope, record in
            guard receivedScope == scope else { return }
            Task { @MainActor in
                _ = try? await service.receiveRemote(record, for: scope)
                onChange()
            }
        }
    }
    func unsubscribe(_ token: UUID) { inbound.unsubscribe(token) }
}
