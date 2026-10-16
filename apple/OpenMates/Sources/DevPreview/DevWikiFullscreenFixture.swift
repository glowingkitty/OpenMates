// Synthetic public Wiki wire summaries exercise the production fullscreen shell.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/wiki/WikipediaFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history

#if DEBUG
import SwiftUI

struct DevWikiFullscreenFixture: View {
    @State private var externalURL = ""
    @State private var actionCount = 0
    @State private var context: RecipientMediaContext
    private let records = [WikiArticleIdentity(title: "YouTube_Shorts").inlineRecord(),
        WikiArticleIdentity(title: "OpenAI").inlineRecord()]

    init() {
        // A small PNG is returned by the presentation transport, so the real
        // CachedRemoteImage decoding path runs with no internet/account state.
        let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMwTjvzHwAEmgJlc/kGHwAAAABJRU5ErkJggg==")!
        let media = try! RecipientMediaContext(
            linkURL: URL(string: "https://app.dev.openmates.org/share/chat/wiki-fixture#key=abc")!,
            requestLoader: { request in
                let url = request.url!
                let bytes: Data
                if url.path == "/v1/wikipedia/summary" {
                    let title = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
                        .first(where: { $0.name == "title" })?.value ?? ""
                    let isOpenAI = title == "OpenAI"
                    bytes = try JSONSerialization.data(withJSONObject: [
                        "title": isOpenAI ? "OpenAI" : "YouTube Shorts",
                        "canonical_title": isOpenAI ? "OpenAI" : "YouTube Shorts",
                        "language": "en",
                        "description": isOpenAI ? "Artificial intelligence research organization" : "Short-form video platform",
                        "extract": isOpenAI ? "OpenAI researches and develops artificial intelligence." : "YouTube Shorts is a short-form video platform.",
                        "thumbnail_url": "https://upload.wikimedia.org/wiki-fixture/\(isOpenAI ? "openai" : "shorts").png",
                        "source_url": "https://en.wikipedia.org/wiki/\(isOpenAI ? "OpenAI" : "YouTube_Shorts")"
                    ])
                } else {
                    guard url.host == "preview.openmates.org", url.path == "/api/v1/image" else {
                        throw URLError(.badURL)
                    }
                    bytes = png
                }
                return (bytes, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
            })
        _context = State(initialValue: media)
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            EmbedFullscreenContainer(embeds: records, initialEmbedId: records[0].id,
                allEmbedRecords: Dictionary(uniqueKeysWithValues: records.map { ($0.id, $0) }),
                chatId: nil)
                .environment(\.recipientMediaContext, context)
                .environment(\.openURL, OpenURLAction { url in
                    actionCount += 1
                    externalURL = url.absoluteString
                    return .handled
                })
            Text(" ").font(.omTiny).foregroundStyle(Color.clear)
                .frame(width: 1, height: 1).allowsHitTesting(false)
                .accessibilityLabel("\(actionCount)|\(externalURL)")
                .accessibilityIdentifier("wiki-fixture-opened-url")
        }
        .onDisappear { context.cancel() }
    }
}
#endif
