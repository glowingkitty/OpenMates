// Wikipedia/wiki embed renderers — inline wiki links and fullscreen article view.
// Mirrors the web app's embeds/wiki/WikiInlineLink.svelte + WikipediaFullscreen.svelte.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/wiki/WikipediaFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/wiki/WikiInlineLink.svelte
//         frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// CSS: WikipediaFullscreen.svelte .wiki-description, .wiki-extract
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
//                specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chats.surface.semantic-parity

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct WikiInlineLinkView: View {
    let title: String
    let summary: String?
    let url: String?

    var body: some View {
        HStack(spacing: .spacing3) {
            Icon("book", size: 20)
                .foregroundStyle(Color.fontTertiary)

            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.buttonPrimary)
                if let summary {
                    Text(summary)
                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                        .lineLimit(1)
                }
            }
        }
        .onTapGesture {
            if let url, let link = WikiArticleIdentity.articleURL(url) {
                #if os(iOS)
                UIApplication.shared.open(link)
                #elseif os(macOS)
                NSWorkspace.shared.open(link)
                #endif
            }
        }
    }
}

struct WikiRenderer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @State private var loadState = WikiArticleLoadState()
    @State private var loadedImageURL: URL?

    private var identity: WikiArticleIdentity {
        WikiArticleIdentity(data: data ?? [:], fallbackLanguage: LocalizationManager.shared.currentLanguage.code)
    }
    private var article: WikiArticleSummary? { loadState.article(for: identity) }
    private var resolvedTitle: String {
        article?.resolvedTitle ?? data?["title"]?.value as? String ?? identity.title
    }
    private var resolvedDescription: String? {
        article?.description ?? data?["description"]?.value as? String
    }
    private var resolvedImageURL: URL? {
        let raw = article?.imageURL ?? data?["thumbnail_url"]?.value as? String
            ?? data?["image_url"]?.value as? String
        // Use the same preview proxy as web. Relative bundled example assets
        // resolve against the presentation's origin, including anonymous shares.
        let base = recipientMediaContext?.webBaseURL ?? ServerProfile.current().webBaseURL
        return WikiArticleSummary.proxiedImageURL(raw, webBaseURL: base)
    }
    private struct FetchIdentity: Hashable {
        let article: WikiArticleIdentity
        let authority: UUID
        let api: String
    }
    private var fetchIdentity: FetchIdentity {
        FetchIdentity(article: identity,
            authority: recipientMediaContext?.generation ?? OfflineStore.shared.scopeGeneration,
            api: (recipientMediaContext?.apiBaseURL ?? ServerProfile.current().apiBaseURL).absoluteString)
    }

    var body: some View {
        if mode == .preview {
            previewLayout
        } else {
            fullscreenLayout.task(id: fetchIdentity) { await loadWikipediaSummary() }
        }
    }

    private var previewLayout: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                Icon("book", size: 16).foregroundStyle(Color.buttonPrimary)
                Text(AppStrings.localized("embeds.wiki.wikipedia"))
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }
            Text(resolvedTitle).font(.omSmall).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(2)
            if let description = resolvedDescription ?? data?["summary"]?.value as? String {
                Text(description).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(3)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fullscreenLayout: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            // The action belongs to EmbedFullscreenHeader, which paints it over
            // the banner edge and reserves its full hit bounds.
            if let imageURL = resolvedImageURL {
                CachedRemoteImage(url: imageURL, onSuccess: { loadedImageURL = imageURL }) { image in
                    image.resizable().scaledToFit()
                } placeholder: { wikiImageFallback }
                .frame(maxWidth: 511, maxHeight: 340)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(resolvedTitle)
                .accessibilityIdentifier("wiki-hero-image")
                .accessibilityValue(loadedImageURL == imageURL ? "loaded" : "loading")
                .frame(maxWidth: .infinity)
            } else if loadState.isLoading || loadState.identity != identity {
                wikiImageFallback.overlay { ProgressView() }
            }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(resolvedTitle).font(.omH3).fontWeight(.semibold)
                    .foregroundStyle(Color.grey90)
                    .accessibilityIdentifier("wiki-fullscreen-title")
                if let description = resolvedDescription, !description.isEmpty {
                    SourceQuoteHighlightedText(text: description, locationID: "wiki-description", pointSize: 14, textColor: .grey60, lineHeight: 21, italic: true)
                        .font(.omSmall).italic().foregroundStyle(Color.grey60)
                        .accessibilityIdentifier("wiki-fullscreen-description")
                }
            }
            if let extract = article?.extract, !extract.isEmpty {
                SourceQuoteTextDocument(text: extract, locationPrefix: "wiki-extract-paragraph", textColor: .grey80)
                    .font(.omP).foregroundStyle(Color.grey80).textSelection(.enabled)
                    .accessibilityIdentifier("wiki-fullscreen-extract")
            }
            if loadState.identity == identity && loadState.failed {
                Text(AppStrings.localized("embeds.wiki.article_not_found"))
                    .font(.omSmall).foregroundStyle(Color.fontTertiary)
                    .accessibilityIdentifier("wiki-fullscreen-error")
            }
            if article != nil {
                Text(AppStrings.localized("embeds.wiki.source_wikipedia"))
                    .font(.omTiny).foregroundStyle(Color.grey40)
                    .frame(maxWidth: .infinity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing8)
        .frame(maxWidth: 600)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("wiki-fullscreen-content")
    }

    private var wikiImageFallback: some View {
        RoundedRectangle(cornerRadius: .radius5).fill(Color.grey10)
            .frame(maxWidth: .infinity, minHeight: 200, maxHeight: 200)
    }

    @MainActor
    private func loadWikipediaSummary() async {
        let requested = fetchIdentity
        guard !requested.article.title.isEmpty else { return }
        let request = loadState.begin(requested.article)
        let recipient = recipientMediaContext
        let profile = ServerProfile.current()
        let account = await AuthManager.currentUserId()
        do {
            try Task.checkCancellation()
            let bytes: Data
            if let recipient {
                var url = URLComponents(url: recipient.apiBaseURL.appendingPathComponent("v1/wikipedia/summary"), resolvingAgainstBaseURL: false)!
                let query = URLComponents(string: requested.article.summaryPath)!
                url.percentEncodedQuery = query.percentEncodedQuery
                bytes = try await recipient.download(url.url!)
                try recipient.checkCurrent()
            } else {
                guard requested == fetchIdentity else { throw CancellationError() }
                bytes = try await APIClient.shared.request(.get, path: requested.article.summaryPath,
                    serverProfile: profile, expectedAccountID: account,
                    expectedScope: account == nil ? nil : requested.authority)
            }
            try Task.checkCancellation()
            if let recipient { try recipient.checkCurrent() }
            else {
                let currentAccount = await AuthManager.currentUserId()
                guard currentAccount == account, requested == fetchIdentity else { throw CancellationError() }
            }
            guard requested == fetchIdentity else { throw CancellationError() }
            let summary = try WikiArticleSummary.decode(bytes)
            try summary.validate(for: requested.article,
                displayTitle: data?["title"]?.value as? String ?? requested.article.title)
            loadState.finish(summary, request: request)
        } catch {
            guard !Task.isCancelled, requested == fetchIdentity else { return }
            if error is CancellationError { loadState.finish(nil, request: request); return }
            loadState.finish(nil, request: request, failed: true)
        }
    }
}
