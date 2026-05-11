// Keychain wrapper for secure local storage of E2EE keys and auth tokens.
// OpenMates never stores or syncs encryption keys through Apple cloud services.
// All keys use kSecClassGenericPassword with the OpenMates service prefix.

import Foundation
import OSLog
import Security

enum KeychainHelper {
    private static let service = "org.openmates.app"
    private static let logger = Logger(subsystem: "org.openmates.app", category: "NativeKeychain")

    private static var configuredAccessGroup: String? {
        guard let rawValue = Bundle.main.object(forInfoDictionaryKey: "OpenMatesKeychainAccessGroup") as? String else {
            return nil
        }
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains("$(") else {
            return nil
        }
        return trimmed
    }

    private static var queryAccessGroup: String? {
        #if targetEnvironment(simulator)
        return nil
        #else
        return configuredAccessGroup
        #endif
    }

    static func save(key: String, data: Data) throws {
        logContext(operation: "save.begin", key: key, dataSize: data.count)

        let matchQuery = baseQuery(key: key)
        let update: [CFString: Any] = [
            kSecValueData: data,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]

        let updateStatus = SecItemUpdate(matchQuery as CFDictionary, update as CFDictionary)
        switch updateStatus {
        case errSecSuccess:
            logStatus(operation: "save.update", status: updateStatus, key: key, dataSize: data.count)
            return
        case errSecItemNotFound:
            break
        default:
            logStatus(operation: "save.update", status: updateStatus, key: key, dataSize: data.count)
            throw KeychainError.saveFailed(updateStatus)
        }

        var query = baseQuery(key: key)
        query[kSecValueData] = data
        query[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

        let status = SecItemAdd(query as CFDictionary, nil)
        logStatus(operation: "save.add", status: status, key: key, dataSize: data.count)
        guard status == errSecSuccess else {
            throw KeychainError.saveFailed(status)
        }
    }

    static func load(key: String) throws -> Data? {
        logContext(operation: "load.begin", key: key, dataSize: nil)

        var query = baseQuery(key: key)
        query[kSecReturnData] = kCFBooleanTrue!
        query[kSecMatchLimit] = kSecMatchLimitOne

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        switch status {
        case errSecSuccess:
            let data = result as? Data
            logStatus(operation: "load.match", status: status, key: key, dataSize: data?.count)
            return data
        case errSecItemNotFound:
            logStatus(operation: "load.match", status: status, key: key, dataSize: nil)
            return nil
        default:
            logStatus(operation: "load.match", status: status, key: key, dataSize: nil)
            throw KeychainError.loadFailed(status)
        }
    }

    static func delete(key: String) throws {
        logContext(operation: "delete.begin", key: key, dataSize: nil)

        let query = baseQuery(key: key)
        let status = SecItemDelete(query as CFDictionary)
        logStatus(operation: "delete.item", status: status, key: key, dataSize: nil)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.deleteFailed(status)
        }
    }

    static func deleteAll() throws {
        logContext(operation: "deleteAll.begin", key: "*", dataSize: nil)

        var query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrSynchronizable: kSecAttrSynchronizableAny,
        ]
        if let queryAccessGroup {
            query[kSecAttrAccessGroup] = queryAccessGroup
        }

        let status = SecItemDelete(query as CFDictionary)
        logStatus(operation: "deleteAll.service", status: status, key: "*", dataSize: nil)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.deleteFailed(status)
        }
    }

    #if DEBUG
    static func debugSelfTest() {
        let key = "openmates.masterKey.debugSelfTest"
        let payload = Data([0x4f, 0x4d, 0x01, 0x02])
        do {
            try save(key: key, data: payload)
            let loaded = try load(key: key)
            guard loaded == payload else {
                logger.error("debugSelfTest.roundTripMismatch expectedBytes=\(payload.count, privacy: .public) loadedBytes=\(loaded?.count ?? -1, privacy: .public)")
                return
            }
            try delete(key: key)
            logger.info("debugSelfTest.success")
        } catch {
            logger.error("debugSelfTest.failed error=\(error.localizedDescription, privacy: .public)")
        }
    }
    #endif

    private static func baseQuery(key: String) -> [CFString: Any] {
        var query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: key,
            kSecAttrSynchronizable: kCFBooleanFalse!,
        ]
        if let queryAccessGroup {
            query[kSecAttrAccessGroup] = queryAccessGroup
        }
        return query
    }

    private static func logContext(operation: String, key: String, dataSize: Int?) {
        logger.info(
            """
            \(operation, privacy: .public) account=\(redactedAccount(key), privacy: .public) \
            service=\(service, privacy: .public) bundle=\(bundleIdentifier, privacy: .public) \
            configuredAccessGroup=\(configuredAccessGroup ?? "<none>", privacy: .public) \
            queryAccessGroup=\(queryAccessGroup ?? "<default>", privacy: .public) \
            accessible=AfterFirstUnlockThisDeviceOnly synchronizable=false \
            bytes=\(dataSize.map(String.init) ?? "<none>", privacy: .public)
            """
        )
    }

    private static func logStatus(operation: String, status: OSStatus, key: String, dataSize: Int?) {
        let message = SecCopyErrorMessageString(status, nil) as String? ?? "No Security.framework message"
        let level: OSLogType = status == errSecSuccess || status == errSecItemNotFound ? .info : .error
        logger.log(
            level: level,
            """
            \(operation, privacy: .public) status=\(status, privacy: .public) \
            message=\(message, privacy: .public) account=\(redactedAccount(key), privacy: .public) \
            service=\(service, privacy: .public) bundle=\(bundleIdentifier, privacy: .public) \
            configuredAccessGroup=\(configuredAccessGroup ?? "<none>", privacy: .public) \
            queryAccessGroup=\(queryAccessGroup ?? "<default>", privacy: .public) \
            bytes=\(dataSize.map(String.init) ?? "<none>", privacy: .public)
            """
        )
    }

    private static var bundleIdentifier: String {
        Bundle.main.bundleIdentifier ?? "<unknown>"
    }

    private static func redactedAccount(_ key: String) -> String {
        if key == "*" {
            return "*"
        }
        if key.hasPrefix("openmates.masterKey.") {
            return "openmates.masterKey.<user>"
        }
        return "<redacted>"
    }
}

enum KeychainError: LocalizedError {
    case saveFailed(OSStatus)
    case loadFailed(OSStatus)
    case deleteFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .saveFailed(let s): return "Keychain save failed (status \(s))"
        case .loadFailed(let s): return "Keychain load failed (status \(s))"
        case .deleteFailed(let s): return "Keychain delete failed (status \(s))"
        }
    }
}
