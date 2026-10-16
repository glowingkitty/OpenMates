// Shared Apple extension environment for OpenMates.
// Keeps app-group identifiers, cookie storage, and shared defaults in one place
// so the main app, share extension, widgets, and background send paths agree.
// The standalone Watch keeps these preferences in its own app container;
// WatchConnectivity carries cross-device messages, not a shared defaults suite.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.private-session
// Secrets still live in the Keychain access group; App Group defaults are only
// for session IDs, cached user metadata, server selection, and lightweight state.

import Foundation
#if canImport(Darwin)
import Darwin
#endif

enum OpenMatesSharedEnvironment {
    static let appGroupIdentifier = "group.org.openmates.app.shared"
    static let sharedKeychainAccessGroup = "$(AppIdentifierPrefix)org.openmates.app"

    static var defaults: UserDefaults {
        #if os(watchOS)
        return preferences(standaloneWatch: true)
        #else
        return preferences(standaloneWatch: false)
        #endif
    }

    // Watch has no App Groups entitlement. Opening a suite can still return a
    // UserDefaults object whose synchronization fails on a signed device.
    static func preferences(standaloneWatch: Bool, standard: UserDefaults = .standard,
                            appGroup: () -> UserDefaults? = { UserDefaults(suiteName: appGroupIdentifier) }) -> UserDefaults {
        if standaloneWatch { return standard }
        return appGroup() ?? standard
    }

    static let cookieStorage: HTTPCookieStorage = {
        #if os(watchOS)
        return HTTPCookieStorage.shared
        #else
        // This API can return distinct wrapper instances for repeated calls.
        // Retain one process-wide object so login responses, WebSockets, and
        // cross-host upload request construction observe the same live jar.
        return HTTPCookieStorage.sharedCookieStorage(forGroupContainerIdentifier: appGroupIdentifier)
        #endif
    }()

    static func cookieHeader(for url: URL) -> String? {
        let cookieURL = httpCookieURL(for: url)
        let cookies = cookieStorage.cookies(for: cookieURL) ?? []
        guard !cookies.isEmpty else { return nil }
        return HTTPCookie.requestHeaderFields(with: cookies)["Cookie"]
    }

    private static func httpCookieURL(for url: URL) -> URL {
        guard url.scheme == "wss" || url.scheme == "ws",
              var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        components.scheme = url.scheme == "wss" ? "https" : "http"
        return components.url ?? url
    }
}

/// Coarse release identity only; no device identifiers or account material.
struct NativeClientIdentity: Equatable, Sendable {
    let appVersion: String
    let appBuild: String
    let deviceClass: String

    init(appVersion: String?, appBuild: String?, deviceClass: String) {
        func sanitized(_ value: String?, fallback: String) -> String {
            guard let value, !value.isEmpty, value.utf8.count <= 64,
                  value.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_").contains($0) }) else { return fallback }
            return value
        }
        self.appVersion = sanitized(appVersion, fallback: "1.0.0")
        self.appBuild = sanitized(appBuild, fallback: "unknown")
        self.deviceClass = ["iphone", "ipad", "mac", "watch"].contains(deviceClass) ? deviceClass : "unknown"
    }

    static var current: NativeClientIdentity {
        #if os(watchOS)
        let deviceClass = "watch"
        #elseif os(iOS)
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        var machine = [CChar](repeating: 0, count: max(1, size))
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        let model = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? String(cString: machine)
        let deviceClass = ProcessInfo.processInfo.isiOSAppOnMac ? "mac" :
            (model.hasPrefix("iPad") ? "ipad" : "iphone")
        #elseif os(macOS)
        let deviceClass = "mac"
        #else
        let deviceClass = "unknown"
        #endif
        return NativeClientIdentity(appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String,
            appBuild: Bundle.main.infoDictionary?["CFBundleVersion"] as? String, deviceClass: deviceClass)
    }

    func apply(to request: inout URLRequest) {
        headers.forEach { request.setValue($1, forHTTPHeaderField: $0) }
    }

    var diagnosticSummary: String { "app_version=\(appVersion) app_build=\(appBuild) device_class=\(deviceClass)" }
    var headers: [String: String] {
        ["X-OpenMates-App-Version": appVersion, "X-OpenMates-App-Build": appBuild,
         "X-OpenMates-Device-Class": deviceClass]
    }
}
