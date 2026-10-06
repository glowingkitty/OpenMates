import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ControlProjectsTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-controls.project,apple-controls.private-cache
    func testCiphertextAndOwnerFenceRejectDeletedOrForeignConfiguredProject() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "ControlProjectsTests." + UUID().uuidString))
        let key = SymmetricKey(size: .bits256)
        let store = ControlProjectsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: {})
        defer { store.clear() }
        let owner = String(repeating: "a", count: 64)
        store.activate(owner: owner)
        try store.save(.init(owner: owner, teamID: nil, projects: [.init(id: "project-1", title: "Private project")]))
        let route = ControlProjectRoute(identifier: owner + ":project-1")
        XCTAssertEqual(ControlProjectRoute.parse(try XCTUnwrap(route.url)), route)
        XCTAssertEqual(route.project(in: try XCTUnwrap(store.load()))?.id, "project-1")
        let bytes = try XCTUnwrap(defaults.data(forKey: "control_projects_ciphertext"))
        XCTAssertFalse(String(decoding: bytes, as: UTF8.self).contains("Private project"))
        try store.save(.init(owner: owner, teamID: nil, projects: []))
        XCTAssertNil(route.project(in: try XCTUnwrap(store.load())))
        store.activate(owner: String(repeating: "b", count: 64))
        XCTAssertNil(store.load())
        XCTAssertNil(defaults.data(forKey: "control_projects_ciphertext"))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-controls.project,apple-controls.private-cache
    func testProjectRouteCannotFallThroughToChatAndReplacementClearsPending() throws {
        let handler = DeepLinkHandler()
        let route = ControlProjectRoute(identifier: String(repeating: "a", count: 64) + ":project-1")
        handler.handle(url: try XCTUnwrap(route.url))
        XCTAssertEqual(handler.pendingControlProject, route)
        XCTAssertNil(handler.pendingChatId)
        handler.handle(url: URL(string: "openmates://new-chat")!)
        XCTAssertNil(handler.pendingControlProject)
        handler.handle(url: URL(string: "openmates://control-project?target=invalid")!)
        XCTAssertNil(handler.pendingControlProject)
        XCTAssertNil(handler.pendingChatId)
        XCTAssertNil(ControlProjectRoute.parse(URL(string: "openmates://control-project?target=a&target=b")!))
        handler.handle(url: URL(string: "openmates://projects")!)
        XCTAssertTrue(handler.pendingProjectsWorkspace)
        handler.clearPending()
        XCTAssertFalse(handler.pendingProjectsWorkspace)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-controls.project
    func testPendingRouteSurvivesSuspendedDetailLoadingAndReplacementWins() async throws {
        var pending: String? = "selected"
        var detailLoaded = false
        var continuation: CheckedContinuation<Void, Never>?
        let delivery = Task {
            await ControlProjectNavigation.selectAndComplete(isCurrent: { pending == "selected" }, select: {
                await withCheckedContinuation { continuation = $0 }
                detailLoaded = true
            }, complete: { pending = nil })
        }
        for _ in 0..<20 where continuation == nil { await Task.yield() }
        XCTAssertNotNil(continuation)
        XCTAssertEqual(pending, "selected", "The SwiftUI task identity must remain intact while detail loading suspends")
        XCTAssertFalse(detailLoaded)
        continuation?.resume(); continuation = nil
        await delivery.value
        XCTAssertTrue(detailLoaded)
        XCTAssertNil(pending)

        pending = "selected"; detailLoaded = false
        let replacement = Task {
            await ControlProjectNavigation.selectAndComplete(isCurrent: { pending == "selected" }, select: {
                await withCheckedContinuation { continuation = $0 }
                detailLoaded = true
            }, complete: { pending = nil })
        }
        for _ in 0..<20 where continuation == nil { await Task.yield() }
        XCTAssertNotNil(continuation)
        pending = "replacement"
        continuation?.resume(); continuation = nil
        await replacement.value
        XCTAssertEqual(pending, "replacement", "An old selected detail cannot consume a newer route")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-controls.quick-actions
    func testControlsDeliverEveryExistingQuickActionThroughColdLaunchQueue() async throws {
        for raw in ["ask", "newTask", "recordRequest", "askAboutPhoto", "search", "incognitoAsk"] {
            _ = try await OpenMatesQuickControlIntent(action: raw).perform()
            XCTAssertEqual(AppQuickActionCenter.shared.consumePendingAction(), AppQuickAction(rawValue: raw))
        }
    }
}
