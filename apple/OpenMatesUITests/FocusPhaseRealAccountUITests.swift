// Explicit opt-in native Career insights inference. Synthetic coverage stays separate.
import XCTest

@MainActor
final class FocusPhaseRealAccountUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        guard RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_FOCUS_PHASE_LIVE") == "1" else {
            throw XCTSkip("Eight-turn focus verification requires explicit OPENMATES_TEST_FOCUS_PHASE_LIVE=1")
        }
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases,focus-modes.restoration,focus-modes.history-events,focus-modes.history-side-effects,focus-modes.controls
    func testEightCareerInsightTurnsRestoreEncryptedProgressAndLinkedHistory() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-fresh-new-chat", "--ui-test-focus-phase-probe",
                "--ui-test-expose-chat-ids", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        let sync = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-sync-complete", "true")).firstMatch
        XCTAssertTrue(sync.waitForExistence(timeout: 45))
        let turns: [(String, String)] = [
            ("@focus:jobs:career_insights I am a fictional software developer named Alex and I feel stuck in my career. Please activate Career insights and help me in English. Ask one question at a time, include examples and your recommendation, and wait for my answer.", "understand"),
            ("I enjoy mentoring other developers and explaining technical ideas. Routine maintenance work is draining. Please ask your next single question with examples and your recommendation.", "understand"),
            ("Please give me all the remaining intake questions at once so I can answer them together.", "understand"),
            ("My goal is to explore a more fulfilling career while keeping my current income. I can invest two hours per week for the next six months. Explicitly skip the remaining intake questions and proceed to confirming my career profile, stating any unknowns.", "confirm_profile"),
            ("Correction: remote flexibility is essential, and I do not want management responsibility. Update the profile, but I am explicitly withholding approval and confirmation for now.", "confirm_profile"),
            ("I confirm and approve the corrected career profile. Please research and explore suitable career directions.", "explore"),
            ("I choose technical writing. Please move on to a low-risk plan that lets me keep my income while testing that direction for two hours a week over six months.", "next_steps"),
            ("Return to Understand your situation. I want to reconsider my priorities. Stay in that phase for this turn and do not advance again immediately.", "understand")
        ]
        var chatID: String?
        var finalProbe = ""
        for (index, turn) in turns.enumerated() {
            let response = try send(turn.0, in: app)
            XCTAssertFalse(response.contains("focus_phase_changed"), "Phase protocol must not leak into the assistant reply")
            XCTAssertFalse(response.contains("evaluated_boundaries"))
            let probe = app.descendants(matching: .any)["focus-phase-state-probe"].firstMatch
            let expected = NSPredicate { _, _ in
                probe.exists && probe.label.contains("focus=jobs-career_insights;phase=\(turn.1);")
            }
            XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: expected, object: nil)], timeout: 45), .completed,
                "Turn \(index + 1) must retain/advance the expected live phase")
            finalProbe = probe.label
            let current = field("chat", in: finalProbe)
            if let chatID { XCTAssertEqual(current, chatID, "All eight turns must stay in the same chat") }
            else { chatID = current }
            XCTAssertTrue(app.descendants(matching: .any)["focus-pill-label"].exists,
                "The existing active focus chrome must remain present")
            if index == 0 || index == 1 {
                XCTAssertEqual(response.filter { $0 == "?" }.count, 1, "Sequential clarification asks one question and waits")
                let normalized = response.lowercased()
                XCTAssertTrue(["example", "e.g.", "for instance"].contains { normalized.contains($0) },
                    "Sequential questions include concrete examples")
                XCTAssertTrue(["recommend", "suggest"].contains { normalized.contains($0) },
                    "Sequential questions include a recommendation")
            }
            if index == 2 {
                XCTAssertGreaterThan(response.filter { $0 == "?" }.count, 1, "Batching must honor the user's request")
            }
            attach(app, "Native focus turn \(index + 1): \(turn.1)")
        }
        let receiptIDs = field("receipts", in: finalProbe).split(separator: ",").map(String.init)
        XCTAssertGreaterThanOrEqual(receiptIDs.count, 4)
        XCTAssertEqual(Set(receiptIDs).count, receiptIDs.count)
        XCTAssertTrue(receiptIDs.allSatisfy { UUID(uuidString: $0) != nil })
        let restoredChatID = try XCTUnwrap(chatID)
        app.terminate()
        app.launchArguments = ["--ui-test-focus-phase-probe", "--ui-test-expose-chat-ids",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let probe = app.descendants(matching: .any)["focus-phase-state-probe"].firstMatch
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            probe.exists && self.field("chat", in: probe.label) == restoredChatID && probe.label == finalProbe
        }, object: nil)], timeout: 45), .completed, "Relaunch must restore the same encrypted phase snapshot and receipt UUIDs")
        let history = app.descendants(matching: .any)["chat-history-surface"].firstMatch
        let linkQuery = app.buttons.matching(identifier: "focus-phase-details-link")
        for _ in 0..<12 {
            if linkQuery.allElementsBoundByIndex.contains(where: \.isHittable) { break }
            if history.exists { history.swipeDown() } else { app.swipeDown() }
        }
        let link = try XCTUnwrap(linkQuery.allElementsBoundByIndex.first(where: \.isHittable))
        link.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-focus-detail-page"].waitForExistence(timeout: 20))
        let phases = app.descendants(matching: .any).matching(identifier: "focus-mode-phase")
        XCTAssertEqual(phases.count, 4)
        XCTAssertFalse(app.webViews.firstMatch.exists)
        // Opening a historical title must preserve the observed live snapshot.
        XCTAssertEqual(probe.label, finalProbe)
        attach(app, "Restored phase history opens native four-phase detail")
    }

    private func send(_ prompt: String, in app: XCUIApplication) throws -> String {
        let completions = app.descendants(matching: .any).matching(identifier: "assistant-response-feedback")
        let responses = app.descendants(matching: .any).matching(identifier: "message-assistant")
        let priorCount = responses.count
        let editor = try XCTUnwrap(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 20))
        XCTAssertTrue(RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor"))
        let value = editor.value as? String ?? ""
        XCTAssertTrue(value.isEmpty || value == editor.placeholderValue, "The next turn must not overwrite an unrelated draft")
        app.typeText(prompt)
        XCTAssertEqual(editor.value as? String, prompt)
        app.buttons["send-button"].tap()
        let stop = app.buttons["stop-processing-button"]
        let processing = app.descendants(matching: .any)["streaming-banner"].firstMatch
        let done = NSPredicate { _, _ in
            guard responses.count > priorCount, completions.firstMatch.exists,
                  !stop.exists, !processing.exists,
                  let latest = responses.allElementsBoundByIndex.last,
                  let value = latest.value as? String, let data = value.data(using: .utf8),
                  let manifest = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return false }
            return manifest["is_streaming"] as? Bool == false && latest.label.count > 8
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: done, object: nil)], timeout: 180), .completed,
            "Each actual native send must finish a new assistant response")
        let last = try XCTUnwrap(responses.allElementsBoundByIndex.last)
        XCTAssertGreaterThan(last.label.count, 8)
        return last.label
    }

    private func field(_ key: String, in label: String) -> String {
        label.split(separator: ";").first { $0.hasPrefix(key + "=") }.map { String($0.dropFirst(key.count + 1)) } ?? ""
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
