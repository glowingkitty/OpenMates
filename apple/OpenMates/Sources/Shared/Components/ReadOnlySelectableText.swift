// Read-only embed text uses native range handles with an OpenMates Copy action.
// Web: frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//      frontend/packages/ui/src/components/embeds/code/CodeEmbedFullscreen.svelte
//      frontend/packages/ui/src/components/embeds/web/WebsiteEmbedFullscreen.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

private struct ReadOnlyTextSelectionKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var readOnlyTextSelection: Bool {
        get { self[ReadOnlyTextSelectionKey.self] }
        set { self[ReadOnlyTextSelectionKey.self] = newValue }
    }
}

/// Selection stays in TextKit; the small action overlay leaves handles, links
/// and the surrounding scroll viewport interactive. No annotation/chat action
/// is registered for these read-only surfaces.
struct ReadOnlySelectableText: View {
    let content: NSAttributedString
    let identifier: String
    var wrapsText = true
    // Route source-quote highlight identity to the native text only. Applying
    // it outside this view would overwrite the Copy overlay's own identifier.
    var textAccessibilityIdentifier: String? = nil
    @State private var selection: MessageTextSelectionSnapshot?

    var body: some View {
        PlatformMessageSelectableText(content: AttributedString(), context: .init(
            messageID: identifier, preserveWhitespace: true,
            onSelection: { selection = $0 },
            onContextMenu: { selection = $0 }
        ), monospace: false, attributedContent: content, wrapsText: wrapsText)
        .accessibilityIdentifier(textAccessibilityIdentifier ?? identifier)
        .overlay(alignment: .topLeading) {
            if let selection {
                GeometryReader { geometry in
                    let frame = geometry.frame(in: .global)
                    let anchor = selection.anchorRect ?? frame
                    Button { Self.copy(selection) } label: {
                        HStack(spacing: .spacing1) {
                            Icon("copy", size: 14)
                            Text(AppStrings.copy).font(.omXs).fontWeight(.semibold)
                        }
                        .foregroundStyle(Color.grey0)
                        .padding(.spacing2)
                        .frame(minWidth: 72, minHeight: 36)
                        .background(Color.grey100)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("\(identifier)-copy-selection")
                    .offset(x: min(max(0, anchor.minX - frame.minX), max(0, geometry.size.width - 100)),
                            y: max(0, anchor.minY - frame.minY - 44))
                }
            }
        }
        .onChange(of: content.string) { _, _ in selection = nil }
    }

    static func copy(_ selection: MessageTextSelectionSnapshot) {
        #if os(iOS)
        UIPasteboard.general.string = selection.copyText
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(selection.copyText, forType: .string)
        #endif
    }

    /// Explicit web typography survives the UIKit/AppKit boundary, including
    /// syntax foreground colors and source quote background spans.
    static func attributed(_ text: AttributedString, pointSize: CGFloat = 16,
                           color: Color = .fontPrimary, monospace: Bool = false,
                           lineHeight: CGFloat? = nil, italic: Bool = false, bold: Bool = false) -> NSAttributedString {
        let plain = String(text.characters)
        let paragraph = NSMutableParagraphStyle()
        if let lineHeight {
            paragraph.minimumLineHeight = lineHeight
            paragraph.maximumLineHeight = lineHeight
        }
        #if os(iOS)
        let base = UIFont(name: FontRegistration.mediumPostScriptName, size: pointSize)
            ?? UIFont.systemFont(ofSize: pointSize, weight: .medium)
        var font = monospace ? UIFont.monospacedSystemFont(ofSize: pointSize, weight: bold ? .bold : .regular) : base
        if italic, let descriptor = font.fontDescriptor.withSymbolicTraits(.traitItalic) {
            font = UIFont(descriptor: descriptor, size: pointSize)
        }
        let foreground = NativeSelectableTextColors.color(color)
        #else
        let base = NSFont(name: FontRegistration.mediumPostScriptName, size: pointSize)
            ?? NSFont.systemFont(ofSize: pointSize, weight: .medium)
        var font = monospace ? NSFont.monospacedSystemFont(ofSize: pointSize, weight: bold ? .bold : .regular) : base
        if italic { font = NSFontManager.shared.convert(font, toHaveTrait: .italicFontMask) }
        let foreground = NativeSelectableTextColors.color(color)
        #endif
        let result = NSMutableAttributedString(string: plain, attributes: [
            .font: font, .foregroundColor: foreground, NativeSelectableTextColors.foregroundSource: color, .paragraphStyle: paragraph
        ])
        for run in text.runs {
            let start = text.characters.distance(from: text.characters.startIndex, to: run.range.lowerBound)
            let end = text.characters.distance(from: text.characters.startIndex, to: run.range.upperBound)
            let lower = plain.index(plain.startIndex, offsetBy: start)
            let upper = plain.index(plain.startIndex, offsetBy: end)
            let range = NSRange(lower..<upper, in: plain)
            #if os(iOS)
            if let color = run.foregroundColor { result.addAttribute(.foregroundColor, value: NativeSelectableTextColors.color(color), range: range) }
            if let color = run.backgroundColor { result.addAttribute(.backgroundColor, value: NativeSelectableTextColors.color(color), range: range) }
            #else
            if let color = run.foregroundColor { result.addAttribute(.foregroundColor, value: NativeSelectableTextColors.color(color), range: range) }
            if let color = run.backgroundColor { result.addAttribute(.backgroundColor, value: NativeSelectableTextColors.color(color), range: range) }
            #endif
            if let color = run.foregroundColor { result.addAttribute(NativeSelectableTextColors.foregroundSource, value: color, range: range) }
            if let color = run.backgroundColor { result.addAttribute(NativeSelectableTextColors.backgroundSource, value: color, range: range) }
            if let link = run.link { result.addAttribute(.link, value: link, range: range) }
            if let intent = run.inlinePresentationIntent {
                if intent.contains(.strikethrough) {
                    result.addAttribute(.strikethroughStyle, value: NSUnderlineStyle.single.rawValue, range: range)
                }
                var styled = font
                #if os(iOS)
                var traits = font.fontDescriptor.symbolicTraits
                if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
                if intent.contains(.emphasized) { traits.insert(.traitItalic) }
                if let descriptor = font.fontDescriptor.withSymbolicTraits(traits) { styled = UIFont(descriptor: descriptor, size: pointSize) }
                #else
                if intent.contains(.stronglyEmphasized) { styled = NSFontManager.shared.convert(styled, toHaveTrait: .boldFontMask) }
                if intent.contains(.emphasized) { styled = NSFontManager.shared.convert(styled, toHaveTrait: .italicFontMask) }
                #endif
                result.addAttribute(.font, value: styled, range: range)
            }
        }
        return result
    }
}

/// Foundation's AttributedString bridge does not transfer SwiftUI Color attributes.
/// Retain the source token and resolve it against the view's effective scheme,
/// including an app theme override that differs from the operating system theme.
@MainActor
enum NativeSelectableTextColors {
    static let foregroundSource = NSAttributedString.Key("openmates.foregroundColorSource")
    static let backgroundSource = NSAttributedString.Key("openmates.backgroundColorSource")

    #if os(iOS)
    static func color(_ source: Color, scheme: ColorScheme? = nil) -> UIColor {
        guard let scheme else { return UIColor(source) }
        var environment = EnvironmentValues()
        environment.colorScheme = scheme
        return UIColor(cgColor: source.resolve(in: environment).cgColor)
    }
    #else
    static func color(_ source: Color, scheme: ColorScheme? = nil) -> NSColor {
        guard let scheme else { return NSColor(source) }
        var environment = EnvironmentValues()
        environment.colorScheme = scheme
        return NSColor(cgColor: source.resolve(in: environment).cgColor) ?? NSColor(source)
    }
    #endif

    static func transfer(_ value: AttributedString, into result: NSMutableAttributedString) {
        let plain = String(value.characters)
        result.addAttributes([.foregroundColor: color(.fontPrimary), foregroundSource: Color.fontPrimary],
                             range: NSRange(location: 0, length: result.length))
        for run in value.runs {
            let start = value.characters.distance(from: value.characters.startIndex, to: run.range.lowerBound)
            let end = value.characters.distance(from: value.characters.startIndex, to: run.range.upperBound)
            let range = NSRange(plain.index(plain.startIndex, offsetBy: start)..<plain.index(plain.startIndex, offsetBy: end), in: plain)
            if let source = run.foregroundColor {
                result.addAttributes([.foregroundColor: color(source), foregroundSource: source], range: range)
            }
            if let source = run.backgroundColor {
                result.addAttributes([.backgroundColor: color(source), backgroundSource: source], range: range)
            }
            if let link = run.link { result.addAttribute(.link, value: link, range: range) }
        }
    }

    static func resolved(_ content: NSAttributedString, scheme: ColorScheme) -> NSAttributedString {
        let result = NSMutableAttributedString(attributedString: content)
        content.enumerateAttributes(in: NSRange(location: 0, length: content.length)) { attributes, range, _ in
            if let source = attributes[foregroundSource] as? Color {
                result.addAttribute(.foregroundColor, value: color(source, scheme: scheme), range: range)
            } else if attributes[.foregroundColor] == nil {
                result.addAttribute(.foregroundColor, value: color(.fontPrimary, scheme: scheme), range: range)
            }
            if let source = attributes[backgroundSource] as? Color {
                result.addAttribute(.backgroundColor, value: color(source, scheme: scheme), range: range)
            }
        }
        return result
    }
}
