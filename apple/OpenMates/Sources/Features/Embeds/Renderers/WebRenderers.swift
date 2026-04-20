// Web embed renderers — website preview and full article reading.

import SwiftUI

struct WebsiteRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Website" }
    private var url: String { data?["url"]?.value as? String ?? "" }
    private var description: String? { data?["description"]?.value as? String }
    private var favicon: String? { data?["meta_url_favicon"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing2) {
                    if let favicon, let faviconURL = URL(string: favicon) {
                        AsyncImage(url: faviconURL) { image in
                            image.resizable().frame(width: 16, height: 16)
                        } placeholder: {
                            Icon("web", size: 14)
                        }
                    }
                    Text(hostFrom(url))
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                        .lineLimit(1)
                }

                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let description {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(3)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                Link(destination: URL(string: url) ?? URL(string: "https://openmates.org")!) {
                    HStack(spacing: .spacing2) {
                        Icon("web", size: 14)
                        Text(url)
                            .lineLimit(1)
                    }
                    .font(.omSmall)
                    .foregroundStyle(Color.buttonPrimary)
                }

                if let description {
                    Text(description)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                }
            }
        }
    }

    private func hostFrom(_ urlString: String) -> String {
        URL(string: urlString)?.host ?? urlString
    }
}

struct WebReadRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Article" }
    private var url: String { data?["url"]?.value as? String ?? "" }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(4)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                Link(destination: URL(string: url) ?? URL(string: "https://openmates.org")!) {
                    Text(url).font(.omSmall).foregroundStyle(Color.buttonPrimary).lineLimit(1)
                }

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                }
            }
        }
    }
}
