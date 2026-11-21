// Start-screen row composition for the Chats start screen: own chats with the
// day's unopened video/article inspirations interleaved, plus the browse
// actions tile as the last item. Swift port of the pure helpers in
// frontend/packages/ui/src/utils/startScreenRow.ts (interleaveStartRow,
// selectChatRowInspirations).
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/welcome/StartScreenChatCard.svelte
//          frontend/packages/ui/src/components/welcome/StartScreenRowActions.svelte
//          frontend/packages/ui/src/components/ActiveChat.svelte
// TS:      frontend/packages/ui/src/utils/startScreenRow.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/daily-inspiration/specification.yml
// Assertions: daily-inspiration.start-row-rhythm, daily-inspiration.start-row-cards,
//             daily-inspiration.start-row-actions, daily-inspiration.start-row-suggestions
import SwiftUI

/// One entry of the start-screen row.
enum StartScreenRowEntry<Own, Inspiration> {
    case own(Own)
    case inspiration(Inspiration)
}

extension StartScreenRowEntry: Identifiable where Own == WelcomeChatCardData, Inspiration == DailyInspirationData {
    var id: String {
        switch self {
        case .own(let card): return "own-" + card.id
        case .inspiration(let item): return "inspiration-" + (item.inspirationId ?? item.text)
        }
    }
}

enum StartScreenRow {
    /// Own items shown before the first inspiration.
    static let leadingOwnItems = 2
    /// Own items between two inspirations after the leading group.
    static let ownItemsBetweenInspirations = 3
    /// Most recent own items shown in the row.
    static let maxOwnItems = 10
    /// The row shows at most this many cards (own items plus inspirations).
    static let maxCards = 10

    /// Own 1-2, inspiration, own 3-5, inspiration, ...; no own items: only inspirations.
    static func interleave<Own, Inspiration>(
        own ownItems: [Own], inspirations: [Inspiration]
    ) -> [StartScreenRowEntry<Own, Inspiration>] {
        let own = Array(ownItems.prefix(maxOwnItems))
        if own.isEmpty { return inspirations.prefix(maxCards).map { .inspiration($0) } }
        var entries: [StartScreenRowEntry<Own, Inspiration>] = []
        var next = 0
        for (index, item) in own.enumerated() {
            entries.append(.own(item))
            let count = index + 1
            let groupComplete = count == leadingOwnItems
                || (count > leadingOwnItems && (count - leadingOwnItems) % ownItemsBetweenInspirations == 0)
            if groupComplete, next < inspirations.count {
                entries.append(.inspiration(inspirations[next]))
                next += 1
            }
        }
        if own.count < leadingOwnItems, next < inspirations.count {
            entries.append(.inspiration(inspirations[next]))
        }
        return Array(entries.prefix(maxCards))
    }

    /// Video and article inspirations that have not been opened yet (an opened one is a real chat).
    static func chatRowInspirations(_ inspirations: [DailyInspirationData]) -> [DailyInspirationData] {
        inspirations.filter { inspiration in
            let type = inspiration.contentType
                ?? (inspiration.video != nil ? "video" : inspiration.wiki != nil ? "wiki" : nil)
            // Signed-out hardcoded defaults carry no type: they are plain chat starters.
            let startsChat = type == "video" || type == "wiki" || (type == nil && inspiration.feature == nil)
            return startsChat && inspiration.startedChatId == nil
        }
    }

    /// The card data an inspiration row card renders with the shared large chat card.
    static func cardData(for inspiration: DailyInspirationData) -> WelcomeChatCardData {
        WelcomeChatCardData(
            id: "inspiration-" + (inspiration.inspirationId ?? inspiration.text),
            title: inspiration.title ?? inspiration.text, summary: nil,
            category: inspiration.category ?? "general_knowledge",
            iconName: inspiration.iconName ?? "insight", isPinned: false)
    }
}

/// One browse action inside the row's last tile.
struct StartRowAction: Identifiable {
    let title: String
    let icon: String
    let identifier: String
    let action: () -> Void
    var id: String { identifier }
}

/// Last item of the row: Show all / Search (signed in), Select interests / Show all (guests).
struct StartRowActionsTile: View {
    let actions: [StartRowAction]
    let width: CGFloat
    let height: CGFloat

    var body: some View {
        VStack(spacing: .spacing2) {
            ForEach(actions) { item in
                WorkspaceContinuationLink(title: item.title, icon: item.icon, identifier: item.identifier, action: item.action)
            }
        }
        .frame(width: width, height: height)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("welcome-row-actions")
    }
}

/// Inspiration card of the row: always the normal chat card with a small "Daily inspiration"
/// label, never a picture background (owner decision 21 Nov; web drops that variant too).
struct StartRowInspirationCard: View {
    let inspiration: DailyInspirationData
    let width: CGFloat
    let large: Bool
    let onTap: () -> Void

    var body: some View {
        let card = StartScreenRow.cardData(for: inspiration)
        Group {
            if large {
                WelcomeResumeCard(badge: AppStrings.dailyInspiration, card: card, width: width, height: 200,
                    onTap: onTap, onLongPress: {})
            } else {
                WelcomeResumeCompactCard(card: card, width: width, onTap: onTap, onLongPress: {})
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("welcome-row-inspiration-card")
    }
}

extension StartScreenRow {
    /// Projects row inspirations: every not-yet-opened inspiration of the Projects surface.
    /// Mirrors selectProjectRowInspirations in utils/startScreenRow.ts.
    // Specification: specifications/features/daily-inspiration/specification.yml
    // Assertions: daily-inspiration.workspace-start-screens
    static func projectRowInspirations(_ inspirations: [DailyInspirationData]) -> [DailyInspirationData] {
        inspirations.filter { $0.surface == "projects" && $0.startedChatId == nil }
    }
}

/// Suggestions below the start row. Port of the filter in
/// frontend/packages/ui/src/services/startScreenSuggestions.ts: only full
/// prompts (at least 4 words or 8 CJK characters), plain text, no duplicates.
enum StartScreenSuggestions {
    static let maxVisible = 3
    private static let minWords = 4
    private static let minCJKCharacters = 8

    static func plainText(_ raw: String) -> String {
        raw.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^\s*\[[^\]]+\]\s*"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func isFullPrompt(_ text: String) -> Bool {
        let cjk = text.unicodeScalars.filter {
            (0x3400...0x9FFF).contains($0.value) || (0xF900...0xFAFF).contains($0.value)
                || (0x3040...0x30FF).contains($0.value) || (0xAC00...0xD7AF).contains($0.value)
        }.count
        if cjk >= minCJKCharacters { return true }
        return text.split(whereSeparator: \.isWhitespace).count >= minWords
    }

    /// Up to `maxVisible` unique full prompts, in the given order.
    static func visibleTexts(from raw: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        for item in raw {
            let text = plainText(item)
            guard isFullPrompt(text), seen.insert(text).inserted else { continue }
            result.append(text)
            if result.count == maxVisible { break }
        }
        return result
    }
}
