// Deterministic public-media contract. No live requests, account data or cache writes.
// Mirrors frontend/packages/ui/src/utils/imageProxy.ts and Website preview's
// public favicon flow; exercising the real production downloader via an adapter.
import XCTest
@testable import OpenMates

final class PublicImageLoaderTests: XCTestCase {
    private let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMwTjvzHwAEmgJlc/kGHwAAAABJRU5ErkJggg==")!

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

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFaviconExtractionGetsOneBoundedRasterProxyAndPreservesEncodedSource() throws {
        let page = "https://example.org/path?first=a&second=b#fragment"
        let url = try XCTUnwrap(EmbedFieldReader.proxiedFaviconImageURL(directURL: nil, pageURL: page))
        let outer = try XCTUnwrap(URLComponents(string: url))
        XCTAssertEqual(outer.host, "preview.openmates.org")
        XCTAssertEqual(outer.path, "/api/v1/image")
        XCTAssertEqual(outer.queryItems?.first { $0.name == "max_width" }?.value, "38")
        let inner = try XCTUnwrap(URLComponents(string: XCTUnwrap(outer.queryItems?.first { $0.name == "url" }?.value)))
        XCTAssertEqual(inner.path, "/api/v1/favicon")
        XCTAssertEqual(inner.queryItems?.first { $0.name == "url" }?.value, page)
        XCTAssertEqual(EmbedFieldReader.proxiedFaviconImageURL(directURL: url, pageURL: page), url,
                       "Repeated hydration must not build an unbounded chain of image proxies")
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
