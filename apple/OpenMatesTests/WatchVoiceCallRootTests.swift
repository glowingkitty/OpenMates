// Production Watch root support: consent cancellation and account-scoped ciphertext retention.
import XCTest
import Combine
@testable import OpenMates

@MainActor
final class WatchVoiceCallRootTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning
    func testConsentCancelAndReplacementCannotAcceptDepartedRequest() async {
        let consent = WatchVoiceCallConsent()
        let firstPresented = expectation(description: "First consent presented")
        var subscription: AnyCancellable? = consent.$isPresented.dropFirst().filter { $0 }.prefix(1)
            .sink { _ in firstPresented.fulfill() }
        let first = Task { await consent.request() }
        await fulfillment(of: [firstPresented], timeout: 2)
        first.cancel()
        let rejected = await first.value
        XCTAssertFalse(rejected); XCTAssertFalse(consent.isPresented)
        subscription?.cancel()
        let secondPresented = expectation(description: "Replacement consent presented")
        subscription = consent.$isPresented.dropFirst().filter { $0 }.prefix(1)
            .sink { _ in secondPresented.fulfill() }
        let second = Task { await consent.request() }
        await fulfillment(of: [secondPresented], timeout: 2)
        consent.finish(true)
        let accepted = await second.value
        XCTAssertTrue(accepted); XCTAssertFalse(consent.isPresented)
        subscription?.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,apple-watch.chats.input-actions
    func testScopedCallFilesRejectRevokedLeaseAndEraseOnlyDepartedAccount() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-call-storage-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let disk = WatchVoiceCallScopedDisk(directory: directory)
        let a = NativeVoiceCallScope(accountID: "account-a", profileID: "development", workspaceGeneration: UUID(),
                                     chatID: "chat", mateCategory: "general_knowledge")
        let b = NativeVoiceCallScope(accountID: "account-b", profileID: "development", workspaceGeneration: UUID(),
                                     chatID: "chat", mateCategory: "general_knowledge")
        let aLease = WatchVoiceCallStorageLease(accountID: a.accountID, profileID: a.profileID)
        let bLease = WatchVoiceCallStorageLease(accountID: b.accountID, profileID: b.profileID)
        let aStore = WatchVoiceCallAuxiliaryStorage(disk: disk, lease: aLease)
        let bStore = WatchVoiceCallAuxiliaryStorage(disk: disk, lease: bLease)
        let row = NativeVoiceCallAuxiliaryRecord(frame: ["encrypted_content": .string("ciphertext-sentinel")], confirmed: false)
        try await aStore.save(["row": row], scope: a)
        try await bStore.save(["row": row], scope: b)
        let retained = try await aStore.load(scope: a)
        XCTAssertEqual(retained["row"]?.frame["encrypted_content"]?.string, "ciphertext-sentinel")
        aLease.revoke()
        try await disk.erase(accountID: a.accountID)
        do { try await aStore.save(["row": row], scope: a); XCTFail("Departed write must fail") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        let freshLease = WatchVoiceCallStorageLease(accountID: a.accountID, profileID: a.profileID)
        let erased = try await WatchVoiceCallAuxiliaryStorage(disk: disk, lease: freshLease).load(scope: a)
        let other = try await bStore.load(scope: b)
        XCTAssertTrue(erased.isEmpty); XCTAssertEqual(other.count, 1)
        do { _ = try await bStore.load(scope: a); XCTFail("Cross-account reads must fail") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        let otherProfile = NativeVoiceCallScope(accountID: b.accountID, profileID: "production", workspaceGeneration: UUID(),
                                                chatID: "chat", mateCategory: "general_knowledge")
        do { _ = try await bStore.load(scope: otherProfile); XCTFail("Cross-profile reads must fail") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
    }
}
