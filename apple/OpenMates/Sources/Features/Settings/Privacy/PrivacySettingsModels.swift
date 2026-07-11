// Privacy settings contracts and state shared by the native Apple privacy views.
// Uses the same authenticated REST, encrypted memory, retention, and diagnostics
// contracts as the web settings surface without browser or visual-only fallbacks.
// Published summaries exclude connected-account token envelopes and private fields.
// All request failures remain visible through typed state and NativeDiagnostics.

import CryptoKit
import Combine
import Foundation

enum PrivacyAPIContract {
    static let autoDeleteChatsPath = "/v1/settings/auto-delete-chats"
    static let connectedAccountsPath = "/v1/connected-accounts"
    static let debugSessionPath = "/v1/settings/debug-session"
    static let debugLogsPath = "/v1/settings/debug-logs"
    static let memoriesPath = "/v1/sdk/memories?app_id=privacy"
    static let memoriesStorePath = "/v1/sdk/memories"
    static let autoDeleteFilesPath: String? = nil
}

enum PrivacyRetentionPolicy {
    static let filesDays = 90
    static let usageDataRetentionYears = 3
    static let complianceLogRetentionYears = 1
    static let invoiceRetentionYears = 10
}

enum AutoDeletionPeriod: String, CaseIterable, Codable, Identifiable, Sendable {
    case thirtyDays = "30d"
    case sixtyDays = "60d"
    case ninetyDays = "90d"
    case sixMonths = "6m"
    case oneYear = "1y"
    case twoYears = "2y"
    case fiveYears = "5y"
    case never

    var id: String { rawValue }

    static func from(days: Int?) -> AutoDeletionPeriod {
        switch days {
        case nil: return .never
        case 30: return .thirtyDays
        case 60: return .sixtyDays
        case 90: return .ninetyDays
        case 180: return .sixMonths
        case 365: return .oneYear
        case 730: return .twoYears
        case 1_825: return .fiveYears
        default: return .ninetyDays
        }
    }
}

struct AutoDeleteChatsRequest: Encodable, Sendable {
    let period: AutoDeletionPeriod
}

struct PrivacyDiagnosticsPreferences {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var stabilityLogsEnabled: Bool {
        !NativeDiagnosticsPreferences.defaultTelemetryOptedOut(defaults: defaults)
    }

    var detailedDebugLoggingEnabled: Bool {
        NativeDiagnosticsPreferences.detailedDebugLoggingEnabled(defaults: defaults)
    }

    func setStabilityLogsEnabled(_ enabled: Bool) {
        NativeDiagnosticsPreferences.setDefaultTelemetryOptedOut(!enabled, defaults: defaults)
        if enabled {
            NativeLogForwarder.shared.startDefaultTelemetry()
        } else {
            NativeLogForwarder.shared.stopDefaultTelemetry()
        }
    }

    func setDetailedDebugLoggingEnabled(_ enabled: Bool) {
        NativeDiagnosticsPreferences.setDetailedDebugLoggingEnabled(enabled, defaults: defaults)
    }
}

enum PrivacyDebugDuration: String, CaseIterable, Codable, Identifiable, Sendable {
    case fiveMinutes = "5m"
    case oneHour = "1h"
    case threeDays = "3d"
    case sevenDays = "7d"
    case noLimit = "none"

    var id: String { rawValue }
}

struct PrivacyDebugSession: Decodable, Equatable, Sendable {
    let active: Bool
    let debuggingId: String?
    let expiresAt: String?
    let duration: PrivacyDebugDuration?

    enum CodingKeys: String, CodingKey {
        case active
        case debuggingId = "debugging_id"
        case expiresAt = "expires_at"
        case duration
    }
}

struct PrivacyDebugSessionCreateRequest: Encodable, Sendable {
    let duration: PrivacyDebugDuration
}

@MainActor
final class PrivacyDebugSessionController: ObservableObject {
    @Published private(set) var session = PrivacyDebugSession(active: false, debuggingId: nil, expiresAt: nil, duration: nil)
    @Published private(set) var isLoading = false
    @Published var selectedDuration: PrivacyDebugDuration = .fiveMinutes
    @Published var errorMessage: String?

    private let api = APIClient.shared

    func load() async {
        guard !isLoading else { return }
        await perform("load") {
            let response: PrivacyDebugSession = try await api.request(.get, path: PrivacyAPIContract.debugSessionPath)
            session = response
            if let duration = response.duration { selectedDuration = duration }
            syncForwarder(response)
        }
    }

    func activate() async {
        await perform("activate") {
            let response: PrivacyDebugSession = try await api.request(
                .post,
                path: PrivacyAPIContract.debugSessionPath,
                body: PrivacyDebugSessionCreateRequest(duration: selectedDuration)
            )
            session = response
            syncForwarder(response)
        }
    }

    func deactivate() async {
        await perform("deactivate") {
            let response: PrivacyDebugSession = try await api.request(.delete, path: PrivacyAPIContract.debugSessionPath)
            session = response
            NativeLogForwarder.shared.stopDebugSession()
        }
    }

    private func perform(_ operation: String, action: () async throws -> Void) async {
        guard !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await action()
        } catch {
            NativeDiagnostics.error("Privacy debug session \(operation) failed: \(type(of: error))", category: "privacy")
            errorMessage = AppStrings.privacyDebugSessionError
        }
    }

    private func syncForwarder(_ response: PrivacyDebugSession) {
        if response.active, let debuggingId = response.debuggingId, !debuggingId.isEmpty {
            NativeLogForwarder.shared.startDebugSession(debuggingID: debuggingId)
        } else {
            NativeLogForwarder.shared.stopDebugSession()
        }
    }
}

struct ConnectedAccountEncryptedRow: Decodable, Sendable {
    let id: String
    let encryptedProviderType: String
    let encryptedAccountLabel: String
    let encryptedRefreshTokenBundle: String
    let encryptedCapabilities: String
    let encryptedAppPermissions: String
    let encryptedAccountDirectoryHint: String?
    let updatedAt: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case encryptedProviderType = "encrypted_provider_type"
        case encryptedAccountLabel = "encrypted_account_label"
        case encryptedRefreshTokenBundle = "encrypted_refresh_token_bundle"
        case encryptedCapabilities = "encrypted_capabilities"
        case encryptedAppPermissions = "encrypted_app_permissions"
        case encryptedAccountDirectoryHint = "encrypted_account_directory_hint"
        case updatedAt = "updated_at"
    }

}

struct ConnectedAccountSummary: Identifiable, Equatable, Sendable {
    let id: String
    let providerId: String
    let appId: String
    let label: String
    let capabilities: [String]
    let runtimeModes: [String: String]

}

private struct ConnectedAccountListResponse: Decodable {
    let rows: [ConnectedAccountEncryptedRow]
}

private struct ConnectedAccountPermissions: Decodable {
    let appId: String?
    let allowedActions: [String]?

    enum CodingKeys: String, CodingKey {
        case appId = "app_id"
        case allowedActions = "allowed_actions"
    }
}

private struct ConnectedAccountDirectoryHint: Decodable {
    let label: String?
    let capabilities: [String]?
    let runtimeModes: [String: String]?

    enum CodingKeys: String, CodingKey {
        case label, capabilities
        case runtimeModes = "runtime_modes"
    }
}

@MainActor
final class PrivacyConnectedAccountsController: ObservableObject {
    @Published private(set) var summaries: [ConnectedAccountSummary] = []
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    func load() async {
        guard !isLoading else { return }
        if PrivacySettingsUITestFixture.enabled {
            summaries = [ConnectedAccountSummary(
                id: "fixture-account",
                providerId: "google_calendar",
                appId: "calendar",
                label: AppStrings.privacyProviderGoogleCalendar,
                capabilities: ["read"],
                runtimeModes: ["search": "automatic"]
            )]
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            guard let userId = await AuthManager.currentUserId(),
                  let masterKey = try await CryptoManager.shared.loadMasterKey(for: userId) else {
                throw PrivacySettingsError.masterKeyUnavailable
            }
            let response: ConnectedAccountListResponse = try await APIClient.shared.request(
                .get,
                path: PrivacyAPIContract.connectedAccountsPath
            )
            summaries = try await response.rows.asyncMap { try await Self.summarize($0, masterKey: masterKey) }
        } catch {
            NativeDiagnostics.error("Connected accounts load failed: \(type(of: error))", category: "privacy")
            errorMessage = AppStrings.privacyConnectedAccountsLoadError
        }
    }

    private static func summarize(_ row: ConnectedAccountEncryptedRow, masterKey: SymmetricKey) async throws -> ConnectedAccountSummary {
        async let provider: String = decrypt(row.encryptedProviderType, masterKey: masterKey)
        async let label: String = decrypt(row.encryptedAccountLabel, masterKey: masterKey)
        async let capabilities: [String] = decryptCapabilities(row.encryptedCapabilities, masterKey: masterKey)
        async let permissions: ConnectedAccountPermissions = decrypt(row.encryptedAppPermissions, masterKey: masterKey)
        let hint: ConnectedAccountDirectoryHint? = if let encryptedHint = row.encryptedAccountDirectoryHint {
            try await decrypt(encryptedHint, masterKey: masterKey)
        } else {
            nil
        }
        let resolvedProvider = try await provider
        let resolvedLabel = try await label
        let resolvedPermissions = try await permissions
        let resolvedCapabilities = try await capabilities
        return ConnectedAccountSummary(
            id: row.id,
            providerId: resolvedProvider,
            appId: resolvedPermissions.appId ?? (resolvedProvider == "google_calendar" ? "calendar" : resolvedProvider),
            label: hint?.label ?? resolvedLabel,
            capabilities: hint?.capabilities ?? (resolvedCapabilities.isEmpty ? capabilitiesForActions(resolvedPermissions.allowedActions ?? []) : resolvedCapabilities),
            runtimeModes: hint?.runtimeModes ?? [:]
        )
    }

    private static func decrypt<T: Decodable>(_ value: String, masterKey: SymmetricKey) async throws -> T {
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: value, key: masterKey)
        return try JSONDecoder().decode(T.self, from: Data(plaintext.utf8))
    }

    private static func decryptCapabilities(_ value: String, masterKey: SymmetricKey) async throws -> [String] {
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: value, key: masterKey)
        let data = Data(plaintext.utf8)
        let object = try JSONSerialization.jsonObject(with: data)
        if let values = object as? [String] { return values }
        if let dictionary = object as? [String: Any], let values = dictionary["capabilities"] as? [String] {
            return values
        }
        throw DecodingError.typeMismatch(
            [String].self,
            DecodingError.Context(codingPath: [], debugDescription: "Connected account capabilities have an invalid shape")
        )
    }

    private static func capabilitiesForActions(_ actions: [String]) -> [String] {
        var values: [String] = []
        if actions.contains(where: { $0.contains("read") || $0.contains("search") || $0.contains("list") }) { values.append("read") }
        if actions.contains(where: { $0.contains("create") || $0.contains("update") || $0.contains("write") }) { values.append("write") }
        if actions.contains(where: { $0.contains("delete") }) { values.append("delete") }
        return values
    }

}

enum PrivacySettingsError: Error {
    case masterKeyUnavailable
}

enum PrivacySettingsUITestFixture {
    static var enabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-privacy-settings-fixture")
    }
}

private extension Array {
    func asyncMap<T>(_ transform: (Element) async throws -> T) async rethrows -> [T] {
        var values: [T] = []
        values.reserveCapacity(count)
        for element in self { values.append(try await transform(element)) }
        return values
    }
}
