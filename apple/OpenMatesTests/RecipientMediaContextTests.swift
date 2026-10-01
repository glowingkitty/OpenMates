// Synthetic anonymous media transport/export tests. No owner account or networking.
import AVFoundation
import CryptoKit
import XCTest
import ZIPFoundation
@testable import OpenMates

@MainActor
final class RecipientMediaContextTests: XCTestCase {
    private let link = URL(string: "https://app.dev.openmates.org/share/chat/synthetic#key=abc")!
    private let mediaURL = URL(string: "https://chatfiles.nbg1.your-objectstorage.com/synthetic.enc?signature=fixture")!

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testAnonymousSessionAndURLSafetyBoundaries() {
        let config = RecipientMediaTransport.configuration()
        XCTAssertNil(config.httpCookieStorage)
        XCTAssertNil(config.urlCredentialStorage)
        XCTAssertNil(config.urlCache)
        XCTAssertFalse(config.httpShouldSetCookies)
        XCTAssertEqual(config.requestCachePolicy, .reloadIgnoringLocalCacheData)
        for value in ["http://media.example.org/file", "https://owner:secret@media.example.org/file",
                      "https://media.example.org:443/file", "https://media.example.org/file#secret",
                      "https://127.0.0.1/file", "https://[::1]/file", "https://localhost/file",
                      "https://device.local/file", "file:///private/file"] {
            XCTAssertFalse(RecipientMediaTransport.allowed(URL(string: value)!))
        }
        XCTAssertTrue(RecipientMediaTransport.allowed(mediaURL))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testEncryptedOriginalExportUsesSelectedAPIAndNoSharedCache() async throws {
        let plaintext = Data("synthetic original media".utf8)
        let key = Data(repeating: 13, count: 32)
        let encrypted = try AES.GCM.seal(plaintext, using: SymmetricKey(data: key)).combined!
        let recorder = RecipientMediaRequests()
        let target = mediaURL
        let context = try RecipientMediaContext(linkURL: link, requestLoader: { request in
            await recorder.append(request)
            let url = request.url!
            let bytes = url.path == "/v1/embeds/presigned-url"
                ? try JSONSerialization.data(withJSONObject: ["url": target.absoluteString]) : encrypted
            return (bytes, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        defer { context.cancel() }
        let embed = try record(type: "image", payload: ["filename": "original.png", "aes_key": key.base64EncodedString(),
            "files": ["original": ["s3_key": "synthetic&encoded=key", "format": "png", "encryption": S3MediaClient.noncePrefixedEncryption]]])
        for _ in 0..<2 {
            let exported = try await ChatSettingsExport.file(embed, scope: nil, recipientContext: context)
            XCTAssertEqual(exported.data, plaintext)
            XCTAssertEqual(exported.filename, "original.png")
        }
        let requests = await recorder.snapshot()
        // A second export performs a second isolated download rather than reading
        // either shared memory or the shared persistent decrypted-media cache.
        XCTAssertEqual(requests.count, 4)
        XCTAssertEqual(requests[0].url?.host, "api.dev.openmates.org")
        XCTAssertEqual(requests[2].url?.host, "api.dev.openmates.org")
        XCTAssertEqual(URLComponents(url: requests[0].url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value,
                       "synthetic&encoded=key")
        XCTAssertTrue(requests.allSatisfy { $0.value(forHTTPHeaderField: "Authorization") == nil &&
            $0.value(forHTTPHeaderField: "Cookie") == nil && $0.value(forHTTPHeaderField: "Referer") == nil &&
            !$0.httpShouldHandleCookies && $0.url?.fragment == nil })
        let other = try RecipientMediaContext(linkURL: URL(string: "https://openmates.org/share/chat/synthetic#key=abc")!)
        XCTAssertEqual(other.apiBaseURL.host, "api.openmates.org")
        XCTAssertEqual(context.webBaseURL.host, "app.dev.openmates.org")
        XCTAssertEqual(context.resolvedPublicURL("/preview/video.mp4")?.host, "app.dev.openmates.org")
        XCTAssertEqual(other.resolvedPublicURL("/preview/video.mp4")?.host, "openmates.org")
        XCTAssertNil(context.resolvedPublicURL("http://unsafe.example/video.mp4"))
        XCTAssertNotEqual(other.namespace, context.namespace)
        other.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testLateResponseCannotReturnPlaintextAfterPresentationChanges() async throws {
        let gate = RecipientMediaGate()
        let key = Data(repeating: 11, count: 32)
        let encrypted = try AES.GCM.seal(Data("late plaintext".utf8), using: SymmetricKey(data: key)).combined!
        var current = true
        let context = try RecipientMediaContext(linkURL: link, isCurrent: { current }, requestLoader: { request in
            await gate.block()
            return (encrypted, HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        let url = mediaURL.absoluteString
        let task = Task { try await context.fetchAndDecrypt(s3Url: url, aesKeyHex: key.base64EncodedString(),
                        aesNonceHex: nil, encryption: S3MediaClient.noncePrefixedEncryption) }
        await gate.waitUntilStarted()
        current = false
        await gate.release()
        do { _ = try await task.value; XCTFail("Replaced presentation returned plaintext") }
        catch { XCTAssertTrue(error is CancellationError) }
        context.cancel()
        XCTAssertThrowsError(try context.checkCurrent())
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testPreviewProxyRefererIsOnlySelectedShareOriginAtExactEndpoints() async throws {
        let requests = RecipientMediaRequests()
        let context = try RecipientMediaContext(linkURL: link, requestLoader: { request in
            await requests.append(request)
            return (Data([1]), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        defer { context.cancel() }
        let values = [
            "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.org%2Fimage",
            "https://preview.openmates.org/api/v1/favicon?url=https%3A%2F%2Fexample.org",
            "https://preview.openmates.org/api/v1/youtube?url=https%3A%2F%2Fyoutu.be%2Fsynthetic",
            "https://preview.openmates.org/api/v1/image/other",
            "https://preview.openmates.org/other/api/v1/image",
            "https://other.example.org/api/v1/image",
            "https://api.dev.openmates.org/v1/wikipedia/summary?title=Synthetic",
            "https://chatfiles.nbg1.your-objectstorage.com/synthetic.enc"
        ]
        for value in values { _ = try await context.download(URL(string: value)!) }
        let captured = await requests.snapshot()
        XCTAssertEqual(captured.count, values.count)
        for request in captured.prefix(3) {
            XCTAssertEqual(request.value(forHTTPHeaderField: "Referer"), "https://app.dev.openmates.org/")
            XCTAssertFalse(request.value(forHTTPHeaderField: "Referer")!.contains("synthetic"))
            XCTAssertFalse(request.value(forHTTPHeaderField: "Referer")!.contains("key="))
        }
        XCTAssertTrue(captured.dropFirst(3).allSatisfy { $0.value(forHTTPHeaderField: "Referer") == nil })
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testPublicVideoUsesAnonymousTransportMemoryAssetAndCancellation() async throws {
        let requests = RecipientMediaRequests()
        let context = try RecipientMediaContext(linkURL: link, requestLoader: { request in
            await requests.append(request)
            return (Data("synthetic-video-buffer".utf8), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        let url = try XCTUnwrap(context.resolvedPublicURL("/preview/synthetic-video.mp4"))
        let player = try await context.player(url: url)
        let captured = await requests.snapshot()
        XCTAssertEqual(captured.map(\.url), [url])
        XCTAssertNil(captured.first?.value(forHTTPHeaderField: "Authorization"))
        XCTAssertEqual((player.currentItem?.asset as? AVURLAsset)?.url.scheme, "openmates-recipient-media")
        context.cancel()
        XCTAssertNil(player.currentItem)
        do { _ = try await context.player(url: url); XCTFail("Cancelled scope allowed video playback") }
        catch { XCTAssertTrue(error is CancellationError) }
        let afterCancellation = await requests.snapshot()
        XCTAssertEqual(afterCancellation.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testRejectsRedirectedAndOversizedPresignedResponses() async throws {
        let target = mediaURL
        let redirected = try RecipientMediaContext(linkURL: link, requestLoader: { _ in
            (Data(), HTTPURLResponse(url: target, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        do { _ = try await redirected.fetchAndDecrypt(s3Url: "", aesKeyHex: "", aesNonceHex: nil, s3Key: "key"); XCTFail("Redirect accepted") }
        catch { XCTAssertEqual((error as? URLError)?.code, .badServerResponse) }
        redirected.cancel()
        let oversized = try RecipientMediaContext(linkURL: link, requestLoader: { request in
            (Data(repeating: 0, count: 65_537), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        })
        do { _ = try await oversized.fetchAndDecrypt(s3Url: "", aesKeyHex: "", aesNonceHex: nil, s3Key: "key"); XCTFail("Oversized metadata accepted") }
        catch { XCTAssertEqual((error as? URLError)?.code, .dataLengthExceedsMaximum) }
        oversized.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.readonly-viewer-controls
    func testInlineCodeSheetAndZipExportWithoutOwnerScopeOrNetwork() async throws {
        let context = try RecipientMediaContext(linkURL: link, requestLoader: { _ in
            throw URLError(.notConnectedToInternet)
        })
        let code = try record(type: "code-code", payload: ["filename": "../script.py", "language": "python", "code": "print(7)"])
        let sheet = try record(type: "sheets-sheet", payload: ["title": "table", "table": "| Name | Value |\n| --- | --- |\n| Synthetic | 7 |"])
        let exportedCode = try await ChatSettingsExport.file(code, scope: nil, recipientContext: context)
        XCTAssertEqual(exportedCode.filename, "script.py")
        XCTAssertEqual(String(decoding: exportedCode.data, as: UTF8.self), "print(7)")
        let exportedSheet = try await ChatSettingsExport.file(sheet, scope: nil, recipientContext: context)
        XCTAssertEqual(exportedSheet.filename, "table.xlsx")
        let workbook = try Archive(data: exportedSheet.data, accessMode: .read)
        XCTAssertNotNil(workbook["xl/worksheets/sheet1.xml"])
        let chat = Chat(id: "synthetic", title: "Synthetic", lastMessageAt: nil, createdAt: "2026-01-01", updatedAt: nil,
                        isArchived: false, isPinned: false, appId: nil, encryptedTitle: nil, encryptedChatKey: nil)
        let zipped = try await ChatSettingsExport.zip(chat: chat, messages: [], embeds: [code, sheet], scope: nil,
                                                      recipientContext: context, check: { try context.checkCurrent() })
        let archive = try Archive(data: zipped, accessMode: .read)
        XCTAssertNotNil(archive["chat.yaml"])
        XCTAssertNotNil(archive["chat.md"])
        XCTAssertNotNil(archive["script.py"])
        XCTAssertNotNil(archive["table.xlsx"])
        context.cancel()
        do { _ = try await ChatSettingsExport.file(code, scope: nil, recipientContext: context); XCTFail("Cancelled inline export accepted") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    private func record(type: String, payload: [String: Any]) throws -> EmbedRecord {
        try JSONDecoder().decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject:
            ["id": "synthetic-\(type)", "type": type, "status": "finished", "data": payload]))
    }
}

private actor RecipientMediaRequests {
    private var requests: [URLRequest] = []
    func append(_ request: URLRequest) { requests.append(request) }
    func snapshot() -> [URLRequest] { requests }
}

private actor RecipientMediaGate {
    private var started = false
    private var observer: CheckedContinuation<Void, Never>?
    private var blocked: CheckedContinuation<Void, Never>?
    func block() async {
        started = true
        observer?.resume(); observer = nil
        await withCheckedContinuation { blocked = $0 }
    }
    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { observer = $0 }
    }
    func release() { blocked?.resume(); blocked = nil }
}
