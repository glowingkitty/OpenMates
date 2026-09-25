import XCTest
@testable import OpenMates

@MainActor
final class PendingUploadStoreTests: XCTestCase {
    override func tearDown() {
        PendingUploadStore.shared.clearAll()
        super.tearDown()
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testFailedRecordingUploadKeepsDeferredSendQueuedUntilRetryFinishes() {
        let store = PendingUploadStore.shared
        let chatID = "failed-recording-chat"
        let uploadID = "failed-recording-upload"
        var dispatchCount = 0
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingDeferredSendRequested,
            object: nil,
            queue: nil
        ) { notification in
            guard notification.userInfo?["chatId"] as? String == chatID else { return }
            dispatchCount += 1
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        store.startUpload(id: uploadID, chatId: chatID, filename: "recording.m4a")
        store.addPendingSend(
            chatId: chatID,
            content: "",
            blockingUploadIds: [uploadID]
        )

        store.markError(id: uploadID, message: "Upload failed")

        XCTAssertEqual(dispatchCount, 0)
        XCTAssertTrue(store.hasActiveUploads(chatId: chatID), "A failed blocker must not let a second Send bypass it")
        XCTAssertTrue(store.hasPendingSends(chatId: chatID))
        XCTAssertEqual(store.uploadsForChat(chatID).first?.status, .error("Upload failed"))

        store.startUpload(id: uploadID, chatId: chatID, filename: "recording.m4a")
        store.markFinished(id: uploadID)

        XCTAssertEqual(dispatchCount, 1)
        XCTAssertFalse(store.hasPendingSends(chatId: chatID))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testRemovingFailedEmbedCancelsEveryQueuedSendItBlocked() {
        let store = PendingUploadStore.shared
        let chatID = "removed-failed-embed-chat"
        let uploadID = "removed-failed-embed-upload"
        var dispatchCount = 0
        let observer = NotificationCenter.default.addObserver(
            forName: .pendingDeferredSendRequested,
            object: nil,
            queue: nil
        ) { _ in dispatchCount += 1 }
        defer { NotificationCenter.default.removeObserver(observer) }

        store.startUpload(id: uploadID, chatId: chatID, filename: "image.png")
        store.addPendingSend(chatId: chatID, content: "first", blockingUploadIds: [uploadID])
        store.markError(id: uploadID, message: "Upload failed")
        store.addPendingSend(chatId: chatID, content: "second", blockingUploadIds: [uploadID])

        store.cancelUpload(id: uploadID)

        XCTAssertFalse(store.hasActiveUploads(chatId: chatID))
        XCTAssertFalse(store.hasPendingSends(chatId: chatID))
        XCTAssertEqual(dispatchCount, 0)
    }
}
