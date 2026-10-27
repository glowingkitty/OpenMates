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
    private var avatarPNG: Data {
        Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMwTjvzHwAEmgJlc/kGHwAAAABJRU5ErkJggg==")!
    }

    private func avatarRequest(owner: String = "synthetic-owner", profile: ServerProfile = .development,
                               url: String? = nil, scope: UUID = UUID()) -> SettingsProfileImageRequest? {
        let authority = AuthSessionRecoveryContext(accountID: owner, profile: profile,
            sessionID: "synthetic-session", generation: UUID())
        return SettingsProfileImageRequest(ownerID: owner, rawURL: url, authority: authority, scope: scope)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testSettingsBannerUsesWindowBreakpointRatherThanPanelWidth() {
        XCTAssertEqual(SettingsMainBannerLayout.expandedHeight(viewportWidth: 390), 190)
        XCTAssertEqual(SettingsMainBannerLayout.expandedHeight(viewportWidth: 730), 190)
        XCTAssertEqual(SettingsMainBannerLayout.expandedHeight(viewportWidth: 731), 240)
        XCTAssertEqual(SettingsMainBannerLayout.expandedHeight(viewportWidth: 1440), 240)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,settings-ui.parity.web-apple-shell
    func testProfileAvatarMissingURLAndAbsoluteFirstPartyProxyUseAuthenticatedTransport() throws {
        let fallback = try XCTUnwrap(avatarRequest())
        XCTAssertEqual(fallback.source, .authenticated("/v1/users/synthetic-owner/profile-image"))
        let absolute = ServerProfile.development.apiBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let request = try XCTUnwrap(avatarRequest(url: absolute + "/v1/users/synthetic-owner/profile-image"))
        XCTAssertEqual(request.source, fallback.source)
        XCTAssertNil(avatarRequest(url: "https://other.example/v1/users/synthetic-owner/profile-image"))
        XCTAssertNil(avatarRequest(url: "/v1/users/other-owner/profile-image"))
        XCTAssertNil(avatarRequest(url: "file:///private/avatar.png"))
        XCTAssertNil(avatarRequest(url: "data:image/png;base64,AA=="))
        let legacy = URL(string: "https://public.example/avatar.jpg")!
        XCTAssertEqual(avatarRequest(url: legacy.absoluteString)?.source, .legacy(legacy))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,settings-ui.parity.web-apple-shell
    func testProfileAvatarRetriesFailureRejectsInvalidBytesAndPublishesRealRaster() async throws {
        let request = try XCTUnwrap(avatarRequest())
        let loader = SettingsProfileImageLoader()
        await loader.load(request, isCurrent: { true }, fetch: { _ in throw APIError.invalidResponse })
        XCTAssertNil(loader.data)
        await loader.load(request, isCurrent: { true }, fetch: { _ in Data("<html>not an image</html>".utf8) })
        XCTAssertNil(loader.data)
        let png = avatarPNG
        await loader.load(request, isCurrent: { true }, fetch: { _ in png })
        XCTAssertEqual(loader.data, png)
        XCTAssertEqual(loader.loadedRequest, request)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testProfileAvatarScopeMatchesAccountServerNativeSessionAndAuthorityGeneration() throws {
        let request = try XCTUnwrap(avatarRequest())
        let authority = request.authority
        XCTAssertTrue(request.matches(authority: authority, scope: request.scope))
        XCTAssertFalse(request.matches(authority: nil, scope: request.scope))
        XCTAssertFalse(request.matches(authority: authority, scope: UUID()))
        for changed in [
            AuthSessionRecoveryContext(accountID: "another-owner", profile: authority.profile,
                sessionID: authority.sessionID, generation: authority.generation),
            AuthSessionRecoveryContext(accountID: authority.accountID, profile: .production,
                sessionID: authority.sessionID, generation: authority.generation),
            AuthSessionRecoveryContext(accountID: authority.accountID, profile: authority.profile,
                sessionID: "another-session", generation: authority.generation),
            AuthSessionRecoveryContext(accountID: authority.accountID, profile: authority.profile,
                sessionID: authority.sessionID, generation: UUID()),
        ] {
            XCTAssertFalse(request.matches(authority: changed, scope: request.scope))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testProfileAvatarDiscardsLateCompletionAfterItsScopeChanges() async throws {
        let request = try XCTUnwrap(avatarRequest())
        let loader = SettingsProfileImageLoader()
        var currentScope = request.scope
        let png = avatarPNG
        await loader.load(request, isCurrent: {
            request.matches(authority: request.authority, scope: currentScope)
        }, fetch: { _ in
            currentScope = UUID()
            return png
        })
        XCTAssertNil(loader.data)
        XCTAssertNil(loader.loadedRequest)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testProfileAvatarNewRequestClearsPreviousAccountImageAndHasDistinctScopeIdentity() async throws {
        let first = try XCTUnwrap(avatarRequest())
        let second = try XCTUnwrap(avatarRequest(owner: "synthetic-second"))
        let loader = SettingsProfileImageLoader()
        let png = avatarPNG
        await loader.load(first, isCurrent: { true }, fetch: { _ in png })
        XCTAssertEqual(loader.data, png)
        await loader.load(second, isCurrent: { true }, fetch: { _ in
            XCTAssertNil(loader.data)
            XCTAssertNil(loader.loadedRequest)
            throw APIError.invalidResponse
        })
        XCTAssertNil(loader.data)
        XCTAssertNotEqual(first, second)
        let rescope = SettingsProfileImageRequest(ownerID: first.ownerID, rawURL: nil,
            authority: first.authority, scope: UUID())
        XCTAssertNotEqual(first, rescope)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell,settings-ui.composition.canonical-and-accessible
    func testTeamMenuFitsRowsAndOnlyScrollsAtViewportCap() {
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 0, expanded: false, viewportHeight: 900), 55)
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 1, expanded: false, viewportHeight: 900), 106)
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 2, expanded: false, viewportHeight: 900), 157)
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 8, expanded: false, viewportHeight: 900), 361)
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 8, expanded: true, viewportHeight: 900), 480)
        XCTAssertEqual(SettingsTeamMenuBounds.height(teamCount: 8, expanded: true, viewportHeight: 320), 304)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testTeamChoiceWhilePersonalOnlyRemembersItAndSurvivesToggleOff() {
        var selection = SettingsTeamQuickSelection()
        let teams = ["one", "two"]
        XCTAssertNil(selection.selectedID(activeID: nil, readableIDs: []))
        XCTAssertEqual(selection.selectedID(activeID: nil, readableIDs: ["one"]), "one")
        XCTAssertEqual(selection.selectedID(activeID: nil, readableIDs: teams), "one")
        XCTAssertFalse(selection.choose("two", activeID: nil), "Choosing while off cannot activate a team")
        XCTAssertEqual(selection.selectedID(activeID: nil, readableIDs: teams), "two")
        selection.remember("two") // Turn on, then return to Personal.
        selection.remember(nil)
        XCTAssertEqual(selection.selectedID(activeID: nil, readableIDs: teams), "two")
        XCTAssertTrue(selection.choose("one", activeID: "two"))
        XCTAssertFalse(selection.choose("one", activeID: "one"))
        selection.reconcile(readableIDs: ["two"])
        XCTAssertEqual(selection.selectedID(activeID: nil, readableIDs: ["two"]), "two")
        selection = SettingsTeamQuickSelection() // Account change drops the choice.
        XCTAssertNil(selection.preferredID)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
    func testTeamContextMenuBoundsReserveViewportMargin() {
        XCTAssertEqual(SettingsTeamMenuBounds.maximumHeight(viewportHeight: 900), 480)
        XCTAssertEqual(SettingsTeamMenuBounds.maximumHeight(viewportHeight: 320), 304)
        XCTAssertEqual(SettingsTeamMenuBounds.maximumHeight(viewportHeight: 68), 52)
        XCTAssertEqual(SettingsTeamMenuBounds.maximumHeight(viewportHeight: 40), 24)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testTeamMenuFollowsTriggerClampsRightAndFlipsAbove() {
        let below = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 200, y: 100, width: 48, height: 41),
            canvas: CGSize(width: 400, height: 720), contentHeight: 157)
        XCTAssertEqual(below, CGRect(x: 200, y: 147, width: 185, height: 157))
        let clamped = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 270, y: 100, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 720), contentHeight: 157)
        XCTAssertEqual(clamped.minX, 143)
        let above = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 200, y: 600, width: 48, height: 41),
            canvas: CGSize(width: 400, height: 720), contentHeight: 157)
        XCTAssertEqual(above.minY, 437)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testTeamMenuNeitherSideFitsClampsAllScrollableContentInsideCanvas() {
        let frame = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 200, y: 100, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 320), contentHeight: 480)
        XCTAssertEqual(frame, CGRect(x: 143, y: 8, width: 185, height: 304))
        XCTAssertEqual(frame.maxY, 312, "New team must remain inside the scrollable menu viewport")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testTeamMenuNearCanvasTopAndBottomKeepsInsetsAndTriggerGapWhenPossible() {
        let top = SettingsTeamMenuBounds.frame(trigger: CGRect(x: -20, y: 0, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 320), contentHeight: 157)
        XCTAssertEqual(top, CGRect(x: 8, y: 47, width: 185, height: 157))
        let bottom = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 330, y: 290, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 320), contentHeight: 157)
        XCTAssertEqual(bottom, CGRect(x: 143, y: 127, width: 185, height: 157))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testTeamMenuSideFitIncludesSixPointGapAndEightPointCanvasInset() {
        let exactBelow = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 20, y: 165, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 320), contentHeight: 100)
        XCTAssertEqual(exactBelow.minY, 212)
        XCTAssertEqual(exactBelow.maxY, 312)
        let onePointShort = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 20, y: 166, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 320), contentHeight: 100)
        XCTAssertEqual(onePointShort.minY, 60, "Room for the menu without its gap must flip above")
        let exactAbove = SettingsTeamMenuBounds.frame(trigger: CGRect(x: 20, y: 114, width: 48, height: 41),
            canvas: CGSize(width: 336, height: 200), contentHeight: 100)
        XCTAssertEqual(exactAbove.minY, 8)
        XCTAssertEqual(exactAbove.maxY, 108)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testTeamMenuTinyCanvasAndOversizedContentNeverProduceOutsideOrNegativeBounds() {
        for canvas in [CGSize.zero, CGSize(width: 8, height: 6), CGSize(width: 16, height: 16),
                       CGSize(width: 17, height: 17), CGSize(width: 100, height: 100)] {
            for trigger in [CGRect(x: -100, y: -100, width: 48, height: 41),
                            CGRect(x: 500, y: 500, width: 48, height: 41)] {
                for contentHeight: CGFloat in [-1, 0, 480, 1000] {
                    let frame = SettingsTeamMenuBounds.frame(trigger: trigger, canvas: canvas, contentHeight: contentHeight)
                    XCTAssertGreaterThanOrEqual(frame.minX, 0)
                    XCTAssertGreaterThanOrEqual(frame.minY, 0)
                    XCTAssertGreaterThanOrEqual(frame.width, 0)
                    XCTAssertGreaterThanOrEqual(frame.height, 0)
                    XCTAssertLessThanOrEqual(frame.maxX, canvas.width)
                    XCTAssertLessThanOrEqual(frame.maxY, canvas.height)
                }
            }
        }
        XCTAssertEqual(SettingsTeamMenuBounds.frame(trigger: .zero, canvas: CGSize(width: 8, height: 6),
            contentHeight: 480), CGRect(x: 4, y: 3, width: 0, height: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testLearningModeClientUsesCanonicalBackendRoutes() {
        XCTAssertEqual(LearningModeAPIClient.statusPath, "/v1/learning-mode")
        XCTAssertEqual(LearningModeAPIClient.activationPath, "/v1/learning-mode/activate")
        XCTAssertEqual(LearningModeAPIClient.deactivationPath, "/v1/learning-mode/deactivate")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,message-input.privacy-context
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
