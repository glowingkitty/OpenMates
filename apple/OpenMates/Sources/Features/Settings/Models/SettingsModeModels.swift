// State and API contracts for native Settings Incognito and Learning Mode.
// Account Learning Mode uses the canonical backend policy endpoints.
// Guest Learning Mode and active Incognito state are process-session only.
// Only the Incognito explainer acknowledgement persists on this device.
// Views consume these types without owning persistence or chat encryption.

import Combine
import Foundation

enum LearningModeAgeGroup: String, CaseIterable, Codable, Identifiable, Sendable {
    case under10 = "under_10"
    case age10To12 = "10_12"
    case age13To15 = "13_15"
    case age16To18 = "16_18"
    case adult

    var id: String { rawValue }
}

enum LearningModeSource: Equatable, Sendable {
    case account
    case guestSession
}

struct LearningModeStatus: Decodable, Equatable, Sendable {
    static let maximumDeactivationAttempts = 5

    var enabled: Bool
    var ageGroup: LearningModeAgeGroup?
    var failedAttempts: Int
    var deactivationBlockedUntil: Int?
    var source: LearningModeSource
    /// Web `learning_mode.collaborative_build`: the AI may build things together with the learner.
    var collaborativeBuild: Bool

    init(
        enabled: Bool,
        ageGroup: LearningModeAgeGroup? = nil,
        failedAttempts: Int = 0,
        deactivationBlockedUntil: Int? = nil,
        source: LearningModeSource = .account,
        collaborativeBuild: Bool = false
    ) {
        self.enabled = enabled
        self.ageGroup = ageGroup
        self.failedAttempts = failedAttempts
        self.deactivationBlockedUntil = deactivationBlockedUntil
        self.source = source
        self.collaborativeBuild = collaborativeBuild
    }

    var isLocked: Bool {
        guard let deactivationBlockedUntil else { return false }
        return deactivationBlockedUntil > Int(Date().timeIntervalSince1970)
    }

    private enum CodingKeys: String, CodingKey {
        case enabled
        case ageGroup
        case failedAttempts
        case deactivationBlockedUntil
        case collaborativeBuild
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try container.decode(Bool.self, forKey: .enabled)
        ageGroup = try container.decodeIfPresent(LearningModeAgeGroup.self, forKey: .ageGroup)
        failedAttempts = try container.decodeIfPresent(Int.self, forKey: .failedAttempts) ?? 0
        deactivationBlockedUntil = try container.decodeIfPresent(Int.self, forKey: .deactivationBlockedUntil)
        collaborativeBuild = try container.decodeIfPresent(Bool.self, forKey: .collaborativeBuild) ?? false
        source = .account
    }
}

struct LearningModeActivateRequest: Encodable, Sendable {
    let passcode: String
    let ageGroup: LearningModeAgeGroup
    /// Omitted when nil so the server applies its default (on, except under 10).
    var collaborativeBuild: Bool?
}

struct LearningModeCollaborativeRequest: Encodable, Sendable {
    let enabled: Bool
    /// Required by the server only when turning collaborative building on.
    var passcode: String?
}

struct LearningModeDeactivateRequest: Encodable, Sendable {
    let passcode: String
}

@MainActor
protocol LearningModeClientProtocol: AnyObject {
    func loadStatus() async throws -> LearningModeStatus
    func activate(passcode: String, ageGroup: LearningModeAgeGroup) async throws -> LearningModeStatus
    func deactivate(passcode: String) async throws -> LearningModeStatus
    func activate(passcode: String, ageGroup: LearningModeAgeGroup, collaborativeBuild: Bool) async throws -> LearningModeStatus
    func setCollaborativeBuild(enabled: Bool, passcode: String?) async throws -> LearningModeStatus
}

extension LearningModeClientProtocol {
    func activate(passcode: String, ageGroup: LearningModeAgeGroup, collaborativeBuild: Bool) async throws -> LearningModeStatus {
        try await activate(passcode: passcode, ageGroup: ageGroup)
    }

    func setCollaborativeBuild(enabled: Bool, passcode: String?) async throws -> LearningModeStatus {
        try await loadStatus()
    }
}

@MainActor
final class LearningModeAPIClient: LearningModeClientProtocol {
    static let statusPath = "/v1/learning-mode"
    static let activationPath = "/v1/learning-mode/activate"
    static let deactivationPath = "/v1/learning-mode/deactivate"
    static let collaborativePath = "/v1/learning-mode/collaborative"

    func activate(passcode: String, ageGroup: LearningModeAgeGroup, collaborativeBuild: Bool) async throws -> LearningModeStatus {
        try await APIClient.shared.request(
            .post,
            path: Self.activationPath,
            body: LearningModeActivateRequest(passcode: passcode, ageGroup: ageGroup, collaborativeBuild: collaborativeBuild)
        )
    }

    func setCollaborativeBuild(enabled: Bool, passcode: String?) async throws -> LearningModeStatus {
        try await APIClient.shared.request(
            .post,
            path: Self.collaborativePath,
            body: LearningModeCollaborativeRequest(enabled: enabled, passcode: enabled ? passcode : nil)
        )
    }

    func loadStatus() async throws -> LearningModeStatus {
        try await APIClient.shared.request(.get, path: Self.statusPath)
    }

    func activate(passcode: String, ageGroup: LearningModeAgeGroup) async throws -> LearningModeStatus {
        try await APIClient.shared.request(
            .post,
            path: Self.activationPath,
            body: LearningModeActivateRequest(passcode: passcode, ageGroup: ageGroup)
        )
    }

    func deactivate(passcode: String) async throws -> LearningModeStatus {
        try await APIClient.shared.request(
            .post,
            path: Self.deactivationPath,
            body: LearningModeDeactivateRequest(passcode: passcode)
        )
    }
}

@MainActor
final class LearningModeGuestSession: ObservableObject {
    static let shared = LearningModeGuestSession()
    @Published private(set) var status = LearningModeStatus(enabled: false, source: .guestSession)

    func activate(ageGroup: LearningModeAgeGroup, collaborativeBuild: Bool = true) {
        status = LearningModeStatus(
            enabled: true, ageGroup: ageGroup, source: .guestSession,
            collaborativeBuild: ageGroup != .under10 && collaborativeBuild
        )
    }

    /// Guest Learning Mode has no passcode on Apple, so both directions are free here.
    func setCollaborativeBuild(_ enabled: Bool) {
        guard status.enabled, status.ageGroup != .under10 else { return }
        status.collaborativeBuild = enabled
    }

    func deactivate() {
        status = LearningModeStatus(enabled: false, source: .guestSession)
    }
}

@MainActor
final class LearningModeController: ObservableObject {
    enum Failure: Equatable {
        case load
        case save
        case deactivationRejected
    }

    @Published private(set) var status = LearningModeStatus(enabled: false)
    @Published private(set) var isLoading = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var error: Failure?

    private let client: LearningModeClientProtocol

    init(client: LearningModeClientProtocol = LearningModeAPIClient()) {
        self.client = client
    }

    func loadAccountStatus() async {
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.loadStatus()
            hasLoaded = true
            error = nil
        } catch {
            hasLoaded = true
            self.error = .load
            NativeDiagnostics.error("Learning Mode status load failed: \(type(of: error))", category: "learning_mode")
        }
    }

    func activateAccount(passcode: String, ageGroup: LearningModeAgeGroup, collaborativeBuild: Bool = true) async {
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.activate(
                passcode: passcode, ageGroup: ageGroup,
                collaborativeBuild: ageGroup != .under10 && collaborativeBuild
            )
            hasLoaded = true
            error = nil
        } catch {
            self.error = .save
            NativeDiagnostics.error("Learning Mode activation failed: \(type(of: error))", category: "learning_mode")
        }
    }

    func setAccountCollaborativeBuild(_ enabled: Bool, passcode: String?) async {
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.setCollaborativeBuild(enabled: enabled, passcode: passcode)
            error = nil
        } catch {
            self.error = .save
            NativeDiagnostics.error("Learning Mode collaborative update failed: \(type(of: error))", category: "learning_mode")
        }
    }

    func deactivateAccount(passcode: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            status = try await client.deactivate(passcode: passcode)
            hasLoaded = true
            error = nil
        } catch {
            self.error = .deactivationRejected
            NativeDiagnostics.warning("Learning Mode deactivation rejected", category: "learning_mode")
            do {
                status = try await client.loadStatus()
                hasLoaded = true
            } catch {
                NativeDiagnostics.error("Learning Mode status refresh failed: \(type(of: error))", category: "learning_mode")
            }
        }
    }
}

struct AnonymousLearningModeContext: Encodable, Equatable, Sendable {
    let enabled: Bool
    let ageGroup: LearningModeAgeGroup
    let source = "anonymous_session"
}

struct IncognitoExplainerSeenState {
    private static let key = "openmates.apple.incognito_explainer_seen"
    @MainActor private static var didResetForUITesting = false
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var hasSeenExplainer: Bool {
        defaults.bool(forKey: Self.key)
    }

    func markSeen() {
        defaults.set(true, forKey: Self.key)
    }

    @MainActor
    func resetForUITestingOnce() {
        guard !Self.didResetForUITesting else { return }
        Self.didResetForUITesting = true
        defaults.removeObject(forKey: Self.key)
    }
}

enum SettingsIncognitoAction: Sendable {
    case activate
    case deactivate
}

@MainActor
final class IncognitoSettingsSession: ObservableObject {
    static let shared = IncognitoSettingsSession()
    @Published var isEnabled = false

    static func isolated() -> IncognitoSettingsSession { IncognitoSettingsSession() }
    private init() {}
}
