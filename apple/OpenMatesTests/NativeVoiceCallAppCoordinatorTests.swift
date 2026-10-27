// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.typed-input, video-call.chat.fixed-binding,
// video-call.privacy.first-call-warning, video-call.lifecycle.recovery-and-billing
import XCTest
import Combine
@testable import OpenMates

@MainActor
final class NativeVoiceCallAppCoordinatorTests: XCTestCase {
    private func ticket(_ driver: AppCallDriver, _ text: String = "Original", revision: UInt64 = 1) -> NativeVoiceCallDraftTicket {
        .init(id: UUID(), revision: revision, scope: driver.scope, text: text, originalComposerState: Data([1, 2, 3]))
    }
    private func make(_ driver: AppCallDriver, accepted: @escaping @MainActor (NativeVoiceCallDraftTicket, String) -> Void = { _, _ in },
                      restore: @escaping @MainActor (NativeVoiceCallDraftTicket) -> Bool = { _ in true }) -> NativeVoiceCallAppCoordinator {
        .init(driver: driver, accepted: accepted, restore: restore,
              artifacts: { _, _, _ in .unsupported }, usage: { _, _, _ in })
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testWireSubmissionDoesNotClearDraft() async throws {
        let driver = AppCallDriver(); var accepted = 0
        let coordinator = make(driver, accepted: { _, _ in accepted += 1 })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        let original = ticket(driver); try await coordinator.send(original)
        XCTAssertEqual(accepted, 0)
        await driver.emit(.transcript(driver.transcript(text: original.text)))
        XCTAssertEqual(accepted, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testPartialAndWrongCallEchoNeverAccept() async throws {
        let driver = AppCallDriver(); var accepted = 0
        let coordinator = make(driver, accepted: { _, _ in accepted += 1 })
        await coordinator.start(.existing(chatID: driver.scope.chatID)); try await coordinator.send(ticket(driver))
        await driver.emit(.transcript(driver.transcript(final: false)))
        await driver.emit(.transcript(driver.transcript(callID: "other")))
        XCTAssertEqual(accepted, 0)
        await coordinator.hangup()
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testEchoBeforeSubmissionReturnsAcceptsExactUUID() async throws {
        let driver = AppCallDriver(); var accepted: [String] = []
        let coordinator = make(driver, accepted: { _, id in accepted.append(id) })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        driver.duringSend = { await driver.emit(.transcript(driver.transcript())) }
        try await coordinator.send(ticket(driver))
        XCTAssertEqual(accepted, [driver.messageID])
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testFinalEchoThenTerminalBeforeReturnStillAccepts() async throws {
        let driver = AppCallDriver(); var accepted = 0; var restored = 0
        let coordinator = make(driver, accepted: { _, _ in accepted += 1 }, restore: { _ in restored += 1; return true })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        driver.duringSend = {
            await driver.emit(.transcript(driver.transcript()))
            await driver.hangup()
        }
        try await coordinator.send(ticket(driver))
        XCTAssertEqual(accepted, 1); XCTAssertEqual(restored, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testRejectedSubmissionPreservesCompleteOriginalSnapshot() async throws {
        let driver = AppCallDriver(); var restored: [NativeVoiceCallDraftTicket] = []
        let coordinator = make(driver, restore: { restored.append($0); return true })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        let original = ticket(driver); try await coordinator.send(original)
        await driver.emit(.typedRejected(messageID: driver.messageID))
        XCTAssertEqual(restored, [original])
        await driver.hangup(); XCTAssertEqual(restored, [original])
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testEarlyRejectRestoresOnce() async {
        let driver = AppCallDriver(); var restored = 0
        let coordinator = make(driver, restore: { _ in restored += 1; return true })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        driver.duringSend = { await driver.emit(.typedRejected(messageID: driver.messageID)) }
        do { try await coordinator.send(ticket(driver)); XCTFail("rejection must throw") } catch {}
        XCTAssertEqual(restored, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testNewerDraftIsNotOverwrittenAndRecoveryRemainsAvailable() async throws {
        let driver = AppCallDriver(); var canRestore = false
        let coordinator = make(driver, restore: { _ in canRestore })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        let original = ticket(driver); try await coordinator.send(original); await driver.hangup()
        XCTAssertEqual(coordinator.recoverableDrafts, [original])
        canRestore = true; coordinator.retryRestore(original.id)
        XCTAssertTrue(coordinator.recoverableDrafts.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testChangedEchoNeverClearsOriginal() async throws {
        let driver = AppCallDriver(); var accepted = 0; var restored = 0
        let coordinator = make(driver, accepted: { _, _ in accepted += 1 }, restore: { _ in restored += 1; return true })
        await coordinator.start(.existing(chatID: driver.scope.chatID)); try await coordinator.send(ticket(driver))
        await driver.emit(.transcript(driver.transcript(text: "Changed")))
        XCTAssertEqual(accepted, 0); XCTAssertEqual(restored, 1)
        XCTAssertEqual(coordinator.integrationError, .invalidResponse)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testMinimizeAndNavigationDoNotHangUpOrChangeBinding() async {
        let driver = AppCallDriver(); let coordinator = make(driver)
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        coordinator.minimized = true; coordinator.minimized = false
        XCTAssertEqual(coordinator.boundChatID, driver.scope.chatID); XCTAssertEqual(driver.hangups, 0)
        await coordinator.invalidateOwner(); XCTAssertEqual(driver.invalidations, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testConsentUsesExactRequestIdentityAndCanBeCancelled() async {
        let driver = AppCallDriver(); let coordinator = make(driver)
        driver.requireConsent = true
        let observer = coordinator.$consentRequestID.compactMap { $0 }.first().sink { _ in driver.markConsentPresented() }
        defer { observer.cancel() }
        let starting = Task { await coordinator.start(.existing(chatID: driver.scope.chatID)) }
        await driver.waitForConsent()
        guard let id = coordinator.consentRequestID else { XCTFail("missing disclosure"); return }
        coordinator.decideConsent(id: UUID(), accepted: true)
        XCTAssertEqual(coordinator.consentRequestID, id)
        coordinator.decideConsent(id: id, accepted: false)
        await starting.value
        XCTAssertEqual(driver.audioStarts, 0)
        XCTAssertEqual(coordinator.integrationError, .consentRequired)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding
    func testAnotherChatTicketIsRejectedBeforeSubmission() async {
        let driver = AppCallDriver(); let coordinator = make(driver)
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        let foreign = ticket(AppCallDriver())
        do { try await coordinator.send(foreign); XCTFail("foreign draft admitted") } catch {}
        XCTAssertEqual(driver.textSubmissions, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding
    func testOwnerInvalidationAfterEarlyEchoDoesNotClearDraft() async {
        let driver = AppCallDriver(); var accepted = 0; var restored = 0
        let coordinator = make(driver, accepted: { _, _ in accepted += 1 }, restore: { _ in restored += 1; return true })
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        driver.duringSend = {
            await driver.emit(.transcript(driver.transcript()))
            await coordinator.invalidateOwner()
        }
        do { try await coordinator.send(ticket(driver)); XCTFail("stale owner admitted") } catch {}
        XCTAssertEqual(accepted, 0); XCTAssertEqual(restored, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding
    func testNewCallWaitsForSuspendedSubmissionToResolve() async throws {
        let driver = AppCallDriver(); let coordinator = make(driver)
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        driver.duringSend = {
            await driver.hangup()
            await coordinator.start(.existing(chatID: driver.scope.chatID))
        }
        do { try await coordinator.send(ticket(driver)); XCTFail("ended call admitted") } catch {}
        XCTAssertEqual(driver.starts, 1)
        driver.duringSend = nil
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        XCTAssertEqual(driver.starts, 2)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.lifecycle.recovery-and-billing
    func testUnsupportedToolStopsCallWithoutFabricatedResponse() async {
        let driver = AppCallDriver(); let coordinator = make(driver)
        let stopped = expectation(description: "unsupported router stops call")
        driver.onHangup = { stopped.fulfill() }
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        await driver.emit(.tool(["type": .string("voice_memory"), "call_id": .string(driver.callID),
            "function_call_id": .string("function"), "assistant_message_id": .string("assistant"),
            "user_message_id": .string("user"), "payload": .object(["request_id": .string("request")])]))
        await fulfillment(of: [stopped], timeout: 2)
        XCTAssertEqual(coordinator.integrationError, .unsupportedTransport)
        XCTAssertEqual(driver.toolResponses, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.fixed-binding,video-call.privacy.first-call-warning,video-call.lifecycle.recovery-and-billing
    func testMeterRejectsOtherCallAndBoundsRealSamples() async {
        let driver = AppCallDriver(); let coordinator = make(driver)
        await coordinator.start(.existing(chatID: driver.scope.chatID))
        coordinator.updateMeter([1], scope: driver.scope, callID: "other")
        XCTAssertTrue(coordinator.meterLevels.isEmpty)
        coordinator.updateMeter(Array(repeating: .infinity, count: 60), scope: driver.scope, callID: driver.callID)
        XCTAssertEqual(coordinator.meterLevels.count, 48)
        XCTAssertTrue(coordinator.meterLevels.allSatisfy { $0 == 0 })
        await driver.hangup(); XCTAssertTrue(coordinator.meterLevels.isEmpty)
    }
}

@MainActor
private final class AppCallDriver: NativeVoiceCallAppDriving {
    let scope = NativeVoiceCallScope(accountID: "owner", profileID: "development", workspaceGeneration: UUID(),
                                    chatID: UUID().uuidString, mateCategory: "general_knowledge")
    let callID = "call"; let messageID = UUID().uuidString
    var consent: (@MainActor @Sendable () async -> Bool)?
    var event: (@MainActor @Sendable (NativeVoiceCallEvent) async -> Void)?
    var duringSend: (() async -> Void)?
    var state = NativeVoiceCallSnapshot()
    var starts = 0; var textSubmissions = 0; var toolResponses = 0
    var onHangup: (() -> Void)?
    var hangups = 0; var invalidations = 0; var audioStarts = 0; var requireConsent = false
    private var consentWaiting: CheckedContinuation<Void, Never>?
    private var reachedConsent = false
    func bind(consent: @escaping @MainActor @Sendable () async -> Bool,
              event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void) { self.consent = consent; self.event = event }
    func waitForConsent() async {
        if reachedConsent { return }
        await withCheckedContinuation { consentWaiting = $0 }
    }
    func markConsentPresented() {
        reachedConsent = true; consentWaiting?.resume(); consentWaiting = nil
    }
    func start(_ destination: NativeVoiceCallAppDestination) async throws {
        if requireConsent {
            guard await consent?() == true else { throw NativeVoiceCallError.consentRequired }
        }
        starts += 1; audioStarts += 1; state = .init(status: .live, scope: scope, callID: callID)
        await emit(.state(state))
    }
    func sendText(_ text: String) async throws -> String { textSubmissions += 1; await duringSend?(); return messageID }
    func setMuted(_ muted: Bool) async { state.muted = muted; await emit(.state(state)) }
    func hangup() async { hangups += 1; onHangup?(); state.status = .ended; await emit(.state(state)) }
    func invalidate() async { invalidations += 1; await hangup() }
    func snapshot() async -> NativeVoiceCallSnapshot { state }
    func respondToTool(_ frame: NativeVoiceCallFrame) async throws { toolResponses += 1; throw NativeVoiceCallError.unsupportedTransport }
    func emit(_ event: NativeVoiceCallEvent) async { await self.event?(event) }
    func transcript(text: String = "Original", final: Bool = true, callID: String = "call") -> NativeVoiceCallTranscript {
        .init(callID: callID, messageID: messageID, role: .user, text: text, final: final, interrupted: false,
              userMessageID: messageID, createdAt: 1, modelName: nil, mateCategory: nil, mateName: nil)
    }
}
