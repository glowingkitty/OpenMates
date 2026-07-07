// Shared Apple extension environment for OpenMates.
// Keeps app-group identifiers, cookie storage, and shared defaults in one place
// so the main app, share extension, widgets, and background send paths agree.
// Secrets still live in the Keychain access group; App Group defaults are only
// for session IDs, cached user metadata, server selection, and lightweight state.

import Foundation

enum OpenMatesSharedEnvironment {
    static let appGroupIdentifier = "group.org.openmates.app.shared"
    static let sharedKeychainAccessGroup = "$(AppIdentifierPrefix)org.openmates.app"

    static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroupIdentifier) ?? .standard
    }

    static var cookieStorage: HTTPCookieStorage {
        #if os(watchOS)
        HTTPCookieStorage.shared
        #else
        HTTPCookieStorage.sharedCookieStorage(forGroupContainerIdentifier: appGroupIdentifier)
        #endif
    }

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
