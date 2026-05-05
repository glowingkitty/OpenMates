// Code and document embed renderers.

import SwiftUI

struct CodeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var code: String { data?["code"]?.value as? String ?? "" }
    private var language: String { data?["language"]?.value as? String ?? "" }
    private var filename: String? { data?["filename"]?.value as? String }
    private var lineCount: Int {
        data?["lineCount"]?.value as? Int
            ?? data?["line_count"]?.value as? Int
            ?? code.components(separatedBy: "\n").count
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: 0) {
                if code.isEmpty {
                    VStack(spacing: .spacing4) {
                        Circle()
                            .fill(LinearGradient.primary)
                            .frame(width: 12, height: 12)
                        Text(LocalizationManager.shared.text("common.processing"))
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Text(previewCode)
                        .font(.system(size: 12, design: .monospaced))
                        .lineSpacing(4)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(8)
                        .truncationMode(.tail)
                        .padding(.top, .spacing5)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
            }
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
                        Icon("copy", size: 16)
                    }
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

    private var previewCode: String {
        code.components(separatedBy: "\n").prefix(8).joined(separator: "\n")
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
                Icon("sheets", size: 32)
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
