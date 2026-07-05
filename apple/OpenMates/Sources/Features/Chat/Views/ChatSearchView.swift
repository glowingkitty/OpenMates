// Chat search — local full-text search across decrypted chats and messages.
// Mirrors the web app's SearchBar.svelte, SearchResults.svelte, and searchService.ts.
// Search is deliberately client-side for encrypted-on-device parity: no plaintext
// query/content is sent to the backend, and the derived index stays in memory for
// this view only. Results carry message IDs so snippet taps can open and scroll
// to the matching message like the web sidebar search flow.

import Foundation
import SwiftUI

struct ChatSearchSelection: Equatable {
    let chatId: String
    let messageId: String?
    let query: String
}

struct ChatSearchView: View {
    let chats: [Chat]
    let activeChatId: String?
    let chatStore: ChatStore
    let onSelectResult: (ChatSearchSelection) -> Void
    let onClose: () -> Void

    @State private var query = ""
    @State private var results = ChatSearchResults.empty
    @State private var isSearching = false
    @State private var searchTask: Task<Void, Never>?
    @FocusState private var isFocused: Bool

    private let offlineStore = OfflineStore.shared

    var body: some View {
        VStack(spacing: 0) {
            searchBar

            if isSearching {
                searchStatusRow(AppStrings.loading)
                    .accessibilityIdentifier("warming-up")
            } else if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Spacer(minLength: 0)
            } else if results.totalCount == 0 {
                noResults
            } else {
                resultsList
            }
        }
        .background(Color.grey0)
        .onAppear { isFocused = true }
        .onDisappear { searchTask?.cancel() }
    }

    private var searchBar: some View {
        HStack(spacing: .spacing4) {
            Icon("search", size: 20)
                .foregroundStyle(Color.fontTertiary)
                .accessibilityHidden(true)

            TextField(AppStrings.search, text: $query)
                .textFieldStyle(.plain)
                .font(.omP)
                .focused($isFocused)
                .onSubmit { runSearchImmediately() }
                .onChange(of: query) { _, _ in scheduleSearch() }
                .accessibilityIdentifier("search-input")

            Button {
                query = ""
                results = .empty
                onClose()
            } label: {
                Icon("close", size: 20)
                    .foregroundStyle(Color.fontTertiary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.close)
            .accessibilityIdentifier("search-close-button")
        }
        .padding(.horizontal, .spacing6)
        .padding(.vertical, .spacing4)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .overlay(
            RoundedRectangle(cornerRadius: .radius5)
                .stroke(isFocused ? Color.grey50 : Color.grey25, lineWidth: 1)
        )
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing4)
        .accessibilityIdentifier("search-bar")
    }

    private var resultsList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing2) {
                ForEach(results.groups) { group in
                    searchSectionHeader(group.title)
                    ForEach(group.items) { result in
                        searchChatResult(result)
                    }
                }
            }
            .padding(.vertical, .spacing3)
        }
        .accessibilityIdentifier("search-results")
        .accessibilityLabel(AppStrings.searchResultsLabel)
    }

    private var noResults: some View {
        VStack(spacing: .spacing4) {
            Icon("search", size: 36)
                .foregroundStyle(Color.fontTertiary)
                .accessibilityHidden(true)
            Text(AppStrings.searchNoResults)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing10)
        .padding(.top, .spacing20)
        .accessibilityIdentifier("search-no-results")
    }

    private func searchStatusRow(_ title: String) -> some View {
        HStack(spacing: .spacing4) {
            ProgressView()
                .scaleEffect(0.7)
            Text(title)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing6)
    }

    private func searchSectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontTertiary)
            .tracking(0.8)
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing4)
            .padding(.bottom, .spacing1)
    }

    private func searchChatResult(_ result: ChatSearchResult) -> some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Button {
                onSelectResult(.init(chatId: result.chat.id, messageId: nil, query: query))
            } label: {
                ChatListRow(chat: result.chat)
                    .background(activeChatId == result.chat.id ? Color.buttonPrimary.opacity(0.12) : Color.clear)
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("search-chat-item")
            .accessibilityLabel(result.decryptedTitle ?? result.chat.displayTitle)

            if !result.messageSnippets.isEmpty {
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(result.messageSnippets) { snippet in
                        snippetButton(snippet, chatId: result.chat.id)
                    }
                }
                .padding(.leading, .spacing16)
                .padding(.trailing, .spacing5)
                .padding(.bottom, .spacing2)
            } else if let metadataSnippet = result.metadataSnippets.first {
                metadataSnippetButton(metadataSnippet, chatId: result.chat.id)
                    .padding(.leading, .spacing16)
                    .padding(.trailing, .spacing5)
                    .padding(.bottom, .spacing2)
            }
        }
        .padding(.horizontal, .spacing3)
    }

    private func snippetButton(_ snippet: ChatSearchSnippet, chatId: String) -> some View {
        Button {
            onSelectResult(.init(chatId: chatId, messageId: snippet.messageId, query: query))
        } label: {
            VStack(alignment: .leading, spacing: .spacing1) {
                if let label = snippet.sourceLabel {
                    Text(label.uppercased())
                        .font(.omMicro)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontTertiary)
                }
                Text(highlighted(snippet.text, query: query))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: .radius1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(snippet.text)
        .accessibilityHint(AppStrings.searchGoToMessage)
        .accessibilityIdentifier("search-message-snippet")
    }

    private func metadataSnippetButton(_ snippet: ChatMetadataSnippet, chatId: String) -> some View {
        Button {
            onSelectResult(.init(chatId: chatId, messageId: nil, query: query))
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                Text(snippet.sourceLabel.uppercased())
                    .font(.omMicro)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontTertiary)
                Text(highlighted(snippet.text, query: query))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(2)
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(snippet.text)
        .accessibilityIdentifier("search-metadata-snippet")
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        let nextQuery = query
        guard !nextQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            results = .empty
            isSearching = false
            return
        }
        isSearching = true
        searchTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard !Task.isCancelled else { return }
            performSearch(nextQuery)
        }
    }

    private func runSearchImmediately() {
        searchTask?.cancel()
        performSearch(query)
    }

    private func performSearch(_ rawQuery: String) {
        let trimmed = rawQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            results = .empty
            isSearching = false
            return
        }

        results = ChatSearchEngine.search(
            query: trimmed,
            chats: chats,
            chatStore: chatStore,
            offlineStore: offlineStore
        )
        isSearching = false
    }

    private func highlighted(_ text: String, query: String) -> AttributedString {
        var attributed = AttributedString(text)
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return attributed }

        var searchStart = attributed.startIndex
        while let range = attributed[searchStart...].range(of: trimmed, options: [.caseInsensitive, .diacriticInsensitive]) {
            attributed[range].backgroundColor = Color.highlightYellowSolid.opacity(0.4)
            attributed[range].foregroundColor = Color.fontPrimary
            searchStart = range.upperBound
        }
        return attributed
    }
}

private struct ChatSearchResults {
    let groups: [ChatSearchResultGroup]
    let totalCount: Int

    static let empty = ChatSearchResults(groups: [], totalCount: 0)
}

private struct ChatSearchResultGroup: Identifiable {
    let id: String
    let title: String
    let items: [ChatSearchResult]
}

private struct ChatSearchResult: Identifiable {
    let id: String
    let chat: Chat
    let decryptedTitle: String?
    let titleMatch: Bool
    let messageSnippets: [ChatSearchSnippet]
    let metadataSnippets: [ChatMetadataSnippet]
    let sortDate: Date
}

private struct ChatSearchSnippet: Identifiable {
    let id: String
    let messageId: String
    let text: String
    let sourceLabel: String?
    let sortDate: Date
}

private struct ChatMetadataSnippet: Identifiable {
    let id: String
    let text: String
    let sourceLabel: String
}

private enum ChatSearchEngine {
    private static let snippetContextCharacters = 50
    private static let maxSnippetsPerChat = 5
    private static let maxSnippetsPerMessage = 2
    private static let maxEmbedTextCharacters = 1500
    private static let ignoredEmbedSearchKeyFragments = [
        "url", "uri", "href", "src", "image", "thumbnail", "token", "key",
        "secret", "signature", "signed", "authorization", "auth", "cookie",
        "hash"
    ]
    private static let ignoredEmbedSearchKeys = ["id", "embed_id", "chat_id", "user_id"]

    @MainActor
    static func search(
        query: String,
        chats: [Chat],
        chatStore: ChatStore,
        offlineStore: OfflineStore
    ) -> ChatSearchResults {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return .empty }

        let results = chats
            .filter { !$0.isHiddenFromNormalSurfaces }
            .compactMap { chat -> ChatSearchResult? in
                searchChat(chat, query: normalized, chatStore: chatStore, offlineStore: offlineStore)
            }
            .sorted { a, b in
                if a.titleMatch != b.titleMatch { return a.titleMatch }
                let aHasMessages = !a.messageSnippets.isEmpty
                let bHasMessages = !b.messageSnippets.isEmpty
                if aHasMessages != bHasMessages { return aHasMessages }
                return a.sortDate > b.sortDate
            }

        return ChatSearchResults(groups: group(results), totalCount: results.count)
    }

    @MainActor
    private static func searchChat(
        _ chat: Chat,
        query: String,
        chatStore: ChatStore,
        offlineStore: OfflineStore
    ) -> ChatSearchResult? {
        let title = chat.displayTitle
        let titleMatch = title.range(of: query, options: [.caseInsensitive, .diacriticInsensitive]) != nil

        let messages = messages(for: chat, chatStore: chatStore, offlineStore: offlineStore)
        let embeds = embeds(for: chat, chatStore: chatStore, offlineStore: offlineStore)
        let snippets = messageSnippets(in: messages, embeds: embeds, query: query)
        let metadataSnippets = metadataSnippets(in: chat, query: query)

        guard titleMatch || !snippets.isEmpty || !metadataSnippets.isEmpty else { return nil }

        return ChatSearchResult(
            id: chat.id,
            chat: chat,
            decryptedTitle: title,
            titleMatch: titleMatch,
            messageSnippets: snippets,
            metadataSnippets: metadataSnippets,
            sortDate: chat.lastMessageDate ?? chat.updatedDate ?? chat.createdDate ?? Date.distantPast
        )
    }

    @MainActor
    private static func messages(for chat: Chat, chatStore: ChatStore, offlineStore: OfflineStore) -> [Message] {
        if let publicChat = PublicChatContent.chat(for: chat.id) {
            return publicChat.messages
        }

        let inMemory = chatStore.messages(for: chat.id)
        if !inMemory.isEmpty { return inMemory }
        return offlineStore.loadMessages(chatId: chat.id)
    }

    @MainActor
    private static func embeds(for chat: Chat, chatStore: ChatStore, offlineStore: OfflineStore) -> [EmbedRecord] {
        let inMemory = chatStore.embeds(for: chat.id)
        if !inMemory.isEmpty { return inMemory }
        return offlineStore.loadEmbeds(chatId: chat.id)
    }

    private static func messageSnippets(in messages: [Message], embeds: [EmbedRecord], query: String) -> [ChatSearchSnippet] {
        let embedById = EmbedRecord.dictionaryById(embeds, context: "chatSearch.messageSnippets")
        var snippets: [ChatSearchSnippet] = []
        var snippetsPerMessage: [String: Int] = [:]

        let entries = messages.flatMap { message -> [SearchableMessageEntry] in
            var result: [SearchableMessageEntry] = []
            let createdDate = parseDate(message.createdAt) ?? Date.distantPast
            if let content = message.content?.trimmingCharacters(in: .whitespacesAndNewlines), !content.isEmpty {
                result.append(.init(
                    messageId: message.id,
                    text: stripMarkdown(content),
                    sourceLabel: nil,
                    createdAt: createdDate
                ))
            }

            for embedRef in message.embedRefs ?? [] {
                guard let embed = embedById[embedRef.id], embed.status == .finished else { continue }
                guard let embedText = searchableEmbedText(embed), !embedText.isEmpty else { continue }
                result.append(.init(
                    messageId: message.id,
                    text: embedText,
                    sourceLabel: embedSourceLabel(embed),
                    createdAt: createdDate
                ))
            }
            return result
        }
        .sorted { a, b in
            if a.createdAt != b.createdAt { return a.createdAt > b.createdAt }
            return (a.sourceLabel == nil ? 0 : 1) < (b.sourceLabel == nil ? 0 : 1)
        }

        for entry in entries {
            guard snippets.count < maxSnippetsPerChat else { break }
            let existing = snippetsPerMessage[entry.messageId] ?? 0
            guard existing < maxSnippetsPerMessage else { continue }
            guard let range = entry.text.range(of: query, options: [.caseInsensitive, .diacriticInsensitive]) else { continue }
            let snippet = buildSnippet(text: entry.text, matchRange: range)
            snippets.append(.init(
                id: "\(entry.messageId)-\(existing)-\(entry.sourceLabel ?? "message")",
                messageId: entry.messageId,
                text: snippet,
                sourceLabel: entry.sourceLabel,
                sortDate: entry.createdAt
            ))
            snippetsPerMessage[entry.messageId] = existing + 1
        }

        return snippets
    }

    @MainActor
    private static func metadataSnippets(in chat: Chat, query: String) -> [ChatMetadataSnippet] {
        var snippets: [ChatMetadataSnippet] = []
        if let summary = chat.chatSummary?.trimmingCharacters(in: .whitespacesAndNewlines),
           !summary.isEmpty,
           let range = summary.range(of: query, options: [.caseInsensitive, .diacriticInsensitive]) {
            snippets.append(.init(id: "\(chat.id)-summary", text: buildSnippet(text: summary, matchRange: range), sourceLabel: AppStrings.summary))
        }
        if let category = chat.category?.trimmingCharacters(in: .whitespacesAndNewlines),
           !category.isEmpty,
           let range = category.range(of: query, options: [.caseInsensitive, .diacriticInsensitive]) {
            snippets.append(.init(id: "\(chat.id)-category", text: buildSnippet(text: category, matchRange: range), sourceLabel: AppStrings.searchTagMatch))
        }
        return snippets
    }

    @MainActor
    private static func group(_ results: [ChatSearchResult]) -> [ChatSearchResultGroup] {
        let calendar = Calendar.current
        let now = Date()
        let specs: [(id: String, title: String, predicate: (Date) -> Bool)] = [
            ("today", AppStrings.today, { calendar.isDateInToday($0) }),
            ("yesterday", AppStrings.yesterday, { calendar.isDateInYesterday($0) }),
            ("previous_7_days", AppStrings.previous7Days, { date in
                guard let days = calendar.dateComponents([.day], from: date, to: now).day else { return false }
                return days >= 0 && days < 7
            }),
            ("previous_30_days", AppStrings.previous30Days, { date in
                guard let days = calendar.dateComponents([.day], from: date, to: now).day else { return false }
                return days >= 7 && days < 30
            })
        ]

        var emitted = Set<String>()
        var groups: [ChatSearchResultGroup] = []
        for spec in specs {
            let items = results.filter { result in
                guard !emitted.contains(result.id), spec.predicate(result.sortDate) else { return false }
                emitted.insert(result.id)
                return true
            }
            if !items.isEmpty {
                groups.append(.init(id: spec.id, title: spec.title, items: items))
            }
        }

        let remaining = results.filter { !emitted.contains($0.id) }
        if !remaining.isEmpty {
            groups.append(.init(id: "older", title: AppStrings.chats, items: remaining))
        }
        return groups
    }

    private static func buildSnippet(text: String, matchRange: Range<String.Index>) -> String {
        let matchStart = text.distance(from: text.startIndex, to: matchRange.lowerBound)
        let matchEnd = text.distance(from: text.startIndex, to: matchRange.upperBound)
        let startOffset = max(0, matchStart - snippetContextCharacters)
        let endOffset = min(text.count, matchEnd + snippetContextCharacters)
        let start = text.index(text.startIndex, offsetBy: startOffset)
        let end = text.index(text.startIndex, offsetBy: endOffset)
        var snippet = String(text[start..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
        if startOffset > 0 { snippet = "... " + snippet }
        if endOffset < text.count { snippet += " ..." }
        return snippet
    }

    private static func searchableEmbedText(_ embed: EmbedRecord) -> String? {
        var pieces: [String] = []
        if let raw = embed.rawData {
            collectText(from: raw, into: &pieces)
        }
        let text = pieces.joined(separator: " ")
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        return String(text.prefix(maxEmbedTextCharacters))
    }

    private static func collectText(from value: Any, into pieces: inout [String]) {
        switch value {
        case let dict as [String: AnyCodable]:
            for (key, item) in dict where shouldIndexEmbedField(key) {
                collectText(from: item.value, into: &pieces)
            }
        case let dict as [String: Any]:
            for (key, item) in dict where shouldIndexEmbedField(key) {
                collectText(from: item, into: &pieces)
            }
        case let array as [AnyCodable]:
            for item in array { collectText(from: item.value, into: &pieces) }
        case let array as [Any]:
            for item in array { collectText(from: item, into: &pieces) }
        case let string as String:
            if !string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                pieces.append(string)
            }
        case let number as NSNumber:
            pieces.append(number.stringValue)
        default:
            break
        }
    }

    private static func shouldIndexEmbedField(_ key: String) -> Bool {
        let normalized = key.lowercased()
        if ignoredEmbedSearchKeys.contains(normalized) { return false }
        return !ignoredEmbedSearchKeyFragments.contains { normalized.contains($0) }
    }

    private static func embedSourceLabel(_ embed: EmbedRecord) -> String {
        let readable = embed.type
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
        return readable.capitalized
    }

    private static func stripMarkdown(_ text: String) -> String {
        var result = text
        let replacements: [(String, String)] = [
            (#"```json\s*\{[\s\S]*?\}\s*```"#, ""),
            (#"```[\s\S]*?```"#, " "),
            (#"`([^`]+)`"#, "$1"),
            (#"!\[([^\]]*)\]\([^)]+\)"#, "$1"),
            (#"\[([^\]]+)\]\([^)]+\)"#, "$1"),
            (#"(\*{1,3}|_{1,3})(\S[\s\S]*?\S)\1"#, "$2"),
            (#"(?m)^#{1,6}\s+"#, ""),
            (#"(?m)^>\s?"#, ""),
            (#"(?m)^\s*[-*+]\s+"#, ""),
            (#"(?m)^\s*\d+\.\s+"#, ""),
            (#"\s+"#, " ")
        ]
        for (pattern, replacement) in replacements {
            result = result.replacingOccurrences(of: pattern, with: replacement, options: .regularExpression)
        }
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func parseDate(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        return ISO8601DateFormatter().date(from: value)
    }

    private struct SearchableMessageEntry {
        let messageId: String
        let text: String
        let sourceLabel: String?
        let createdAt: Date
    }
}
