// Focused data and privacy checks for the native document page renderer.

import CryptoKit
import XCTest
@testable import OpenMates

final class DocumentCanvasTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testGeneratedPagesStayOrderedAndInlineOnly() {
        let svg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3C%2Fsvg%3E"
        let source = DocumentCanvasSource(data: [
            "preview_page_urls": AnyCodable([
                "2": svg,
                "1": "https://example.org/private-page.png",
                "3": "data:image/png;base64,aGVsbG8="
            ]),
            "html": AnyCodable("<h1>Legacy</h1>")
        ])
        XCTAssertEqual(source.pageURLs, [svg, "data:image/png;base64,aGVsbG8="])
        XCTAssertFalse(DocumentCanvasSource.isAllowedPageURL("file:///tmp/private.png"))
        XCTAssertFalse(DocumentCanvasSource.isAllowedPageURL("javascript:alert(1)"))
        XCTAssertFalse(DocumentCanvasSource.isAllowedPageURL("data:image/svg+xml;charset=utf-8,%3Csvg%20onload%3D%22alert(1)%22%3E%3C%2Fsvg%3E"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testLegacyHTMLPreservesStructureWithoutScriptsOrExternalResources() {
        let source = DocumentCanvasSource(data: [
            "html": AnyCodable("""
                <h1 class="x" onclick="alert(1)">Report</h1>
                <script>fetch('https://example.org/leak')</script>
                <p style="background:url(https://example.org/leak)">Safe <strong>text</strong></p>
                <img src="https://example.org/private.png">
                """)
        ])
        let rendered = source.documentHTML(preview: false, scale: 0.38)
        XCTAssertTrue(rendered.contains("<h1>Report</h1>"))
        XCTAssertTrue(rendered.contains("<strong>text</strong>"))
        XCTAssertFalse(rendered.contains("onclick"))
        XCTAssertFalse(rendered.contains("example.org"))
        XCTAssertFalse(rendered.contains("<script"))
        XCTAssertTrue(rendered.contains("default-src 'none'"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testPreviewRendersOnlyFirstGeneratedPage() {
        let source = DocumentCanvasSource(data: [
            "preview_page_urls": AnyCodable([
                "1": "data:image/png;base64,YQ==",
                "2": "data:image/png;base64,Yg=="
            ])
        ])
        let preview = source.documentHTML(preview: true, scale: 0.32)
        let fullscreen = source.documentHTML(preview: false, scale: 0.38)
        XCTAssertTrue(preview.contains("YQ=="))
        XCTAssertFalse(preview.contains("Yg=="))
        XCTAssertTrue(fullscreen.contains("Yg=="))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testEncryptedPageKeysAreOrderedWithoutBecomingWebResources() {
        let source = DocumentCanvasSource(data: [
            "screenshot_s3_keys": AnyCodable([
                "2": "private/chat/page-2.png.enc",
                "1": "private/chat/page-1.png.enc"
            ]),
            "aes_key": AnyCodable("base64-key"),
            "html": AnyCodable("<p>Legacy fallback</p>")
        ])
        XCTAssertEqual(source.encryptedPageKeys, [
            "private/chat/page-1.png.enc", "private/chat/page-2.png.enc"
        ])
        let loading = source.documentHTML(preview: false, scale: 0.4)
        XCTAssertFalse(loading.contains("private/chat"))
        XCTAssertFalse(loading.contains("base64-key"))
        XCTAssertFalse(loading.contains("Legacy fallback"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testPrivateDocumentFetchNeverReadsOrWritesDecryptedDiskCache() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("document-cache-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let disk = MediaDiskCache(directoryName: "private-documents", baseDirectory: root)
        let keyData = Data((0..<32).map(UInt8.init))
        let nonceData = Data((0..<12).map(UInt8.init))
        let plaintext = Data([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3])
        let sealed = try AES.GCM.seal(
            plaintext,
            using: SymmetricKey(data: keyData),
            nonce: AES.GCM.Nonce(data: nonceData)
        )
        let encrypted = nonceData + sealed.ciphertext + sealed.tag
        let client = S3MediaClient(diskCache: disk, encryptedDataLoader: { _, _ in encrypted })
        let mediaKey = "private/chat/page-1.png.enc"
        let cacheKey = S3MediaClient.cacheKey(
            s3Url: "", aesKey: keyData.base64EncodedString(), nonce: nil,
            encryption: S3MediaClient.noncePrefixedEncryption,
            s3Key: mediaKey, namespace: "account-scope"
        )
        let stalePlaintext = Data("previous disk plaintext".utf8)
        try disk.save(stalePlaintext, cacheKey: cacheKey)

        let first = try await client.fetchAndDecrypt(
            s3Url: "", aesKeyHex: keyData.base64EncodedString(), aesNonceHex: nil,
            encryption: S3MediaClient.noncePrefixedEncryption,
            s3Key: mediaKey, cacheNamespace: "account-scope",
            cachePolicy: .memoryOnly
        )
        XCTAssertEqual(first, plaintext, "Memory-only fetch must bypass an existing disk entry")
        XCTAssertEqual(try disk.load(cacheKey: cacheKey), stalePlaintext,
                       "Memory-only fetch must not overwrite decrypted disk data")

        let secondKey = "private/chat/page-2.png.enc"
        _ = try await client.fetchAndDecrypt(
            s3Url: "", aesKeyHex: keyData.base64EncodedString(), aesNonceHex: nil,
            encryption: S3MediaClient.noncePrefixedEncryption,
            s3Key: secondKey, cacheNamespace: "account-scope",
            cachePolicy: .memoryOnly
        )
        let secondCacheKey = S3MediaClient.cacheKey(
            s3Url: "", aesKey: keyData.base64EncodedString(), nonce: nil,
            encryption: S3MediaClient.noncePrefixedEncryption,
            s3Key: secondKey, namespace: "account-scope"
        )
        XCTAssertNil(try disk.load(cacheKey: secondCacheKey),
                     "Memory-only fetch must not create a plaintext disk entry")

        let defaultResult = try await client.fetchAndDecrypt(
            s3Url: "", aesKeyHex: keyData.base64EncodedString(), aesNonceHex: nil,
            encryption: S3MediaClient.noncePrefixedEncryption,
            s3Key: secondKey, cacheNamespace: "account-scope"
        )
        XCTAssertEqual(defaultResult, plaintext)
        XCTAssertEqual(try disk.load(cacheKey: secondCacheKey), plaintext,
                       "Existing media callers retain persistent caching by default")
    }
}
