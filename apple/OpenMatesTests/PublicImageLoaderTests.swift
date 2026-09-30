// Deterministic public-media contract. No live requests, account data or cache writes.
// Mirrors frontend/packages/ui/src/utils/imageProxy.ts and Website preview's
// public favicon flow; exercising the real production downloader via an adapter.
import XCTest
import CryptoKit
@testable import OpenMates

final class PublicImageLoaderTests: XCTestCase {
    private let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMwTjvzHwAEmgJlc/kGHwAAAABJRU5ErkJggg==")!

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPreviewServiceRequestUsesOnlyApprovedAppOriginReferer() throws {
        let appURL = URL(string: "https://app.dev.openmates.org/private/chat/route?token=secret")!
        let image = URL(string: "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.org%2Fphoto.jpg")!
        let favicon = URL(string: "https://preview.openmates.org/api/v1/favicon?url=https%3A%2F%2Fexample.org")!
        XCTAssertEqual(RemoteImageCache.request(for: image, appWebURL: appURL).value(forHTTPHeaderField: "Referer"),
                       "https://app.dev.openmates.org/")
        XCTAssertEqual(RemoteImageCache.request(for: favicon, appWebURL: appURL).value(forHTTPHeaderField: "Referer"),
                       "https://app.dev.openmates.org/")

        let external = URL(string: "https://images.example.org/photo.jpg")!
        let lookalike = URL(string: "https://preview.openmates.org.evil.example/api/v1/image")!
        let otherPath = URL(string: "https://preview.openmates.org/api/v1/image-other")!
        for url in [external, lookalike, otherPath] {
            XCTAssertNil(RemoteImageCache.request(for: url, appWebURL: appURL).value(forHTTPHeaderField: "Referer"))
        }
        let customApp = URL(string: "https://private.example.org/chat")!
        XCTAssertNil(RemoteImageCache.request(for: image, appWebURL: customApp).value(forHTTPHeaderField: "Referer"))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testWebsiteDescriptionReclaimsImageSpaceAfterProxyFailure() {
        XCTAssertEqual(WebsitePreviewLayout.descriptionWidth(containerWidth: 300, hasLoadedImageSlot: true), 120)
        XCTAssertEqual(WebsitePreviewLayout.descriptionWidth(containerWidth: 300, hasLoadedImageSlot: false), 300)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRealRasterBytesDecodeAndDownloadWithoutTrustingMIME() async throws {
        let url = URL(string: "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.org%2Ffavicon.png&max_width=38")!
        let probe = PublicImageTransportProbe(data: png, status: 200, mime: nil)
        let received = try await RemoteImageCache.download(url.absoluteString) { try await probe.fetch($0) }
        XCTAssertEqual(received, png)
        XCTAssertTrue(RemoteImageCache.isDecodableImageData(received))
        let requests = await probe.requests
        XCTAssertEqual(requests, [url])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFailedProxyDoesNotRetryThirdPartyOriginEvenWithValidImageBody() async {
        let url = URL(string: "https://preview.openmates.org/api/v1/image?url=https%3A%2F%2Fexample.org%2Ffavicon.png&max_width=38")!
        let probe = PublicImageTransportProbe(data: png, status: 502, mime: "image/png")
        do {
            _ = try await RemoteImageCache.download(url.absoluteString) { try await probe.fetch($0) }
            XCTFail("A failed proxy status is not a successful public image")
        } catch {
            XCTAssertTrue(error is S3Error)
        }
        let requests = await probe.requests
        XCTAssertEqual(requests, [url], "Never follow the query parameter directly after proxy failure")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testHTMLSVGAndCorruptRasterCannotEnterSuccessfulImageCache() async {
        let url = URL(string: "https://preview.openmates.org/api/v1/favicon?url=https%3A%2F%2Fexample.org")!
        let bodies = [
            Data("<!doctype html><html>Temporarily unavailable</html>".utf8),
            Data("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1\" height=\"1\"><rect width=\"1\" height=\"1\"/></svg>".utf8),
            Data([0x89, 0x50, 0x4E, 0x47]), Data()
        ]
        for body in bodies {
            let probe = PublicImageTransportProbe(data: body, status: 200, mime: "image/png")
            XCTAssertFalse(RemoteImageCache.isDecodableImageData(body))
            do {
                _ = try await RemoteImageCache.download(url.absoluteString) { try await probe.fetch($0) }
                XCTFail("An image Content-Type cannot make undecodable bytes usable")
            } catch {
                XCTAssertTrue(error is S3Error)
            }
            let requests = await probe.requests
            XCTAssertEqual(requests, [url])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testStaticSVGOptInAcceptsLocalGradientAndRetainsOriginalRequest() async throws {
        let svg = Data("""
        <svg xmlns="http://www.w3.org/2000/svg" width="29" height="29"><defs><linearGradient id="paint"><stop stop-color="#4969CE"/><stop offset="1" stop-color="#5A85EB"/></linearGradient></defs><path fill="url(#paint)" d="M0 0h29v29H0z"/></svg>
        """.utf8)
        XCTAssertNotNil(StaticSVGImageSource(data: svg))
        XCTAssertFalse(RemoteImageCache.isDecodableImageData(svg), "The raster validation contract remains unchanged")
        let url = URL(string: "https://app.dev.openmates.org/favicon.svg")!
        let probe = PublicImageTransportProbe(data: svg, status: 200, mime: "image/svg+xml")
        let received = try await RemoteImageCache.download(url.absoluteString, allowStaticSVG: true) {
            try await probe.fetch($0)
        }
        XCTAssertEqual(received, svg)
        let requests = await probe.requests
        XCTAssertEqual(requests, [url], "Render the selected source without an alternate image URL")
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testStaticSVGRejectsActiveMarkupExternalResourcesAndEntities() async {
        let contents = [
            "<script>alert(1)</script>", "<foreignObject><div>HTML</div></foreignObject>",
            "<style>path{fill:red}</style>", "<rect width='1' height='1' onload='alert(1)'/>",
            "<use href='https://example.org/image.svg#image'/>",
            "<path fill='url(https://example.org/image.svg)' d='M0 0h1v1z'/>",
            "<image href='data:image/png;base64,AAAA'/>",
        ]
        let unsafe = contents.map { "<svg xmlns='http://www.w3.org/2000/svg'>\($0)</svg>" } + [
            "<!DOCTYPE svg [<!ENTITY image SYSTEM 'https://example.org/private'>]><svg xmlns='http://www.w3.org/2000/svg'>&image;</svg>",
            "<?xml-stylesheet href='https://example.org/style.css'?><svg xmlns='http://www.w3.org/2000/svg'/>",
            "<svg xmlns='http://www.w3.org/2000/svg'><path></svg>",
        ]
        let url = URL(string: "https://preview.openmates.org/api/v1/favicon?url=https%3A%2F%2Fexample.org")!
        for text in unsafe {
            let bytes = Data(text.utf8)
            XCTAssertNil(StaticSVGImageSource(data: bytes))
            let probe = PublicImageTransportProbe(data: bytes, status: 200, mime: "image/svg+xml")
            do {
                _ = try await RemoteImageCache.download(url.absoluteString, allowStaticSVG: true) { try await probe.fetch($0) }
                XCTFail("Unsafe SVG must not enter the opt-in public image cache")
            } catch { XCTAssertTrue(error is S3Error) }
            let requests = await probe.requests
            XCTAssertEqual(requests, [url], "A rejected SVG must not trigger another origin request")
        }
        XCTAssertNil(StaticSVGImageSource(data: Data(repeating: 32, count: 2_000_001)))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFaviconExtractionUsesDedicatedProxyAndDoesNotWrapItAgain() throws {
        let page = "https://example.org/path?first=a&second=b#fragment"
        let url = try XCTUnwrap(EmbedFieldReader.proxiedFaviconImageURL(directURL: nil, pageURL: page))
        let outer = try XCTUnwrap(URLComponents(string: url))
        XCTAssertEqual(outer.host, "preview.openmates.org")
        XCTAssertEqual(outer.path, "/api/v1/favicon")
        XCTAssertEqual(outer.queryItems?.first { $0.name == "url" }?.value, page)
        XCTAssertNil(outer.queryItems?.first { $0.name == "max_width" })
        XCTAssertEqual(EmbedFieldReader.proxiedFaviconImageURL(directURL: url, pageURL: page), url,
                       "Repeated hydration must not wrap the favicon extractor in image proxies")
        let direct = try XCTUnwrap(EmbedFieldReader.proxiedFaviconImageURL(
            directURL: "https://example.org/favicon.png", pageURL: page))
        let directProxy = try XCTUnwrap(URLComponents(string: direct))
        XCTAssertEqual(directProxy.path, "/api/v1/image")
        XCTAssertEqual(directProxy.queryItems?.first { $0.name == "max_width" }?.value, "38")
        XCTAssertEqual(directProxy.queryItems?.first { $0.name == "url" }?.value,
                       "https://example.org/favicon.png")
        let lookalike = try XCTUnwrap(URLComponents(string: XCTUnwrap(
            EmbedFieldReader.proxiedImageURL("https://evil.example/api/v1/favicon?url=x", maxWidth: 38))))
        XCTAssertEqual(lookalike.host, "preview.openmates.org")
        XCTAssertEqual(lookalike.path, "/api/v1/image")
        XCTAssertNil(EmbedFieldReader.proxiedFaviconImageURL(directURL: nil, pageURL: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testWebsiteModelNormalizesNestedFaviconMetadataThroughImageProxy() throws {
        let raw: [String: Any] = ["url": "https://example.org/article", "title": "Source",
                                  "meta_url": ["favicon": "https://example.org/favicon.svg"]]
        let embed = EmbedRecord(id: "public-source", type: EmbedType.webWebsite.rawValue, status: .finished,
                                data: .raw(raw.mapValues { AnyCodable($0) }), parentEmbedId: nil,
                                appId: "web", skillId: nil, embedIds: nil, createdAt: nil)
        let model = try XCTUnwrap(WebsiteResultModel(embed: embed))
        let image = try XCTUnwrap(URLComponents(string: XCTUnwrap(model.faviconURL)))
        XCTAssertEqual(image.path, "/api/v1/image")
        XCTAssertEqual(image.queryItems?.first { $0.name == "url" }?.value, "https://example.org/favicon.svg")
        XCTAssertEqual(image.queryItems?.first { $0.name == "max_width" }?.value, "38")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testLocalExampleAssetsResolveAgainstConfiguredWebOriginAndExternalHostsStayProxied() throws {
        let web = URL(string: "https://app.dev.openmates.org/")!
        XCTAssertEqual(EmbedFieldReader.proxiedImageURL("/store-examples/house.webp", maxWidth: 520, webBaseURL: web),
                       "https://app.dev.openmates.org/store-examples/house.webp")
        let external = try XCTUnwrap(URLComponents(string: XCTUnwrap(
            EmbedFieldReader.proxiedImageURL("//example.org/image.png", maxWidth: 520, webBaseURL: web))))
        XCTAssertEqual(external.host, "preview.openmates.org")
        XCTAssertEqual(external.queryItems?.first { $0.name == "url" }?.value, "https://example.org/image.png")
        let misleading = "https://preview.openmates.org/api/v1/image-other?url=x"
        let wrapped = try XCTUnwrap(URLComponents(string: XCTUnwrap(
            EmbedFieldReader.proxiedImageURL(misleading, maxWidth: 38, webBaseURL: web))))
        XCTAssertEqual(wrapped.path, "/api/v1/image")
        XCTAssertEqual(wrapped.queryItems?.first { $0.name == "url" }?.value, misleading)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testOriginalImageDownloadRequiresExplicitEncryptedOriginalAndSafeFilename() throws {
        let data: [String: AnyCodable] = [
            "files": AnyCodable([
                "preview": ["s3_key": "account/preview.enc"],
                "full": ["s3_key": "account/full.enc"],
                "original": ["s3_key": "account/original.enc", "format": "png",
                             "encryption": S3MediaClient.noncePrefixedEncryption]
            ]),
            "aes_key": AnyCodable("encoded-key"),
            "filename": AnyCodable("../../private/photo")
        ]
        let payload = try XCTUnwrap(ImageOriginalDownloadPayload(data: data))
        XCTAssertEqual(payload.s3Key, "account/original.enc")
        XCTAssertEqual(payload.filename, "photo.png")
        XCTAssertTrue(ImageOriginalDownloadController.canDownload(data: data))

        let noOriginal: [String: AnyCodable] = [
            "files": AnyCodable(["preview": ["s3_key": "account/preview.enc"]]),
            "aes_key": AnyCodable("encoded-key"),
            "encryption": AnyCodable(S3MediaClient.noncePrefixedEncryption)
        ]
        XCTAssertNil(ImageOriginalDownloadPayload(data: noOriginal))
        XCTAssertFalse(ImageOriginalDownloadController.canDownload(data: noOriginal))
        var noKey = data
        noKey.removeValue(forKey: "aes_key")
        XCTAssertNil(ImageOriginalDownloadPayload(data: noKey))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testOriginalImageDownloadDecryptsOriginalWithoutPlaintextCache() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("image-export-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let disk = MediaDiskCache(directoryName: "image-export", baseDirectory: root)
        let key = Data((0..<32).map(UInt8.init))
        let nonce = Data((0..<12).map(UInt8.init))
        let sealed = try AES.GCM.seal(png, using: SymmetricKey(data: key),
                                      nonce: AES.GCM.Nonce(data: nonce))
        let ciphertext = nonce + sealed.ciphertext + sealed.tag
        let originalKey = "account/original-image.enc"
        let client = S3MediaClient(diskCache: disk, encryptedDataLoader: { _, s3Key in
            guard s3Key == originalKey else { throw S3Error.downloadFailed }
            return ciphertext
        })
        let data: [String: AnyCodable] = [
            "files": AnyCodable(["original": ["s3_key": originalKey, "format": "png",
                                                "encryption": S3MediaClient.noncePrefixedEncryption]]),
            "aes_key": AnyCodable(key.base64EncodedString()),
            "filename": AnyCodable("photo.png")
        ]
        let payload = try XCTUnwrap(ImageOriginalDownloadPayload(data: data))
        let decrypted = try await payload.load(using: client, scope: "test-account-scope")
        XCTAssertEqual(decrypted, png)
        let cacheKey = S3MediaClient.cacheKey(
            s3Url: "", aesKey: key.base64EncodedString(), nonce: nil,
            encryption: S3MediaClient.noncePrefixedEncryption, s3Key: originalKey,
            namespace: "test-account-scope"
        )
        XCTAssertNil(try disk.load(cacheKey: cacheKey),
                     "Original plaintext must remain memory-only until the OS export handoff")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImageDownloadFenceRejectsNavigationAndAccountScopeChanges() {
        let generation = UUID()
        let selection = UUID()
        let fence = ImageOriginalDownloadFence(scope: "account-a", scopeGeneration: generation,
                                               selectionGeneration: selection)
        XCTAssertTrue(fence.permits(scope: "account-a", scopeGeneration: generation,
                                    selectionGeneration: selection))
        XCTAssertFalse(fence.permits(scope: "account-a", scopeGeneration: generation,
                                     selectionGeneration: UUID()))
        XCTAssertFalse(fence.permits(scope: "account-b", scopeGeneration: generation,
                                     selectionGeneration: selection))
        XCTAssertFalse(fence.permits(scope: "account-a", scopeGeneration: UUID(),
                                     selectionGeneration: selection))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTappedImagePreviewUsesIsolatedTemporaryFileAndRemovesIt() throws {
        #if os(iOS)
        var requestedAttributes: [FileAttributeKey: Any]?
        let url = try NativeImagePreviewFile.create(png, suggestedFilename: "../../private/photo.png",
                                                    attributeWriter: { attributes, path in
            requestedAttributes = attributes
            try FileManager.default.setAttributes(attributes, ofItemAtPath: path)
        })
        #else
        let url = try NativeImagePreviewFile.create(png, suggestedFilename: "../../private/photo.png")
        #endif
        defer { NativeImagePreviewFile.remove(url) }
        XCTAssertEqual(url.lastPathComponent, "photo.png")
        XCTAssertEqual(try Data(contentsOf: url), png)
        XCTAssertEqual(try url.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
        #if os(iOS)
        XCTAssertEqual(requestedAttributes?[.protectionKey] as? FileProtectionType, .complete,
                       "The QuickLook writer must request complete file protection even where a simulator cannot report it")
        XCTAssertEqual(requestedAttributes?[.posixPermissions] as? Int, 0o600)
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        XCTAssertEqual(attributes[.posixPermissions] as? Int, 0o600)
        let reportedProtection = try url.resourceValues(forKeys: [.fileProtectionKey]).fileProtection
        #if targetEnvironment(simulator)
        // The host-backed simulator reports CompleteUntilFirstUserAuthentication
        // for this file even after both Complete write and attribute requests;
        // its volume capability flag still says protection is supported. Keep
        // asserting the requested class and actual 0600 mode above. Device
        // builds require a Complete readback before showing plaintext.
        XCTAssertTrue(reportedProtection == nil || reportedProtection == .complete
                      || reportedProtection == .completeUntilFirstUserAuthentication)
        #else
        let volumeValues = try url.resourceValues(forKeys: [.volumeSupportsFileProtectionKey])
        XCTAssertEqual(volumeValues.allValues[.volumeSupportsFileProtectionKey] as? Bool, true)
        XCTAssertEqual(reportedProtection, .complete)
        #endif
        #endif
        NativeImagePreviewFile.remove(url)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTappedImagePreviewRejectsWeakerProtectionAndDeletesPlaintext() throws {
        #if os(iOS)
        let accepted = try NativeImagePreviewFile.create(png, suggestedFilename: "accepted.png",
                                                         protectionReader: { _ in .complete })
        XCTAssertTrue(FileManager.default.fileExists(atPath: accepted.path))
        NativeImagePreviewFile.remove(accepted)
        let weakerProtections: [URLFileProtection?] = [
            URLFileProtection.completeUntilFirstUserAuthentication,
            URLFileProtection.none,
            nil,
        ]
        for reportedProtection in weakerProtections {
            var writtenURL: URL?
            XCTAssertThrowsError(try NativeImagePreviewFile.create(
                png, suggestedFilename: "private.png",
                protectionReader: { url in
                    writtenURL = url
                    return reportedProtection
                }
            )) { error in
                XCTAssertEqual((error as? CocoaError)?.code, .fileWriteNoPermission)
            }
            let url = try XCTUnwrap(writtenURL)
            XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
            XCTAssertFalse(FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
        }
        #endif
    }
}

private actor PublicImageTransportProbe {
    let data: Data
    let status: Int
    let mime: String?
    private(set) var requests: [URL] = []

    init(data: Data, status: Int, mime: String?) {
        self.data = data
        self.status = status
        self.mime = mime
    }

    func fetch(_ url: URL) throws -> (Data, URLResponse) {
        requests.append(url)
        let headers = mime.map { ["Content-Type": $0] }
        let response = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: status,
                                                   httpVersion: "HTTP/1.1", headerFields: headers))
        return (data, response)
    }
}
