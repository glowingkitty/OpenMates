// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.inline-entity-interaction
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/ChatMessage.svelte, MessageSelectionToolbar.svelte
// CSS: frontend/packages/ui/src/styles/chat.css, MessageSelectionToolbar.svelte
// ────────────────────────────────────────────────────────────────────
import SwiftUI
import CoreText
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// Resolve bundled weight before slant: Lexend Deca has a 600 face but no
/// italic face. A font matrix works in TextKit 2, unlike NSObliquenessAttributeName.
@MainActor
enum NativeMarkdownEmphasisFont {
    static let semiboldPostScriptName = "LexendDeca-SemiBold"
    static let syntheticSlant: CGFloat = 0.2

    #if os(iOS)
    static func resolve(pointSize: CGFloat, monospace: Bool, bold: Bool = false, italic: Bool = false, regularMonospace: Bool = false) -> UIFont {
        let font = monospace
            ? UIFont.monospacedSystemFont(ofSize: pointSize, weight: bold ? .bold : (regularMonospace ? .regular : .medium))
            : UIFont(name: bold ? semiboldPostScriptName : FontRegistration.mediumPostScriptName, size: pointSize)
                ?? UIFont.systemFont(ofSize: pointSize, weight: bold ? .semibold : .medium)
        guard italic else { return font }
        if let descriptor = font.fontDescriptor.withSymbolicTraits(font.fontDescriptor.symbolicTraits.union(.traitItalic)) {
            let candidate = UIFont(descriptor: descriptor, size: pointSize)
            if candidate.fontDescriptor.symbolicTraits.contains(.traitItalic), candidate.familyName == font.familyName {
                return candidate
            }
        }
        // UIFont(descriptor:size:) may normalize away a descriptor-only matrix.
        // UIFont and CTFont are toll-free bridged; keep the resolved glyph matrix.
        let base = unsafeBitCast(font, to: CTFont.self)
        var matrix = CGAffineTransform(a: 1, b: 0, c: syntheticSlant, d: 1, tx: 0, ty: 0)
        let oblique = CTFontCreateCopyWithAttributes(base, pointSize, &matrix, nil)
        return unsafeBitCast(oblique, to: UIFont.self)
    }
    #elseif os(macOS)
    static func resolve(pointSize: CGFloat, monospace: Bool, bold: Bool = false, italic: Bool = false, regularMonospace: Bool = false) -> NSFont {
        let font = monospace
            ? NSFont.monospacedSystemFont(ofSize: pointSize, weight: bold ? .bold : (regularMonospace ? .regular : .medium))
            : NSFont(name: bold ? semiboldPostScriptName : FontRegistration.mediumPostScriptName, size: pointSize)
                ?? NSFont.systemFont(ofSize: pointSize, weight: bold ? .semibold : .medium)
        guard italic else { return font }
        let candidate = NSFontManager.shared.convert(font, toHaveTrait: .italicFontMask)
        if candidate.fontDescriptor.symbolicTraits.contains(.italic), candidate.familyName == font.familyName {
            return candidate
        }
        let base = unsafeBitCast(font, to: CTFont.self)
        var matrix = CGAffineTransform(a: 1, b: 0, c: syntheticSlant, d: 1, tx: 0, ty: 0)
        let oblique = CTFontCreateCopyWithAttributes(base, pointSize, &matrix, nil)
        return unsafeBitCast(oblique, to: NSFont.self)
    }
    #endif
}

struct MessageTextSelectionSnapshot: Equatable {
    let messageID: String
    let segmentID: String
    let anchor: MessageHighlightAnchor
    let range: NSRange
    /// Clipboard content retains the native range verbatim; annotations use the trimmed anchor.
    var copyText: String = ""
    var anchorRect: CGRect? = nil
    /// Keep the owning text and its native range handles interactive under the toolbar.
    var interactionRect: CGRect? = nil
    static func capture(messageID: String, segmentID: String, text: String, range: NSRange, preserveWhitespace: Bool = false) -> Self? {
        guard range.length > 0, let selected = Range(range, in: text) else { return nil }
        let exact = preserveWhitespace ? String(text[selected]) : String(text[selected]).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !exact.isEmpty else { return nil }
        let selectedText = String(text[selected])
        let leading = preserveWhitespace ? 0 : selectedText.prefix(while: { $0.isWhitespace }).count
        let lower = text.index(selected.lowerBound, offsetBy: leading)
        let upper = text.index(lower, offsetBy: exact.count)
        return .init(messageID: messageID, segmentID: segmentID,
                     anchor: .init(exact: exact, prefix: String(text[..<lower].suffix(20)),
                                   suffix: String(text[upper...].prefix(20))), range: NSRange(lower..<upper, in: text), copyText: selectedText)
    }
    var explanationTerm: String {
        let normalized = anchor.exact.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        var units = 0, result = ""
        for character in normalized {
            let next = String(character); guard units + next.utf16.count <= 500 else { break }
            units += next.utf16.count; result.append(character)
        }
        return result
    }
}

struct MessageTextSelectionTarget {
    let messageID: String
    let select: () -> Void
    var dismiss: () -> Void = {}
}

@MainActor
struct MessageTextSelectionContext {
    let messageID: String
    var highlights: [MessageHighlightAnchor] = []
    var preserveWhitespace = false
    var onSelectTarget: ((MessageTextSelectionTarget) -> Void)? = nil
    let onSelection: (MessageTextSelectionSnapshot?) -> Void
    let onContextMenu: (MessageTextSelectionSnapshot?) -> Void
}
private struct MessageTextSelectionKey: EnvironmentKey { static let defaultValue: MessageTextSelectionContext? = nil }
extension EnvironmentValues {
    var messageTextSelection: MessageTextSelectionContext? {
        get { self[MessageTextSelectionKey.self] }
        set { self[MessageTextSelectionKey.self] = newValue }
    }
}

struct MessageSelectionActionPolicy {
    let authenticated: Bool
    let readOnly: Bool
    let incognito: Bool
    let assistant: Bool
    let streaming: Bool
    var canHighlight: Bool { authenticated && !readOnly && !streaming }
    var canExplain: Bool { canHighlight && assistant && !incognito }
}

/// A selectable prose range may span words and bold runs, while entity views
/// keep their existing tap targets, URLs, and preview ownership.
struct MessageSelectableInlineGroup: Identifiable {
    let id: Int
    let tokens: [InlineMarkdownToken]
    var isProse: Bool { guard let first = tokens.first else { return false }; if case .text = first { return true }; return false }
    static func group(_ tokens: [InlineMarkdownToken]) -> [Self] {
        var result: [Self] = [], prose: [InlineMarkdownToken] = [], sourceIndex = 0
        func flush() { if !prose.isEmpty { result.append(.init(id: sourceIndex, tokens: prose)); sourceIndex += prose.count; prose = [] } }
        for token in tokens {
            if case .text = token { prose.append(token) }
            else { flush(); result.append(.init(id: sourceIndex, tokens: [token])); sourceIndex += 1 }
        }
        flush(); return result
    }
}

/// Platform selection owns the range and handles; product actions remain SwiftUI.
/// An unchanged attributed update deliberately preserves the actual selection.
struct MessageSelectableText: View {
    let content: AttributedString
    let context: MessageTextSelectionContext
    var monospace = false
    var body: some View {
        PlatformMessageSelectableText(content: content, context: context, monospace: monospace)
            .accessibilityIdentifier("message-selectable-text-\(context.messageID)")
    }
    static func attributed(_ value: AttributedString, monospace: Bool, highlights: [MessageHighlightAnchor], colorScheme: ColorScheme? = nil, alignment: TextAlignment = .leading) -> NSAttributedString {
        let pointSize: CGFloat = monospace ? 14 : 16
        let result = NSMutableAttributedString(attributedString: NSAttributedString(value))
        NativeSelectableTextColors.transfer(value, into: result)
        let paragraph = NSMutableParagraphStyle(); paragraph.lineSpacing = 2
        // Code keeps its source layout; ordinary message prose follows the bubble.
        switch monospace ? TextAlignment.leading : alignment {
        case .leading: paragraph.alignment = .left
        case .center: paragraph.alignment = .center
        case .trailing: paragraph.alignment = .right
        }
        let font = NativeMarkdownEmphasisFont.resolve(pointSize: pointSize, monospace: monospace)
        result.addAttributes([.font: font, .paragraphStyle: paragraph], range: NSRange(location: 0, length: result.length))
        // AttributedString intents do not supply platform fonts automatically.
        for run in value.runs {
            guard let intent = run.inlinePresentationIntent else { continue }
            let start = value.characters.distance(from: value.characters.startIndex, to: run.range.lowerBound)
            let end = value.characters.distance(from: value.characters.startIndex, to: run.range.upperBound)
            let plain = String(value.characters)
            guard let lower = plain.index(plain.startIndex, offsetBy: start, limitedBy: plain.endIndex),
                  let upper = plain.index(plain.startIndex, offsetBy: end, limitedBy: plain.endIndex) else { continue }
            let styled = NativeMarkdownEmphasisFont.resolve(pointSize: pointSize, monospace: monospace,
                bold: intent.contains(.stronglyEmphasized), italic: intent.contains(.emphasized))
            result.addAttribute(.font, value: styled, range: NSRange(lower..<upper, in: plain))
        }
        for anchor in highlights {
            guard let range = anchor.resolve(in: result.string) else { continue }
            #if os(iOS)
            result.addAttribute(.backgroundColor, value: UIColor(Color.highlightYellowSolid.opacity(0.4)), range: range)
            #else
            result.addAttribute(.backgroundColor, value: NSColor(Color.highlightYellowSolid.opacity(0.4)), range: range)
            #endif
        }
        return colorScheme.map { NativeSelectableTextColors.resolved(result, scheme: $0) } ?? result
    }
}

/// Retained native paragraphs frequently receive unrelated parent updates.
/// Prepare attributes once per actual content/style/theme change and measure
/// once per width proposal; selection-only updates never invalidate the cache.
@MainActor
final class NativeSelectableTextPreparation {
    private enum Input: Equatable {
        case message(AttributedString, Bool, [MessageHighlightAnchor], ColorScheme, TextAlignment)
        case attributed(NSAttributedString, ColorScheme)
    }
    private struct LayoutKey: Hashable { let width: CGFloat?; let wrapsText: Bool }
    private var input: Input?
    private var rendered: NSAttributedString?
    private var layouts: [LayoutKey: CGSize] = [:]
    private var recentLayoutKeys: [LayoutKey] = []
    private static let maximumLayouts = 8
    private(set) var preparationCount = 0
    private(set) var measurementCount = 0

    func prepare(content: AttributedString, raw: NSAttributedString?, monospace: Bool,
                 highlights: [MessageHighlightAnchor], scheme: ColorScheme, alignment: TextAlignment = .leading) -> NSAttributedString {
        let next: Input = raw.map { .attributed($0, scheme) } ?? .message(content, monospace, highlights, scheme, monospace ? .leading : alignment)
        if input == next, let rendered { return rendered }
        let prepared = raw.map { NativeSelectableTextColors.resolved($0, scheme: scheme) }
            ?? MessageSelectableText.attributed(content, monospace: monospace, highlights: highlights, colorScheme: scheme, alignment: alignment)
        input = next
        rendered = prepared
        layouts.removeAll(keepingCapacity: true)
        recentLayoutKeys.removeAll(keepingCapacity: true)
        preparationCount += 1
        return prepared
    }

    func size(width: CGFloat?, wrapsText: Bool, measure: @MainActor () -> CGSize) -> CGSize {
        let key = LayoutKey(width: width, wrapsText: wrapsText)
        if let cached = layouts[key] {
            recentLayoutKeys.removeAll { $0 == key }
            recentLayoutKeys.append(key)
            return cached
        }
        let value = measure()
        // Intrinsic sizing, constrained sizing and resize proposals may alternate.
        // Keep exact widths without throwing away every useful measurement when
        // a fourth proposal arrives. Evict only the least recently used size.
        if layouts.count >= Self.maximumLayouts, let oldest = recentLayoutKeys.first {
            layouts.removeValue(forKey: oldest)
            recentLayoutKeys.removeFirst()
        }
        layouts[key] = value
        recentLayoutKeys.append(key)
        measurementCount += 1
        return value
    }
}

#if os(iOS)
struct PlatformMessageSelectableText: UIViewRepresentable {
    let content: AttributedString
    let context: MessageTextSelectionContext
    let monospace: Bool
    var attributedContent: NSAttributedString? = nil
    var wrapsText = true
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.multilineTextAlignment) private var textAlignment
    func makeCoordinator() -> Coordinator { Coordinator(context) }
    func makeUIView(context: Context) -> UITextView {
        let view = Self.makeTextView(); view.delegate = context.coordinator; return view
    }
    static func makeTextView() -> UITextView {
        let view = UITextView(); view.backgroundColor = .clear; view.isEditable = false
        view.isSelectable = true; view.isScrollEnabled = false; view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0; view.textContainer.lineBreakMode = .byWordWrapping
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.context = self.context
        let next = context.coordinator.preparation.prepare(content: content, raw: attributedContent, monospace: monospace,
            highlights: self.context.highlights, scheme: colorScheme, alignment: textAlignment)
        view.textContainer.lineBreakMode = wrapsText ? .byWordWrapping : .byClipping
        Self.update(next, in: view, colorScheme: colorScheme, colorsResolved: true)

    }
    static func update(_ value: NSAttributedString, in view: UITextView, colorScheme: ColorScheme? = nil, colorsResolved: Bool = false) {
        if let colorScheme { configureColors(in: view, scheme: colorScheme) }
        let value = colorsResolved ? value : colorScheme.map { NativeSelectableTextColors.resolved(value, scheme: $0) } ?? value
        guard view.attributedText?.isEqual(to: value) != true else { return }
        let previous = view.selectedRange, sameText = view.text == value.string
        view.attributedText = value
        if sameText, NSMaxRange(previous) <= value.length { view.selectedRange = previous }
        view.accessibilityLabel = value.string
    }
    static func configureColors(in view: UITextView, scheme: ColorScheme) {
        view.overrideUserInterfaceStyle = scheme == .dark ? .dark : .light
        let link = NativeSelectableTextColors.color(.buttonPrimary, scheme: scheme)
        view.tintColor = link
        view.linkTextAttributes = [.foregroundColor: link]
    }
    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        context.coordinator.preparation.size(width: proposal.width, wrapsText: wrapsText) {
            let width: CGFloat
            if wrapsText, let proposedWidth = proposal.width { width = proposedWidth }
            else {
                width = ceil(uiView.attributedText.boundingRect(with: CGSize(width: CGFloat.greatestFiniteMagnitude,
                    height: CGFloat.greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil).width)
            }
            return CGSize(width: width, height: ceil(uiView.sizeThatFits(CGSize(width: max(1, width), height: .greatestFiniteMagnitude)).height))
        }
    }
    final class Coordinator: NSObject, UITextViewDelegate {
        var context: MessageTextSelectionContext
        let preparation = NativeSelectableTextPreparation()
        init(_ context: MessageTextSelectionContext) { self.context = context }
        func textView(_ view: UITextView, editMenuForTextIn range: NSRange, suggestedActions: [UIMenuElement]) -> UIMenu? {
            // UIKit's proposed edit-menu range can cover the paragraph even
            // while selection handles delimit a word. The native selection owns
            // the user's range; use the proposal only before a range is active.
            let native = MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.text, text: view.text, range: view.selectedRange, preserveWhitespace: context.preserveWhitespace)
            let selectionRange = native == nil ? range : view.selectedRange
            var snapshot = native ?? MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.text, text: view.text, range: range, preserveWhitespace: context.preserveWhitespace)
            if let selected = view.selectedTextRange { snapshot?.anchorRect = view.convert(view.firstRect(for: selected), to: nil) }
            snapshot?.interactionRect = view.convert(view.bounds, to: nil)
            context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                guard let view else { return }; view.becomeFirstResponder(); view.selectedRange = selectionRange
            }, dismiss: { [weak view] in
                view?.selectedRange = NSRange(location: 0, length: 0)
                view?.resignFirstResponder()
            }))
            // An overlay intercepts selection handles on touch. Keep the native
            // range active and let the floating product toolbar supply actions.
            if let snapshot { context.onSelection(snapshot) }
            else { context.onContextMenu(nil) }
            return UIMenu(children: [])
        }
        func textViewDidChangeSelection(_ view: UITextView) {
            var snapshot = MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.text, text: view.text, range: view.selectedRange, preserveWhitespace: context.preserveWhitespace)
            if let range = view.selectedTextRange { snapshot?.anchorRect = view.convert(view.firstRect(for: range), to: nil) }
            snapshot?.interactionRect = view.convert(view.bounds, to: nil)
            if snapshot != nil {
                let range = view.selectedRange
                context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                    view?.becomeFirstResponder(); view?.selectedRange = range
                }, dismiss: { [weak view] in
                    view?.selectedRange = NSRange(location: 0, length: 0); view?.resignFirstResponder()
                }))
            }
            let selectedRange = view.selectedRange
            DispatchQueue.main.async { [context, weak view] in
                guard view?.selectedRange == selectedRange else { return }
                context.onSelection(snapshot)
            }
        }
    }
}
#elseif os(macOS)
struct PlatformMessageSelectableText: NSViewRepresentable {
    let content: AttributedString
    let context: MessageTextSelectionContext
    let monospace: Bool
    var attributedContent: NSAttributedString? = nil
    var wrapsText = true
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.multilineTextAlignment) private var textAlignment
    func makeCoordinator() -> Coordinator { Coordinator(context) }
    func makeNSView(context: Context) -> SelectionTextView {
        let view = Self.makeTextView(); view.delegate = context.coordinator
        return view
    }
    static func makeTextView() -> SelectionTextView {
        let view = SelectionTextView()
        view.isEditable = false; view.isSelectable = true; view.drawsBackground = false
        view.textContainerInset = .zero; view.textContainer?.lineFragmentPadding = 0
        // SwiftUI owns the row frame. AppKit must not resize it during glyph layout.
        view.isVerticallyResizable = false; view.isHorizontallyResizable = false
        view.textContainer?.widthTracksTextView = true
        view.textContainer?.heightTracksTextView = false
        view.textContainer?.containerSize.height = .greatestFiniteMagnitude
        return view
    }
    func updateNSView(_ view: SelectionTextView, context: Context) {
        context.coordinator.context = self.context
        view.textContainer?.lineBreakMode = wrapsText ? .byWordWrapping : .byClipping
        view.textContainer?.widthTracksTextView = true
        view.onContext = { [context = self.context] view in
            context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                guard let view else { return }; view.window?.makeFirstResponder(view)
                if view.selectedRange().length == 0 { view.setSelectedRange(NSRange(location: view.contextClickIndex, length: 0)); view.selectWord(nil) }
            }, dismiss: { [weak view] in
                view?.setSelectedRange(NSRange(location: 0, length: 0))
                if let view, view.window?.firstResponder === view { view.window?.makeFirstResponder(nil) }
            }))
            context.onContextMenu(MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.string, text: view.string, range: view.selectedRange(), preserveWhitespace: context.preserveWhitespace))
        }
        let next = context.coordinator.preparation.prepare(content: content, raw: attributedContent, monospace: monospace,
            highlights: self.context.highlights, scheme: colorScheme, alignment: textAlignment)
        Self.update(next, in: view, colorScheme: colorScheme, colorsResolved: true)
    }
    static func update(_ content: NSAttributedString, in view: SelectionTextView, colorScheme: ColorScheme, colorsResolved: Bool = false) {
        view.appearance = NSAppearance(named: colorScheme == .dark ? .darkAqua : .aqua)
        view.linkTextAttributes = [.foregroundColor: NativeSelectableTextColors.color(.buttonPrimary, scheme: colorScheme)]
        let next = colorsResolved ? content : NativeSelectableTextColors.resolved(content, scheme: colorScheme)
        if view.textStorage?.isEqual(to: next) != true {
            let previous = view.selectedRange(), same = view.string == next.string
            view.textStorage?.setAttributedString(next)
            if same, NSMaxRange(previous) <= next.length { view.setSelectedRange(previous) }
        }
        view.setAccessibilityLabel(next.string)
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: SelectionTextView, context: Context) -> CGSize? {
        guard let storage = nsView.textStorage else { return nil }
        return context.coordinator.preparation.size(width: proposal.width, wrapsText: wrapsText) {
            Self.measuredSize(storage, width: proposal.width, wrapsText: wrapsText)
        }
    }
    /// Proposals can arrive in a different order from the frame SwiftUI commits.
    /// Measuring in the drawing container would leave retained rows laid out at
    /// the last proposed width, even when a cached size is used for another width.
    static func measuredSize(_ content: NSAttributedString, width proposedWidth: CGFloat?, wrapsText: Bool) -> CGSize {
        let width = (wrapsText ? proposedWidth : nil) ?? ceil(content.boundingRect(with: CGSize(width: CGFloat.greatestFiniteMagnitude,
            height: CGFloat.greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading]).width)
        let storage = NSTextStorage(attributedString: content)
        let layout = NSLayoutManager()
        let container = NSTextContainer(containerSize: CGSize(width: max(1, width), height: .greatestFiniteMagnitude))
        container.lineFragmentPadding = 0
        container.lineBreakMode = wrapsText ? .byWordWrapping : .byClipping
        container.widthTracksTextView = false
        storage.addLayoutManager(layout)
        layout.addTextContainer(container)
        layout.ensureLayout(for: container)
        return CGSize(width: width, height: ceil(layout.usedRect(for: container).height))
    }
    final class SelectionTextView: NSTextView {
        var onContext: ((SelectionTextView) -> Void)?
        var contextClickIndex = 0
        override func menu(for event: NSEvent) -> NSMenu? {
            let point = convert(event.locationInWindow, from: nil)
            let index = characterIndexForInsertion(at: point)
            contextClickIndex = index
            if index < (textStorage?.length ?? 0), textStorage?.attribute(.link, at: index, effectiveRange: nil) != nil { return super.menu(for: event) }
            onContext?(self); return nil
        }
    }
    @MainActor final class Coordinator: NSObject, NSTextViewDelegate {
        var context: MessageTextSelectionContext
        let preparation = NativeSelectableTextPreparation()
        init(_ context: MessageTextSelectionContext) { self.context = context }
        func textViewDidChangeSelection(_ notification: Notification) {
            guard let view = notification.object as? NSTextView else { return }
            var snapshot = MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.string, text: view.string, range: view.selectedRange(), preserveWhitespace: context.preserveWhitespace)
            if let layout = view.layoutManager, let container = view.textContainer, let window = view.window {
                let glyphs = layout.glyphRange(forCharacterRange: view.selectedRange(), actualCharacterRange: nil)
                let bounds = view.convert(layout.boundingRect(forGlyphRange: glyphs, in: container), to: nil)
                snapshot?.anchorRect = CGRect(x: bounds.minX, y: window.contentLayoutRect.height - bounds.maxY, width: bounds.width, height: bounds.height)
                let textBounds = view.convert(view.bounds, to: nil)
                snapshot?.interactionRect = CGRect(x: textBounds.minX, y: window.contentLayoutRect.height - textBounds.maxY,
                    width: textBounds.width, height: textBounds.height)
            }
            if snapshot != nil {
                let range = view.selectedRange()
                context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                    guard let view else { return }; view.window?.makeFirstResponder(view); view.setSelectedRange(range)
                }, dismiss: { [weak view] in
                    view?.setSelectedRange(NSRange(location: 0, length: 0))
                    if let view, view.window?.firstResponder === view { view.window?.makeFirstResponder(nil) }
                }))
            }
            let selectedRange = view.selectedRange()
            DispatchQueue.main.async { [context, weak view] in
                guard view?.selectedRange() == selectedRange else { return }
                context.onSelection(snapshot)
            }
        }
    }
}
#endif

/// Product toolbar colors follow the actual SwiftUI scheme. Grey tokens invert
/// with the theme; using grey100 unconditionally creates a white bar in dark mode.
struct MessageSelectionToolbarColors {
    let scheme: ColorScheme
    var background: Color { scheme == .dark ? .grey20 : .grey100 }
    var foreground: Color { scheme == .dark ? .grey100 : .grey0 }
}

/// A consumed outside tap cannot activate the link/button underneath. The hole
/// preserves the source text view, links and native selection handles.
struct MessageSelectionDismissRegion: Shape {
    var textRect: CGRect?
    func path(in rect: CGRect) -> Path {
        var path = Path(rect)
        if let textRect {
            let visibleText = textRect.insetBy(dx: -24, dy: -24).intersection(rect)
            if !visibleText.isNull && !visibleText.isEmpty { path.addRect(visibleText) }
        }
        return path
    }
}
struct MessageSelectionDismissBackdrop: View {
    let selection: MessageTextSelectionSnapshot
    let onDismiss: () -> Void
    var body: some View {
        GeometryReader { geometry in
            let origin = geometry.frame(in: .global).origin
            let textRect = (selection.interactionRect ?? selection.anchorRect).map {
                $0.offsetBy(dx: -origin.x, dy: -origin.y)
            }
            let region = MessageSelectionDismissRegion(textRect: textRect)
            region.fill(Color.clear, style: FillStyle(eoFill: true))
                .contentShape(region, eoFill: true)
                .onTapGesture(perform: onDismiss)
                .accessibilityIdentifier("message-selection-dismiss-backdrop")
        }.ignoresSafeArea()
    }
}

struct MessageSelectionToolbar: View {
    @Environment(\.colorScheme) private var colorScheme
    private var colors: MessageSelectionToolbarColors { .init(scheme: colorScheme) }
    let canExplain: Bool
    var canHighlight = true
    var onCopy: (() -> Void)? = nil
    var onMore: (() -> Void)? = nil
    let onHighlight: () -> Void
    let onComment: () -> Void
    let onExplain: () -> Void
    var body: some View {
        HStack(spacing: .spacing1) {
            if let onCopy {
                Button(action: onCopy) {
                    Icon("copy", size: 14).foregroundStyle(colors.foreground)
                        .padding(.spacing2).frame(minWidth: 44, minHeight: 36)
                }.buttonStyle(.plain).accessibilityLabel(AppStrings.copy)
                    .accessibilityIdentifier("message-selection-copy")
            }
            if canHighlight {
                action("highlight", key: "highlight", onHighlight)
                action("highlight-and-comment", key: "highlight_and_comment", onComment)
            }
            if canExplain { action("explain-new-chat", key: "explain_in_new_chat", onExplain) }
            if let onMore {
                Button(action: onMore) {
                    Icon("more", size: 14).foregroundStyle(colors.foreground)
                        .padding(.spacing2).frame(minWidth: 44, minHeight: 36)
                }.buttonStyle(.plain).accessibilityLabel(AppStrings.localized("common.more_actions"))
                    .accessibilityIdentifier("message-selection-more")
            }
        }.padding(.spacing2).background(colors.background).clipShape(RoundedRectangle(cornerRadius: .radius8))
            .accessibilityElement(children: .contain).accessibilityIdentifier("message-selection-toolbar")
    }
    private func action(_ id: String, key: String, _ perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            HStack(spacing: .spacing1) {
                Icon(key == "explain_in_new_chat" ? "planning" : "quote", size: 14)
                    .foregroundStyle(Color.highlightYellowSolid)
                Text(AppStrings.localized("chats.context_menu.\(key).text"))
                    .font(.omXs).fontWeight(.semibold).foregroundStyle(colors.foreground).lineLimit(1)
            }.padding(.spacing2).frame(minWidth: 44, minHeight: 36)
        }.buttonStyle(.plain).accessibilityIdentifier("message-selection-\(id)")
    }
}

struct MessageActionsHoldModifier: ViewModifier {
    let nativeSelection: Bool
    let action: (() -> Void)?
    @ViewBuilder func body(content: Content) -> some View {
        if nativeSelection { content }
        else { content.onLongPressGesture { action?() } }
    }
}
