import XCTest
@testable import OpenMates
@MainActor final class ModelPreferenceTransportTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testQueuedSameChatWaitsWhileDifferentChatCanStart() async throws {
        let connection = ModelPreferenceConnection(server: "dev", userID: "fixture", socketGeneration: 1)
        var entered: [String] = []
        var release: CheckedContinuation<Void, Never>?
        let firstStarted = expectation(description: "first started")
        let otherStarted = expectation(description: "other chat starts")
        let transport = ModelPreferenceSocketTransport(current: { connection }, generation: { 1 }, exchange: { _, payload, _, _ in
            let label = payload["label"] as! String; entered.append(label)
            if label == "first" { await withCheckedContinuation { release = $0; firstStarted.fulfill() } }
            if label == "other" { otherStarted.fulfill() }
            return .init(type: "chat_model_preference", fields: payload)
        })
        let first = Task { try await transport.request(connection, type: "get", payload: ["chat_id": "a", "label": "first"], events: ["chat_model_preference"], timeout: .seconds(10)) }
        await fulfillment(of: [firstStarted], timeout: 2)
        let second = Task { try await transport.request(connection, type: "get", payload: ["chat_id": "a", "label": "second"], events: ["chat_model_preference"], timeout: .seconds(10)) }
        let other = Task { try await transport.request(connection, type: "get", payload: ["chat_id": "b", "label": "other"], events: ["chat_model_preference"], timeout: .seconds(10)) }
        await fulfillment(of: [otherStarted], timeout: 2)
        XCTAssertEqual(entered, ["first", "other"])
        release?.resume(); _ = try await first.value; _ = try await second.value; _ = try await other.value
        XCTAssertEqual(entered.last, "second")
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testReplacementRejectsLatePayload() async {
        var generation = 1
        let connection = ModelPreferenceConnection(server: "dev", userID: "fixture", socketGeneration: 1)
        let transport = ModelPreferenceSocketTransport(current: { connection }, generation: { generation }, exchange: { _, _, _, _ in
            generation = 2
            return .init(type: "chat_model_preference", fields: ["chat_id": "a"])
        })
        do { _ = try await transport.request(connection, type: "get", payload: ["chat_id": "a"], events: ["chat_model_preference"], timeout: .seconds(10)); XCTFail("Expected stale reply") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .staleContext) }
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testTimeoutPropagatesAndReleasesLane() async throws {
        let connection = ModelPreferenceConnection(server: "dev", userID: "fixture", socketGeneration: 1)
        var count = 0
        let transport = ModelPreferenceSocketTransport(current: { connection }, generation: { 1 }, exchange: { _, payload, _, timeout in
            XCTAssertEqual(timeout, .seconds(10)); count += 1
            if count == 1 { throw WebSocketError.messageTimeout }
            return .init(type: "chat_model_preference", fields: payload)
        })
        do { _ = try await transport.request(connection, type: "get", payload: ["chat_id": "a"], events: [], timeout: .seconds(10)); XCTFail() } catch {}
        _ = try await transport.request(connection, type: "get", payload: ["chat_id": "a"], events: [], timeout: .seconds(10))
        XCTAssertEqual(count, 2)
    }
}
