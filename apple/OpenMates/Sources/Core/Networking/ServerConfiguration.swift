// Server endpoint configuration for the Apple app.
// Keeps the native API, web app origin, and passkey relying-party domain aligned.
// The selected web domain is persisted locally so testers can switch servers
// without rebuilding the app. Simulator/debug builds default to dev.
// Native passkeys still require the chosen web credential domain to be present
// in the app entitlement and in the domain's apple-app-site-association file.

import Foundation

struct ServerProfile: Equatable, Codable {
    let id: String
    let displayDomain: String
    let webBaseURL: URL
    let apiBaseURL: URL
    let webSocketBaseURL: URL
    let uploadBaseURL: URL

    var diagnosticsKind: String {
        switch id {
        case "production": return "production"
        case "development": return "development"
        default: return "self_hosted"
        }
    }

    var endpointConfiguration: ServerEndpointConfiguration {
        ServerEndpointConfiguration(
            selectedDomain: displayDomain,
            customDomains: id == "production" ? [] : [displayDomain]
        )
    }

    static let production = ServerProfile(domain: ServerEndpointConfiguration.productionDomain, id: "production")
    static let development = ServerProfile(domain: ServerEndpointConfiguration.developmentDomain, id: "development")

    static func custom(domain: String) -> ServerProfile {
        let normalized = ServerEndpointConfiguration.normalizedDomain(domain)
        return ServerProfile(domain: normalized, id: "custom:\(normalized)")
    }

    static func validatedSelfHostedURL(_ rawValue: String) throws -> ServerProfile {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.lowercased().hasPrefix("http://") else {
            throw ServerProfileValidationError.invalidHTTPSURL
        }
        let urlString = trimmed.lowercased().hasPrefix("https://") ? trimmed : "https://\(trimmed)"
        guard let components = URLComponents(string: urlString),
              components.scheme == "https",
              components.host?.isEmpty == false,
              components.user == nil,
              components.password == nil,
              components.port == nil,
              components.path.isEmpty || components.path == "/",
              components.query == nil,
              components.fragment == nil else {
            throw ServerProfileValidationError.invalidHTTPSURL
        }
        return custom(domain: components.host ?? "")
    }

    static func current() -> ServerProfile {
        from(configuration: ServerConfiguration.current)
    }

    static func from(configuration: ServerEndpointConfiguration) -> ServerProfile {
        switch configuration.selectedDomain {
        case ServerEndpointConfiguration.productionDomain:
            return .production
        case ServerEndpointConfiguration.developmentDomain:
            return .development
        default:
            return .custom(domain: configuration.selectedDomain)
        }
    }

    static func fromPayload(
        id: String,
        webBaseURLString: String,
        apiBaseURLString: String,
        uploadBaseURLString: String?
    ) -> ServerProfile? {
        guard let webBaseURL = URL(string: webBaseURLString),
              let apiBaseURL = URL(string: apiBaseURLString) else { return nil }
        let uploadBaseURL = uploadBaseURLString.flatMap { URL(string: $0) } ?? uploadBaseURL(for: id, apiBaseURL: apiBaseURL)
        return ServerProfile(
            id: id,
            displayDomain: webBaseURL.host() ?? webBaseURLString,
            webBaseURL: webBaseURL,
            apiBaseURL: apiBaseURL,
            webSocketBaseURL: webSocketURL(for: apiBaseURL),
            uploadBaseURL: uploadBaseURL
        )
    }

    private init(domain: String, id: String) {
        let normalized = ServerEndpointConfiguration.normalizedDomain(domain)
        let webBaseURL = ServerEndpointConfiguration.httpsURL(for: normalized)
        let apiBaseURL = ServerEndpointConfiguration.apiURL(forWebDomain: normalized)
        self.init(
            id: id,
            displayDomain: webBaseURL.host() ?? normalized,
            webBaseURL: webBaseURL,
            apiBaseURL: apiBaseURL,
            webSocketBaseURL: Self.webSocketURL(for: apiBaseURL),
            uploadBaseURL: Self.uploadBaseURL(for: id, apiBaseURL: apiBaseURL)
        )
    }

    private init(
        id: String,
        displayDomain: String,
        webBaseURL: URL,
        apiBaseURL: URL,
        webSocketBaseURL: URL,
        uploadBaseURL: URL
    ) {
        self.id = id
        self.displayDomain = displayDomain
        self.webBaseURL = webBaseURL
        self.apiBaseURL = apiBaseURL
        self.webSocketBaseURL = webSocketBaseURL
        self.uploadBaseURL = uploadBaseURL
    }

    private static func webSocketURL(for apiBaseURL: URL) -> URL {
        var components = URLComponents(url: apiBaseURL, resolvingAgainstBaseURL: false)
        components?.scheme = apiBaseURL.scheme == "http" ? "ws" : "wss"
        components?.path = "/v1/ws"
        return components?.url ?? URL(string: "wss://api.openmates.org/v1/ws")!
    }

    private static func uploadBaseURL(for id: String, apiBaseURL: URL) -> URL {
        id == "production" ? ServerEndpointConfiguration.uploadBaseURL : apiBaseURL
    }
}

enum ServerProfileValidationError: Error {
    case invalidHTTPSURL
}

struct WatchServerProfileStore {
    private static let successfulProfileKey = "openmates.watch.successfulServerProfile"

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func currentProfile() -> ServerProfile {
        guard let data = defaults.data(forKey: Self.successfulProfileKey),
              let profile = try? JSONDecoder().decode(ServerProfile.self, from: data) else {
            return .production
        }
        return profile
    }

    func saveSuccessfulProfile(_ profile: ServerProfile) {
        guard profile != .production, let data = try? JSONEncoder().encode(profile) else {
            resetToProduction()
            return
        }
        defaults.set(data, forKey: Self.successfulProfileKey)
    }

    func resetToProduction() {
        defaults.removeObject(forKey: Self.successfulProfileKey)
    }
}

struct ServerEndpointConfiguration: Equatable {
    let selectedDomain: String
    let customDomains: [String]

    var apiBaseURL: URL {
        Self.apiURL(forWebDomain: selectedDomain)
    }

    var webAppURL: URL {
        Self.httpsURL(for: selectedDomain)
    }

    var uploadBaseURL: URL {
        Self.uploadBaseURL
    }

    var displayDomain: String {
        webAppURL.host() ?? webAppURL.absoluteString
    }

    var selectableDomains: [String] {
        Self.uniqueDomains([Self.productionDomain] + customDomains)
    }

    init(selectedDomain: String, customDomains: [String]) {
        let normalizedCustomDomains = Self.uniqueDomains(customDomains.map(Self.normalizedDomain))
        let normalizedSelected = Self.normalizedDomain(selectedDomain)
        let fallback = Self.defaultSelectedDomain
        self.customDomains = normalizedCustomDomains
        self.selectedDomain = ([Self.productionDomain] + normalizedCustomDomains).contains(normalizedSelected)
            ? normalizedSelected
            : fallback
    }

    static let productionDomain = "openmates.org"
    static let developmentDomain = "app.dev.openmates.org"
    static let uploadBaseURL = URL(string: "https://upload.openmates.org")!

    static var defaultSelectedDomain: String {
        #if DEBUG
        developmentDomain
        #else
        productionDomain
        #endif
    }

    static var defaultCustomDomains: [String] {
        #if DEBUG
        [developmentDomain]
        #else
        []
        #endif
    }

    static func normalizedDomain(_ domain: String) -> String {
        let withoutScheme = domain
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "https://", with: "")
            .replacingOccurrences(of: "http://", with: "")
        let host = withoutScheme.split(separator: "/").first.map(String.init) ?? ""
        return host.isEmpty ? productionDomain : host.lowercased()
    }

    static func httpsURL(for domain: String) -> URL {
        let normalized = normalizedDomain(domain)
        return URL(string: "https://\(normalized)") ?? URL(string: "https://openmates.org")!
    }

    private static func uniqueDomains(_ domains: [String]) -> [String] {
        var seen: Set<String> = []
        return domains.compactMap { domain in
            let normalized = normalizedDomain(domain)
            guard !seen.contains(normalized) else { return nil }
            seen.insert(normalized)
            return normalized
        }
    }

    static func apiURL(forWebDomain domain: String) -> URL {
        let host = httpsURL(for: domain).host() ?? domain
        let apiHost: String
        if host == "openmates.org" || host == "app.openmates.org" {
            apiHost = "api.openmates.org"
        } else if host == "app.dev.openmates.org" {
            apiHost = "api.dev.openmates.org"
        } else if host.hasPrefix("app.") {
            apiHost = "api." + host.dropFirst(4)
        } else {
            apiHost = host
        }
        return URL(string: "https://\(apiHost)") ?? URL(string: "https://api.openmates.org")!
    }
}

enum ServerConfiguration {
    static let didChangeNotification = Notification.Name("OpenMatesServerConfigurationDidChange")

    private static let selectedDomainKey = "openmates.server.selectedDomain"
    private static let customDomainsKey = "openmates.server.customDomains"
    private static let debugDefaultMigrationKey = "openmates.server.debugDefaultMigration.v1"

    static var current: ServerEndpointConfiguration {
        get {
            migrateDebugDefaultIfNeeded()
            let selectedDomain = defaults.string(forKey: selectedDomainKey)
                ?? ServerEndpointConfiguration.defaultSelectedDomain
            let customDomains = defaults.stringArray(forKey: customDomainsKey)
                ?? ServerEndpointConfiguration.defaultCustomDomains
            return ServerEndpointConfiguration(selectedDomain: selectedDomain, customDomains: customDomains)
        }
        set {
            defaults.set(newValue.selectedDomain, forKey: selectedDomainKey)
            defaults.set(newValue.customDomains, forKey: customDomainsKey)
            NotificationCenter.default.post(name: didChangeNotification, object: nil)
        }
    }

    private static var defaults: UserDefaults {
        OpenMatesSharedEnvironment.defaults
    }

    private static func migrateDebugDefaultIfNeeded() {
        #if DEBUG
        guard !defaults.bool(forKey: debugDefaultMigrationKey) else { return }
        let storedDomain = defaults.string(forKey: selectedDomainKey)
        let normalizedDomain = storedDomain.map(ServerEndpointConfiguration.normalizedDomain)
        if normalizedDomain == nil || normalizedDomain == ServerEndpointConfiguration.productionDomain {
            defaults.set(ServerEndpointConfiguration.developmentDomain, forKey: selectedDomainKey)
        }
        let customDomains = defaults.stringArray(forKey: customDomainsKey)
            ?? ServerEndpointConfiguration.defaultCustomDomains
        let migratedDomains = ServerEndpointConfiguration(
            selectedDomain: ServerEndpointConfiguration.developmentDomain,
            customDomains: customDomains + [ServerEndpointConfiguration.developmentDomain]
        ).customDomains
        defaults.set(migratedDomains, forKey: customDomainsKey)
        defaults.set(true, forKey: debugDefaultMigrationKey)
        #endif
    }
}
