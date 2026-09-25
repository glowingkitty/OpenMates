// Follow-up quick-send actions rendered below the latest assistant response.
//
// ─── Web source ───────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/FollowUpSuggestions.svelte
//          frontend/packages/ui/src/components/ChatHistory.svelte
// CSS:     FollowUpSuggestions.svelte .suggestions-wrapper, .suggestion-item,
//          .suggestion-enter-icon; ChatHistory.svelte .follow-up-suggestions-wrapper
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ───────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.layout.responsive-history, chats.surface.semantic-parity

import Foundation
import SwiftUI

#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct FollowUpSuggestions: View {
    let suggestions: [String]
    // Kept at the call-site boundary until the obsolete gradient-card metadata
    // is removed from ChatView after its concurrent header work lands.
    var category: String? = nil
    var icon: String? = nil
    let onSelect: (String) -> Void
    private let visibleSuggestions: [FollowUpSuggestionPresentation.Item]
    private let compact: Bool

    @State private var isDismissing = false

    init(
        suggestions: [String],
        category: String? = nil,
        icon: String? = nil,
        compact: Bool = false,
        onSelect: @escaping (String) -> Void
    ) {
        self.suggestions = suggestions
        self.category = category
        self.icon = icon
        self.compact = compact
        self.onSelect = onSelect
        visibleSuggestions = FollowUpSuggestionPresentation.visibleItems(from: suggestions)
    }

    private var itemSpacing: CGFloat {
        #if os(iOS)
        // Web coarse pointers use 0.8rem. The nearest generated token is 12pt.
        return .spacing6
        #else
        // Web mouse/trackpad layout uses 0.35rem (5.6px).
        return .spacing3
        #endif
    }

    var body: some View {
        if !visibleSuggestions.isEmpty {
            VStack(alignment: .trailing, spacing: itemSpacing) {
                ForEach(visibleSuggestions) { suggestion in
                    Button {
                        guard !isDismissing else { return }
                        withAnimation(.easeOut(duration: 0.18)) {
                            isDismissing = true
                        }
                        onSelect(suggestion.body)
                    } label: {
                        HStack(alignment: .center, spacing: .spacing4) {
                            Text(suggestion.body)
                                .font(compact ? .omXs : .omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.grey70)
                                .multilineTextAlignment(.trailing)

                            FollowUpEnterArrow()
                                .stroke(
                                    Color.grey70,
                                    style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round)
                                )
                                .frame(width: 17, height: 17)
                                .accessibilityHidden(true)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(isDismissing)
                    .accessibilityIdentifier("follow-up-suggestion-item")
                }
            }
            .frame(maxWidth: 780, alignment: .trailing)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.top, .spacing4)
            // Web ChatHistory.svelte uses an exact 14px bottom inset here.
            .padding(.bottom, 14)
            .padding(.horizontal, compact ? .spacing5 : .spacing10)
            .opacity(isDismissing ? 0 : 1)
            .allowsHitTesting(!isDismissing)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("suggestions-wrapper")
            .onChange(of: suggestions) { _, _ in
                isDismissing = false
            }
        }
    }
}

/// Pure normalization shared by the production renderer and deterministic tests.
/// It deliberately follows the web order: deduplicate exact raw inputs, decode
/// HTML to visible text, remove a legacy `[app-skill]` prefix, then omit blanks.
enum FollowUpSuggestionPresentation {
    struct Item: Identifiable, Equatable {
        let id: Int
        let body: String
    }

    static func items(from suggestions: [String]) -> [Item] {
        var seen = Set<String>()
        return suggestions.compactMap { raw -> String? in
            guard seen.insert(raw).inserted else { return nil }
            let plain = stripHTML(from: raw)
            let withoutLegacyPrefix = plain.replacingOccurrences(
                of: #"^\s*\[[^\]]+\]\s*"#,
                with: "",
                options: .regularExpression
            )
            let body = withoutLegacyPrefix.trimmingCharacters(in: .whitespacesAndNewlines)
            return body.isEmpty ? nil : body
        }
        .enumerated()
        .map { Item(id: $0.offset, body: $0.element) }
    }

    static func visibleItems(from suggestions: [String]) -> [Item] {
        Array(items(from: suggestions).prefix(4))
    }

    private static func stripHTML(from value: String) -> String {
        guard value.contains("<") || value.contains("&") else { return value }
        guard let data = value.data(using: .utf8),
              let attributed = try? NSAttributedString(
                data: data,
                options: [
                    .documentType: NSAttributedString.DocumentType.html,
                    .characterEncoding: String.Encoding.utf8.rawValue,
                ],
                documentAttributes: nil
              ) else {
            return value.replacingOccurrences(of: #"<[^>]+>"#, with: "", options: .regularExpression)
        }
        return attributed.string
    }
}

/// The web component owns this 24×24 enter-arrow path inline rather than using
/// an icon asset. Drawing the same path avoids substituting a platform glyph.
private struct FollowUpEnterArrow: Shape {
    func path(in rect: CGRect) -> Path {
        let scaleX = rect.width / 24
        let scaleY = rect.height / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: x * scaleX, y: y * scaleY)
        }

        var path = Path()
        path.move(to: point(9, 10))
        path.addLine(to: point(9, 14))
        path.addLine(to: point(16, 14))
        path.addCurve(
            to: point(20, 10),
            control1: point(18.21, 14),
            control2: point(20, 12.21)
        )
        path.addLine(to: point(20, 4))
        path.addLine(to: point(18, 4))
        path.addLine(to: point(18, 10))
        path.addCurve(
            to: point(16, 12),
            control1: point(18, 11.10),
            control2: point(17.10, 12)
        )
        path.addLine(to: point(9, 12))
        path.addLine(to: point(9, 8))
        path.addLine(to: point(4, 13))
        path.addLine(to: point(9, 18))
        path.addLine(to: point(9, 14))
        return path
    }
}
