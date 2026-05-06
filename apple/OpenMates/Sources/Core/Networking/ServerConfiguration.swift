// Server endpoint configuration for the Apple app.
// Keeps the native API, web app origin, and passkey relying-party domain aligned.
// The selected web domain is persisted locally so testers can switch servers
// without rebuilding the app. Simulator/debug builds default to dev.
// Native passkeys still require the chosen web credential domain to be present
// in the app entitlement and in the domain's apple-app-site-association file.

import Foundation

struct ServerEndpointConfiguration: Equatable {
    let selectedDomain: String
    let customDomains: [String]

    var apiBaseURL: URL {
        Self.apiURL(forWebDomain: selectedDomain)
    }

    var webAppURL: URL {
        Self.httpsURL(for: selectedDomain)
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

    private static func apiURL(forWebDomain domain: String) -> URL {
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
            let selectedDomain = UserDefaults.standard.string(forKey: selectedDomainKey)
                ?? ServerEndpointConfiguration.defaultSelectedDomain
            let customDomains = UserDefaults.standard.stringArray(forKey: customDomainsKey)
                ?? ServerEndpointConfiguration.defaultCustomDomains
            return ServerEndpointConfiguration(selectedDomain: selectedDomain, customDomains: customDomains)
        }
        set {
            UserDefaults.standard.set(newValue.selectedDomain, forKey: selectedDomainKey)
            UserDefaults.standard.set(newValue.customDomains, forKey: customDomainsKey)
            NotificationCenter.default.post(name: didChangeNotification, object: nil)
        }
    }

    private static func migrateDebugDefaultIfNeeded() {
        #if DEBUG
        guard !UserDefaults.standard.bool(forKey: debugDefaultMigrationKey) else { return }
        let storedDomain = UserDefaults.standard.string(forKey: selectedDomainKey)
        let normalizedDomain = storedDomain.map(ServerEndpointConfiguration.normalizedDomain)
        if normalizedDomain == nil || normalizedDomain == ServerEndpointConfiguration.productionDomain {
            UserDefaults.standard.set(ServerEndpointConfiguration.developmentDomain, forKey: selectedDomainKey)
        }
        let customDomains = UserDefaults.standard.stringArray(forKey: customDomainsKey)
            ?? ServerEndpointConfiguration.defaultCustomDomains
        let migratedDomains = ServerEndpointConfiguration(
            selectedDomain: ServerEndpointConfiguration.developmentDomain,
            customDomains: customDomains + [ServerEndpointConfiguration.developmentDomain]
        ).customDomains
        UserDefaults.standard.set(migratedDomains, forKey: customDomainsKey)
        UserDefaults.standard.set(true, forKey: debugDefaultMigrationKey)
        #endif
    }
}
