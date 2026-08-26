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
    private let markerPrompt = "Say: Kyoto neighbors Osaka."
    private let anonymousPrompt = "Anonymous native smoke test: answer with one short sentence."
    private let assistantResponseTimeout: TimeInterval = 90

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted
    func testPasswordOtpLoginCreatesChatAndReceivesAssistantResponse() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
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
        let responseVisibleAt = RealAccountUITestSupport.awaitAssistantResponseForProof(
            app: app,
            timeout: assistantResponseTimeout
        )
        let responseVisibleMs = Int(responseVisibleAt.timeIntervalSince(started) * 1000)
        assertAssistantContentFitsHorizontally(in: app)
        let responseReadyMs = Int(Date().timeIntervalSince(started) * 1000)

        attachScreenshot(name: "Apple core parity response ready")
        try attachProofTimeline(
            profile: proofDeviceProfile,
            loginReadyMs: loginReadyMs,
            messageSentMs: messageSentMs,
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
                    ["id": "shell", "text": "The authenticated native chat shell shows the sent travel prompt.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "chat", "text": "One assistant response appears below that message without duplication.", "checkpoint": "response-visible", "devices": [profile]],
                ],
                "assertions": [
                    ["id": "auth.ready", "visual": "The authenticated native chat composer is visible.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "chat.response", "visual": "The sent user message and assistant response are visible once.", "checkpoint": "response-visible", "devices": [profile]],
                ],
            ],
            "events": [
                ["kind": "checkpoint", "id": "login-ready", "at_ms": loginReadyMs],
                ["kind": "action", "id": "send-message", "start_ms": loginReadyMs, "end_ms": messageSentMs],
                ["kind": "checkpoint", "id": "message-sent", "at_ms": messageSentMs],
                ["kind": "checkpoint", "id": "response-visible", "at_ms": responseVisibleMs],
                ["kind": "checkpoint", "id": "response-ready", "at_ms": responseReadyMs],
            ],
            "assertion_results": [
                ["id": "auth.ready", "status": "passed", "at_ms": messageSentMs],
                ["id": "chat.response", "status": "passed", "at_ms": responseVisibleMs],
            ],
        ]
        let data = try JSONSerialization.data(withJSONObject: timeline, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "proof-timeline.json"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func openChatsPanel(in app: XCUIApplication) {
        let panel = RealAccountUITestSupport.accessibilityElement(in: app, identifier: "chat-history-panel")
        let rows = chatRows(in: app)
        if panel.exists && (panel.isHittable || rows.firstMatch.exists) {
            return
        }

        let toggle = RealAccountUITestSupport.accessibilityElement(in: app, identifier: "sidebar-toggle")
        XCTAssertTrue(
            toggle.waitForExistence(timeout: 10),
            "Missing sidebar-toggle. Visible UI: \(visibleStateLabels(in: app))"
        )
        toggle.tap()
        XCTAssertTrue(panel.waitForExistence(timeout: 15), "Chat history panel did not open")
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
        app.descendants(matching: .any)
            .matching(NSPredicate(
                format: "(identifier == %@ AND value == %@) OR identifier BEGINSWITH %@ OR identifier BEGINSWITH %@",
                "chat-item-wrapper",
                "user-chat",
                "welcome-chat-compact-card-",
                "welcome-chat-card-"
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
