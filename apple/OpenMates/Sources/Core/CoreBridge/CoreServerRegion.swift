// The device-local "Prefer EU servers" setting (Settings > AI > Server region).
// The core owns the wire value and when it is sent with a turn; it does not
// persist the setting. Swift keeps the choice as a plain preference in
// UserDefaults (not a credential) and hands it to the core when the core is
// created (`CoreSession.launch`) and whenever the user changes it. The core
// keeps it across sign-ins, so no per-login re-apply is needed.
// Web: the same setting is `server_region_preference` ('eu' | 'global') in the
// profile store; EU is the default and only "global" switches it off.
// Specification: specifications/features/ai-model-routing/specification.yml
// Assertions: ai-model-routing.settings.hierarchy-canonical

import Combine
import Foundation

@MainActor
final class ServerRegionSetting: ObservableObject {
    /// The app's setting; attached to the app's core by `CoreSession.launch()`.
    static let shared = ServerRegionSetting()

    static let storageKey = "openmates.server_region_preference"

    /// Stored text for each choice; the core reads the same two words.
    static func storedText(_ preference: ServerRegionPreferenceRecord) -> String {
        switch preference {
        case .eu: return "eu"
        case .global: return "global"
        }
    }

    /// Any value other than "global" (or none) is EU, as the web reads it.
    static func preference(fromStored value: String?) -> ServerRegionPreferenceRecord {
        value == "global" ? .global : .eu
    }

    @Published private(set) var preference: ServerRegionPreferenceRecord

    private let defaults: UserDefaults
    private weak var core: ViewModelCore?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        preference = Self.preference(fromStored: defaults.string(forKey: Self.storageKey))
    }

    /// True while AI turns prefer EU-hosted servers (the toggle's state).
    var prefersEU: Bool { preference == .eu }

    /// Sets and stores the choice, and applies it to the attached core.
    func setPrefersEU(_ prefersEU: Bool) {
        let next: ServerRegionPreferenceRecord = prefersEU ? .eu : .global
        preference = next
        defaults.set(Self.storedText(next), forKey: Self.storageKey)
        core?.setServerRegionPreference(preference: next)
    }

    /// Hands the stored choice to `core` (core start); later changes follow.
    func attach(core: ViewModelCore) {
        self.core = core
        core.setServerRegionPreference(preference: preference)
    }
}
