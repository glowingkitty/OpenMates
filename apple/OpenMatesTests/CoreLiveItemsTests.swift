// Tests of the Swift side of live collaboration (Core/CoreBridge/CoreLiveItems.swift):
// the file outbox store's compare-and-put and which socket frames reach the core.
// The core's own protocol behaviour is covered by the crate tests.
import Foundation
import XCTest
@testable import OpenMates

final class CoreLiveItemsTests: XCTestCase {
    private var directory: URL!

    override func setUp() {
        super.setUp()
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("live-outbox-\(UUID().uuidString)")
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: directory)
        super.tearDown()
    }

    // contract-test: supporting surface=gui.apple assertions=live-collab.offline.merge-on-reconnect
    func testCompareAndPutWritesOnlyWhenExpectedMatches() {
        let store = LiveOutboxFileStore(directory: directory)
        XCTAssertEqual(store.compareAndPut(key: "q/a b", expected: "x", next: "1"), .conflict)
        XCTAssertEqual(store.compareAndPut(key: "q/a b", expected: nil, next: "1"), .written)
        XCTAssertEqual(store.compareAndPut(key: "q/a b", expected: nil, next: "2"), .conflict)
        XCTAssertEqual(store.read(key: "q/a b"), .found(value: "1"))
        XCTAssertEqual(store.compareAndPut(key: "q/a b", expected: "1", next: "2"), .written)
        XCTAssertEqual(store.read(key: "q/a b"), .found(value: "2"))
    }

    // contract-test: supporting surface=gui.apple assertions=live-collab.offline.merge-on-reconnect
    func testCompareAndPutDeletesAndKeysFilterByPrefix() {
        let store = LiveOutboxFileStore(directory: directory)
        XCTAssertEqual(store.keys(prefix: "q/"), [])
        _ = store.compareAndPut(key: "q/1", expected: nil, next: "a")
        _ = store.compareAndPut(key: "q/2", expected: nil, next: "b")
        _ = store.compareAndPut(key: "other", expected: nil, next: "c")
        XCTAssertEqual(store.keys(prefix: "q/"), ["q/1", "q/2"])
        XCTAssertEqual(store.compareAndPut(key: "q/1", expected: "a", next: nil), .written)
        XCTAssertEqual(store.read(key: "q/1"), .missing)
        XCTAssertEqual(store.compareAndPut(key: "q/2", expected: "wrong", next: nil), .conflict)
        XCTAssertEqual(store.keys(prefix: "q/"), ["q/2"])
    }

    // contract-test: supporting surface=gui.apple assertions=live-collab.core.one-shared-model
    func testOnlyLiveFramesAreRoutedToTheCore() {
        XCTAssertTrue(CoreLiveItems.routes("live_item_state"))
        XCTAssertTrue(CoreLiveItems.routes("live_item_update"))
        XCTAssertFalse(CoreLiveItems.routes("chat_message_confirmed"))
        XCTAssertFalse(CoreLiveItems.routes("error"))
    }

    // contract-test: supporting surface=gui.apple assertions=live-collab.core.one-shared-model
    func testPayloadIsExtractedFromTheFrame() {
        let frame = Data(#"{"type":"live_item_state","payload":{"item_id":"i1"}}"#.utf8)
        XCTAssertEqual(CoreLiveItems.payloadJSON(fromFrame: frame), #"{"item_id":"i1"}"#)
        XCTAssertEqual(CoreLiveItems.payloadJSON(fromFrame: Data(#"{"type":"x"}"#.utf8)), "{}")
    }
}
