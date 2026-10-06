// Live UI coverage for the native chat flow.
// Mirrors the core web chat-flow.spec.ts path for a real account and covers the
// signed-out anonymous free-usage path from the welcome composer. Real-account
// credentials are read only from the test process environment and are never
// logged or committed.

import CryptoKit
import Foundation
import XCTest

@MainActor
final class ChatFlowRealAccountUITests: XCTestCase {
    private let markerPrompt = "Write four short sentences about Kyoto and Osaka. Start with: Kyoto neighbors Osaka."
    private let anonymousPrompt = "Anonymous native smoke test: answer with one short sentence."
    private let assistantResponseTimeout: TimeInterval = 90

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    override func tearDownWithError() throws {
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        try super.tearDownWithError()
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.layout.responsive-history,chats.surface.semantic-parity
    func testRecentPersonalChatsOpenAndScrollReadOnlyWithTimingEvidence() throws {
        guard RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_READ_ONLY") == "1",
              let expectedIdentityHash = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_IDENTITY_HASH"),
              !expectedIdentityHash.isEmpty,
              let expectedAccountHash = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"),
              !expectedAccountHash.isEmpty else {
            throw XCTSkip("Personal read-only verification requires explicit opt-in and verified credential/account identity hashes")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        guard stableHash(credentials.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) == expectedIdentityHash else {
            throw XCTSkip("Configured credentials do not match the approved personal identity")
        }
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        // Authenticate through the ordinary production UI to verify the opted-in
        // identity instead of trusting an unrelated cached simulator session.
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-expose-chat-ids", "--ui-test-read-only-performance",
                "-AppleInterfaceStyle", "Dark", "-themeMode", "dark"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 45))
        let metricsProbe = app.descendants(matching: .any)
            .matching(identifier: "read-only-responsiveness-metrics").firstMatch
        XCTAssertTrue(metricsProbe.waitForExistence(timeout: 10))
        func probeFields() -> [String: String] {
            Dictionary(metricsProbe.label.split(separator: ";").compactMap { field in
                let pair = field.split(separator: "=", maxSplits: 1)
                guard pair.count == 2 else { return nil }
                return (String(pair[0]), String(pair[1]))
            }, uniquingKeysWith: { _, latest in latest })
        }
        let verifiedContext = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let fields = probeFields()
            return fields["account-hash"] == expectedAccountHash && fields["server-kind"] == "development"
                && (Double(fields["samples"] ?? "") ?? 0) > 0
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [verifiedContext], timeout: 10), .completed,
                       "Native performance probe must confirm the approved personal account on development with frame samples")
        guard probeFields()["account-hash"] == expectedAccountHash,
              probeFields()["server-kind"] == "development" else { return }
        func frameMetrics() throws -> [String: Double] {
            let fields = probeFields()
            var numbers: [String: Double] = [:]
            for key in ["samples", "average-fps", "worst-frame-ms", "jank-count"] {
                let number = try XCTUnwrap(Double(fields[key] ?? ""), "Expected a numeric native frame metric")
                XCTAssertTrue(number.isFinite && number >= 0, "Native frame metrics must be finite and nonnegative")
                numbers[key] = number
            }
            XCTAssertGreaterThan(numbers["samples"] ?? 0, 0, "Native frame metrics require positive samples")
            return numbers
        }
        struct RecentConversation: Decodable { let id: String; let title: String }
        guard let selectedJSON = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_RECENT_COMPLETED_CHATS_JSON"),
              let selectionData = selectedJSON.data(using: .utf8) else {
            throw XCTSkip("Configure three existing completed recent conversations from the approved personal account")
        }
        let recentChats = try JSONDecoder().decode([RecentConversation].self, from: selectionData)
        XCTAssertEqual(recentChats.count, 3)
        XCTAssertEqual(Set(recentChats.map(\.id)).count, 3)
        XCTAssertTrue(recentChats.allSatisfy { !$0.id.isEmpty && !$0.title.isEmpty })
        // The private fixture is obtained read-only from the personal CLI's most
        // recent20. Drafts have no generated header and cannot prove this flow.
        // Search is the ordinary production control; selected IDs/titles stay
        // private and are never copied into timing artifacts.
        var samples: [[String: Any]] = []
        let options = XCTMeasureOptions()
        options.iterationCount = 1
        var performanceMetrics: [XCTMetric] = [XCTClockMetric(), XCTCPUMetric(application: app), XCTMemoryMetric(application: app)]
        #if os(iOS)
        // Apple's UIKit signposts isolate actual dragging/deceleration animation
        // intervals from AX polling and idle time. The xcresult stores their FPS,
        // frame count and hitch metrics. This aggregates scrolls in this read-only
        // flow; the per-chat probe snapshots below remain recent rolling windows.
        performanceMetrics.append(XCTOSSignpostMetric.scrollingAndDecelerationMetric)
        #endif
        measure(metrics: performanceMetrics, options: options) {
            do {
                for pass in 0..<2 {
                    for (index, chat) in recentChats.enumerated() {
                        openChatsPanel(in: app)
                        let search = try NativeUITestElementResolution.requireVisible(
                            app.buttons.matching(identifier: "search-button"), in: app, timeout: 5)
                        search.tap()
                        let input = try NativeUITestElementResolution.requireVisible(
                            app.textFields.matching(identifier: "search-input"), in: app, timeout: 5)
                        input.tap()
                        input.typeText(chat.title)
                        // Different conversations can share a generated title.
                        // Resolve the actual retained row by its opted-in identity,
                        // irrespective of SwiftUI's Button/Other representation.
                        let rowQuery = app.descendants(matching: .any).matching(NSPredicate(
                            format: "identifier IN %@ AND value == %@",
                            ["search-chat-item", "chat-item-wrapper"], "user-chat:\(chat.id)"))
                        let row = try NativeUITestElementResolution.requireVisible(
                            rowQuery, in: app, timeout: 30)
                        let rowFrame = row.frame
                        let controlGeometry: [String: Any] = ["pass": pass, "chat_index": index,
                            "x": rowFrame.minX, "y": rowFrame.minY,
                            "width": rowFrame.width, "height": rowFrame.height,
                            "hittable": row.isHittable, "enabled": row.isEnabled,
                            "identity_hash": stableHash(row.value as? String ?? "")]
                        let geometryData = try JSONSerialization.data(withJSONObject: controlGeometry, options: [.sortedKeys])
                        let geometryProof = XCTAttachment(data: geometryData, uniformTypeIdentifier: "public.json")
                        geometryProof.name = "selected-search-control-geometry.json"
                        geometryProof.lifetime = .keepAlways
                        add(geometryProof)
                        let start = Date()
                        row.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
                        let selectedRoute = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                            let fields = probeFields()
                            return fields["route-hash"] == self.stableHash(chat.id)
                                && fields["search-visible"] == "false"
                        }, object: nil)
                        let routeResult = XCTWaiter.wait(for: [selectedRoute], timeout: 10)
                        let routeProof = XCTAttachment(data: try JSONSerialization.data(withJSONObject: probeFields(), options: [.sortedKeys]),
                            uniformTypeIdentifier: "public.json")
                        routeProof.name = "selected-chat-route-metrics.json"
                        routeProof.lifetime = .keepAlways
                        add(routeProof)
                        XCTAssertEqual(routeResult, .completed, "The production search tap must select this exact chat and close search")
                        let chatID = chat.id
                        _ = try NativeUITestElementResolution.requireVisible(
                            app.descendants(matching: .any).matching(identifier: "chat-view-\(chatID)"),
                            in: app, timeout: 20, actionable: false)
                        let history = try NativeUITestElementResolution.requireVisible(
                            app.scrollViews.matching(identifier: "chat-history-container"), in: app, timeout: 20)
                        // A saved message anchor can restore below the banner. Resolve
                        // the rendered title in this visible transcript without moving it.
                        let headerQuery = history.descendants(matching: .any).matching(identifier: "chat-header-title")
                        let titleMatches = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                            headerQuery.allElementsBoundByIndex.contains { candidate in
                                candidate.exists && candidate.label.trimmingCharacters(in: .whitespacesAndNewlines) == chat.title
                            }
                        }, object: nil)
                        let titleResult = XCTWaiter.wait(for: [titleMatches], timeout: 10)
                        @MainActor func attachRetainedHeaderGeometry() throws {
                            let viewport = app.windows.firstMatch.frame
                            let historyFrame = history.frame
                            let headerEvidence: [[String: Any]] = headerQuery.allElementsBoundByIndex.map { candidate in
                                let frame = candidate.frame
                                let midpoint = CGPoint(x: frame.midX, y: frame.midY)
                                return ["label_hash": self.stableHash(candidate.label),
                                    "label_length": candidate.label.count,
                                    "matches_expected_title": candidate.label.trimmingCharacters(in: .whitespacesAndNewlines) == chat.title,
                                    "exists": candidate.exists, "hittable": !frame.isEmpty && viewport.contains(midpoint) && historyFrame.contains(midpoint) && candidate.isHittable,
                                    "midpoint_in_window": !frame.isEmpty && viewport.contains(midpoint),
                                    "midpoint_in_history": !frame.isEmpty && historyFrame.contains(midpoint),
                                    "above_history_viewport": !frame.isEmpty && frame.maxY <= historyFrame.minY,
                                    "frame": [frame.minX, frame.minY, frame.width, frame.height]]
                            }
                            let receipt = XCTAttachment(data: try JSONSerialization.data(withJSONObject:
                                ["phase": "retained_header_after_restoration", "pass": pass, "chat_index": index,
                                 "expected_title_hash": self.stableHash(chat.title), "expected_title_length": chat.title.count,
                                 "candidates": headerEvidence, "history_frame": [historyFrame.minX, historyFrame.minY, historyFrame.width, historyFrame.height],
                                 "route": probeFields()], options: [.sortedKeys]), uniformTypeIdentifier: "public.json")
                            receipt.name = "personal-retained-header-restoration-geometry"; receipt.lifetime = .keepAlways; add(receipt)
                        }
                        if titleResult != .completed {
                            try attachRetainedHeaderGeometry()
                            let hierarchy = XCTAttachment(string: app.debugDescription)
                            hierarchy.name = "private-personal-header-failure-AX"; hierarchy.lifetime = .keepAlways; add(hierarchy)
                            attachScreenshot(name: "Private personal header failure")
                        }
                        XCTAssertTrue(headerQuery.firstMatch.exists, "The selected conversation must retain its rendered header")
                        XCTAssertEqual(titleResult, .completed,
                                       "The selected conversation must render its expected header")
                        let renderedRows = history.descendants(matching: .any).matching(NSPredicate(
                            format: "identifier IN %@", ["message-user", "message-assistant"]))
                        _ = try NativeUITestElementResolution.requireVisible(renderedRows, in: app,
                            timeout: 20, actionable: false)
                        let openedSeconds = Date().timeIntervalSince(start)
                        // Evidence reads follow the captured opening interval so AX
                        // diagnostics cannot change the original performance measure.
                        try attachRetainedHeaderGeometry()
                        XCTAssertLessThan(openedSeconds, 20, "Existing conversation opening must remain bounded")
                        let openingFrameMetrics = try frameMetrics()
                        var observedUser = false
                        var observedAssistant = false
                        var scrollSeconds: [Double] = []
                        var scrollFrameMetrics: [[String: Double]] = []
                        // Long real responses can span more than three screens. Find an
                        // actual user row before alternating scroll direction; retain
                        // the same per-interaction timing limit and both role checks.
                        for step in 0..<20 {
                            observedUser = observedUser || NativeUITestElementResolution.visible(
                                history.descendants(matching: .any).matching(identifier: "message-user"),
                                in: app, actionable: false) != nil
                            observedAssistant = observedAssistant || NativeUITestElementResolution.visible(
                                history.descendants(matching: .any).matching(identifier: "message-assistant"),
                                in: app, actionable: false) != nil
                            let direction = (!observedUser || step < 3 || !step.isMultiple(of: 2)) ? "down" : "up"
                            let interactionStart = Date()
                            if direction == "down" { history.swipeDown() }
                            else { history.swipeUp() }
                            let swipeSeconds = Date().timeIntervalSince(interactionStart)
                            _ = try NativeUITestElementResolution.requireVisible(renderedRows,
                                in: app, timeout: 5, actionable: false)
                            let elapsed = Date().timeIntervalSince(interactionStart)
                            // Capture after stopping the same end-to-end timer, before
                            // the unchanged limit can stop this private opted-in run.
                            // The rolling probe does not isolate the native scroll phase;
                            // Apple's scroll/deceleration metric is recorded separately.
                            let postScrollProbe = probeFields()
                            let interactionEvidence: [String: Any] = [
                                "pass": pass, "chat_index": index, "scroll_step": step,
                                "direction": direction,
                                "current_phase": "after_swipe_and_visible_row_resolution",
                                "elapsed_seconds": elapsed, "swipe_and_idle_seconds": swipeSeconds,
                                "visible_row_resolution_seconds": max(0, elapsed - swipeSeconds),
                                "rendered_row_count": renderedRows.count,
                                "observed_user_before_scroll": observedUser,
                                "observed_assistant_before_scroll": observedAssistant,
                                "probe_fields": postScrollProbe,
                                "frame_snapshot_scope": "recent_240_display_link_intervals_with_on_demand_probe_read",
                                "frame_snapshot_isolates_scroll_phase": false]
                            let interactionData = try JSONSerialization.data(withJSONObject: interactionEvidence,
                                options: [.prettyPrinted, .sortedKeys])
                            let interactionProof = XCTAttachment(data: interactionData, uniformTypeIdentifier: "public.json")
                            interactionProof.name = "private-scroll-pass-\(pass)-index-\(index)-step-\(step)-metrics.json"
                            interactionProof.lifetime = .keepAlways
                            add(interactionProof)
                            if elapsed >= 5 {
                                attachScreenshot(name: "Private over-budget scroll pass \(pass) index \(index) step \(step)")
                                let hierarchy = XCTAttachment(string: app.debugDescription)
                                hierarchy.name = "private-scroll-pass-\(pass)-index-\(index)-step-\(step)-full-AX.txt"
                                hierarchy.lifetime = .keepAlways
                                add(hierarchy)
                            }
                            XCTAssertLessThan(elapsed, 5, "Transcript scroll interaction must remain bounded")
                            scrollSeconds.append(elapsed)
                            scrollFrameMetrics.append(try frameMetrics())
                            observedUser = observedUser || NativeUITestElementResolution.visible(
                                history.descendants(matching: .any).matching(identifier: "message-user"),
                                in: app, actionable: false) != nil
                            observedAssistant = observedAssistant || NativeUITestElementResolution.visible(
                                history.descendants(matching: .any).matching(identifier: "message-assistant"),
                                in: app, actionable: false) != nil
                            if step >= 5 && observedUser && observedAssistant { break }
                        }
                        XCTAssertTrue(observedUser, "Existing history must render a visible user message")
                        XCTAssertTrue(observedAssistant, "Existing history must render a visible assistant message")
                        samples.append(["pass": pass, "chat_index": index,
                            "opening_seconds": openedSeconds, "scroll_seconds": scrollSeconds,
                            "opening_frame_metrics": openingFrameMetrics, "scroll_frame_metrics": scrollFrameMetrics,
                            "rendered_row_count": renderedRows.count])
                        attachScreenshot(name: "Private recent chat pass \(pass) index \(index)")
                        let close = try NativeUITestElementResolution.requireVisible(
                            app.buttons.matching(identifier: "chat-close-button"), in: app, timeout: 5)
                        close.tap()
                        _ = try NativeUITestElementResolution.requireVisible(
                            app.buttons.matching(identifier: "sidebar-toggle"), in: app, timeout: 5)
                    }
                }
            } catch {
                let candidates = app.descendants(matching: .any).matching(NSPredicate(
                    format: "identifier IN %@", ["search-chat-item", "chat-item-wrapper"]))
                let geometry = candidates.allElementsBoundByIndex.map { element -> [String: Any] in
                    let frame = element.frame
                    return ["identifier": element.identifier, "type": element.elementType.rawValue,
                        "identity_hash": stableHash(element.value as? String ?? ""),
                        "x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height,
                        "enabled": element.isEnabled, "hittable": element.isHittable]
                }
                if let data = try? JSONSerialization.data(withJSONObject: geometry, options: [.sortedKeys]) {
                    let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
                    attachment.name = "search-result-geometry.json"
                    attachment.lifetime = .keepAlways
                    add(attachment)
                }
                XCTFail("Read-only recent-chat navigation could not resolve a required production control")
            }
        }
        let data = try JSONSerialization.data(withJSONObject: ["chat_count": recentChats.count,
            "frame_snapshot_scope": "recent_240_display_link_intervals_with_on_demand_probe_read",
            "frame_snapshots_isolate_scroll_phase": false,
            "native_scroll_metric": "UIKit scrolling_and_deceleration_intervals_in_xcresult_iOS_only",
            "native_scroll_metric_scope": "aggregate_read_only_flow_scrolls",
            "samples": samples], options: [.prettyPrinted, .sortedKeys])
        let evidence = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        evidence.name = "personal-read-only-chat-timings.json"
        evidence.lifetime = .keepAlways
        add(evidence)
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible,chats.surface.semantic-parity,sync.surface.semantic-parity
    func testExistingPersonalTasksAndLargeCodeEmbedLoadReadOnly() throws {
        guard let chatID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_CODE_CHAT_ID"),
              let embedID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_CODE_EMBED_ID"),
              let sourceLine = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_CODE_SOURCE_LINE"),
              !chatID.isEmpty, !embedID.isEmpty, !sourceLine.isEmpty else {
            throw XCTSkip("Configure the existing personal-account code chat, canonical embed and expected source line")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let reuseAuthentication = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_REUSE_AUTH") == "1"
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: !reuseAuthentication,
            extraArguments: (reuseAuthentication ? [] : ["--ui-test-open-login"]) + ["--ui-test-expose-chat-ids"])
        if !reuseAuthentication { RealAccountUITestSupport.logIn(app: app, credentials: credentials) }
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 45))
        #if os(iOS)
        // Authenticate in the ordinary phone layout before verifying the wide
        // workspace. A short landscape viewport places the email step below
        // the initial login-method choices in the authentication scroll view.
        XCUIDevice.shared.orientation = .landscapeLeft
        #endif
        guard app.windows.firstMatch.frame.width > 600 else {
            throw XCTSkip("Run this large-card verification on iPad landscape or a wide macOS window")
        }

        func openWorkspace(_ name: String) {
            let entry = app.descendants(matching: .any).matching(identifier: "\(name)-nav-link").firstMatch
            if !entry.exists || !entry.isHittable {
                let switcher = app.descendants(matching: .any).matching(identifier: "workspace-switcher").firstMatch
                XCTAssertTrue(switcher.waitForExistence(timeout: 10))
                switcher.tap()
            }
            XCTAssertTrue(entry.waitForExistence(timeout: 10))
            entry.tap()
        }

        openWorkspace("tasks")
        let board = app.descendants(matching: .any).matching(identifier: "task-board").firstMatch
        XCTAssertTrue(board.waitForExistence(timeout: 45))
        XCTAssertTrue(board.descendants(matching: .any).matching(identifier: "task-card").firstMatch.waitForExistence(timeout: 45),
                      "The real account must render decrypted Task cards")
        let boardScroll = app.scrollViews.matching(identifier: "task-board").firstMatch
        XCTAssertTrue(boardScroll.exists)
        func columnHeaderVisible(_ column: XCUIElement) -> Bool {
            guard column.exists, !column.frame.isEmpty else { return false }
            let viewport = board.frame.intersection(app.windows.firstMatch.frame)
            return viewport.contains(CGPoint(x: column.frame.midX, y: column.frame.minY + 14))
        }
        for status in ["backlog", "todo", "in_progress", "blocked", "done"] {
            let column = board.descendants(matching: .any).matching(identifier: "task-column-\(status)").firstMatch
            for _ in 0..<6 {
                if columnHeaderVisible(column) { break }
                boardScroll.swipeLeft()
            }
            XCTAssertTrue(columnHeaderVisible(column), "Every lifecycle column must render in the board viewport")
        }
        let backlog = board.descendants(matching: .any).matching(identifier: "task-column-backlog").firstMatch
        for _ in 0..<6 {
            if columnHeaderVisible(backlog) { break }
            boardScroll.swipeRight()
        }
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "tasks-load-error").firstMatch.exists)
        let tasksProof = XCTAttachment(screenshot: app.screenshot())
        tasksProof.name = "Personal Tasks board loaded"
        tasksProof.lifetime = .keepAlways
        add(tasksProof)

        openWorkspace("chats")
        openChatsPanel(in: app)
        let row = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatID)"
        )).firstMatch
        if row.waitForExistence(timeout: 5) && row.isHittable {
            row.tap()
        } else {
            guard let query = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_CODE_CHAT_QUERY"), !query.isEmpty else {
                XCTFail("Configure a private title-search fallback for the existing code conversation")
                return
            }
            let search = app.textFields.matching(NSPredicate(
                format: "identifier == %@ OR placeholderValue == %@", "search-input", "Search"
            )).firstMatch
            if !search.exists {
                let searchButton = app.buttons.matching(NSPredicate(
                    format: "identifier == %@ OR label == %@", "search-button", "Search"
                )).firstMatch
                XCTAssertTrue(searchButton.waitForExistence(timeout: 10))
                searchButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            }
            XCTAssertTrue(search.waitForExistence(timeout: 10))
            search.tap()
            if let value = search.value as? String, !value.isEmpty {
                search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
            }
            search.typeText(query)
            let results = try NativeUITestElementResolution.requireVisible(
                app.descendants(matching: .any).matching(identifier: "search-results"),
                in: app, timeout: 45, actionable: false)
            let matchingResults = results.buttons.matching(NSPredicate(
                format: "identifier == %@ AND label CONTAINS[cd] %@", "search-chat-item", query))
            let result = try NativeUITestElementResolution.requireVisible(matchingResults, in: app, timeout: 45)
            XCTAssertTrue(result.isHittable, "The configured existing conversation must be searchable")
            // The result is already visible. Tap its production hit area without
            // XCTest's automatic scroll against a transient keyboard snapshot.
            result.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        // chat-view-ID confirms navigation through a DEBUG marker. It is a
        // sibling of the production transcript, not its accessibility parent.
        _ = try NativeUITestElementResolution.requireVisible(
            app.descendants(matching: .any).matching(identifier: "chat-view-\(chatID)"),
            in: app, timeout: 20, actionable: false)
        // A regular-width sidebar remains open after choosing a chat. Its own
        // header supplies the close action; the menu button exists only closed.
        if let sidebarClose = NativeUITestElementResolution.visible(
            app.buttons.matching(identifier: "chat-sidebar-close"), in: app) { sidebarClose.tap() }
        _ = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "sidebar-toggle"), in: app)
        let history = try NativeUITestElementResolution.requireVisible(
            app.scrollViews.matching(identifier: "chat-history-container"), in: app, timeout: 20)
        XCTAssertTrue(history.descendants(matching: .any).matching(identifier: "message-assistant").firstMatch.waitForExistence(timeout: 20))
        // Scroll navigation is an overlay sibling of the history container.
        if let toTop = NativeUITestElementResolution.visible(
            app.buttons.matching(identifier: "scroll-to-top-button"), in: app) { toTop.tap() }
        // Code cards contain their source accessibility children, so SwiftUI
        // may expose the exact actionable wrapper as Other rather than Button.
        // A stored embed can appear repeatedly in this conversation. Resolve
        // the visible occurrence after scrolling rather than its first AX match.
        let previews = history.descendants(matching: .any)
            .matching(identifier: "embed-preview-\(embedID)")
        for _ in 0..<12 {
            if NativeUITestElementResolution.visible(previews, in: app) != nil { break }
            history.swipeUp()
        }
        let visiblePreview = try NativeUITestElementResolution.requireVisible(previews, in: app)
        XCTAssertTrue(visiblePreview.exists && visiblePreview.isHittable, "The exact stored greeting.js card must hydrate inside the transcript viewport")
        let largeSourceReady = NSPredicate { _, _ in
            guard let preview = NativeUITestElementResolution.visible(previews, in: app) else { return false }
            return preview.exists && preview.isEnabled && preview.isHittable && (preview.value as? String) == "Ready" && preview.frame.height >= 400
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: largeSourceReady, object: nil)], timeout: 20), .completed,
                       "The wide production card must show ready source in its large layout")
        let largeProof = XCTAttachment(screenshot: app.screenshot())
        largeProof.name = "Existing greeting.js large source card"
        largeProof.lifetime = .keepAlways
        add(largeProof)
        let preview = try NativeUITestElementResolution.requireVisible(previews, in: app)
        preview.tap()

        let header = app.descendants(matching: .any).matching(identifier: "embed-fullscreen-header").firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 15))
        XCTAssertEqual(header.value as? String, embedID, "The production card must open the canonical stored code embed")
        XCTAssertEqual(app.staticTexts["embed-header-title"].firstMatch.label, "src/greeting.js")
        XCTAssertTrue(app.staticTexts["embed-header-subtitle"].firstMatch.label.contains("JavaScript"))
        let source = app.scrollViews.matching(identifier: "code-source-panel").firstMatch
        XCTAssertTrue(source.waitForExistence(timeout: 15))
        XCTAssertTrue(source.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", sourceLine)).firstMatch.waitForExistence(timeout: 10),
                      "The opened code view must render the expected source line")
        let sourceProof = XCTAttachment(screenshot: app.screenshot())
        sourceProof.name = "Existing greeting.js opened source"
        sourceProof.lifetime = .keepAlways
        add(sourceProof)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.surface.semantic-parity
    func testExistingEncryptedChatsRestoreUserMessagesAndEmbedPreviews() throws {
        guard let configured = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_EMBED_CHAT_IDS") else {
            throw XCTSkip("Configure existing test-account chats containing user messages and embeds")
        }
        guard let queries = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_EMBED_CHAT_QUERIES")?.split(separator: "|").map(String.init),
              queries.count == configured.split(separator: ",").count else {
            throw XCTSkip("Configure matching chat search titles for the existing embed fixtures")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let reuseAuthentication = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_REUSE_AUTH") == "1"
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: !reuseAuthentication,
            extraArguments: (reuseAuthentication ? [] : ["--ui-test-open-login"]) + ["--ui-test-start-new-chat", "--ui-test-expose-chat-ids"])
        if !reuseAuthentication {
            RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        }
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        for (index, chatId) in configured.split(separator: ",").map(String.init).enumerated() {
            openChatsPanel(in: app, allowingSearch: true)
            // SwiftUI can propagate the panel identifier over its header
            // buttons on iOS; retain the actual Search accessibility label.
            let searchButton = app.buttons.matching(NSPredicate(
                format: "identifier == %@ OR label == %@", "search-button", "Search"
            )).firstMatch
            let existingSearch = app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch
            if !existingSearch.exists {
                XCTAssertTrue(searchButton.waitForExistence(timeout: 10))
                searchButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            }
            let search = app.textFields.matching(NSPredicate(
                format: "identifier == %@ OR placeholderValue == %@", "search-input", "Search"
            )).firstMatch
            XCTAssertTrue(search.waitForExistence(timeout: 10))
            search.tap()
            if index > 0, let value = search.value as? String, !value.isEmpty {
                search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
            }
            search.typeText(queries[index])
            let result = app.buttons.matching(identifier: "search-chat-item").firstMatch
            XCTAssertTrue(result.waitForExistence(timeout: 45), "Configured conversation must be searchable")
            let start = Date()
            result.tap()
            XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "chat-view-\(chatId)").firstMatch.waitForExistence(timeout: 20))
            let user = app.descendants(matching: .any).matching(identifier: "message-user").firstMatch
            let assistant = app.descendants(matching: .any).matching(identifier: "message-assistant").firstMatch
            XCTAssertTrue(assistant.waitForExistence(timeout: 20), "Existing assistant message must remain visible")
            let scrollToTop = app.buttons["scroll-to-top-button"]
            if scrollToTop.exists { scrollToTop.tap() }
            XCTAssertTrue(user.waitForExistence(timeout: 20), "Existing user message must remain visible")
            let elapsed = Date().timeIntervalSince(start)
            let timing = XCTAttachment(string: "existing-chat-visible-seconds=\(elapsed)")
            timing.lifetime = .keepAlways
            add(timing)
            let preview = app.buttons.matching(identifier: "embed-preview").firstMatch
            XCTAssertTrue(preview.waitForExistence(timeout: 20), "Hydrated embed preview must be available")
            preview.tap()
            let minimize = app.buttons["embed-minimize"]
            XCTAssertTrue(minimize.waitForExistence(timeout: 10), "Embed preview must open its fullscreen content")
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Existing conversation embed content"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            minimize.tap()
        }
    }

    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    func testExistingVideoTranscriptChildHydratesFullscreenContent() throws {
        guard let transcriptChatQuery = RealAccountTestCredentials.configurationValue(
            for: "OPENMATES_TEST_VIDEO_TRANSCRIPT_CHAT_QUERY"
        ), !transcriptChatQuery.isEmpty else {
            throw XCTSkip("Configure the test-account chat containing a video transcript")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let reuseAuthentication = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_REUSE_AUTH") == "1"
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: !reuseAuthentication,
            extraArguments: reuseAuthentication ? [] : ["--ui-test-open-login"]
        )
        if !reuseAuthentication {
            RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        }
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))

        for query in [transcriptChatQuery] {
            openChatsPanel(in: app, allowingSearch: true)
            let searchButton = app.buttons.matching(NSPredicate(
                format: "identifier == %@ OR label == %@", "search-button", "Search"
            )).firstMatch
            let existingSearch = app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch
            if !existingSearch.exists {
                XCTAssertTrue(searchButton.waitForExistence(timeout: 10))
                searchButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            }
            let search = app.textFields.matching(NSPredicate(
                format: "identifier == %@ OR placeholderValue == %@", "search-input", "Search"
            )).firstMatch
            XCTAssertTrue(search.waitForExistence(timeout: 10))
            search.tap()
            if let value = search.value as? String, !value.isEmpty {
                search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
            }
            search.typeText(query)
            let result = app.buttons.matching(identifier: "search-chat-item").firstMatch
            XCTAssertTrue(result.waitForExistence(timeout: 45))
            result.tap()
            let openedChat = app.descendants(matching: .any).matching(NSPredicate(
                format: "identifier BEGINSWITH %@", "chat-view-"
            )).firstMatch
            XCTAssertTrue(openedChat.waitForExistence(timeout: 15), "Search result must open its chat")

            let preview = app.descendants(matching: .any)["video-transcript-preview"].firstMatch
            guard preview.waitForExistence(timeout: 15) else { continue }
            preview.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

            let transcript = app.staticTexts["video-transcript-fullscreen-text"].firstMatch
            XCTAssertTrue(transcript.waitForExistence(timeout: 15), "Persisted transcript child must render in fullscreen")
            XCTAssertFalse(
                transcript.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                "Persisted transcript content must be nonempty"
            )
            XCTAssertFalse(app.descendants(matching: .any)["video-transcript-fullscreen-empty"].exists)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Existing video transcript fullscreen"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            return
        }

        XCTFail("Configured embed chats did not expose a video transcript preview")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,sync.surface.semantic-parity
    func testExistingLongChatScrollsToFinalMessageRepeatedly() throws {
        guard let query = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_QUERY") else {
            throw XCTSkip("Configure an existing long test-account conversation")
        }
        guard let firstMessageID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_FIRST_MESSAGE_ID"),
              let lastMessageID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_LAST_MESSAGE_ID"),
              !firstMessageID.isEmpty, !lastMessageID.isEmpty else {
            throw XCTSkip("Configure exact oldest/newest message IDs from the web fixture; arrow visibility alone is insufficient")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true,
            extraArguments: ["--ui-test-start-new-chat", "--ui-test-history-window-metrics"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app, allowingSearch: true)
        let search = app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch
        if !search.exists {
            let button = app.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "search-button", "Search")).firstMatch
            XCTAssertTrue(button.waitForExistence(timeout: 10))
            button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        if let value = search.value as? String, !value.isEmpty {
            search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
        search.typeText(query)
        let result = app.buttons.matching(identifier: "search-chat-item").firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 45))
        XCTAssertTrue(result.label.localizedCaseInsensitiveContains(query))
        result.tap()
        let history = app.scrollViews.matching(identifier: "chat-history-container").firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 20))
        let oldest = app.descendants(matching: .any)["chat-history-message-" + firstMessageID].firstMatch
        let latest = app.descendants(matching: .any)["chat-history-message-" + lastMessageID].firstMatch
        let content = app.descendants(matching: .any)["chat-history-content"].firstMatch
        func endpointIsVisible(_ row: XCUIElement) -> Bool {
            guard row.exists, !row.frame.isEmpty else { return false }
            let intersection = row.frame.intersection(history.frame)
            return !intersection.isNull && intersection.height > 1 && intersection.width > 1
        }
        func assertBoundedWindow() {
            let value = content.value as? String ?? ""
            let renderedField = value.split(separator: ";").first { $0.hasPrefix("rendered=") }
            let count = renderedField.flatMap { Int($0.dropFirst("rendered=".count)) } ?? -1
            XCTAssertTrue((1...50).contains(count), "Rendered history must remain bounded throughout traversal")
        }
        let toTop = app.buttons["scroll-to-top-button"]
        let toBottom = app.buttons["scroll-to-bottom-button"]
        for pass in 1...3 {
            if toTop.exists { toTop.tap() }
            XCTAssertTrue(toTop.waitForNonExistence(timeout: 10))
            XCTAssertTrue(endpointIsVisible(oldest), "The configured oldest web message must be in the viewport")
            assertBoundedWindow()
            var gestures = 0
            let started = Date()
            repeat {
                history.swipeUp()
                gestures += 1
                assertBoundedWindow()
            } while (toBottom.exists || !endpointIsVisible(latest)) && gestures < 180
            XCTAssertTrue(endpointIsVisible(latest), "The exact newest web message must be visible")
            XCTAssertFalse(toBottom.exists, "The true end must be reached after rendering that message")
            XCTAssertTrue(toTop.exists, "Long conversation must remain navigable back to the beginning")
            XCTAssertTrue(app.state == .runningForeground)
            XCTAssertNotNil(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 5))
            let attachment = XCTAttachment(string: "full-scroll-pass=\(pass) gestures=\(gestures) seconds=\(Date().timeIntervalSince(started))")
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        toTop.tap()
        XCTAssertTrue(toTop.waitForNonExistence(timeout: 10))
        let preview = app.buttons.matching(identifier: "embed-preview").firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        preview.tap()
        let minimize = app.buttons["embed-minimize"]
        XCTAssertTrue(minimize.waitForExistence(timeout: 10), "Citation/embed actions must still work after repeated full traversal")
        minimize.tap()
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted
    func testCachedAccountLaunchCompletesInitialSync() throws {
        _ = try RealAccountTestCredentials.fromEnvironment()
        let app = RealAccountUITestSupport.launchApp(extraArguments: ["--ui-test-expose-chat-ids"])
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35),
                      "A cached account must finish the real phased sync after launch")
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted
    func testPasswordOtpLoginCreatesChatAndReceivesAssistantResponse() throws {
        let markerPrompt = "Reply with one short sentence: Hello from Osaka."
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-start-new-chat", "--ui-test-expose-chat-ids", "--ui-test-welcome-send-stage"]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)

        let active = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-")).firstMatch
        XCTAssertTrue(active.exists)
        let chatId = String(active.identifier.dropFirst("chat-view-".count))
        XCTAssertFalse(chatId.isEmpty)
        app.terminate()
        app.launchArguments.removeAll { ["--ui-test-disable-auth-cache", "--ui-test-open-login", "--ui-test-start-new-chat"].contains($0) }
        app.launch()
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app)
        let row = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatId)"
        )).firstMatch
        // Drafts sort ahead of recent conversations; expand and scroll the
        // sidebar before asserting that a particular persisted identity is absent.
        let history = app.scrollViews.matching(identifier: "chat-sidebar-scroll").firstMatch
        for _ in 0..<12 {
            if row.exists { break }
            let more = app.buttons["load-more-chats"]
            // A short page can place Load More just below the panel's top.
            // Check its tap point, not its whole frame, while keeping the tap
            // away from system edge gestures. XCTest can report a button under
            // the home indicator as hittable even when its tap is intercepted.
            if more.exists && more.isHittable && history.frame.insetBy(dx: 0, dy: 35).contains(
                CGPoint(x: more.frame.midX, y: more.frame.midY)
            ) {
                more.tap()
            } else {
                history.swipeUp()
            }
        }
        XCTAssertTrue(row.waitForExistence(timeout: 5), "Created chat must survive relaunch")
        row.tap()
        let userMessage = RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-user", labelContaining: markerPrompt)
        XCTAssertTrue(userMessage.waitForExistence(timeout: 25), "Original user message must survive relaunch")
        let assistants = app.otherElements.matching(identifier: "message-assistant")
        XCTAssertTrue(assistants.firstMatch.waitForExistence(timeout: 25), "Assistant response must survive relaunch")
        assertCompletionCommitted(in: app, minimumVersion: 2, assistantCount: 1)
        let previousCount = assistants.count
        let editor = try XCTUnwrap(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 10))
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        let followUpPrompt = "Which city did I mention? Reply with only the city name."
        app.typeText(followUpPrompt)
        XCTAssertEqual(editor.value as? String, followUpPrompt, "Typing must preserve the complete follow-up")
        app.buttons["send-button"].tap()
        let completed = NSPredicate { _, _ in assistants.count > previousCount }
        expectation(for: completed, evaluatedWith: app)
        waitForExpectations(timeout: assistantResponseTimeout)
        let streaming = RealAccountUITestSupport.accessibilityElement(in: app, identifier: "streaming-banner")
        XCTAssertTrue(streaming.waitForNonExistence(timeout: assistantResponseTimeout), "Follow-up must finish streaming")
        XCTAssertTrue(assistants.element(boundBy: assistants.count - 1).label.contains("Osaka"),
                      "Follow-up must use the persisted conversation history")
        assertCompletionCommitted(in: app, minimumVersion: 4, assistantCount: 2)
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted,chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction,web-search.surface-parity
    func testPasswordOtpWebSearchStreamsChildrenAndPersistsAfterRelaunch() throws {
        let prompt = "Search the web for the OpenMates AI assistant official website and summarize the top two results."
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: [
                "--ui-test-open-login", "--ui-test-fresh-new-chat",
                "--ui-test-expose-chat-ids", "--ui-test-welcome-send-stage",
            ]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: prompt)

        let userMessage = RealAccountUITestSupport.accessibilityElement(
            in: app,
            identifier: "message-user",
            labelContaining: prompt
        )
        XCTAssertTrue(userMessage.waitForExistence(timeout: 30), "The sent web-search request must render as the user message")

        let streaming = RealAccountUITestSupport.accessibilityElement(in: app, identifier: "streaming-banner")
        let skillCard = app.buttons.matching(identifier: "embed-preview").firstMatch
        let liveCard = NSPredicate { _, _ in streaming.exists && skillCard.exists }
        let liveCardExpectation = XCTNSPredicateExpectation(predicate: liveCard, object: app)
        XCTAssertEqual(
            XCTWaiter.wait(for: [liveCardExpectation], timeout: assistantResponseTimeout),
            .completed,
            "The web-search skill card must become visible while the assistant turn is still streaming"
        )
        XCTAssertTrue(skillCard.label.localizedCaseInsensitiveContains("search"),
                      "The live app-skill card must be the requested web search")

        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
        XCTAssertTrue(streaming.waitForNonExistence(timeout: assistantResponseTimeout))
        // A completed answer can be taller than the viewport. The card is near
        // the beginning of the answer while chat follows the newest text.
        for _ in 0..<12 where skillCard.exists && !skillCard.isHittable {
            app.swipeDown()
        }
        let finishedCard = NSPredicate { _, _ in
            skillCard.exists && skillCard.isEnabled && skillCard.isHittable
        }
        XCTAssertEqual(
            XCTWaiter.wait(
                for: [XCTNSPredicateExpectation(predicate: finishedCard, object: skillCard)],
                timeout: 20
            ),
            .completed,
            "The finished skill card must remain interactive in the response"
        )
        skillCard.tap()
        XCTAssertTrue(
            app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch.waitForExistence(timeout: 15),
            "The finished web-search card must open fullscreen"
        )
        let resultCards = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "embed-preview-"))
        let firstResult = resultCards.firstMatch
        XCTAssertTrue(firstResult.waitForExistence(timeout: 30), "Fullscreen must hydrate at least one web-search child result")
        XCTAssertFalse(
            firstResult.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            "The hydrated child result must expose nonempty content"
        )
        app.buttons["embed-minimize"].firstMatch.tap()

        let active = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-"))
            .firstMatch
        XCTAssertTrue(active.exists)
        let chatId = String(active.identifier.dropFirst("chat-view-".count))
        XCTAssertFalse(chatId.isEmpty)
        let title = app.descendants(matching: .any).matching(identifier: "chat-header-title").firstMatch
        let readyTitle = NSPredicate { _, _ in
            guard title.exists else { return false }
            let value = title.label.trimmingCharacters(in: .whitespacesAndNewlines)
            let normalized = value.lowercased()
            return !value.isEmpty && !normalized.contains("creating") && !normalized.contains("untitled")
        }
        let titleExpectation = XCTNSPredicateExpectation(predicate: readyTitle, object: title)
        XCTAssertEqual(XCTWaiter.wait(for: [titleExpectation], timeout: 60), .completed,
                       "Post-processing must replace the new-chat placeholder with a durable title")
        let summary = app.descendants(matching: .any).matching(identifier: "chat-header-summary").firstMatch
        let readySummary = NSPredicate { _, _ in
            summary.exists && !summary.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        XCTAssertEqual(
            XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: readySummary, object: summary)], timeout: 60),
            .completed,
            "Post-processing must also persist the generated chat summary before relaunch"
        )
        let persistedTitle = title.label.trimmingCharacters(in: .whitespacesAndNewlines)

        app.terminate()
        app.launchArguments.removeAll {
            ["--ui-test-disable-auth-cache", "--ui-test-open-login", "--ui-test-start-new-chat", "--ui-test-fresh-new-chat"].contains($0)
        }
        app.launch()
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app)
        let persistedRow = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatId)"
        )).firstMatch
        let history = app.scrollViews.matching(identifier: "chat-sidebar-scroll").firstMatch
        for _ in 0..<12 where !persistedRow.exists {
            let more = app.buttons["load-more-chats"]
            if more.exists && more.isHittable && history.frame.insetBy(dx: 0, dy: 35).contains(
                CGPoint(x: more.frame.midX, y: more.frame.midY)
            ) {
                more.tap()
            } else {
                history.swipeUp()
            }
        }
        XCTAssertTrue(persistedRow.waitForExistence(timeout: 10), "The web-search chat must survive relaunch")
        XCTAssertTrue(persistedRow.label.localizedCaseInsensitiveContains(persistedTitle),
                      "The generated chat title must survive relaunch; expected=\(persistedTitle), restored=\(persistedRow.label)")
        persistedRow.tap()
        XCTAssertTrue(
            RealAccountUITestSupport.accessibilityElement(
                in: app,
                identifier: "message-user",
                labelContaining: prompt
            ).waitForExistence(timeout: 25),
            "The original web-search request must survive relaunch"
        )
        let persistedCard = app.buttons.matching(identifier: "embed-preview").firstMatch
        XCTAssertTrue(persistedCard.waitForExistence(timeout: 30), "The encrypted web-search card must survive relaunch")
        persistedCard.tap()
        XCTAssertTrue(
            app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "embed-preview-"))
                .firstMatch.waitForExistence(timeout: 30),
            "Persisted fullscreen must hydrate its child results after relaunch"
        )
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,message-input.embeds.gated-send,chats.persistence.client-encrypted,chats.rendering.inline-entity-interaction
    func testPasswordOtpPhotoAttachmentSendsAndPersistsAfterRelaunch() throws {
        let prompt = "Use the image viewing skill to inspect the attached image. What single color fills it? Reply with that color."
        let filename = "quick-action-photo.png"
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: [
                "--ui-test-open-login", "--ui-test-fresh-new-chat",
                "--ui-test-expose-chat-ids", "--ui-test-photo-live-upload",
                "--ui-test-welcome-send-stage",
            ]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        let composerImage = app.descendants(matching: .any)
            .matching(identifier: "native-composer-preview-image-finished").firstMatch
        XCTAssertTrue(composerImage.waitForExistence(timeout: 15), "The photo quick-action fixture must reach the composer")
        XCTAssertTrue(app.staticTexts[filename].waitForExistence(timeout: 10), "The selected photo filename must be visible before send")
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: prompt)

        let userMessage = RealAccountUITestSupport.accessibilityElement(
            in: app,
            identifier: "message-user",
            labelContaining: prompt
        )
        XCTAssertTrue(userMessage.waitForExistence(timeout: 30), "The prompt and uploaded photo must render as the sent user message")
        let sentThumbnail = userMessage.descendants(matching: .any)
            .matching(identifier: "sent-image-thumbnail").firstMatch
        XCTAssertTrue(sentThumbnail.waitForExistence(timeout: 30), "The sent message must render the uploaded photo thumbnail")
        XCTAssertTrue(app.staticTexts[filename].waitForExistence(timeout: 20), "The sent photo must retain its filename")

        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
        let assistant = app.descendants(matching: .any).matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(assistant.waitForExistence(timeout: 20), "The image request must receive an assistant response")
        XCTAssertTrue(
            assistant.label.localizedCaseInsensitiveContains("red"),
            "The assistant must identify the red pixels in the uploaded image, proving actual image access"
        )
        let assistantSkill = assistant.descendants(matching: .button)
            .matching(identifier: "embed-preview").firstMatch
        XCTAssertTrue(
            assistantSkill.waitForExistence(timeout: 30),
            "An explicit image-view request must preserve its assistant skill content"
        )

        let active = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-"))
            .firstMatch
        XCTAssertTrue(active.exists)
        let chatId = String(active.identifier.dropFirst("chat-view-".count))
        XCTAssertFalse(chatId.isEmpty)

        app.terminate()
        app.launchArguments.removeAll {
            [
                "--ui-test-disable-auth-cache", "--ui-test-open-login", "--ui-test-start-new-chat", "--ui-test-fresh-new-chat",
                "--ui-test-photo-live-upload",
            ].contains($0)
        }
        app.launch()
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app)
        let persistedRow = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatId)"
        )).firstMatch
        let history = app.scrollViews.matching(identifier: "chat-sidebar-scroll").firstMatch
        for _ in 0..<12 where !persistedRow.exists {
            let more = app.buttons["load-more-chats"]
            if more.exists && more.isHittable && history.frame.insetBy(dx: 0, dy: 35).contains(
                CGPoint(x: more.frame.midX, y: more.frame.midY)
            ) {
                more.tap()
            } else {
                history.swipeUp()
            }
        }
        XCTAssertTrue(persistedRow.waitForExistence(timeout: 10), "The photo chat must survive relaunch")
        persistedRow.tap()
        let persistedUserMessage = RealAccountUITestSupport.accessibilityElement(
            in: app,
            identifier: "message-user",
            labelContaining: prompt
        )
        XCTAssertTrue(persistedUserMessage.waitForExistence(timeout: 25), "The sent photo message must survive relaunch")
        XCTAssertTrue(
            persistedUserMessage.descendants(matching: .any)
                .matching(identifier: "sent-image-thumbnail").firstMatch.waitForExistence(timeout: 30),
            "The uploaded photo thumbnail must hydrate after relaunch"
        )
        XCTAssertTrue(app.staticTexts[filename].waitForExistence(timeout: 20), "The persisted photo must retain its filename")
    }

    private func assertCompletionCommitted(in app: XCUIApplication, minimumVersion: Int, assistantCount: Int) {
        let probe = app.descendants(matching: .any).matching(identifier: "chat-recovery-state").firstMatch
        let committed = NSPredicate { _, _ in
            guard probe.exists, let value = probe.value as? String else { return false }
            let fields = value.split(separator: ";").reduce(into: [String: Int]()) { result, field in
                let parts = field.split(separator: "=", maxSplits: 1)
                if parts.count == 2, let number = Int(parts[1]) { result[String(parts[0])] = number }
            }
            return fields["pending"] == 0 && fields["version", default: 0] >= minimumVersion
                && fields["encrypted", default: 0] >= assistantCount
        }
        let expectation = XCTNSPredicateExpectation(predicate: committed, object: probe)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 150), .completed,
                       "The rendered reply must also reach server-acknowledged encrypted persistence, including another client's lease expiry")
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.surface.semantic-parity
    func testAppleCoreParityProof() throws {
        let credentials = try RealAccountTestCredentials.fromReservedSlot(14)
        let proofDeviceProfile = try String(contentsOfFile: "/tmp/openmates-proof-device-profile", encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        switch proofDeviceProfile {
        case "apple-iphone-portrait":
            XCUIDevice.shared.orientation = .portrait
        case "apple-ipad-landscape":
            XCUIDevice.shared.orientation = .landscapeLeft
        default:
            XCTFail("Apple proof device profile is invalid")
            return
        }
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        let captureEpochValue = try String(
            contentsOfFile: "/tmp/openmates-recording-started-unix-ms",
            encoding: .utf8
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let captureEpochMilliseconds = Double(captureEpochValue) else {
            XCTFail("Apple proof recording epoch is invalid")
            return
        }
        let started = Date(timeIntervalSince1970: captureEpochMilliseconds / 1000)
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-start-new-chat"]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        let loginReadyMs = Int(Date().timeIntervalSince(started) * 1000)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        let messageSentMs = Int(Date().timeIntervalSince(started) * 1000)
        let streamingBanner = RealAccountUITestSupport.accessibilityElement(
            in: app,
            identifier: "streaming-banner"
        )
        XCTAssertTrue(streamingBanner.waitForExistence(timeout: 30), "Expected visible processing state")
        let processingVisibleMs = Int(Date().timeIntervalSince(started) * 1000)
        let responseProgress = RealAccountUITestSupport.awaitProgressiveAssistantResponseForProof(
            app: app,
            timeout: assistantResponseTimeout
        )
        let firstChunkVisibleMs = Int(responseProgress.firstChunkVisibleAt.timeIntervalSince(started) * 1000)
        let responseVisibleMs = Int(responseProgress.completedAt.timeIntervalSince(started) * 1000)
        assertAssistantContentFitsHorizontally(in: app)
        assertAssistantUsesTranscriptWidth(in: app)
        assertFollowUpSuggestionsClearComposer(in: app)
        let responseReadyMs = Int(Date().timeIntervalSince(started) * 1000)

        attachScreenshot(name: "Apple core parity response ready")
        try attachProofTimeline(
            profile: proofDeviceProfile,
            loginReadyMs: loginReadyMs,
            messageSentMs: messageSentMs,
            processingVisibleMs: processingVisibleMs,
            firstChunkVisibleMs: firstChunkVisibleMs,
            responseVisibleMs: responseVisibleMs,
            responseReadyMs: responseReadyMs
        )
    }

    private func assertAssistantContentFitsHorizontally(in app: XCUIApplication) {
        let assistant = app.otherElements.matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(assistant.exists, "Expected an assistant message before checking its layout")
        let maximumX = assistant.frame.maxX + 1
        let overflowing = assistant.descendants(matching: .any).allElementsBoundByIndex.filter { element in
            let frame = element.frame
            return element.exists && !frame.isEmpty && frame.maxX > maximumX
        }
        XCTAssertTrue(
            overflowing.isEmpty,
            "Assistant content extended beyond its horizontal bounds: \(overflowing.map { $0.frame })"
        )
    }

    private func assertAssistantUsesTranscriptWidth(in app: XCUIApplication) {
        let history = app.otherElements["chat-history-container"]
        let assistantContent = app.descendants(matching: .any)["assistant-message-content"]
        let senderName = app.descendants(matching: .any)["message-sender-name"]
        XCTAssertTrue(history.exists)
        XCTAssertTrue(assistantContent.exists)
        XCTAssertTrue(senderName.exists)
        XCTAssertLessThanOrEqual(
            senderName.frame.minX,
            history.frame.minX + 24,
            "Assistant response was centered instead of leading-aligned"
        )
        XCTAssertGreaterThanOrEqual(
            assistantContent.frame.width,
            history.frame.width - 48,
            "Assistant response did not use the available transcript width"
        )
    }

    private func assertFollowUpSuggestionsClearComposer(in app: XCUIApplication) {
        let suggestions = app.descendants(matching: .any)["follow-up-suggestions"]
        guard suggestions.exists else { return }
        let composer = app.descendants(matching: .any)["message-editor"]
        let deadline = Date().addingTimeInterval(10)
        while suggestions.frame.maxY > composer.frame.minY + 1, Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            composer.frame.minY + 1,
            "Follow-up suggestions were covered by the fixed composer"
        )
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testPasswordOtpLoginLoadsRecentChatsForWebParityManifest() throws {
        let credentials = try parityCredentials()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        openChatsPanel(in: app)
        XCTAssertTrue(
            waitForInitialSyncComplete(in: app, timeout: 35),
            "Expected initial chat sync to complete before exporting parity manifest. Visible UI: \(visibleStateLabels(in: app))"
        )

        let rows = chatRows(in: app)
        XCTAssertTrue(
            waitForChatRows(rows, timeout: 30),
            "Expected at least one loaded chat row. Visible UI: \(visibleStateLabels(in: app))"
        )

        let manifest = makeLoadedChatsManifest(app: app, rows: rows, credentials: credentials)
        try attachAndWriteManifest(manifest)
        let openedManifest = try makeOpenedChatsManifest(app: app, rows: rows, loadedManifest: manifest, credentials: credentials)
        try attachAndWriteOpenedManifest(openedManifest)
        attachScreenshot(name: "Apple loaded chats parity")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,chats.surface.semantic-parity
    func testSignedOutAnonymousWelcomePromptCreatesChatAndReceivesAssistantResponse() async throws {
        try await requireAnonymousFreeUsageActive()

        let app = RealAccountUITestSupport.launchApp(
            preferPasswordLogin: false,
            disableAuthCache: true,
            extraArguments: ["--ui-test-start-new-chat"]
        )

        XCTAssertTrue(app.buttons["header-login-signup-btn"].waitForExistence(timeout: 15))
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: anonymousPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
    }

    private func requireAnonymousFreeUsageActive() async throws {
        let url = URL(string: "https://api.dev.openmates.org/v1/anonymous/free-usage/status")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let status = try JSONDecoder().decode(AnonymousFreeUsageProbe.self, from: data)
        guard status.active else {
            throw XCTSkip("Anonymous free usage inactive on dev: \(status.reason ?? "unknown")")
        }
    }

    private func attachProofTimeline(
        profile: String,
        loginReadyMs: Int,
        messageSentMs: Int,
        processingVisibleMs: Int,
        firstChunkVisibleMs: Int,
        responseVisibleMs: Int,
        responseReadyMs: Int
    ) throws {
        let timeline: [String: Any] = [
            "schema_version": 1,
            "device": profile,
            "contract": [
                "id": "apple-core-parity",
                "title": "Apple core chat parity",
                "surface": "apple",
                "devices": [profile],
                "transcript": [
                    ["id": "shell", "text": "The authenticated native chat shell is ready for the conversation.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "processing", "text": "A side rainbow marks active processing while the composer remains integrated with the chat background.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "first-chunk", "text": "The left-aligned assistant card appears as the first response chunk arrives.", "checkpoint": "first-chunk-visible", "devices": [profile]],
                    ["id": "chat", "text": "The same assistant card grows chunk by chunk into the completed four-sentence response.", "checkpoint": "response-visible", "devices": [profile]],
                ],
                "assertions": [
                    ["id": "auth.ready", "visual": "The authenticated native chat composer is visible.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "chat.processing_rainbow", "visual": "The processing rainbow stays on the outer chat sides and does not overlay the thinking or message content.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "chat.composer_shell", "visual": "No opaque white strip appears behind the processing status or compact composer.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "chat.progressive_response", "visual": "The assistant response is visibly shorter at first-chunk-visible than at response-visible.", "checkpoint": "first-chunk-visible", "devices": [profile]],
                    ["id": "chat.response", "visual": "The completed assistant response is left-aligned, uses the available transcript width, and appears once.", "checkpoint": "response-visible", "devices": [profile]],
                ],
            ],
            "events": [
                ["kind": "checkpoint", "id": "login-ready", "at_ms": loginReadyMs],
                ["kind": "action", "id": "send-message", "start_ms": loginReadyMs, "end_ms": messageSentMs],
                ["kind": "checkpoint", "id": "message-sent", "at_ms": messageSentMs],
                ["kind": "checkpoint", "id": "processing-visible", "at_ms": processingVisibleMs],
                ["kind": "checkpoint", "id": "first-chunk-visible", "at_ms": firstChunkVisibleMs],
                ["kind": "checkpoint", "id": "response-visible", "at_ms": responseVisibleMs],
                ["kind": "checkpoint", "id": "response-ready", "at_ms": responseReadyMs],
            ],
            "assertion_results": [
                ["id": "auth.ready", "status": "passed", "at_ms": messageSentMs],
                ["id": "chat.processing_rainbow", "status": "passed", "at_ms": processingVisibleMs],
                ["id": "chat.composer_shell", "status": "passed", "at_ms": processingVisibleMs],
                ["id": "chat.progressive_response", "status": "passed", "at_ms": firstChunkVisibleMs],
                ["id": "chat.response", "status": "passed", "at_ms": responseVisibleMs],
            ],
        ]
        let data = try JSONSerialization.data(withJSONObject: timeline, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "proof-timeline.json"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func openChatsPanel(in app: XCUIApplication, allowingSearch: Bool = false) {
        // Wait for the actual panel after tapping: during a cold relaunch the
        // startup overlay can still cover the header when sync first completes.
        let toggle = app.buttons["sidebar-toggle"]
        let panel = app.otherElements.matching(identifier: "chat-history-panel").firstMatch
        for _ in 0..<3 {
            if panel.exists && app.frame.contains(CGPoint(x: panel.frame.midX, y: panel.frame.midY)) { break }
            guard toggle.waitForExistence(timeout: 2) else { break }
            toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            if chatRows(in: app).firstMatch.waitForExistence(timeout: 3) { break }
        }
        if allowingSearch && app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch.exists { return }
        XCTAssertTrue(chatRows(in: app).firstMatch.waitForExistence(timeout: 15),
                      "Chat history did not expose account rows after opening")
    }

    private func parityCredentials() throws -> RealAccountTestCredentials {
        let slotValue = ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_ACCOUNT_SLOT"] ?? ""
        if !slotValue.isEmpty {
            guard let slot = Int(slotValue) else {
                throw XCTSkip("CHAT_RENDERING_PARITY_ACCOUNT_SLOT must be an integer from 1-20")
            }
            return try RealAccountTestCredentials.fromSlot(slot)
        }
        return try RealAccountTestCredentials.fromEnvironment()
    }

    private func chatRows(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND (value == %@ OR value BEGINSWITH %@)",
            "chat-item-wrapper", "user-chat", "user-chat:"
        ))
    }

    private func waitForChatRows(_ rows: XCUIElementQuery, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if rows.count > 0 {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < deadline
        return rows.count > 0
    }

    private func waitForInitialSyncComplete(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let marker = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@ AND value == %@", "chat-sync-complete", "true"))
            .firstMatch
        return marker.waitForExistence(timeout: timeout)
    }

    private func makeLoadedChatsManifest(app: XCUIApplication, rows: XCUIElementQuery, credentials: RealAccountTestCredentials) -> [String: Any] {
        let maxRows = Int(ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_MAX_ROWS"] ?? "40") ?? 40
        let rowCount = min(rows.count, maxRows)
        let windowFrame = app.windows.firstMatch.frame
        var chats: [[String: Any]] = []

        for index in 0..<rowCount {
            let row = rows.element(boundBy: index)
            let label = row.label.trimmingCharacters(in: .whitespacesAndNewlines)
            let title = normalizedChatTitle(from: label)
            let frame = row.frame
            chats.append([
                "index": index,
                "titleText": title,
                "titleState": titleState(for: title),
                "accessibilityLabel": label,
                "isSubChat": false,
                "pinned": label.localizedCaseInsensitiveContains("pinned"),
                "visible": row.exists && !frame.isEmpty && windowFrame.intersects(frame),
                "rect": [
                    "x": Int(frame.origin.x.rounded()),
                    "y": Int(frame.origin.y.rounded()),
                    "width": Int(frame.size.width.rounded()),
                    "height": Int(frame.size.height.rounded())
                ]
            ])
        }

        return [
            "schema_version": 1,
            "surface": "loaded-user-chats",
            "client": "apple",
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "environment": [
                "account_email_hash": stableHash(credentials.email),
                "viewport_width": Int(windowFrame.size.width.rounded()),
                "viewport_height": Int(windowFrame.size.height.rounded()),
                "max_chat_rows": maxRows
            ],
            "required_elements": [
                "chat_history_panel": RealAccountUITestSupport.accessibilityElement(in: app, identifier: "chat-history-panel").exists,
                "chat_item_wrapper": chats.contains { ($0["isSubChat"] as? Bool) == false },
                "sub_chat_item": chats.contains { ($0["isSubChat"] as? Bool) == true },
                "chat_title": chats.contains { !(($0["titleText"] as? String) ?? "").isEmpty }
            ],
            "sidebar": [
                "is_visible": RealAccountUITestSupport.accessibilityElement(in: app, identifier: "chat-history-panel").exists,
                "chat_count": chats.count
            ],
            "chats": chats
        ]
    }

    private func makeOpenedChatsManifest(
        app: XCUIApplication,
        rows: XCUIElementQuery,
        loadedManifest: [String: Any],
        credentials: RealAccountTestCredentials
    ) throws -> [String: Any] {
        let limit = Int(ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_OPENED_CHAT_LIMIT"] ?? "10") ?? 10
        let loadedChats = loadedManifest["chats"] as? [[String: Any]] ?? []
        let chatCount = min(min(rows.count, loadedChats.count), limit)
        var openedChats: [[String: Any]] = []

        for index in 0..<chatCount {
            openChatsPanel(in: app)
            let row = rows.element(boundBy: index)
            XCTAssertTrue(row.waitForExistence(timeout: 10), "Missing chat row \(index) before opened-chat parity export")
            row.tap()
            XCTAssertTrue(waitForOpenedChatMessages(in: app, timeout: 30), "Expected messages after opening chat row \(index)")
            openedChats.append(makeOpenedChatRenderState(app: app, index: index, loadedChat: loadedChats[index]))
        }

        return [
            "schema_version": 1,
            "surface": "opened-user-chats",
            "client": "apple",
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "environment": [
                "account_email_hash": stableHash(credentials.email),
                "opened_chat_limit": limit
            ],
            "sidebar": [
                "chat_count": loadedManifestValue(loadedManifest, keyPath: ["sidebar", "chat_count"]) ?? chatCount
            ],
            "opened_chats": openedChats
        ]
    }

    private func waitForOpenedChatMessages(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if messageElements(in: app).count > 0 {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < deadline
        return messageElements(in: app).count > 0
    }

    private func makeOpenedChatRenderState(app: XCUIApplication, index: Int, loadedChat: [String: Any]) -> [String: Any] {
        let messages = (0..<messageElements(in: app).count).compactMap { messageIndex -> [String: Any]? in
            let element = messageElements(in: app).element(boundBy: messageIndex)
            guard element.exists else { return nil }
            return decodeMessageRenderManifest(element: element, index: messageIndex)
        }

        return [
            "index": index,
            "titleText": loadedChat["titleText"] as? String ?? "",
            "message_count": messages.count,
            "messages": messages
        ]
    }

    private func messageElements(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier IN %@", ["message-user", "message-assistant", "message-system"])
        )
    }

    private func decodeMessageRenderManifest(element: XCUIElement, index: Int) -> [String: Any]? {
        guard let rawValue = element.value as? String,
              let data = rawValue.data(using: .utf8),
              let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return [
                "index": index,
                "role": element.identifier.replacingOccurrences(of: "message-", with: ""),
                "content_hash": stableHash(element.label.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")),
                "text_length": element.label.count,
                "block_counts": emptyBlockCounts(),
                "has_sender_name": false,
                "has_thinking": false,
                "is_streaming": false
            ]
        }

        return [
            "index": index,
            "role": decoded["role"] as? String ?? element.identifier.replacingOccurrences(of: "message-", with: ""),
            "content_hash": decoded["content_hash"] as? String ?? "",
            "text_length": decoded["text_length"] as? Int ?? 0,
            "block_counts": decoded["block_counts"] as? [String: Int] ?? emptyBlockCounts(),
            "embed_count": decoded["embed_count"] as? Int ?? 0,
            "has_sender_name": decoded["has_sender_name"] as? Bool ?? false,
            "has_thinking": decoded["has_thinking"] as? Bool ?? false,
            "is_streaming": decoded["is_streaming"] as? Bool ?? false
        ]
    }

    private func emptyBlockCounts() -> [String: Int] {
        [
            "paragraph": 0,
            "heading": 0,
            "code_block": 0,
            "blockquote": 0,
            "list": 0,
            "table": 0,
            "source_quote": 0,
            "embed_group": 0,
            "interactive_question": 0,
            "inline_code": 0
        ]
    }

    private func loadedManifestValue(_ manifest: [String: Any], keyPath: [String]) -> Int? {
        var current: Any? = manifest
        for key in keyPath {
            current = (current as? [String: Any])?[key]
        }
        return current as? Int
    }

    private func normalizedChatTitle(from label: String) -> String {
        label
            .replacingOccurrences(of: ", sub-chat", with: "")
            .replacingOccurrences(of: ", pinned", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func stableHash(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
    }

    private func titleState(for title: String) -> String {
        let normalized = title.lowercased()
        if title.isEmpty { return "empty" }
        if normalized.contains("processing") { return "processing" }
        if normalized.contains("untitled") { return "untitled" }
        return "ready"
    }

    private func attachAndWriteManifest(_ manifest: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "apple-loaded-chats-manifest.json"
        attachment.lifetime = .keepAlways
        add(attachment)

        let directory = parityArtifactDirectoryURL()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try data.write(to: directory.appendingPathComponent("apple-loaded-chats-manifest.json"))
    }

    private func attachAndWriteOpenedManifest(_ manifest: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "apple-opened-chats-manifest.json"
        attachment.lifetime = .keepAlways
        add(attachment)

        let directory = parityArtifactDirectoryURL()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try data.write(to: directory.appendingPathComponent("apple-opened-chats-manifest.json"))
    }

    private func parityArtifactDirectoryURL() -> URL {
        if let artifactDir = ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_ARTIFACT_DIR"], !artifactDir.isEmpty {
            let directory = URL(fileURLWithPath: artifactDir, isDirectory: true)
            if directory.path.hasPrefix("/") {
                return directory
            }
            return repoRootURL().appendingPathComponent(artifactDir, isDirectory: true)
        }

        return repoRootURL()
            .appendingPathComponent("artifacts", isDirectory: true)
            .appendingPathComponent("chat-rendering-parity", isDirectory: true)
    }

    private func repoRootURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = app.buttons.allElementsBoundByIndex.compactMap(elementSummary)
        let texts = app.staticTexts.allElementsBoundByIndex.compactMap(elementSummary)
        return (buttons + texts).prefix(30).joined(separator: " | ")
    }

    private func elementSummary(_ element: XCUIElement) -> String? {
        let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !identifier.isEmpty || !label.isEmpty else { return nil }
        if identifier.isEmpty { return label }
        if label.isEmpty || label == identifier { return "#\(identifier)" }
        return "#\(identifier)=\(label.contains("@") ? "<email>" : label)"
    }
}

private struct AnonymousFreeUsageProbe: Decodable {
    let active: Bool
    let reason: String?
}
