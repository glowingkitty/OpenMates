// Code and document embed renderers.

import SwiftUI

struct CodeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var code: String { data?["code"]?.value as? String ?? "" }
    private var language: String { data?["language"]?.value as? String ?? "" }
    private var filename: String? { data?["filename"]?.value as? String }
    private var lineCount: Int { data?["line_count"]?.value as? Int ?? code.components(separatedBy: "\n").count }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack {
                    if let filename {
                        Text(filename)
                            .font(.omXs)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.fontPrimary)
                    }
                    Spacer()
                    Text(language)
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                        .padding(.horizontal, .spacing2)
                        .padding(.vertical, 2)
                        .background(Color.grey20)
                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                }

                Text(code)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(6)
            }
            .padding(.spacing3)
            .background(Color.grey10)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                HStack {
                    if let filename {
                        Label(filename, systemImage: "doc.text")
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                    }
                    Spacer()
                    Text("\(lineCount) lines")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)

                    Button { copyCode() } label: {
                        Image(systemName: "doc.on.doc")
                    }
                    .font(.omSmall)
                }

                ScrollView(.horizontal, showsIndicators: true) {
                    Text(code)
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
        }
    }

    private func copyCode() {
        #if os(iOS)
        UIPasteboard.general.string = code
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        #endif
    }
}

struct DocsRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var html: String? { data?["html"]?.value as? String }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title {
                    Text(title)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(2)
                }
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
                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }
                Text(content ?? html ?? "")
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .textSelection(.enabled)
            }
        }
    }
}

struct SheetRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var markdown: String? { data?["markdown"]?.value as? String }
    private var title: String? { data?["title"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title {
                    Text(title)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                }
                Image(systemName: "tablecells")
                    .font(.system(size: 32))
                    .foregroundStyle(Color.fontTertiary)
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let markdown {
                    Text(markdown)
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                }
            }
        }
    }
}
