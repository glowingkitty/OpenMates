// Focused unit coverage for native Incognito and Learning Mode settings.
// Exercises transient guest state, backend payload contracts, and lockout state
// without account credentials, persisted private data, or live network access.
// The production views are covered separately by SettingsModesParityUITests.
// All passcodes and identifiers below are synthetic test-only values.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class SettingsModesParityTests: XCTestCase {
    func testLearningModeClientUsesCanonicalBackendRoutes() {
        XCTAssertEqual(LearningModeAPIClient.statusPath, "/v1/learning-mode")
        XCTAssertEqual(LearningModeAPIClient.activationPath, "/v1/learning-mode/activate")
        XCTAssertEqual(LearningModeAPIClient.deactivationPath, "/v1/learning-mode/deactivate")
    }

    func testGuestLearningModeStateIsSessionLocal() {
        let firstSession = LearningModeGuestSession()
        firstSession.activate(ageGroup: .age13To15)

        XCTAssertTrue(firstSession.status.enabled)
        XCTAssertEqual(firstSession.status.ageGroup, .age13To15)
        XCTAssertEqual(firstSession.status.source, .guestSession)

        let nextSession = LearningModeGuestSession()
        XCTAssertFalse(nextSession.status.enabled)
        XCTAssertNil(nextSession.status.ageGroup)
    }

    func testLearningModePayloadsUseBackendSchema() throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase

        let activation = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: encoder.encode(LearningModeActivateRequest(passcode: "2468", ageGroup: .under10))
            ) as? [String: String]
        )
        XCTAssertEqual(activation, ["passcode": "2468", "age_group": "under_10"])

        let deactivation = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: encoder.encode(LearningModeDeactivateRequest(passcode: "2468"))
            ) as? [String: String]
        )
        XCTAssertEqual(deactivation, ["passcode": "2468"])

        let anonymous = try XCTUnwrap(
            try JSONSerialization.jsonObject(
                with: encoder.encode(
                    AnonymousChatRequest(
                        anonymousId: "anonymous-test",
                        clientChatId: "anonymous-chat",
                        clientMessageId: "assistant-message",
                        plaintextMessage: "Explain fractions",
                        messageHistory: [],
                        learningMode: AnonymousLearningModeContext(enabled: true, ageGroup: .age10To12)
                    )
                )
            ) as? [String: Any]
        )
        let learningMode = try XCTUnwrap(anonymous["learning_mode"] as? [String: Any])
        XCTAssertEqual(learningMode["enabled"] as? Bool, true)
        XCTAssertEqual(learningMode["age_group"] as? String, "10_12")
        XCTAssertEqual(learningMode["source"] as? String, "anonymous_session")
    }

    func testAccountControllerRefreshesAuthoritativeFailedAttemptsAfterDeactivationError() async {
        let client = LearningModeClientStub(
            statuses: [
                LearningModeStatus(enabled: true, ageGroup: .adult),
                LearningModeStatus(
                    enabled: true,
                    ageGroup: .adult,
                    failedAttempts: 5,
                    deactivationBlockedUntil: 2_000_000_000
                ),
            ],
            deactivateError: NSError(domain: "SettingsModesParityTests", code: 1)
        )
        let controller = LearningModeController(client: client)

        await controller.loadAccountStatus()
        await controller.deactivateAccount(passcode: "wrong")

        XCTAssertEqual(controller.status.failedAttempts, 5)
        XCTAssertEqual(controller.status.deactivationBlockedUntil, 2_000_000_000)
        XCTAssertNotNil(controller.error)
        XCTAssertEqual(client.loadCallCount, 2)
    }

    func testIncognitoExplainerSeenStatePersistsOnlyThroughInjectedDeviceStore() {
        let suiteName = "SettingsModesParityTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        let state = IncognitoExplainerSeenState(defaults: defaults)

        XCTAssertFalse(state.hasSeenExplainer)
        state.markSeen()
        XCTAssertTrue(IncognitoExplainerSeenState(defaults: defaults).hasSeenExplainer)
        defaults.removePersistentDomain(forName: suiteName)
    }
}

@MainActor
private final class LearningModeClientStub: LearningModeClientProtocol {
    private var statuses: [LearningModeStatus]
    private let deactivateError: Error?
    private(set) var loadCallCount = 0

    init(statuses: [LearningModeStatus], deactivateError: Error? = nil) {
        self.statuses = statuses
        self.deactivateError = deactivateError
    }

    func loadStatus() async throws -> LearningModeStatus {
        loadCallCount += 1
        return statuses.removeFirst()
    }

    func activate(passcode: String, ageGroup: LearningModeAgeGroup) async throws -> LearningModeStatus {
        LearningModeStatus(enabled: true, ageGroup: ageGroup)
    }

    func deactivate(passcode: String) async throws -> LearningModeStatus {
        if let deactivateError { throw deactivateError }
        return LearningModeStatus(enabled: false)
    }
}
