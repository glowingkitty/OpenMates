// Shared Apple extension environment for OpenMates.
// Keeps app-group identifiers, cookie storage, and shared defaults in one place
// so the main app, share extension, widgets, and background send paths agree.
// Secrets still live in the Keychain access group; App Group defaults are only
// for session IDs, cached user metadata, server selection, and lightweight state.

import Foundation

enum OpenMatesSharedEnvironment {
    static let appGroupIdentifier = "group.org.openmates.app"
    static let sharedKeychainAccessGroup = "$(AppIdentifierPrefix)org.openmates.app"

    static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroupIdentifier) ?? .standard
    }

    static var cookieStorage: HTTPCookieStorage {
        HTTPCookieStorage.sharedCookieStorage(forGroupContainerIdentifier: appGroupIdentifier)
    }
}
