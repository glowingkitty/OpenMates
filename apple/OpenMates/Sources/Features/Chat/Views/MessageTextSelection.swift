// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.inline-entity-interaction
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/ChatMessage.svelte, MessageSelectionToolbar.svelte
// CSS: frontend/packages/ui/src/styles/chat.css, MessageSelectionToolbar.svelte
// ────────────────────────────────────────────────────────────────────
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct MessageTextSelectionSnapshot: Equatable {
    let messageID: String
    let segmentID: String
    let anchor: MessageHighlightAnchor
    let range: NSRange
    /// Clipboard content retains the native range verbatim; annotations use the trimmed anchor.
    var copyText: String = ""
    var anchorRect: CGRect? = nil
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

struct MessageTextSelectionTarget { let messageID: String; let select: () -> Void }

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
    static func attributed(_ value: AttributedString, monospace: Bool, highlights: [MessageHighlightAnchor]) -> NSAttributedString {
        let pointSize: CGFloat = monospace ? 14 : 16
        let result = NSMutableAttributedString(attributedString: NSAttributedString(value))
        let paragraph = NSMutableParagraphStyle(); paragraph.lineSpacing = 2
        #if os(iOS)
        let base = UIFont(name: FontRegistration.mediumPostScriptName, size: pointSize) ?? UIFont.systemFont(ofSize: pointSize, weight: .medium)
        let font = monospace ? UIFont.monospacedSystemFont(ofSize: pointSize, weight: .medium) : base
        #else
        let base = NSFont(name: FontRegistration.mediumPostScriptName, size: pointSize) ?? NSFont.systemFont(ofSize: pointSize, weight: .medium)
        let font = monospace ? NSFont.monospacedSystemFont(ofSize: pointSize, weight: .medium) : base
        #endif
        result.addAttributes([.font: font, .paragraphStyle: paragraph], range: NSRange(location: 0, length: result.length))
        // AttributedString intents do not supply platform fonts automatically.
        for run in value.runs {
            guard let intent = run.inlinePresentationIntent else { continue }
            let start = value.characters.distance(from: value.characters.startIndex, to: run.range.lowerBound)
            let end = value.characters.distance(from: value.characters.startIndex, to: run.range.upperBound)
            let plain = String(value.characters)
            guard let lower = plain.index(plain.startIndex, offsetBy: start, limitedBy: plain.endIndex),
                  let upper = plain.index(plain.startIndex, offsetBy: end, limitedBy: plain.endIndex) else { continue }
            var styled = font
            #if os(iOS)
            var traits: UIFontDescriptor.SymbolicTraits = []
            if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
            if intent.contains(.emphasized) { traits.insert(.traitItalic) }
            if let descriptor = font.fontDescriptor.withSymbolicTraits(traits) { styled = UIFont(descriptor: descriptor, size: pointSize) }
            #else
            if intent.contains(.stronglyEmphasized) { styled = NSFontManager.shared.convert(styled, toHaveTrait: .boldFontMask) }
            if intent.contains(.emphasized) { styled = NSFontManager.shared.convert(styled, toHaveTrait: .italicFontMask) }
            #endif
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
        return result
    }
}

#if os(iOS)
struct PlatformMessageSelectableText: UIViewRepresentable {
    let content: AttributedString
    let context: MessageTextSelectionContext
    let monospace: Bool
    var attributedContent: NSAttributedString? = nil
    var wrapsText = true
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
        let next = attributedContent ?? MessageSelectableText.attributed(content, monospace: monospace, highlights: self.context.highlights)
        view.textContainer.lineBreakMode = wrapsText ? .byWordWrapping : .byClipping
        Self.update(next, in: view)

    }
    static func update(_ value: NSAttributedString, in view: UITextView) {
        guard view.attributedText?.isEqual(to: value) != true else { return }
        let previous = view.selectedRange, sameText = view.text == value.string
        view.attributedText = value
        if sameText, NSMaxRange(previous) <= value.length { view.selectedRange = previous }
        view.accessibilityLabel = value.string
    }
    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let ideal = uiView.attributedText.boundingRect(with: CGSize(width: proposal.width ?? .greatestFiniteMagnitude, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        let width = wrapsText ? proposal.width ?? ceil(ideal.width) : ceil(uiView.attributedText.boundingRect(with: CGSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil).width)
        return CGSize(width: width, height: ceil(uiView.sizeThatFits(CGSize(width: max(1, width), height: .greatestFiniteMagnitude)).height))
    }
    final class Coordinator: NSObject, UITextViewDelegate {
        var context: MessageTextSelectionContext
        init(_ context: MessageTextSelectionContext) { self.context = context }
        func textView(_ view: UITextView, editMenuForTextIn range: NSRange, suggestedActions: [UIMenuElement]) -> UIMenu? {
            // UIKit's proposed edit-menu range can cover the paragraph even
            // while selection handles delimit a word. The native selection owns
            // the user's range; use the proposal only before a range is active.
            let native = MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.text, text: view.text, range: view.selectedRange, preserveWhitespace: context.preserveWhitespace)
            let selectionRange = native == nil ? range : view.selectedRange
            var snapshot = native ?? MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.text, text: view.text, range: range, preserveWhitespace: context.preserveWhitespace)
            if let selected = view.selectedTextRange { snapshot?.anchorRect = view.convert(view.firstRect(for: selected), to: nil) }
            context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                guard let view else { return }; view.becomeFirstResponder(); view.selectedRange = selectionRange
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
            DispatchQueue.main.async { [context] in context.onSelection(snapshot) }
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
    func makeCoordinator() -> Coordinator { Coordinator(context) }
    func makeNSView(context: Context) -> SelectionTextView {
        let view = SelectionTextView(); view.delegate = context.coordinator
        view.isEditable = false; view.isSelectable = true; view.drawsBackground = false
        view.textContainerInset = .zero; view.textContainer?.lineFragmentPadding = 0
        view.isVerticallyResizable = true; view.isHorizontallyResizable = false
        view.textContainer?.widthTracksTextView = true
        return view
    }
    func updateNSView(_ view: SelectionTextView, context: Context) {
        context.coordinator.context = self.context
        view.textContainer?.lineBreakMode = wrapsText ? .byWordWrapping : .byClipping
        view.textContainer?.widthTracksTextView = wrapsText
        view.onContext = { [context = self.context] view in
            context.onSelectTarget?(.init(messageID: context.messageID, select: { [weak view] in
                guard let view else { return }; view.window?.makeFirstResponder(view)
                if view.selectedRange().length == 0 { view.setSelectedRange(NSRange(location: view.contextClickIndex, length: 0)); view.selectWord(nil) }
            }))
            context.onContextMenu(MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.string, text: view.string, range: view.selectedRange(), preserveWhitespace: context.preserveWhitespace))
        }
        let next = attributedContent ?? MessageSelectableText.attributed(content, monospace: monospace, highlights: self.context.highlights)
        if view.textStorage?.isEqual(to: next) != true {
            let previous = view.selectedRange(), same = view.string == next.string
            view.textStorage?.setAttributedString(next)
            if same, NSMaxRange(previous) <= next.length { view.setSelectedRange(previous) }
        }
        view.setAccessibilityLabel(next.string)
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: SelectionTextView, context: Context) -> CGSize? {
        guard let storage = nsView.textStorage else { return nil }
        let width = (wrapsText ? proposal.width : nil) ?? ceil(storage.boundingRect(with: CGSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading]).width)
        nsView.textContainer?.containerSize = CGSize(width: max(1, width), height: .greatestFiniteMagnitude)
        guard let container = nsView.textContainer, let layout = nsView.layoutManager else { return nil }
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
    final class Coordinator: NSObject, NSTextViewDelegate {
        var context: MessageTextSelectionContext
        init(_ context: MessageTextSelectionContext) { self.context = context }
        func textViewDidChangeSelection(_ notification: Notification) {
            guard let view = notification.object as? NSTextView else { return }
            var snapshot = MessageTextSelectionSnapshot.capture(messageID: context.messageID, segmentID: view.string, text: view.string, range: view.selectedRange(), preserveWhitespace: context.preserveWhitespace)
            if let layout = view.layoutManager, let container = view.textContainer, let window = view.window {
                let glyphs = layout.glyphRange(forCharacterRange: view.selectedRange(), actualCharacterRange: nil)
                let bounds = view.convert(layout.boundingRect(forGlyphRange: glyphs, in: container), to: nil)
                snapshot?.anchorRect = CGRect(x: bounds.minX, y: window.contentLayoutRect.height - bounds.maxY, width: bounds.width, height: bounds.height)
            }
            DispatchQueue.main.async { [context] in context.onSelection(snapshot) }
        }
    }
}
#endif

struct MessageSelectionToolbar: View {
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
                    Icon("copy", size: 14).foregroundStyle(Color.grey0)
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
                    Icon("more", size: 14).foregroundStyle(Color.grey0)
                        .padding(.spacing2).frame(minWidth: 44, minHeight: 36)
                }.buttonStyle(.plain).accessibilityLabel(AppStrings.localized("common.more_actions"))
                    .accessibilityIdentifier("message-selection-more")
            }
        }.padding(.spacing2).background(Color.grey100).clipShape(RoundedRectangle(cornerRadius: .radius8))
            .accessibilityElement(children: .contain).accessibilityIdentifier("message-selection-toolbar")
    }
    private func action(_ id: String, key: String, _ perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            HStack(spacing: .spacing1) {
                Icon(key == "explain_in_new_chat" ? "planning" : "quote", size: 14)
                    .foregroundStyle(Color.highlightYellowSolid)
                Text(AppStrings.localized("chats.context_menu.\(key).text"))
                    .font(.omXs).fontWeight(.semibold).foregroundStyle(Color.grey0).lineLimit(1)
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
