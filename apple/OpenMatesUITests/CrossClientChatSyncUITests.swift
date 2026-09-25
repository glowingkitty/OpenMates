// Cross-client producer and consumer UI-test scaffold.
// Reads only opaque run manifests supplied by the test control plane.
// Producer manifests retain only opaque chat/run identifiers and timestamps;
// credentials, keys, tokens, prompts, and response bodies are never recorded.
// Requires a clean app container for producer-consumer isolation.

import Foundation
import XCTest

@MainActor
final class CrossClientChatSyncUITests: XCTestCase {
    private let timeout: TimeInterval = 120

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testWebAndCliProducerChatsHydrateOnFreshAppleStore() throws {
        let control = try controlPlane()
        let web = try readManifest(control, name: "web-producer")
        let cli = try readManifest(control, name: "cli-producer")
        let credentials = try RealAccountTestCredentials.fromReservedSlot(14)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true, extraArguments: ["--ui-test-expose-chat-ids"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)

        try assertProducerChatVisible(app: app, manifest: web)
        try assertProducerChatVisible(app: app, manifest: cli)
        try writeManifest(control, name: "apple-consumer", value: [
            "schema_version": 1, "run_id": control.runId, "consumer": "apple",
            "web_chat_id": web["chat_id"] as Any, "cli_chat_id": cli["chat_id"] as Any,
            "consumed_at": ISO8601DateFormatter().string(from: Date())
        ])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent,chats.surface.semantic-parity
    func testAppleCreatedChatProducesConsumerManifest() throws {
        let control = try controlPlane()
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        let marker = "Apple parity Apple web search \(control.runId)"
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true, extraArguments: ["--ui-test-fresh-new-chat", "--ui-test-expose-chat-ids"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(
            app: app,
            prompt: "\(marker). Search the web for the OpenMates official website and summarize the top two results."
        )
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: timeout)

        let title = app.descendants(matching: .any).matching(identifier: "chat-header-title").firstMatch
        let summary = app.descendants(matching: .any).matching(identifier: "chat-header-summary").firstMatch
        XCTAssertTrue(waitForGeneratedMetadata(title: title, summary: summary),
                      "The Apple-created chat must finish title and summary generation before cross-client verification")

        let skillCard = app.buttons.matching(identifier: "embed-preview").firstMatch
        XCTAssertTrue(skillCard.waitForExistence(timeout: timeout),
                      "The Apple-created assistant response must retain its finished web-search skill card")
        XCTAssertTrue(skillCard.label.localizedCaseInsensitiveContains("search"))
        for _ in 0..<12 where skillCard.exists && !skillCard.isHittable {
            app.swipeDown()
        }
        XCTAssertTrue(skillCard.isHittable, "The finished web-search card must be reachable in chat history")
        skillCard.tap()
        XCTAssertTrue(app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch.waitForExistence(timeout: 15))
        let firstChild = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "embed-preview-")
        ).firstMatch
        XCTAssertTrue(firstChild.waitForExistence(timeout: timeout),
                      "The Apple-created web-search skill must hydrate at least one child result")
        XCTAssertFalse(firstChild.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        app.buttons["embed-minimize"].firstMatch.tap()

        guard let chatId = selectedChatID(in: app) else { XCTFail("Active chat view did not expose an opaque chat ID"); return }
        try writeManifest(control, name: "apple-producer", value: [
            "schema_version": 1, "run_id": control.runId, "producer": "apple",
            "chat_id": chatId,
            "created_at": ISO8601DateFormatter().string(from: Date())
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.status.incomplete-window-rewarms,sync.deletion.partial-window-not-authoritative,chats.local-state.precedence,chat-navigation.open.local-first-coherent
    func testColdBootAndRapidNavigationRemainSelected() throws {
        let control = try controlPlane()
        let web = try readManifest(control, name: "web-producer")
        let cli = try readManifest(control, name: "cli-producer")
        guard let webId = web["chat_id"] as? String, let cliId = cli["chat_id"] as? String else {
            XCTFail("Producer manifests require opaque chat IDs")
            return
        }
        let credentials = try RealAccountTestCredentials.fromReservedSlot(14)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true, extraArguments: ["--ui-test-expose-chat-ids"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        try selectChat(app: app, chatId: webId)
        app.terminate()
        app.launch()
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        try selectChat(app: app, chatId: webId)
        try selectChat(app: app, chatId: cliId)
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "chat-view-\(cliId)").firstMatch.waitForExistence(timeout: timeout))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.status.incomplete-window-rewarms,sync.deletion.partial-window-not-authoritative,chats.local-state.precedence
    func testReconnectTransportControlsRequired() throws {
        throw XCTSkip("Requires test-only transport controls for restart, reconnect, and delayed hydration; existing UI infrastructure cannot safely induce those states without product instrumentation")
    }

    private func assertProducerChatVisible(app: XCUIApplication, manifest: [String: Any]) throws {
        guard let chatId = manifest["chat_id"] as? String, !chatId.isEmpty else {
            XCTFail("Producer manifest has no opaque chat ID")
            return
        }
        try selectChat(app: app, chatId: chatId)
        let activeChat = app.descendants(matching: .any).matching(identifier: "chat-view-\(chatId)").firstMatch
        XCTAssertTrue(activeChat.waitForExistence(timeout: timeout), "Producer chat did not hydrate")
        XCTAssertGreaterThan(app.descendants(matching: .any).matching(identifier: "message-user").count, 0)
        XCTAssertGreaterThan(app.descendants(matching: .any).matching(identifier: "message-assistant").count, 0)
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@ OR label CONTAINS[c] %@", "ciphertext", "encrypted_content")).firstMatch.exists)
    }

    private func selectedChatID(in app: XCUIApplication) -> String? {
        let active = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-")).firstMatch
        guard active.exists else { return nil }
        return active.identifier.replacingOccurrences(of: "chat-view-", with: "")
    }

    private func waitForGeneratedMetadata(title: XCUIElement, summary: XCUIElement) -> Bool {
        let ready = NSPredicate { _, _ in
            guard title.exists, summary.exists else { return false }
            let titleText = title.label.trimmingCharacters(in: .whitespacesAndNewlines)
            let summaryText = summary.label.trimmingCharacters(in: .whitespacesAndNewlines)
            let normalizedTitle = titleText.lowercased()
            return !titleText.isEmpty
                && !summaryText.isEmpty
                && !normalizedTitle.contains("creating")
                && !normalizedTitle.contains("untitled")
        }
        return XCTWaiter.wait(
            for: [XCTNSPredicateExpectation(predicate: ready, object: title)],
            timeout: timeout
        ) == .completed
    }

    private func selectChat(app: XCUIApplication, chatId: String) throws {
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatId)")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: timeout), "Producer chat shell did not appear")
        row.tap()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "chat-view-\(chatId)").firstMatch.waitForExistence(timeout: timeout))
    }

    private func controlPlane() throws -> (runId: String, directory: URL) {
        let environment = ProcessInfo.processInfo.environment
        let sourceRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
        let controlURL = sourceRoot.appendingPathComponent(".openmates-cross-client-control.json")
        let localControl = (try? Data(contentsOf: controlURL)).flatMap {
            try? JSONSerialization.jsonObject(with: $0) as? [String: String]
        } ?? [:]
        guard let runId = environment["APPLE_CROSS_CLIENT_RUN_ID"] ?? localControl["run_id"], !runId.isEmpty,
              let path = environment["APPLE_CROSS_CLIENT_ARTIFACT_DIR"] ?? localControl["artifact_dir"], !path.isEmpty else {
            throw XCTSkip("Cross-client control-plane environment is unavailable")
        }
        return (runId, URL(fileURLWithPath: path, isDirectory: true))
    }

    private func readManifest(_ control: (runId: String, directory: URL), name: String) throws -> [String: Any] {
        let data = try Data(contentsOf: manifestURL(control, name: name))
        let manifest = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard manifest["run_id"] as? String == control.runId else {
            XCTFail("Control-plane manifest run ID does not match")
            return [:]
        }
        return manifest
    }

    private func writeManifest(_ control: (runId: String, directory: URL), name: String, value: [String: Any]) throws {
        try FileManager.default.createDirectory(at: control.directory, withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "apple-cross-client-\(name).json"
        attachment.lifetime = .keepAlways
        add(attachment)
        try data.write(to: manifestURL(control, name: name), options: .atomic)
    }

    private func manifestURL(_ control: (runId: String, directory: URL), name: String) -> URL {
        control.directory.appendingPathComponent("apple-cross-client-\(control.runId)-\(name).json")
    }
}
