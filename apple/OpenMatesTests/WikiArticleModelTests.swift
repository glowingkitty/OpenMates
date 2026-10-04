// Canonical Wiki wire identity and superseded-request regression coverage.
import XCTest
@testable import OpenMates

@MainActor
final class WikiArticleModelTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testCanonicalIdentityAndReservedCharactersStayInsideTitle() throws {
        let identity = WikiArticleIdentity(title: " C++_&_A/B?# ", language: "DE-de")
        XCTAssertEqual(identity.title, "C++ & A/B?#")
        XCTAssertEqual(identity.language, "de")
        let page = try XCTUnwrap(identity.pageURL)
        XCTAssertEqual(page.host, "de.wikipedia.org")
        XCTAssertNil(page.query); XCTAssertNil(page.fragment)
        XCTAssertTrue(page.absoluteString.contains("%2F"))
        let query = try XCTUnwrap(URLComponents(string: identity.summaryPath))
        XCTAssertEqual(query.queryItems?.first(where: { $0.name == "title" })?.value, identity.title)
        XCTAssertTrue(identity.summaryPath.contains("%2B%2B"))
        let same = WikiArticleIdentity(title: "C++ & A/B?#", language: "de")
        XCTAssertEqual(identity.inlineRecord().id, same.inlineRecord().id)
        XCTAssertNotEqual(identity.inlineRecord().id, WikiArticleIdentity(title: same.title, language: "en").inlineRecord().id)
        XCTAssertNil(identity.inlineRecord().rawData?["summary"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testArticleURLMetadataPreservesCanonicalArticleAndLanguage() {
        let identity = WikiArticleIdentity(data: ["title": AnyCodable("Displayed topic"),
            "url": AnyCodable("https://de.wikipedia.org/wiki/K%C3%BCnstliche_Intelligenz")])
        XCTAssertEqual(identity.title, "Künstliche Intelligenz")
        XCTAssertEqual(identity.language, "de")
        XCTAssertEqual(WikiArticleIdentity(title: "OpenAI", language: "xx").language, "en")
        for unsafe in ["https://wikipedia.org.evil.example/wiki/OpenAI", "javascript:alert(1)",
                       "https://owner:secret@en.wikipedia.org/wiki/OpenAI", "http://en.wikipedia.org/wiki/OpenAI"] {
            XCTAssertNil(WikiArticleIdentity.articleURL(unsafe))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWireSummaryDecodesOriginalImageAndCanonicalDestination() throws {
        let bytes = Data(#"{"title":"OpenAI","description":"AI research organization","extract":"OpenAI develops AI.","thumbnail":{"source":"https://upload.wikimedia.org/thumb.png"},"originalimage":{"source":"https://upload.wikimedia.org/original.png"},"content_urls":{"desktop":{"page":"https://en.wikipedia.org/wiki/OpenAI"}}}"#.utf8)
        let article = try WikiArticleSummary.decode(bytes)
        XCTAssertEqual(article.title, "OpenAI")
        XCTAssertEqual(article.description, "AI research organization")
        XCTAssertEqual(article.extract, "OpenAI develops AI.")
        XCTAssertEqual(article.imageURL, "https://upload.wikimedia.org/original.png")
        XCTAssertEqual(article.pageURL?.absoluteString, "https://en.wikipedia.org/wiki/OpenAI")
        let fallback = try WikiArticleSummary.decode(Data(#"{"thumbnail":{"source":"https://upload.wikimedia.org/thumb.png"}}"#.utf8))
        XCTAssertEqual(fallback.imageURL, "https://upload.wikimedia.org/thumb.png")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHeroUsesSharedImageProxyAndRejectsUnsafeImageSchemes() throws {
        let base = URL(string: "https://app.dev.openmates.org/")!
        let original = "https://upload.wikimedia.org/image.png"
        let image = try XCTUnwrap(WikiArticleSummary.proxiedImageURL(original, webBaseURL: base))
        let query = URLComponents(url: image, resolvingAgainstBaseURL: false)
        XCTAssertEqual(image.host, "preview.openmates.org")
        XCTAssertEqual(image.path, "/api/v1/image")
        XCTAssertEqual(query?.queryItems?.first(where: { $0.name == "url" })?.value, original)
        XCTAssertEqual(query?.queryItems?.first(where: { $0.name == "max_width" })?.value, "1024")
        XCTAssertEqual(WikiArticleSummary.proxiedImageURL("/store-examples/image.png", webBaseURL: base)?.absoluteString,
            "https://app.dev.openmates.org/store-examples/image.png")
        for unsafe in ["file:///private/image", "javascript:alert(1)", "https://owner:secret@images.example.org/image", "http://images.example.org/image"] {
            XCTAssertNil(WikiArticleSummary.proxiedImageURL(unsafe, webBaseURL: base))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testCrossArticleReplacementClearsEveryOldFieldAndRejectsLateResults() throws {
        var state = WikiArticleLoadState()
        let shorts = WikiArticleIdentity(title: "YouTube_Shorts")
        let openAI = WikiArticleIdentity(title: "OpenAI")
        let oldArticle = try WikiArticleSummary.decode(Data(#"{"title":"YouTube Shorts","description":"Short-form video platform","extract":"YouTube Shorts video summary"}"#.utf8))
        let oldRequest = state.begin(shorts)
        state.finish(oldArticle, request: oldRequest)
        XCTAssertEqual(state.article(for: shorts)?.title, "YouTube Shorts")
        // Selection invalidates old fields even before the new task begins.
        XCTAssertNil(state.article(for: openAI))
        let newRequest = state.begin(openAI)
        XCTAssertNil(state.article); XCTAssertTrue(state.isLoading)
        state.finish(oldArticle, request: oldRequest)
        XCTAssertNil(state.article); XCTAssertTrue(state.isLoading)
        let newArticle = try WikiArticleSummary.decode(Data(#"{"title":"OpenAI","description":"AI research organization","extract":"OpenAI develops AI.","originalimage":{"source":"https://upload.wikimedia.org/openai.png"}}"#.utf8))
        state.finish(newArticle, request: newRequest)
        XCTAssertEqual(state.article(for: openAI)?.extract, "OpenAI develops AI.")
        XCTAssertEqual(state.article(for: openAI)?.imageURL, "https://upload.wikimedia.org/openai.png")
        XCTAssertFalse(state.isLoading)
        state.finish(nil, request: oldRequest, failed: true)
        XCTAssertFalse(state.failed)
        XCTAssertEqual(state.article(for: openAI)?.title, "OpenAI")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSameArticleReloadCannotPublishEarlierAuthorityResult() throws {
        var state = WikiArticleLoadState()
        let identity = WikiArticleIdentity(title: "OpenAI")
        let oldRequest = state.begin(identity)
        let currentRequest = state.begin(identity)
        let article = try WikiArticleSummary.decode(Data(#"{"title":"OpenAI"}"#.utf8))
        state.finish(article, request: oldRequest)
        XCTAssertNil(state.article)
        state.finish(nil, request: currentRequest, failed: true)
        XCTAssertTrue(state.failed); XCTAssertFalse(state.isLoading)
    }
}
