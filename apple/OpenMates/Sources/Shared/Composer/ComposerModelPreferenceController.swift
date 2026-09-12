// PRIVATE integration controller. No production target registration.
// Mirrors MessageInput's separate saved-chat, new-draft and incognito lifecycles.
import Foundation
import Combine

@MainActor final class ComposerModelPreferenceController: ObservableObject {
    @Published private(set) var visibleError: String?
    private var subscription: UUID?
    private var runtime: ModelPreferenceAppRuntime?
    enum Context: Equatable, Hashable {
        case saved(ModelPreferenceScope)
        case draft(server: String, userID: String, draftID: String)
        case incognito(server: String, userID: String, chatID: String)
        case guest(sessionID: String)
        var server: String? {
            switch self {
            case .saved(let scope): scope.server
            case .draft(let server, _, _), .incognito(let server, _, _): server
            case .guest: nil
            }
        }
        var userID: String? {
            switch self {
            case .saved(let scope): scope.userID
            case .draft(_, let user, _), .incognito(_, let user, _): user
            case .guest: nil
            }
        }
    }
    private let service: ChatModelPreferenceService
    private let catalog: () -> ModelRoutingCatalog
    private var context: Context?
    private var generation: UInt64 = 0
    private var memorySelection = "auto"
    private var memorySelectionWasChosen = false
    private var loading = false
    var selection: String {
        if case .saved = context { return service.selection }
        return memorySelection
    }
    var isReady: Bool {
        guard context != nil, !loading else { return false }
        if case .saved = context { return service.isReady }
        return true
    }
    init(service: ChatModelPreferenceService, catalog: @escaping () -> ModelRoutingCatalog) {
        self.service = service; self.catalog = catalog
        service.stateDidChange = { [weak self] in self?.objectWillChange.send() }
    }
    func invalidate() {
        if let subscription { runtime?.unsubscribe(subscription); self.subscription = nil }
        generation &+= 1
        context = nil; memorySelection = "auto"; memorySelectionWasChosen = false
        loading = false; visibleError = nil
        service.activate(nil)
        objectWillChange.send()
    }
    func activate(_ newContext: Context?) async throws {
        try Task.checkCancellation()
        guard context != newContext else { return }
        if let subscription { runtime?.unsubscribe(subscription); self.subscription = nil }
        objectWillChange.send()
        generation &+= 1
        let token = generation
        context = newContext
        memorySelection = "auto"
        memorySelectionWasChosen = false
        loading = true
        defer { if generation == token { loading = false; objectWillChange.send() } }
        if case .saved(let scope) = newContext {
            service.activate(scope)
            _ = try await service.restore()
            if generation == token { subscription = runtime?.subscribe(scope: scope, service: service, onChange: { [weak self] in self?.objectWillChange.send() }) }
        } else {
            service.activate(nil)
        }
    }
    func select(_ value: String) async throws {
        objectWillChange.send()
        defer { objectWillChange.send() }
        guard let context else { throw ModelPreferenceFailure.staleContext }
        if case .saved = context {
            _ = try await service.select(value)
        } else {
            guard let canonical = catalog().canonical(value),
                  canonical == "auto" || catalog().usable(canonical) else { throw ModelPreferenceFailure.unavailable }
            memorySelectionWasChosen = true
            memorySelection = canonical // guest/draft/incognito never call encrypted storage or remote APIs.
        }
    }
    /// Called only after preflight creates the exact formerly-unsaved draft ID.
    /// Repeated delivery restores/retries the same durable intent, not a fresh CAS.
    func promoteDraft(draftID: String, to scope: ModelPreferenceScope, waitForRemote: Bool = true) async throws {
        if case .saved(let current) = context, current == scope {
            if waitForRemote, !service.isReady { _ = try await service.restore() }
            return
        }
        guard case .draft(let server, let owner, let currentDraft) = context,
              server == scope.server, owner == scope.userID, currentDraft == draftID else {
            throw ModelPreferenceFailure.staleContext
        }
        let pending = memorySelection
        let shouldPersist = memorySelectionWasChosen
        generation &+= 1
        let token = generation
        loading = true
        defer { if generation == token { loading = false; objectWillChange.send() } }
        service.activate(scope)
        // Retain the promoted identity even if syncing fails: retry must restore
        // the original durable pending ciphertext instead of generating new keys.
        context = .saved(scope)
        if shouldPersist {
            if waitForRemote { _ = try await service.select(pending) }
            else { _ = try await service.stage(pending) }
        } else if waitForRemote { _ = try await service.restore() }
        guard generation == token else { throw ModelPreferenceFailure.staleContext }
        context = .saved(scope)
        memorySelectionWasChosen = false
        subscription = runtime?.subscribe(scope: scope, service: service, onChange: { [weak self] in self?.objectWillChange.send() })
    }
    func bind(runtime: ModelPreferenceAppRuntime) { self.runtime = runtime }
    func selectVisible(_ value: String) async {
        let token = generation
        visibleError = nil
        do { try await select(value) }
        catch {
            guard generation == token else { return }
            visibleError = LocalizationManager.shared.text("enter_message.model_selector.unavailable_reset")
        }
    }
    func retryVisible() async {
        let token = generation
        visibleError = nil
        do { try await reconnect() }
        catch {
            guard generation == token else { return }
            visibleError = LocalizationManager.shared.text("login.cant_connect_to_server")
        }
        if generation == token { objectWillChange.send() }
    }
    func reconnect() async throws {
        guard case .saved(let scope) = context, !loading else { return }
        let token = generation
        loading = true; objectWillChange.send()
        defer { if generation == token { loading = false; objectWillChange.send() } }
        _ = try await service.restore()
        guard generation == token else { throw ModelPreferenceFailure.staleContext }
        if subscription == nil {
            subscription = runtime?.subscribe(scope: scope, service: service,
                onChange: { [weak self] in self?.objectWillChange.send() })
        }
    }
    func textForSend(_ text: String) async throws -> String {
        guard isReady else { throw ModelPreferenceFailure.notRestored }
        if case .saved = context { return try await service.textForSend(text) }
        if text.contains("@ai-model:") || text.contains("@best-model:") { return text }
        guard memorySelection == "auto" || catalog().usable(memorySelection) else {
            // A host must show the same localized unavailable notice before
            // switching this memory-only context to Auto; do not silently route.
            throw ModelPreferenceFailure.unavailable
        }
        return catalog().prefix(selection: memorySelection, text: text)
    }
}

// Snapshot used at the UI → asynchronous routing → send boundary. Never infer
// destination identity again after awaiting a model preference/network operation.
struct ComposerModelSendOwnership: Equatable {
    let server: String
    let accountGeneration: UUID
    let chatID: String
    func matches(server: String, accountGeneration: UUID, chatID: String?) -> Bool {
        self.server == server && self.accountGeneration == accountGeneration && self.chatID == chatID
    }
}
