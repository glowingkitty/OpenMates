// Project Overview README keeps Markdown blocks and lazily resolves safe images.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/projects/ProjectReadme.svelte
// Service: frontend/packages/ui/src/services/projectReadme.ts
// CSS: ProjectReadme.svelte .markdown-body, .readme-image-placeholder
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// Rendered reference: .runtime/build85-web-reference/projects-readme.json
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.surface.semantic-parity
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.maintenance
import SwiftUI
import ImageIO
#if os(iOS)
import UIKit
#else
import AppKit
#endif

struct ProjectReadmeImage: Equatable {
    let source: String
    let alt: String
    var linkURL: URL? = nil
}

enum ProjectReadmePart: Equatable {
    case markdown(MarkdownBlock)
    case literal(String)
}

enum ProjectReadmeInlinePart: Equatable {
    case text(AttributedString)
    case image(ProjectReadmeImage)
}

/// Reuses the production block parser, without enabling chat protocol controls.
/// Parsing is done when the document changes, never from the view body.
enum ProjectReadmeDocument {
    private static let imagePattern = try! NSRegularExpression(pattern:
        #"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)"#)
    private static let definitionPattern = try! NSRegularExpression(pattern:
        #"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|([^\s]+))(?:\s+.*)?$"#)
    private static let referencePattern = try! NSRegularExpression(pattern:
        #"!\[([^\]]+)\](?:\s*\[([^\]]*)\])?"#)
    private static let referenceLinkPattern = try! NSRegularExpression(pattern:
        #"(?<!!)\[((?:!\[[^\]]*\]\([^)]*\))|[^\]]+)\]\s*\[([^\]]*)\]"#)
    private static let linkedImageSuffix = try! NSRegularExpression(pattern: #"^\]\(\s*(?:<([^>]+)>|([^\s)]+))\s*\)"#)
    private static let inlineCodePattern = try! NSRegularExpression(pattern: #"(`+)[\s\S]*?\1"#)

    private struct Fence {
        let marker: Character
        let length: Int
        let language: String?

        static func opening(_ line: String) -> Fence? {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard let marker = trimmed.first, marker == "`" || marker == "~" else { return nil }
            let length = trimmed.prefix(while: { $0 == marker }).count
            guard length >= 3 else { return nil }
            let info = String(trimmed.dropFirst(length)).trimmingCharacters(in: .whitespaces)
            guard marker != "`" || !info.contains("`") else { return nil }
            return Fence(marker: marker, length: length, language: info.isEmpty ? nil : info)
        }

        func closes(_ line: String) -> Bool {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            let count = trimmed.prefix(while: { $0 == marker }).count
            return count >= length && trimmed.dropFirst(count).trimmingCharacters(in: .whitespaces).isEmpty
        }
    }

    static func parse(_ source: String) -> [ProjectReadmePart] {
        let normalized = resolveReferences(source)
        var parts: [ProjectReadmePart] = []
        var outside: [String] = []
        var code: [String] = []
        var fence: Fence?
        for line in normalized.components(separatedBy: "\n") {
            if let active = fence {
                if active.closes(line) {
                    parts.append(.markdown(.codeBlock(language: active.language, code: code.joined(separator: "\n"))))
                    code = []
                    fence = nil
                } else { code.append(line) }
            } else if let opening = Fence.opening(line) {
                parts += parseUnfenced(outside.joined(separator: "\n"))
                outside = []
                fence = opening
            } else { outside.append(line) }
        }
        if let active = fence {
            parts.append(.markdown(.codeBlock(language: active.language, code: code.joined(separator: "\n"))))
        }
        parts += parseUnfenced(outside.joined(separator: "\n"))
        return parts
    }

    private static func parseUnfenced(_ source: String) -> [ProjectReadmePart] {
        let bytes = Array(source.utf8)
        return MarkdownParser.parseSpans(source).map { parsed in
            switch parsed.block {
            case .paragraph, .codeBlock, .header, .horizontalRule, .unorderedList, .orderedList, .table, .blockquote:
                return .markdown(parsed.block)
            default:
                // Chat-only protocol nodes are ordinary literal README content.
                let raw = String(decoding: bytes[parsed.sourceStartUTF8..<parsed.sourceEndUTF8], as: UTF8.self)
                    .trimmingCharacters(in: .newlines)
                return .literal(raw)
            }
        }
    }

    /// Reference definitions are removed only outside fenced code. Image
    /// references are expanded outside inline code, including list/table cells.
    private static func resolveReferences(_ source: String) -> String {
        let lines = source.components(separatedBy: "\n")
        var references: [String: String] = [:]
        var definitionLines = Set<Int>()
        var fence: Fence?
        for (index, line) in lines.enumerated() {
            if let active = fence {
                if active.closes(line) { fence = nil }
                continue
            }
            if let opening = Fence.opening(line) { fence = opening; continue }
            let ns = line as NSString
            if let match = definitionPattern.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) {
                let label = normalizedLabel(ns.substring(with: match.range(at: 1)))
                let range = match.range(at: 2).location == NSNotFound ? match.range(at: 3) : match.range(at: 2)
                if references[label] == nil { references[label] = ns.substring(with: range) }
                definitionLines.insert(index)
            }
        }
        fence = nil
        return lines.enumerated().map { index, line in
            if let active = fence {
                if active.closes(line) { fence = nil }
                return line
            }
            if let opening = Fence.opening(line) { fence = opening; return line }
            if definitionLines.contains(index) { return "" }
            let ns = line as NSString
            let codeRanges = inlineCodePattern.matches(in: line, range: NSRange(location: 0, length: ns.length)).map(\.range)
            var result = line
            for match in referencePattern.matches(in: line, range: NSRange(location: 0, length: ns.length)).reversed() {
                guard !codeRanges.contains(where: { NSIntersectionRange($0, match.range).length > 0 }),
                      match.range.location == 0 || ns.substring(with: NSRange(location: match.range.location - 1, length: 1)) != "\\",
                      NSMaxRange(match.range) == ns.length || ns.substring(with: NSRange(location: NSMaxRange(match.range), length: 1)) != "(" else { continue }
                let alt = ns.substring(with: match.range(at: 1))
                let ref = match.range(at: 2).location == NSNotFound ? alt : ns.substring(with: match.range(at: 2))
                guard let source = references[normalizedLabel(ref.isEmpty ? alt : ref)],
                      let range = Range(match.range, in: result) else { continue }
                result.replaceSubrange(range, with: "![\(alt)](<\(source)>)")
            }
            let expanded = result as NSString
            let expandedRange = NSRange(location: 0, length: expanded.length)
            let expandedCodeRanges = inlineCodePattern.matches(in: result, range: expandedRange).map(\.range)
            for match in referenceLinkPattern.matches(in: result, range: expandedRange).reversed() {
                guard !expandedCodeRanges.contains(where: { NSIntersectionRange($0, match.range).length > 0 }) else { continue }
                let label = expanded.substring(with: match.range(at: 1))
                let reference = expanded.substring(with: match.range(at: 2))
                guard let target = references[normalizedLabel(reference.isEmpty ? label : reference)],
                      let range = Range(match.range, in: result) else { continue }
                result.replaceSubrange(range, with: "[\(label)](<\(target)>)")
            }
            return result
        }.joined(separator: "\n")
    }

    private static func normalizedLabel(_ label: String) -> String {
        label.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
    }

    static func inlineParts(_ text: String) -> [ProjectReadmeInlinePart] {
        let ns = text as NSString
        let range = NSRange(location: 0, length: ns.length)
        let codeRanges = inlineCodePattern.matches(in: text, range: range).map(\.range)
        var parts: [ProjectReadmeInlinePart] = []
        var offset = 0
        for match in imagePattern.matches(in: text, range: range) {
            guard match.range.location >= offset, !codeRanges.contains(where: { NSIntersectionRange($0, match.range).length > 0 }),
                  match.range.location == 0 || ns.substring(with: NSRange(location: match.range.location - 1, length: 1)) != "\\" else { continue }
            var start = match.range.location
            var end = NSMaxRange(match.range)
            var linkURL: URL?
            if start > offset, ns.substring(with: NSRange(location: start - 1, length: 1)) == "[" {
                let trailing = ns.substring(from: end)
                if let suffix = linkedImageSuffix.firstMatch(in: trailing, range: NSRange(location: 0, length: (trailing as NSString).length)) {
                    let targetRange = suffix.range(at: 1).location == NSNotFound ? suffix.range(at: 2) : suffix.range(at: 1)
                    let target = URL(string: (trailing as NSString).substring(with: targetRange))
                    if let target, ["https", "http", "mailto"].contains(target.scheme?.lowercased() ?? "") { linkURL = target }
                    start -= 1
                    end += suffix.range.length
                }
            }
            let prefix = ns.substring(with: NSRange(location: offset, length: start - offset))
            if !prefix.isEmpty { parts.append(.text(inline(prefix))) }
            let sourceRange = match.range(at: 2).location != NSNotFound ? match.range(at: 2) : match.range(at: 3)
            parts.append(.image(ProjectReadmeImage(source: ns.substring(with: sourceRange), alt: ns.substring(with: match.range(at: 1)), linkURL: linkURL)))
            offset = end
        }
        let suffix = ns.substring(from: offset)
        if !suffix.isEmpty { parts.append(.text(inline(suffix))) }
        return parts
    }

    static func textContents(_ part: ProjectReadmePart) -> [String] {
        guard case .markdown(let block) = part else { return [] }
        switch block {
        case .header(_, let text), .paragraph(let text), .blockquote(let text): return [text]
        case .unorderedList(let items), .orderedList(let items): return items
        case .table(let headers, let rows): return headers + rows.flatMap { $0 }
        default: return []
        }
    }

    static func relativePath(_ source: String) -> String? {
        guard !source.hasPrefix("/"), !source.hasPrefix("#"), URLComponents(string: source)?.scheme == nil,
              let decoded = source.components(separatedBy: CharacterSet(charactersIn: "?#")).first?.removingPercentEncoding,
              !decoded.contains("\\") else { return nil }
        var parts: [String] = []
        for part in decoded.split(separator: "/") {
            if part == "." { continue }
            if part == ".." { guard !parts.isEmpty else { return nil }; parts.removeLast() }
            else { parts.append(String(part)) }
        }
        return ProjectWorkspacePath.normalized(parts.joined(separator: "/"))
    }

    static func publicImageURL(_ source: String) -> URL? {
        let raw = source.hasPrefix("//") ? "https:" + source : source
        guard let url = URLComponents(string: raw), let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme), url.user == nil, url.password == nil,
              let host = url.host?.lowercased(), !host.isEmpty,
              host != "localhost", !host.hasSuffix(".localhost"), !host.contains(":"), !host.hasPrefix("["),
              host.range(of: #"^(?:\d{1,3}\.){3}\d{1,3}$"#, options: .regularExpression) == nil,
              let absolute = url.url?.absoluteString else { return nil }
        var proxy = URLComponents(string: "https://preview.openmates.org/api/v1/image")
        proxy?.queryItems = [URLQueryItem(name: "url", value: absolute), URLQueryItem(name: "max_width", value: "1920")]
        return proxy?.url
    }

    static func inline(_ text: String) -> AttributedString {
        // Web's html:false presents raw tags as text. Keep autolinks and
        // angle-bracket link destinations while escaping actual HTML tags.
        let html = try! NSRegularExpression(pattern: #"<(?!https?://|mailto:)[A-Za-z!/][^>]*>"#)
        let ns = text as NSString
        var literalHTML = text
        for match in html.matches(in: text, range: NSRange(location: 0, length: ns.length)).reversed() {
            guard let range = Range(match.range, in: literalHTML) else { continue }
            let tag = ns.substring(with: match.range)
            literalHTML.replaceSubrange(range, with: "\\<\(tag.dropFirst().dropLast())\\>")
        }
        var attributed = (try? AttributedString(markdown: literalHTML,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        let unsafe = attributed.runs.compactMap { run -> Range<AttributedString.Index>? in
            guard let link = run.link else { return nil }
            return ["https", "http", "mailto"].contains(link.scheme?.lowercased() ?? "") ? nil : run.range
        }
        for range in unsafe { attributed[range].link = nil }
        return attributed
    }
}

struct ProjectReadmeView: View {
    let markdown: String
    let identity: ProjectReadmePresentationIdentity
    let viewport: CGRect
    let validate: () async throws -> Void
    let loadImage: (String) async throws -> Data
    @State private var parts: [ProjectReadmePart] = []
    @State private var allowedImageSources: Set<String> = []
    @State private var imageLoads = ProjectReadmeImageLoadQueue()
    @State private var inlineContents: [String: [ProjectReadmeInlinePart]] = [:]

    var body: some View {
        LazyVStack(alignment: .leading, spacing: .spacing8) {
            ForEach(Array(parts.enumerated()), id: \.offset) { index, part in
                switch part {
                case .markdown(let block): blockView(block, index: index)
                case .literal(let text): Text(verbatim: text)
                }
            }
        }
        .font(.omP).foregroundStyle(Color.fontPrimary)
        .environment(\.projectReadmeViewport, viewport)
        .textSelection(.enabled)
        .task(id: identity) {
            allowedImageSources = []
            parts = []
            inlineContents = [:]
            let parsedParts = ProjectReadmeDocument.parse(markdown)
            var sources: Set<String> = []
            var parsedInline: [String: [ProjectReadmeInlinePart]] = [:]
            for part in parsedParts {
                guard !Task.isCancelled else { return }
                await Task.yield()
                for text in ProjectReadmeDocument.textContents(part) where parsedInline[text] == nil {
                    let content = ProjectReadmeDocument.inlineParts(text)
                    parsedInline[text] = content
                    for inline in content {
                        if case .image(let image) = inline { sources.insert(image.source) }
                    }
                }
            }
            guard !Task.isCancelled else { return }
            parts = parsedParts
            inlineContents = parsedInline
            allowedImageSources = sources
        }
    }

    @ViewBuilder private func blockView(_ block: MarkdownBlock, index: Int) -> some View {
        switch block {
        case .header(let level, let text):
            VStack(alignment: .leading, spacing: .spacing4) {
                inlineContent(text)
                    .font(level == 1 ? .omH2 : level == 2 ? .omH3 : .omH4)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("project-readme-heading-\(index)")
                if level <= 2 { Rectangle().fill(Color.grey25).frame(height: 1) }
            }.padding(.top, index == 0 ? 0 : .spacing8)
        case .paragraph(let text): inlineContent(text)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-readme-paragraph-\(index)")
        case .unorderedList(let items): list(items, ordered: false, index: index)
        case .orderedList(let items): list(items, ordered: true, index: index)
        case .blockquote(let text):
            HStack(alignment: .top, spacing: .spacing8) {
                Rectangle().fill(Color.grey30).frame(width: 4)
                inlineContent(text).foregroundStyle(Color.fontTertiary)
            }.fixedSize(horizontal: false, vertical: true)
        case .horizontalRule: Rectangle().fill(Color.grey25).frame(height: 1)
        case .codeBlock(_, let code):
            ScrollView(.horizontal) { Text(verbatim: code).font(.omSmall).monospaced() }
                .accessibilityIdentifier("project-readme-code-\(index)")
                .padding(.spacing8).background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
        case .table(let headers, let rows):
            ScrollView(.horizontal) {
                Grid(alignment: .topLeading, horizontalSpacing: 0, verticalSpacing: 0) {
                    ForEach(Array(([headers] + rows).enumerated()), id: \.offset) { row, cells in
                        GridRow {
                            ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                                inlineContent(cell).fontWeight(row == 0 ? .semibold : .regular)
                                    .padding(.horizontal, .spacing8).padding(.vertical, .spacing4)
                                    .background(row == 0 ? Color.grey10 : Color.clear)
                                    .overlay(Rectangle().stroke(Color.grey30, lineWidth: 1))
                            }
                        }
                    }
                }
            }
            .modifier(ProjectReadmeViewportClip())
            .accessibilityIdentifier("project-readme-table-\(index)")
        default: EmptyView()
        }
    }

    private func inlineContent(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            ForEach(Array((inlineContents[text] ?? []).enumerated()), id: \.offset) { _, part in
                switch part {
                case .text(let attributed): Text(attributed)
                case .image(let image):
                    ProjectReadmeImageView(image: image, identity: identity,
                        permitsLoad: allowedImageSources.contains(image.source), queue: imageLoads,
                        validate: validate, load: loadImage)
                }
            }
        }
    }

    private func list(_ items: [String], ordered: Bool, index: Int) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            ForEach(Array(items.enumerated()), id: \.offset) { row, item in
                HStack(alignment: .top, spacing: .spacing4) {
                    Text(verbatim: ordered ? "\(row + 1)." : "•")
                    inlineContent(item)
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-readme-list-\(index)-\(row)")
            }
        }.padding(.leading, .spacing8)
    }
}

/// Lazy image views share one foreground read at a time. Cancellation removes a
/// queued view before it can fetch; changing Project/account still uses store fences.
@MainActor
final class ProjectReadmeImageLoadQueue {
    private var loading = false
    private var waiters: [(UUID, CheckedContinuation<Void, Error>)] = []

    func load(_ source: String, operation: (String) async throws -> Data) async throws -> Data {
        let id = UUID()
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            if loading {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    waiters.append((id, continuation))
                }
            } else {
                loading = true
            }
        } onCancel: {
            Task { @MainActor in self.cancel(id) }
        }
        defer { release() }
        try Task.checkCancellation()
        await Task.yield()
        try Task.checkCancellation()
        return try await operation(source)
    }

    private func cancel(_ id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.0 == id }) else { return }
        waiters.remove(at: index).1.resume(throwing: CancellationError())
    }

    private func release() {
        if waiters.isEmpty { loading = false }
        else { waiters.removeFirst().1.resume() }
    }
}

/// A mounted paragraph/list/table may contain many eager image rows. Residency
/// follows actual clipped viewport intersection, independently of view mounting.
enum ProjectReadmeImageResidency {
    static func clipped(_ viewport: CGRect, to bounds: CGRect) -> CGRect {
        guard valid(viewport), valid(bounds) else { return .zero }
        let intersection = viewport.intersection(bounds)
        return valid(intersection) ? intersection : .zero
    }

    static func isVisible(frame: CGRect, viewport: CGRect) -> Bool {
        valid(clipped(viewport, to: frame))
    }

    private static func valid(_ rect: CGRect) -> Bool {
        !rect.isNull && !rect.isInfinite && rect.minX.isFinite && rect.minY.isFinite &&
            rect.width.isFinite && rect.height.isFinite && rect.width > 0 && rect.height > 0
    }
}

private struct ProjectReadmeViewportKey: EnvironmentKey {
    static let defaultValue = CGRect.zero
}

private extension EnvironmentValues {
    var projectReadmeViewport: CGRect {
        get { self[ProjectReadmeViewportKey.self] }
        set { self[ProjectReadmeViewportKey.self] = newValue }
    }
}

/// Horizontal table clipping narrows the inherited vertical scroll viewport.
/// The production Grid and selection behavior remain intact.
private struct ProjectReadmeViewportClip: ViewModifier {
    @Environment(\.projectReadmeViewport) private var inheritedViewport
    @State private var bounds = CGRect.zero

    func body(content: Content) -> some View {
        content
            .environment(\.projectReadmeViewport, ProjectReadmeImageResidency.clipped(inheritedViewport, to: bounds))
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { bounds = $0 }
    }
}

/// Debug-only residency evidence belongs to the existing production renderer.
/// Values contain counts/booleans, never private image sources or image bytes.
private struct ProjectReadmeImageEvidence: ViewModifier {
    let resident: Bool
    let visible: Bool
    let loads: Int

    @ViewBuilder func body(content: Content) -> some View {
        #if DEBUG
        content.accessibilityElement(children: .contain)
            .accessibilityIdentifier("project-readme-image-state")
            .accessibilityValue("resident=\(resident);viewport=\(visible);loads=\(loads)")
        #else
        content
        #endif
    }
}

private struct ProjectReadmeImageTaskIdentity: Hashable {
    let presentation: ProjectReadmePresentationIdentity
    let source: String
    let permitsLoad: Bool
    let isVisible: Bool
}

private struct ProjectReadmeImageView: View {
    let image: ProjectReadmeImage
    let identity: ProjectReadmePresentationIdentity
    let permitsLoad: Bool
    let queue: ProjectReadmeImageLoadQueue
    let validate: () async throws -> Void
    let load: (String) async throws -> Data
    @Environment(\.projectReadmeViewport) private var viewport
    @State private var isVisible = false
    @State private var loadCount = 0
    @State private var decoded: Image?
    @State private var decodedSource: String?
    @State private var decodedIdentity: ProjectReadmePresentationIdentity?
    @State private var decodedAspectRatio: CGFloat?
    @Environment(\.openURL) private var openURL
    var body: some View {
        Group {
            if let link = image.linkURL {
                Button { openURL(link) } label: { imageContent }.buttonStyle(.plain)
            } else { imageContent }
        }
        .frame(maxWidth: .infinity).clipShape(RoundedRectangle(cornerRadius: .radius3))
        .modifier(ProjectReadmeImageEvidence(resident: decoded != nil, visible: isVisible, loads: loadCount))
        .accessibilityLabel(image.alt)
        .onGeometryChange(for: Bool.self) {
            ProjectReadmeImageResidency.isVisible(frame: $0.frame(in: .global), viewport: viewport)
        } action: { visible in
            isVisible = visible
            if !visible { decoded = nil }
        }
        .onDisappear { isVisible = false; decoded = nil }
        .task(id: ProjectReadmeImageTaskIdentity(presentation: identity, source: image.source,
            permitsLoad: permitsLoad, isVisible: isVisible)) {
            decoded = nil
            if decodedSource != image.source || decodedIdentity != identity {
                decodedSource = image.source
                decodedIdentity = identity
                decodedAspectRatio = nil
            }
            guard permitsLoad, isVisible else { return }
            let result = try? await queue.load(image.source) { source in
                // A row can scroll away while queued behind another image.
                guard isVisible else { throw CancellationError() }
                try Task.checkCancellation()
                loadCount += 1
                return try await load(source)
            }
            guard isVisible, !Task.isCancelled else { return }
            if let rendered = result.flatMap(decode) {
                // Account/team/key/document authority can change while loading or
                // decoding. Recheck after decoding before publishing private pixels.
                guard (try? await validate()) != nil, isVisible, !Task.isCancelled else { return }
                decoded = rendered.image
                decodedAspectRatio = rendered.aspectRatio
            }
        }
    }
    private var imageContent: some View {
        Group {
            if let decoded {
                decoded.resizable().scaledToFit().accessibilityIdentifier("project-readme-image-rendered")
            } else if let decodedAspectRatio {
                // Release offscreen pixels without collapsing the document's rows.
                Color.clear.aspectRatio(decodedAspectRatio, contentMode: .fit).overlay { placeholder }
            } else { placeholder }
        }
    }
    private var placeholder: some View {
        HStack(spacing: .spacing4) {
            Icon("image", size: 20)
            if !image.alt.isEmpty { Text(verbatim: image.alt) }
        }.font(.omSmall).foregroundStyle(Color.fontSecondary)
            .padding(.spacing4).background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
    }
    private func decode(_ data: Data) -> (image: Image, aspectRatio: CGFloat)? {
        guard data.count <= 2 * 1024 * 1024,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: 1920,
                kCGImageSourceCreateThumbnailWithTransform: true,
              ] as CFDictionary) else { return nil }
        return (Image(decorative: thumbnail, scale: 1), CGFloat(thumbnail.width) / CGFloat(thumbnail.height))
    }
}
