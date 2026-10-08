// Spotlight indexer — indexes chats into Core Spotlight so users can find
// their conversations from the system search (Spotlight / Cmd-Space).
// Each chat becomes a searchable item with its title and last message date.
// Items are updated incrementally when chats are loaded and removed when deleted.

import CoreSpotlight
import CryptoKit
import UniformTypeIdentifiers
#if os(iOS)
import UIKit
#endif

@MainActor
final class SpotlightIndexer {
    static let shared = SpotlightIndexer()
    private let index = CSSearchableIndex(name: "OpenMatesChats")
    private let legacyDefaultIndex = CSSearchableIndex.default()
    private var pendingIndexTask: Task<Void, Never>?
    private let chatIdentifierPrefix = "chat-"
    private let chatsDomainIdentifier = "org.openmates.chats"
    private var indexGeneration = UUID()
    private var currentIdentity: String?
    private let initialIndexDelayNs: UInt64 = 45_000_000_000
    private let perChatPauseNs: UInt64 = 90_000_000

    private init() {}

    /// Index retained metadata across Personal and all authorized Teams. No message
    /// history is downloaded or decrypted for system search.
    func indexChats(_ chats: [Chat]) {
        scheduleIndexChats(chats, reason: "metadata")
    }

    func scheduleIndexChats(
        _ chats: [Chat],
        reason: String,
        metadataProvider: (@MainActor (Chat) async -> Chat)? = nil
    ) {
        guard CSSearchableIndex.isIndexingAvailable() else { return }
        let context = TeamWorkspaceContext.shared.snapshot
        guard let accountID = context.accountID, context.scope == OfflineStore.shared.scopeGeneration,
              context.server == ServerProfile.current() else { removeAllItems(); return }
        let fence = TeamWorkspaceFence(accountID: accountID)
        let identity = Self.identity(accountID: accountID, server: fence.server)
        if currentIdentity != identity { removeAllItems(); currentIdentity = identity }
        let previous = pendingIndexTask
        previous?.cancel()
        let generation = UUID()
        indexGeneration = generation
        let snapshot = Self.authorizedChats(chats, readableTeamIDs: Set(TeamWorkspaceContext.shared.teams.filter(\.canRead).map(\.id)))
        pendingIndexTask = Task { [weak self] in
            // Serialize a cancelled in-flight submission and its cleanup before a
            // replacement can publish the same identifiers.
            await previous?.value
            do { try await Task.sleep(nanoseconds: self?.initialIndexDelayNs ?? 0) } catch { return }
            guard let self, !Task.isCancelled, self.indexGeneration == generation else { return }
            let start = NativeSyncPerfLog.now()
            var items: [CSSearchableItem] = []
            for chat in snapshot {
                do { try await fence.check() } catch { return }
                guard !Task.isCancelled, self.indexGeneration == generation else { return }
                guard Self.isAuthorized(chat, readableTeamIDs: Set(TeamWorkspaceContext.shared.teams.filter(\.canRead).map(\.id))) else { continue }
                let value = await metadataProvider?(chat) ?? chat
                do { try await fence.check() } catch { return }
                guard !Task.isCancelled, self.indexGeneration == generation else { return }
                guard Self.isAuthorized(value, readableTeamIDs: Set(TeamWorkspaceContext.shared.teams.filter(\.canRead).map(\.id))), value.teamId == chat.teamId else { continue }
                if let item = self.metadataOnlySearchableItem(for: value) { items.append(item) }
                // Retained metadata is finite; commit small batches and yield so
                // system indexing does not stall the foreground renderer.
                if items.count == 20 {
                    await self.submitItems(items)
                    guard await self.submissionIsCurrent(items, generation: generation, fence: fence) else { return }
                    items.removeAll(keepingCapacity: true)
                }
                await Task.yield()
                do { try await Task.sleep(nanoseconds: self.perChatPauseNs) } catch { return }
            }
            if !items.isEmpty {
                await self.submitItems(items)
                guard await self.submissionIsCurrent(items, generation: generation, fence: fence) else { return }
            }
            NativeSyncPerfLog.info("phase=spotlightIndex reason=\(reason) mode=metadataOnly chats=\(snapshot.count) indexMs=\(NativeSyncPerfLog.ms(since: start))")
        }
    }

    private func submissionIsCurrent(_ items: [CSSearchableItem], generation: UUID, fence: TeamWorkspaceFence) async -> Bool {
        let validAccount = (try? await fence.check()) != nil
        guard validAccount, !Task.isCancelled, indexGeneration == generation else {
            try? await index.deleteSearchableItems(withIdentifiers: items.map(\.uniqueIdentifier))
            return false
        }
        return true
    }

    static func authorizedChats(_ chats: [Chat], readableTeamIDs: Set<String>) -> [Chat] {
        chats.filter { isEligibleForSpotlight($0) && isAuthorized($0, readableTeamIDs: readableTeamIDs) }
    }

    private static func isAuthorized(_ chat: Chat, readableTeamIDs: Set<String>) -> Bool {
        chat.teamId == nil || chat.teamId.map(readableTeamIDs.contains) == true
    }

    private static func identity(accountID: String, server: ServerProfile) -> String {
        SHA256.hash(data: Data("\(accountID)|\(server.apiBaseURL.absoluteString)".utf8))
            .map { String(format: "%02x", $0) }.joined()
    }

    /// Stable account/server identifiers survive a cold launch; runtime fences
    /// still guard every asynchronous write and membership gates every open.
    static func chatIdentifier(chatID: String, accountID: String, server: ServerProfile) -> String {
        "chat-\(identity(accountID: accountID, server: server)):\(chatID)"
    }

    static func chatID(for identifier: String, accountID: String, server: ServerProfile) -> String? {
        let prefix = "chat-\(identity(accountID: accountID, server: server)):"
        guard identifier.hasPrefix(prefix) else { return nil }
        let id = String(identifier.dropFirst(prefix.count))
        return id.isEmpty ? nil : id
    }

    func chatID(for identifier: String) -> String? {
        let context = TeamWorkspaceContext.shared.snapshot
        guard let accountID = context.accountID, context.server == ServerProfile.current(),
              context.scope == OfflineStore.shared.scopeGeneration else { return nil }
        return Self.chatID(for: identifier, accountID: accountID, server: ServerProfile.current())
    }

    /// Remove a single chat from the Spotlight index (called on delete).
    func removeChat(_ chatId: String) {
        pendingIndexTask?.cancel(); indexGeneration = UUID()
        var identifiers = ["\(chatIdentifierPrefix)\(chatId)"]
        if let currentIdentity { identifiers.append("\(chatIdentifierPrefix)\(currentIdentity):\(chatId)") }
        index.deleteSearchableItems(withIdentifiers: identifiers) { error in
            if let error {
                print("[Spotlight] Failed to remove chat: \(error)")
            }
        }
        legacyDefaultIndex.deleteSearchableItems(withIdentifiers: identifiers, completionHandler: nil)
    }

    /// Clear all OpenMates items from Spotlight (called on logout).
    func removeAllItems() {
        pendingIndexTask?.cancel(); indexGeneration = UUID(); currentIdentity = nil
        let domainIdentifiers = [chatsDomainIdentifier]
        index.deleteSearchableItems(withDomainIdentifiers: domainIdentifiers) { error in
            if let error {
                print("[Spotlight] Failed to clear index: \(error)")
            }
        }
        legacyDefaultIndex.deleteSearchableItems(withDomainIdentifiers: domainIdentifiers, completionHandler: nil)
    }

    private func searchableItem(for chat: Chat, attributes: CSSearchableItemAttributeSet) -> CSSearchableItem {
        let item = CSSearchableItem(
            uniqueIdentifier: "\(chatIdentifierPrefix)\(currentIdentity ?? "unavailable"):\(chat.id)",
            domainIdentifier: chatsDomainIdentifier,
            attributeSet: attributes
        )
        item.expirationDate = .distantFuture
        return item
    }

    private func submitItems(_ items: [CSSearchableItem]) async {
        do {
            try await index.indexSearchableItems(items)
            print("[Spotlight] Indexed \(items.count) chats")
        } catch {
            print("[Spotlight] Failed to index chats: \(error)")
        }
    }

    private func spotlightKeywords(for chat: Chat) -> [String] {
        var keywords = ["OpenMates", "chat"]
        if let category = chat.category?.trimmingCharacters(in: .whitespacesAndNewlines), !category.isEmpty {
            keywords.append(category)
        }
        return keywords
    }

    private func metadataOnlySearchableItem(for chat: Chat) -> CSSearchableItem? {
        guard Self.isEligibleForSpotlight(chat) else { return nil }
        guard let title = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else { return nil }

        let attributes = CSSearchableItemAttributeSet(contentType: .text)
        attributes.title = title
        attributes.displayName = title
        attributes.contentDescription = [chat.category, chat.chatSummary]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
        attributes.lastUsedDate = chat.lastMessageDate
        attributes.keywords = spotlightKeywords(for: chat)

        #if os(iOS)
        attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
        #endif

        return searchableItem(for: chat, attributes: attributes)
    }

    static func isEligibleForSpotlight(_ chat: Chat) -> Bool {
        guard chat.isArchived != true, chat.parentId == nil, chat.isSubChat != true,
              !chat.isRetiredBundledIntro, !IncognitoChatSession.isIncognitoChatId(chat.id) else { return false }
        guard !chat.isHiddenFromNormalSurfaces else { return false }
        guard !isPublicChat(chat.id) else { return false }
        return true
    }

    private static func isPublicChat(_ chatId: String) -> Bool {
        chatId.hasPrefix("demo-") ||
        chatId.hasPrefix("legal-") ||
        chatId.hasPrefix("example-") ||
        chatId.hasPrefix("announcements-")
    }
}
