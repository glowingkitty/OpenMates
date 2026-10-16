// Contextual composer search uses decrypted local state, never a server query.
// Web source: frontend/packages/ui/src/components/NewChatSuggestions.svelte
//             frontend/packages/ui/src/components/ChatSearchSuggestions.svelte
//             frontend/packages/ui/src/services/searchService.ts
// CSS: .suggestion-card, .chat-result-wrapper, .chat-search-scroll
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.suggestions.contextual, message-input.privacy-context

import Combine
import SwiftUI

struct ComposerEmbedSearchResult: Identifiable {
    let record: EmbedRecord
    let title: String
    let appID: String
    var id: String { record.id }
    @MainActor var subtitle: String { (record.isAppSkillUse || record.type.hasPrefix("app:")) ? AppStrings.composerSearchSkillResult : AppStrings.composerSearchEmbed }
    var relatedRecords: [EmbedRecord] = []
    var nodeType: String {
        if record.isAppSkillUse || record.type.hasPrefix("app:") { return "app-skill-use" }
        // Generated write types describe the composer atom; the retained record
        // selects its exact read renderer (including notebooks and applications).
        switch EmbedType.normalized(rawValue: record.type) {
        case .codeNotebook, .codeApplication: return "code-code"
        case .fileFile, .diagramsMermaid, .models3dModelResult: return "docs-doc"
        case .designIconResult: return "image"
        default: return record.type == "audio-recording" ? "recording" : record.type
        }
    }
    var referenceType: String { record.isAppSkillUse || record.type.hasPrefix("app:") ? "app_skill_use" : record.type }

    @MainActor
    func insert(into session: NativeComposerSession, nodeID: String) throws {
        // Web insertion focuses the end, even when the user selected text.
        try session.controller.setSelection(NSRange(location: session.controller.attributedString.length, length: 0))
        try session.insertPendingEmbed(nodeID: nodeID, embedType: nodeType, title: title)
        try session.resolveEmbed(nodeID: nodeID, durableEmbedID: id, referenceType: referenceType,
            status: AppleComposerEmbedLifecycleState.finished.rawValue, embedRecord: record)
    }

    /// Existing references must retain their durable identity and key wrappers.
    /// A nil content payload prevents sending a duplicate upload to the backend.
    @MainActor var pendingReference: ComposerPendingEmbed {
        ComposerPendingEmbed(id: id, type: record.type, referenceType: referenceType,
            status: record.status.rawValue, content: nil, textPreview: title,
            record: record, localData: nil, filename: title, size: 0, piiMappings: [],
            storageDisposition: .existingStoredReference(.current))
    }
}

@MainActor
final class ComposerSearchSuggestionsController: ObservableObject {
    @Published private(set) var query = ""
    @Published private(set) var chats: [Chat] = []
    @Published private(set) var embeds: [ComposerEmbedSearchResult] = []
    private var task: Task<Void, Never>?
    private var searchGeneration = UUID()
    private var isSearchRunning = false
    private var pendingStoreRefresh = false
    private var activeContext: SearchContext?

    // A publisher event can belong to a different composer/account even while
    // the previous metadata task is suspended. Only coalesce the same search.
    private struct SearchContext: Equatable {
        let query: String
        let store: ObjectIdentifier
        let authenticated: Bool
        let accountID: String?
        let chatID: String?
        let scope: UUID
        let server: String
        let teamAccountID: String?
        let teamID: String?
        let teamScope: UUID?
        let teamEpoch: UInt64
        let language: String
    }

    var hasResults: Bool { !chats.isEmpty || !embeds.isEmpty }

    func cancel() {
        task?.cancel()
        task = nil
        searchGeneration = UUID()
        isSearchRunning = false
        pendingStoreRefresh = false
        activeContext = nil
        query = ""
        chats = []
        embeds = []
    }

    func schedule(text: String, store: ChatStore, authenticated: Bool,
                  accountID: String?, currentChatID: String? = nil,
                  prepareMetadata: @escaping () async -> Void = {}, storeChanged: Bool = false) {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else { cancel(); return }
        let scope = OfflineStore.shared.scopeGeneration
        let team = TeamWorkspaceContext.shared.snapshot
        let server = ServerProfile.current().apiBaseURL.absoluteString
        let language = LocalizationManager.shared.currentLanguage.code
        let context = SearchContext(query: normalized, store: ObjectIdentifier(store),
            authenticated: authenticated, accountID: accountID, chatID: currentChatID,
            scope: scope, server: server, teamAccountID: team.accountID, teamID: team.teamID,
            teamScope: team.scope, teamEpoch: team.epoch, language: language)
        // Metadata preparation publishes into the same production store that
        // hosts observe. Coalesce its updates; a changed scope/query must cancel.
        if storeChanged && isSearchRunning && activeContext == context {
            pendingStoreRefresh = true
            return
        }
        task?.cancel()
        activeContext = context
        let generation = UUID()
        searchGeneration = generation
        isSearchRunning = true
        pendingStoreRefresh = false
        task = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled, let self else { return }
            defer {
                if self.searchGeneration == generation {
                    self.isSearchRunning = false
                    self.task = nil
                }
            }
            let isCurrent: @MainActor @Sendable () -> Bool = {
                !Task.isCancelled && self.searchGeneration == generation
                    && scope == OfflineStore.shared.scopeGeneration
                    && server == ServerProfile.current().apiBaseURL.absoluteString
                    && language == LocalizationManager.shared.currentLanguage.code
                    && Self.isTeamContextCurrent(team)
            }
            guard isCurrent() else { return }
            await prepareMetadata()
            guard isCurrent() else { return }
            // Store changes during hydration (including external arrivals) are
            // represented by the fresh snapshot below. Later changes request
            // one follow-up pass after the current search publishes.
            self.pendingStoreRefresh = false
            let expectedScope = accountID.map { OfflineStore.scopeId(userId: $0, apiBaseURL: ServerProfile.current().apiBaseURL) }
            let offline = authenticated && expectedScope == OfflineStore.shared.activeScopeId && expectedScope != nil
                ? OfflineStore.shared : nil
            guard scope == OfflineStore.shared.scopeGeneration else { self.cancel(); return }
            let loaded = store.chats.filter { authenticated || PublicChatContent.isPublicChat($0.id) }
            let cached = offline?.loadChats() ?? []
            let eligible = Self.eligibleChats(loaded + ChatSearchMetadata.missingCachedChats(cached, loaded: loaded))
            guard let matches = try? await ChatSearchEngine.searchAsync(query: normalized,
                chats: eligible, chatStore: store, offlineStore: offline,
                offlineContentChatIds: Set(eligible.map(\.id)), isCurrent: isCurrent),
                  isCurrent() else { return }
            var records: [EmbedRecord] = []
            for (index, chat) in eligible.enumerated() {
                // Local reads stay on their store actor, but a large local
                // catalog must yield to navigation and a replacement query.
                if index.isMultiple(of: 4) { await Task.yield() }
                guard isCurrent() else { return }
                guard let local = try? await Self.localEmbeds(chat: chat, store: store, offline: offline),
                      isCurrent() else { return }
                let decrypted = await Self.decryptLocalEmbeds(local, chatID: chat.id, isCurrent: isCurrent)
                records.append(contentsOf: decrypted)
            }
            /* local decrypted results remain memory-only */
            guard isCurrent() else { return }
            self.query = normalized
            self.chats = Array(matches.groups.flatMap(\.items).map(\.chat).filter { $0.id != currentChatID }.prefix(5))
            self.embeds = Self.searchEmbeds(query: normalized, records: records)
            if self.pendingStoreRefresh {
                self.isSearchRunning = false
                self.schedule(text: text, store: store, authenticated: authenticated,
                    accountID: accountID, currentChatID: currentChatID, prepareMetadata: prepareMetadata)
            }
        }
    }

    static func isTeamContextCurrent(_ snapshot: TeamWorkspaceSnapshot) -> Bool {
        let current = TeamWorkspaceContext.shared.snapshot
        // Public previews/guests have no Team scope. Still fence any transition
        // to an account or Team while the local search is suspended.
        if snapshot.scope == nil {
            return current.scope == nil && current.accountID == snapshot.accountID &&
                current.server == snapshot.server && current.teamID == snapshot.teamID && current.epoch == snapshot.epoch
        }
        return TeamWorkspaceContext.shared.isCurrent(snapshot)
    }

    static func localEmbeds(chat: Chat, store: ChatStore, offline: OfflineStore?) async throws -> [EmbedRecord] {
        if PublicChatContent.isPublicChat(chat.id), let publicChat = PublicChatContent.chat(for: chat.id) {
            return Array(publicChat.embedRecords.values)
        }
        let cached: [EmbedRecord]
        if let offline {
            cached = try await offline.loadSearchContent(chatID: chat.id, includeMessages: false, includeEmbeds: true).embeds
        } else {
            cached = []
        }
        var merged = EmbedRecord.dictionaryById(cached, context: "composerSearch.local")
        for record in store.embeds(for: chat.id) { merged[record.id] = record }
        return Array(merged.values)
    }

    private static func decryptLocalEmbeds(_ records: [EmbedRecord], chatID: String,
                                           isCurrent: () -> Bool) async -> [EmbedRecord] {
        let byID = EmbedRecord.dictionaryById(records, context: "composerSearch.decrypt")
        var result: [EmbedRecord] = []
        for (index, record) in records.enumerated() {
            if index.isMultiple(of: 16) { await Task.yield() }
            guard isCurrent() else { return [] }
            guard record.rawData == nil, record.encryptedContent != nil || record.encryptedType != nil else {
                result.append(record); continue
            }
            guard let key = await EmbedKeyManager.shared.key(for: record, chatId: chatID, allEmbeds: byID), isCurrent() else { continue }
            var content: String?
            var type: String?
            if let encrypted = record.encryptedContent {
                content = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
                guard isCurrent() else { return [] }
            }
            if let encrypted = record.encryptedType {
                type = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
                guard isCurrent() else { return [] }
            }
            result.append(record.decryptedCopy(content: content, type: type))
        }
        return result
    }

    static func eligibleChats(_ chats: [Chat]) -> [Chat] {
        var seen = Set<String>()
        return chats.filter { !$0.isRetiredBundledIntro && !$0.isHiddenFromNormalSurfaces && $0.parentId == nil && $0.isSubChat != true
            && !IncognitoChatSession.isIncognitoChatId($0.id) && seen.insert($0.id).inserted }
    }

    static func searchEmbeds(query: String, records: [EmbedRecord]) -> [ComposerEmbedSearchResult] {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return [] }
        var seen = Set<String>()
        return records.sorted { ($0.createdAt ?? "") > ($1.createdAt ?? "") }.compactMap { record in
            guard record.status == .finished, seen.insert(record.id).inserted, let raw = record.rawData else { return nil }
            // Search only display fields. URLs, encryption material, private PII
            // maps, account identifiers and transport metadata are excluded.
            let fields = ["filename", "file_name", "title", "name", "display_name", "description", "summary", "text_preview"]
            let strings = fields.compactMap { raw[$0]?.value as? String }.filter { !$0.isEmpty }
            guard let title = strings.first,
                  strings.contains(where: { $0.range(of: normalized, options: [.caseInsensitive, .diacriticInsensitive]) != nil }) else { return nil }
            let app = record.appId ?? EmbedType.normalized(rawValue: record.type)?.appId ?? "files"
            return ComposerEmbedSearchResult(record: record, title: title, appID: app,
                relatedRecords: EmbedRecord.relatedRecords(referencedIds: [record.id], from: records, context: "composerSearch.related"))
        }.prefix(10).map { $0 }
    }
}

struct ComposerSearchResultCard: View {
    let title: String
    let subtitle: String?
    let icon: String
    let appID: String
    let width: CGFloat
    let identifier: String
    let onSelect: () -> Void

    var body: some View {
        VStack(spacing: .spacing2) {
            Button(action: onSelect) {
                HStack(spacing: width <= 210 ? .spacing4 : .spacing5) {
                    Icon(icon, size: 24).foregroundStyle(Color.fontButton).frame(width: 27, height: 27)
                    Text(title).font((width <= 210 ? Font.omXs : .omSmall).weight(.bold))
                        .foregroundStyle(Color.fontButton).lineLimit(2).multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, width <= 210 ? .spacing6 : .spacing8)
                .padding(.vertical, width <= 210 ? .spacing5 : .spacing6)
                .frame(width: width).frame(minHeight: 56)
                .background(AppIconView.gradient(forAppId: appID))
                // Web .suggestion-card computed border-radius: 15px.
                .clipShape(RoundedRectangle(cornerRadius: 15))
                .shadow(color: .black.opacity(0.3), radius: 4, x: 0, y: 4)
                .contentShape(RoundedRectangle(cornerRadius: 15))
            }
            .buttonStyle(.plain).accessibilityIdentifier(identifier)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle).font(.omTiny).foregroundStyle(Color.grey50).opacity(0.8).lineLimit(1)
            }
        }
    }
}

struct ComposerSearchSuggestionsHost: View {
    @ObservedObject var store: ChatStore
    let text: String
    let authenticated: Bool
    let accountID: String?
    let currentChatID: String?
    var prepareMetadata: () async -> Void = {}
    let onOpenChat: (String) -> Void
    let onSelectEmbed: (ComposerEmbedSearchResult) -> Void
    @StateObject private var search = ComposerSearchSuggestionsController()
    @ObservedObject private var teamContext = TeamWorkspaceContext.shared

    var body: some View {
        Group {
            if search.hasResults {
                GeometryReader { proxy in
                    let width: CGFloat = proxy.size.width <= 730 ? 210 : 300
                    let inset = max(0, (proxy.size.width - width) / 2)
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(AppStrings.composerRelatedChats).font(proxy.size.width <= 730 ? .omSmall : .omP).foregroundStyle(Color.grey60).padding(.leading, inset)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: proxy.size.width <= 730 ? .spacing5 : .spacing6) {
                                ForEach(search.embeds) { result in
                                    ComposerSearchResultCard(title: result.title, subtitle: result.subtitle,
                                        icon: AppIconView.iconName(forAppId: result.appID), appID: result.appID,
                                        width: width, identifier: "recent-embed-search-result") { onSelectEmbed(result) }
                                }
                                if !search.embeds.isEmpty && !search.chats.isEmpty {
                                    Color.grey30.opacity(0.4).frame(width: 1, height: 40)
                                }
                                ForEach(search.chats) { chat in
                                    ComposerSearchResultCard(title: chat.displayTitle, subtitle: Self.dateLabel(chat),
                                        icon: chat.icon ?? CategoryMapping.iconName(for: chat.category ?? "general_knowledge"),
                                        appID: chat.category ?? "general_knowledge", width: width,
                                        identifier: "chat-search-result") { onOpenChat(chat.id) }
                                }
                            }.padding(.leading, inset)
                                .padding(.trailing, proxy.size.width <= 730 ? 15 : 48)
                                .padding(.top, 4).padding(.bottom, proxy.size.width <= 730 ? 8 : 14)
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("composer-search-results-carousel")
                    }
                    .mask(LinearGradient(stops: [
                        .init(color: .clear, location: 0), .init(color: .black, location: 0.04),
                        .init(color: .black, location: 0.96), .init(color: .clear, location: 1)
                    ], startPoint: .leading, endPoint: .trailing))
                }.frame(height: 106)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("chat-search-suggestions")
            }
        }
        .task(id: text) { schedule() }
        .onReceive(store.objectWillChange) { _ in schedule(storeChanged: true) }
        .onChange(of: teamContext.contextEpoch) { _, _ in search.cancel(); schedule() }
        .onChange(of: authenticated) { _, _ in search.cancel(); schedule() }
        .onChange(of: accountID) { _, _ in search.cancel(); schedule() }
        .onDisappear { search.cancel() }
    }

    static func dateLabel(_ chat: Chat) -> String? {
        guard PublicChatContent.chat(for: chat.id) == nil,
              let date = chat.lastMessageDate ?? chat.updatedDate ?? chat.createdDate else { return nil }
        if Calendar.current.isDateInToday(date) { return AppStrings.today }
        if Calendar.current.isDateInYesterday(date) { return AppStrings.yesterday }
        return Calendar.current.component(.year, from: date) == Calendar.current.component(.year, from: Date())
            ? date.formatted(.dateTime.month(.abbreviated).day())
            : date.formatted(.dateTime.month(.abbreviated).year())
    }

    private func schedule(storeChanged: Bool = false) {
        search.schedule(text: text, store: store, authenticated: authenticated,
            accountID: accountID, currentChatID: currentChatID, prepareMetadata: prepareMetadata, storeChanged: storeChanged)
    }
}
