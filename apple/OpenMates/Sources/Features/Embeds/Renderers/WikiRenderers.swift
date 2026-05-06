// Wikipedia/wiki embed renderers — inline wiki links and fullscreen article view.
// Mirrors the web app's embeds/wiki/WikiInlineLink.svelte + WikipediaFullscreen.svelte.

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
            if let url, let link = URL(string: url) {
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
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @State private var article: WikipediaArticleSummary?
    @State private var isLoading = false
    @State private var loadError: String?

    private var title: String? { data?["title"]?.value as? String }
    private var summary: String? { data?["summary"]?.value as? String ?? data?["extract"]?.value as? String }
    private var thumbnail: String? { data?["thumbnail_url"]?.value as? String }
    private var imageURL: String? {
        thumbnail
            ?? data?["image"]?.value as? String
            ?? data?["image_url"]?.value as? String
    }
    private var url: String? { data?["url"]?.value as? String }
    private var content: String? { data?["content"]?.value as? String }
    private var resolvedTitle: String {
        title ?? article?.title ?? wikipediaTitleFromURL ?? LocalizationManager.shared.text("embed.wikipedia")
    }
    private var resolvedDescription: String? {
        article?.description ?? summary
    }
    private var resolvedExtract: String? {
        article?.extract ?? content ?? summary
    }
    private var resolvedImageURL: String? {
        article?.imageURL ?? imageURL
    }
    private var resolvedURL: String? {
        article?.pageURL ?? url
    }

    var body: some View {
        if mode == .preview {
            previewLayout
        } else {
            fullscreenLayout
                .task(id: summaryFetchTitle) {
                    await loadWikipediaSummaryIfNeeded()
                }
        }
    }

    private var previewLayout: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                Icon("book", size: 16)
                    .foregroundStyle(Color.buttonPrimary)
                Text(LocalizationManager.shared.text("embed.wikipedia"))
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }

            if let title {
                Text(title)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
            }

            if let summary {
                Text(summary)
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                    .lineLimit(3)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fullscreenLayout: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if let url = resolvedURL, let link = URL(string: url) {
                Button {
                    open(link)
                } label: {
                    Text("Open on Wikipedia")
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing10)
                        .padding(.vertical, .spacing5)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                }
                .buttonStyle(.plain)
                .frame(maxWidth: .infinity)
                .offset(y: -28)
                .padding(.bottom, -20)
            }

            if isLoading && article == nil && resolvedImageURL == nil {
                RoundedRectangle(cornerRadius: .radius6)
                    .fill(Color.grey10)
                    .frame(maxWidth: .infinity, minHeight: 260)
                    .overlay {
                        ProgressView()
                    }
            } else if let imageURL = resolvedImageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                    case .failure:
                        wikiImageFallback
                    case .empty:
                        RoundedRectangle(cornerRadius: .radius6)
                            .fill(Color.grey10)
                            .overlay { ProgressView() }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(maxWidth: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
            }

            VStack(alignment: .leading, spacing: .spacing4) {
                Text(resolvedTitle)
                    .font(.omH2)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)

                if let description = resolvedDescription, !description.isEmpty {
                    Text(description)
                        .font(.omP)
                        .fontWeight(.semibold)
                        .italic()
                        .foregroundStyle(Color.fontSecondary)
                }

                if let extract = resolvedExtract, !extract.isEmpty {
                    Text(extract)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                }

                if loadError != nil && article == nil {
                    Text(LocalizationManager.shared.text("embed.wikipedia"))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }

                Text("Source: Wikipedia - content available under CC BY-SA 4.0")
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var wikiImageFallback: some View {
        RoundedRectangle(cornerRadius: .radius6)
            .fill(Color.grey10)
            .frame(maxWidth: .infinity, minHeight: 220)
            .overlay {
                Icon("book", size: 64)
                    .foregroundStyle(Color.fontTertiary)
            }
    }

    private var wikipediaTitleFromURL: String? {
        guard let url, let last = URL(string: url)?.lastPathComponent.removingPercentEncoding else { return nil }
        return last.replacingOccurrences(of: "_", with: " ")
    }

    private var summaryFetchTitle: String {
        (title ?? wikipediaTitleFromURL ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    @MainActor
    private func loadWikipediaSummaryIfNeeded() async {
        guard article == nil, !summaryFetchTitle.isEmpty else { return }
        isLoading = true
        loadError = nil
        do {
            let encoded = summaryFetchTitle.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? summaryFetchTitle
            let response: WikipediaSummaryResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/wikipedia/summary?title=\(encoded)&language=en"
            )
            article = WikipediaArticleSummary(response: response)
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    private func open(_ url: URL) {
        #if os(iOS)
        UIApplication.shared.open(url)
        #elseif os(macOS)
        NSWorkspace.shared.open(url)
        #endif
    }
}

private struct WikipediaArticleSummary {
    let title: String?
    let description: String?
    let extract: String?
    let imageURL: String?
    let pageURL: String?

    init(response: WikipediaSummaryResponse) {
        title = response.title
        description = response.description
        extract = response.extract
        imageURL = response.originalImage?.source ?? response.thumbnail?.source
        pageURL = response.contentUrls?.desktop?.page
    }
}

private struct WikipediaSummaryResponse: Decodable {
    let title: String?
    let description: String?
    let extract: String?
    let thumbnail: WikipediaSummaryImage?
    let originalImage: WikipediaSummaryImage?
    let contentUrls: WikipediaContentURLs?

    enum CodingKeys: String, CodingKey {
        case title
        case description
        case extract
        case thumbnail
        case originalImage = "originalimage"
        case contentUrls = "content_urls"
    }
}

private struct WikipediaSummaryImage: Decodable {
    let source: String?
}

private struct WikipediaContentURLs: Decodable {
    let desktop: WikipediaPageURL?
}

private struct WikipediaPageURL: Decodable {
    let page: String?
}
