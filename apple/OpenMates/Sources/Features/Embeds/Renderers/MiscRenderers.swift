// Miscellaneous embed renderers — mail, math, reminder, focus mode, generic fallback.

import SwiftUI

struct MailRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var subject: String? { data?["subject"]?.value as? String }
    private var to: String? { data?["to"]?.value as? String }
    private var body_: String? { data?["body"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let subject {
                Text(subject).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 1 : nil)
            }
            if let to {
                Label(to, systemImage: "person").font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if let body_ {
                Text(body_).font(mode == .preview ? .omXs : .omP)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(mode == .preview ? 3 : nil)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct MathPlotRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var svgData: String? { data?["svg_data"]?.value as? String }

    @State private var svgImage: Data?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                if let svgData, let data = svgData.data(using: .utf8) {
                    SVGImageView(svgData: data)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Image(systemName: "chart.xyaxis.line")
                        .font(.system(size: 32))
                        .foregroundStyle(Color.fontTertiary)
                }
                if let title {
                    Text(title).font(.omSmall)
                        .foregroundStyle(Color.fontPrimary).lineLimit(1)
                }
            }
            .padding(.spacing3)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let title {
                    Text(title).font(.omH4).fontWeight(.medium).foregroundStyle(Color.fontPrimary)
                }
                if let svgData, let data = svgData.data(using: .utf8) {
                    SVGImageView(svgData: data)
                        .frame(minHeight: 300)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                } else {
                    Image(systemName: "chart.xyaxis.line")
                        .font(.system(size: 48))
                        .foregroundStyle(Color.fontTertiary)
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }
}

// SVG rendering via WKWebView for plot data
#if os(iOS)
import WebKit

struct SVGImageView: UIViewRepresentable {
    let svgData: Data

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let html = """
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{margin:0;display:flex;justify-content:center;align-items:center;background:transparent}
        svg{max-width:100%;height:auto}</style></head>
        <body>\(String(data: svgData, encoding: .utf8) ?? "")</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#elseif os(macOS)
import WebKit

struct SVGImageView: NSViewRepresentable {
    let svgData: Data

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView()
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        let html = """
        <html><head><style>body{margin:0;display:flex;justify-content:center;align-items:center}
        svg{max-width:100%;height:auto}</style></head>
        <body>\(String(data: svgData, encoding: .utf8) ?? "")</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#endif

struct MathCalculateRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var expression: String? { data?["expression"]?.value as? String }
    private var result: String? { data?["result"]?.value as? String }
    private var steps: String? { data?["steps"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let expression {
                Text(expression)
                    .font(.system(mode == .preview ? .body : .title3, design: .monospaced))
                    .foregroundStyle(Color.fontSecondary)
            }
            if let result {
                HStack(spacing: .spacing2) {
                    Text("=").foregroundStyle(Color.fontTertiary)
                    Text(result).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                }
                .font(mode == .preview ? .omP : .omH3)
            }
            if mode == .fullscreen, let steps {
                Divider()
                Text(steps)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(Color.fontSecondary)
                    .textSelection(.enabled)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct ReminderRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var datetime: String? { data?["datetime"]?.value as? String }
    private var recurring: String? { data?["recurring"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Image(systemName: SFSymbol.bell)
                .font(.system(size: mode == .preview ? 24 : 32))
                .foregroundStyle(Color.buttonPrimary)
            if let title {
                Text(title).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
            }
            if let datetime {
                Label(datetime, systemImage: SFSymbol.clock).font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
            if let recurring {
                Label(recurring, systemImage: "repeat").font(.omXs)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct FocusModeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    var body: some View {
        VStack(spacing: .spacing3) {
            Image(systemName: "scope")
                .font(.system(size: mode == .preview ? 28 : 36))
                .foregroundStyle(Color.buttonPrimary)
            Text("Focus Mode Active")
                .font(mode == .preview ? .omSmall : .omP)
                .foregroundStyle(Color.fontPrimary)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil)
    }
}

struct GenericEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let type: String

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Image(systemName: "doc.text")
                .font(.system(size: mode == .preview ? 24 : 32))
                .foregroundStyle(Color.fontTertiary)
            Text(type)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            if mode == .fullscreen, let data {
                ForEach(Array(data.keys.sorted()), id: \.self) { key in
                    HStack(alignment: .top) {
                        Text(key).font(.omXs).foregroundStyle(Color.fontTertiary).frame(width: 100, alignment: .leading)
                        Text("\(data[key]?.value ?? "" as Any)").font(.omXs).foregroundStyle(Color.fontPrimary)
                    }
                }
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}
