// Loads the same generated metadata as the web composer and its public health
// snapshot. Web: stores/appHealthStore.ts and utils/aiModelSelection.ts.
// Every HTTP request is pinned to an explicit server profile; late responses
// cannot replace a different server's catalog health. No private profile fields
// or new settings endpoint are inferred here.
import Foundation
import Combine

@MainActor final class NativeModelCatalogRuntime: ObservableObject {
    static let shared = NativeModelCatalogRuntime()
    @Published private(set) var catalog: NativeModelCatalog?
    @Published private(set) var health: ProviderHealthSnapshot?
    @Published private(set) var error: String?
    @Published private(set) var disabledPreferences = NativeModelDisabledPreferences.Value()
    private let preferenceStore = NativeModelDisabledPreferences()
    private var preferenceScope: (server: String, user: String)?
    var canEditPreferences: Bool { preferenceScope != nil }
    func activatePreferences(server: String, user: String?) {
        guard let user else { preferenceScope = nil; disabledPreferences = .init(); return }
        preferenceScope = (server, user)
        disabledPreferences = preferenceStore.read(server: server, user: user)
    }
    func setModel(_ id: String, enabled: Bool) {
        guard let scope = preferenceScope else { return }
        var value = disabledPreferences
        if enabled { value.disabled_ai_models.remove(id) } else { value.disabled_ai_models.insert(id) }
        do { try preferenceStore.write(value, server: scope.server, user: scope.user); disabledPreferences = value }
        catch { self.error = LocalizationManager.shared.text("login.cant_connect_to_server") }
    }
    func setServer(_ id: String, model: String, enabled: Bool) {
        guard let scope = preferenceScope else { return }
        var value = disabledPreferences
        if enabled { value.disabled_ai_servers[model, default: []].remove(id) }
        else { value.disabled_ai_servers[model, default: []].insert(id) }
        do { try preferenceStore.write(value, server: scope.server, user: scope.user); disabledPreferences = value }
        catch { self.error = LocalizationManager.shared.text("login.cant_connect_to_server") }
    }
    private var server: String?
    private var generation = UUID()
    private var refreshedAt: Date?
    private let loadCatalog: () throws -> NativeModelCatalog
    private let loadHealth: @MainActor (ServerProfile) async throws -> ProviderHealthSnapshot
    private let now: () -> Date
    private let refreshInterval: TimeInterval = 60

    init(loadCatalog: @escaping () throws -> NativeModelCatalog = { try NativeModelCatalog.load(bundle: .main) },
         loadHealth: (@MainActor (ServerProfile) async throws -> ProviderHealthSnapshot)? = nil,
         now: @escaping () -> Date = Date.init) {
        self.loadCatalog = loadCatalog
        self.loadHealth = loadHealth ?? { profile in
            let data: Data = try await APIClient.shared.request(.get, path: "/v1/health", serverProfile: profile)
            return try JSONDecoder().decode(ProviderHealthSnapshot.self, from: data)
        }
        self.now = now
        do { catalog = try loadCatalog() }
        catch {
            self.error = LocalizationManager.shared.text("enter_message.model_selector.load_failed")
            NativeDiagnostics.warning("Model catalog could not be loaded", category: "composer")
        }
    }
    var routing: ModelRoutingCatalog {
        catalog?.routing(disabledModels: disabledPreferences.disabled_ai_models, disabledServers: disabledPreferences.disabled_ai_servers, health: health) ?? ModelRoutingCatalog(entries: [])
    }
    func refresh(profile: ServerProfile, force: Bool = false) async {
        let key = profile.apiBaseURL.absoluteString
        if server == key, !force, let refreshedAt, now().timeIntervalSince(refreshedAt) < refreshInterval { return }
        if server != key { health = nil }
        server = key
        let token = UUID(); generation = token
        if catalog == nil {
            do { catalog = try loadCatalog(); error = nil }
            catch {
                self.error = LocalizationManager.shared.text("enter_message.model_selector.load_failed")
                NativeDiagnostics.warning("Model catalog retry failed", category: "composer")
                return
            }
        }
        do {
            let result = try await loadHealth(profile)
            guard generation == token, server == key, !Task.isCancelled else { return }
            health = result; refreshedAt = now()
        } catch {
            guard generation == token, server == key, !Task.isCancelled else { return }
            // The web treats a failed/missing health snapshot as unknown/usable.
            // Do not retain stale known-unhealthy state from an earlier fetch.
            health = nil; refreshedAt = now()
            NativeDiagnostics.warning("Provider health unavailable; matching web unknown-health policy", category: "composer")
        }
    }
}
