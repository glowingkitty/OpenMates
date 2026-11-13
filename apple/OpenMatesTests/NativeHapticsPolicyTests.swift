// Tests of `NativeHaptics` (Core/Services/NativeHaptics.swift): commit actions
// render one light tap, the shared 3 second quiet window drops (never queues or
// extends) later haptics, silent mode plays nothing yet consumes the event, the
// error cue is distinct and duplicates stay deduplicated. The clock, silent
// switch and renderer are injected; no hardware is touched.
// Specification: specifications/features/notifications/specification.yml
// Assertions: notifications.sounds.important-events, notifications.sounds.quiet-window, notifications.sounds.silent-mode
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeHapticsPolicyTests: XCTestCase {
    @MainActor private final class Harness {
        var cues: [NativeHaptics.Cue] = []
        var time: TimeInterval = 1_000
        var silent = false
        lazy var haptics = NativeHaptics(enabled: { true }, render: { [unowned self] in self.cues.append($0) },
                                         silent: { [unowned self] in self.silent }, clock: { [unowned self] in self.time })
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.important-events
    func testCommitActionsRenderTheSameLightTapAndCuesStayDistinct() {
        let commits: [NativeHaptics.Event] = [.taskCreated, .taskUpdated, .workflowCreated, .workflowUpdated,
                                              .teamCreated, .authenticated, .apiKeyCreated, .chatDeleted]
        for event in commits { XCTAssertEqual(event.cue, .lightTap, "\(event)") }
        XCTAssertEqual(NativeHaptics.Event.messageAccepted.cue, .accepted)
        XCTAssertEqual(NativeHaptics.Event.notification.cue, .notification)
        XCTAssertEqual(NativeHaptics.Event.error.cue, .error)
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.important-events
    func testErrorCueRendersOnceAndDuplicateIsDeduplicated() {
        let harness = Harness()
        harness.haptics.confirmed(.error, id: "toast", scope: "owner")
        harness.time += 10
        harness.haptics.confirmed(.error, id: "toast", scope: "owner")
        XCTAssertEqual(harness.cues, [.error])
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.quiet-window
    func testQuietWindowDropsFollowUpHapticsAndNeverReplaysThem() {
        let harness = Harness()
        harness.haptics.confirmed(.taskCreated, id: "a", scope: "owner")
        harness.time += 2.9
        harness.haptics.confirmed(.error, id: "b", scope: "owner")
        harness.time += 5
        XCTAssertEqual(harness.cues, [.lightTap], "A dropped haptic is never delayed or replayed")
        harness.haptics.confirmed(.error, id: "b", scope: "owner")
        XCTAssertEqual(harness.cues, [.lightTap], "The dropped event stays consumed")
        harness.haptics.confirmed(.error, id: "c", scope: "owner")
        XCTAssertEqual(harness.cues, [.lightTap, .error])
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.quiet-window
    func testDroppedHapticDoesNotExtendTheQuietWindow() {
        let harness = Harness()
        harness.haptics.confirmed(.taskCreated, id: "a", scope: "owner")
        harness.time += 2
        harness.haptics.confirmed(.notification, id: "dropped", scope: "owner")
        harness.time += 1.1
        harness.haptics.confirmed(.workflowUpdated, id: "after", scope: "owner")
        XCTAssertEqual(harness.cues, [.lightTap, .lightTap], "3.1 s after the last played haptic is outside the window")
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.silent-mode
    func testSilentModePlaysNothingAndStillConsumesTheEvent() {
        let harness = Harness()
        harness.silent = true
        harness.haptics.confirmed(.taskCreated, id: "a", scope: "owner")
        harness.haptics.confirmed(.messageAccepted, id: "turn", scope: "owner")
        XCTAssertTrue(harness.cues.isEmpty)
        harness.silent = false
        harness.time += 10
        harness.haptics.confirmed(.taskCreated, id: "a", scope: "owner")
        XCTAssertTrue(harness.cues.isEmpty, "Silenced events never replay after silent mode is turned off")
        harness.haptics.confirmed(.taskCreated, id: "b", scope: "owner")
        XCTAssertEqual(harness.cues, [.lightTap], "Silent mode applies immediately in both directions")
    }

    // contract-test: direct surface=gui.apple assertions=notifications.sounds.silent-mode
    func testSilentModeKeyMatchesTheWebStorageKeyAndPersistsInUserDefaults() {
        XCTAssertEqual(NativeHaptics.silentModeKey, "openmates_silent_mode")
        let previous = NativeHaptics.isSilentMode()
        defer { NativeHaptics.setSilentMode(previous) }
        NativeHaptics.setSilentMode(true)
        XCTAssertTrue(NativeHaptics.isSilentMode())
        NativeHaptics.setSilentMode(false)
        XCTAssertFalse(NativeHaptics.isSilentMode())
    }
}
