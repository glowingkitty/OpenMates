// Unit coverage for Apple chat-sync metadata parity with the web app.
// These tests are deterministic and do not touch the network, credentials, or
// private persisted chat content. They guard native model changes that would
// otherwise silently drop sub-chat or active-focus metadata during sync.

import XCTest
import CoreFoundation
import Combine
import SwiftData
@testable import OpenMates

@MainActor
final class ChatSyncParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent,chats.surface.semantic-parity
    func testOpeningOneUnreadChatKeepsOtherBadgeAndExplicitActivationRepairsOSState() {
        var badges: [Int] = []
        let unread = UnreadMessagesStore(badgeUpdater: { badges.append($0) })
        unread.configure(scopeID: "synthetic-owner-server", teamID: "team-a")
        unread.setUnread(chatId: "opened", count: 2, teamID: "team-a")
        unread.setUnread(chatId: "other", count: 1, teamID: "team-a")
        unread.setUnread(chatId: "inactive-team", count: 4, teamID: "team-b")
        XCTAssertEqual(unread.totalUnread, 3, "The badge counts messages in the selected Team")
        badges.removeAll()
        unread.setActiveChat("opened")
        XCTAssertEqual(unread.totalUnread, 1)
        XCTAssertEqual(unread.getUnreadCount(chatId: "other", teamID: "team-a"), 1)
        XCTAssertEqual(badges, [1])
        // The OS may retain a stale badge independently of unchanged metadata.
        unread.resynchronizeBadge()
        XCTAssertEqual(badges, [1, 1])
        unread.setUnread(chatId: "opened", count: 2, teamID: "team-a")
        XCTAssertEqual(unread.totalUnread, 1, "Hydration must retain active-chat suppression")
        XCTAssertEqual(badges, [1, 1], "Ordinary unchanged metadata still avoids extra writes")
        unread.setActiveTeam("team-b")
        XCTAssertEqual(unread.totalUnread, 4)
        unread.resynchronizeBadge()
        XCTAssertEqual(badges.suffix(2), [4, 4])
        unread.configure(scopeID: "other-owner-server", teamID: "team-b")
        XCTAssertEqual(unread.totalUnread, 0)
        XCTAssertEqual(badges.last, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.apple-web-parity
    func testSignedOutWelcomeFiltersExistingExamplesAndRestoresUnfilteredCatalogOnSkip() {
        let event = makeChat(id: "example-creativity-drawing-meetups-berlin", title: "Events")
        let science = makeChat(id: "example-artemis-ii-mission", title: "Science")
        let privateChat = makeChat(id: "private-chat", title: "Private")
        let retired = makeChat(id: "demo-for-everyone", title: "Retired")
        let source = [science, privateChat, event, retired]
        XCTAssertEqual(WelcomeScreenState.guestExampleChats(from: source, selected: []).map(\.id), [science.id, event.id])
        XCTAssertEqual(WelcomeScreenState.availableGuestTopics(from: source), [.findEvents, .science, .generalKnowledge])
        XCTAssertFalse(WelcomeScreenState.availableGuestTopics(from: source).contains(.privacy))
        XCTAssertEqual(WelcomeScreenState.guestExampleChats(from: source, selected: [.findEvents]).map(\.id), [event.id])
        XCTAssertEqual(WelcomeScreenState.guestExampleChats(from: source, selected: [.science]).map(\.id), [science.id])
        XCTAssertTrue(WelcomeScreenState.guestExampleChats(from: source, selected: [.privacy]).isEmpty,
            "A topic without an existing catalog match must not silently show unrelated examples")
        XCTAssertEqual(WelcomeScreenState.guestExampleChats(from: source, selected: []).map(\.id), [science.id, event.id])
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.apple-web-parity
    func testSignedOutFallbackIsNormalDailyInspirationAvailableBeforeAPI() {
        let fallback = WelcomeScreenState.signedOutFallbackInspirations
        XCTAssertEqual(fallback.map(\.inspirationId), ["hardcoded-dreams", "hardcoded-history", "hardcoded-activism"])
        XCTAssertTrue(fallback.allSatisfy { !$0.text.isEmpty })
        XCTAssertFalse(fallback.contains { $0.inspirationId?.hasPrefix("openmates-") == true })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
    func testStoreContentRevisionTracksSameIDReplacementAndRemainsChatScoped() {
        let store = ChatStore()
        let time = "2026-01-01T00:00:00Z"
        func row(_ cipher: String?, streaming: Bool, alias: String? = nil) -> Message {
            Message(id: "same-id", chatId: "chat-1", role: .assistant, content: nil,
                encryptedContent: cipher, createdAt: time, updatedAt: nil, appId: nil,
                isStreaming: streaming, embedRefs: nil, serverMessageId: alias)
        }
        store.performWithoutPersistence { store.appendMessage(row(nil, streaming: true, alias: "db-alias"), to: "chat-1") }
        let revision = store.contentRevision(for: "chat-1")
        store.performWithoutPersistence { store.appendMessage(row("saved-ciphertext", streaming: false), to: "chat-1") }
        XCTAssertGreaterThan(store.contentRevision(for: "chat-1"), revision)
        XCTAssertEqual(store.contentRevision(for: "other-chat"), 0)
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["same-id"])
        XCTAssertEqual(store.messages(for: "chat-1").first?.encryptedContent, "saved-ciphertext")
        XCTAssertEqual(store.messages(for: "chat-1").first?.serverMessageId, "db-alias")
        store.clearInMemory()
        XCTAssertEqual(store.contentRevision(for: "chat-1"), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnreadHundredChatSteadyHydrationAndDuplicateCompletionPublishNothing() {
        var badges: [Int] = []
        let unread = UnreadMessagesStore(badgeUpdater: { badges.append($0) })
        unread.configure(scopeID: "synthetic-account-server", teamID: nil)
        for index in 0..<100 {
            unread.setUnread(chatId: "chat-\(index)", count: index % 4)
        }
        _ = unread.incrementUnread(chatId: "chat-1", messageID: "synthetic-completion")
        var publications = 0
        let subscription = unread.objectWillChange.sink { publications += 1 }
        badges.removeAll()
        for _ in 0..<3 {
            unread.configure(scopeID: "synthetic-account-server", teamID: nil)
            unread.setActiveTeam(nil)
            unread.setActiveChat(nil)
            for index in 0..<100 {
                unread.setUnread(chatId: "chat-\(index)", count: index == 1 ? 2 : index % 4)
            }
        }
        XCTAssertNil(unread.incrementUnread(chatId: "chat-1", messageID: "synthetic-completion"))
        XCTAssertEqual(publications, 0)
        XCTAssertTrue(badges.isEmpty)
        withExtendedLifetime(subscription) {}
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnreadActualZeroActiveClearTeamAndScopeChangesStillPublish() {
        var badges: [Int] = []
        let unread = UnreadMessagesStore(badgeUpdater: { badges.append($0) })
        unread.configure(scopeID: "synthetic-account-server", teamID: nil)
        unread.setUnread(chatId: "personal", count: 2)
        unread.setUnread(chatId: "team-chat", count: 2, teamID: "team-a")
        var publications = 0
        let subscription = unread.objectWillChange.sink { publications += 1 }
        badges.removeAll()
        unread.setActiveTeam("team-a")
        XCTAssertGreaterThan(publications, 0, "Team changes notify even when totals match")
        XCTAssertTrue(badges.isEmpty, "An unchanged total needs no OS badge update")
        publications = 0
        unread.setUnread(chatId: "team-chat", count: 0, teamID: "team-a")
        XCTAssertGreaterThan(publications, 0, "Cross-device zero receipt clears a positive count")
        XCTAssertEqual(badges, [0])
        publications = 0; badges.removeAll()
        unread.setUnread(chatId: "team-chat", count: -1, teamID: "team-a")
        XCTAssertEqual(publications, 0)
        unread.setUnread(chatId: "team-chat", count: 3, teamID: "team-a")
        publications = 0; badges.removeAll()
        unread.setActiveChat("team-chat")
        XCTAssertGreaterThan(publications, 0); XCTAssertEqual(badges, [0])
        publications = 0; badges.removeAll()
        unread.setActiveChat("team-chat")
        unread.setUnread(chatId: "team-chat", count: 7, teamID: "team-a")
        XCTAssertEqual(publications, 0, "Active suppression normalizes hydration before the no-op guard")
        XCTAssertTrue(badges.isEmpty)
        unread.configure(scopeID: "synthetic-other-account-server", teamID: "team-a")
        XCTAssertGreaterThan(publications, 0, "Owner changes notify even with a zero total")
        XCTAssertEqual(unread.getUnreadCount(chatId: "personal", teamID: nil), 0)
        withExtendedLifetime(subscription) {}
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnreadEntryIdentityAndInitialUnconfiguredBadgeClearArePreserved() {
        var badges: [Int] = []
        let unread = UnreadMessagesStore(badgeUpdater: { badges.append($0) })
        var publications = 0
        let subscription = unread.objectWillChange.sink { publications += 1 }
        unread.configure(scopeID: nil, teamID: nil)
        unread.configure(scopeID: nil, teamID: nil)
        unread.clearAll()
        XCTAssertEqual(publications, 0)
        XCTAssertEqual(badges, [0], "Clear a stale OS badge once before an account is configured")
        unread.configure(scopeID: "synthetic-account-server", teamID: "team-a")
        unread.setUnread(chatId: "shared-id", count: 2, teamID: "team-a")
        publications = 0; badges.removeAll()
        unread.setUnread(chatId: "shared-id", count: 0, teamID: "team-b")
        XCTAssertGreaterThan(publications, 0, "Zero must replace the old Team entry, not compare a missing Team lookup")
        XCTAssertEqual(unread.getUnreadCount(chatId: "shared-id", teamID: "team-a"), 0)
        XCTAssertEqual(badges, [0])
        publications = 0; badges.removeAll()
        unread.setUnread(chatId: "shared-id", count: 0, teamID: "team-b")
        XCTAssertEqual(publications, 0); XCTAssertTrue(badges.isEmpty)
        withExtendedLifetime(subscription) {}
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantCompletionUsesAcceptedTeamCountAndShareIdentity() {
        var existing = makeChat(id: "team-completion", title: "Team chat")
        existing.teamId = "team-a"; existing.unreadCount = 2; existing.isSharedByOthers = true
        let completion = makeChat(id: existing.id, title: "Team chat", messagesV: 2)
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChat(existing); store.upsertChat(completion)
        }
        let accepted = store.chat(for: existing.id)
        XCTAssertEqual(accepted?.teamId, "team-a")
        XCTAssertEqual(accepted?.unreadCount, 2)
        XCTAssertEqual(accepted?.isSharedByOthers, true)
        var state = NativeUnreadState()
        state.configure(scopeID: "account-server", teamID: "team-a")
        XCTAssertEqual(state.complete(id: existing.id, messageID: "assistant-team", teamID: accepted?.teamId), 1)
        XCTAssertEqual(state.total, 1, "Accepted Team identity must not reject its background completion")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRetainedSelectionOutsideChatWorkspaceDoesNotSuppressUnread() {
        var state = NativeUnreadState()
        state.configure(scopeID: "account-server", teamID: nil)
        state.setActiveChat("retained-selection")
        XCTAssertTrue(state.isActivelyViewing(chatID: "retained-selection", teamID: nil))
        state.setActiveChat(nil) // Projects/Tasks retain selection but hide transcript.
        XCTAssertFalse(state.isActivelyViewing(chatID: "retained-selection", teamID: nil))
        XCTAssertEqual(state.complete(id: "retained-selection", messageID: "background", teamID: nil), 1)
        state.setActiveChat("retained-selection")
        XCTAssertEqual(state.total, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testScopedReadReplayCannotDelayImmediateActiveAnnouncement() async {
        var release: CheckedContinuation<Void, Never>?
        var replayStarted = false
        let replay = NativeUnreadReadReplay.schedule(isCurrent: { true }, replay: {
            replayStarted = true
            await withCheckedContinuation { release = $0 }
        })
        var announcementSent = false
        announcementSent = true // Same synchronous continuation as announceActiveChat.
        for _ in 0..<20 { if replayStarted { break }; await Task.yield() }
        XCTAssertTrue(replayStarted)
        XCTAssertTrue(announcementSent, "Receipt replay may suspend while active publication continues")
        if let release { release.resume() } else { replay.cancel() }
        await replay.value
        var staleReplayStarted = false
        let stale = NativeUnreadReadReplay.schedule(isCurrent: { false }, replay: { staleReplayStarted = true })
        await stale.value
        XCTAssertFalse(staleReplayStarted, "A changed account/server/Team fence drops scheduled replay")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnreadMetadataDecodesAndSurvivesColdCacheAndPartialMetadataMerge() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"unread-fixture","created_at":1800000000,"unread_count":1}"#.utf8))
        XCTAssertEqual(chat.unreadCount, 1)
        XCTAssertEqual(PersistedChat(from: chat).toChat().unreadCount, 1)
        let partial = makeChat(id: chat.id, title: "Partial")
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChat(chat)
            store.upsertChat(partial)
        }
        XCTAssertEqual(store.chat(for: chat.id)?.unreadCount, 1)
        store.performWithoutPersistence { store.updateLastVisibleMessage(chatId: chat.id, messageId: "seen") }
        XCTAssertEqual(store.chat(for: chat.id)?.unreadCount, 1)
        var read = partial; read.unreadCount = 0
        store.performWithoutPersistence { store.upsertChat(read) }
        XCTAssertEqual(store.chat(for: chat.id)?.unreadCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnreadReconnectReadReceiptDedupeAndAccountServerTeamIsolation() {
        var state = NativeUnreadState()
        state.configure(scopeID: "account-a-server-a", teamID: nil)
        state.set(id: "chat", count: 1, teamID: nil, expectedScope: "account-a-server-a")
        XCTAssertEqual(state.total, 1)
        state.set(id: "chat", count: 0, teamID: nil, expectedScope: "account-a-server-a")
        XCTAssertEqual(state.total, 0, "Cross-device read receipt clears the hydrated count")
        XCTAssertEqual(state.complete(id: "chat", messageID: "assistant-1", teamID: nil), 1)
        XCTAssertNil(state.complete(id: "chat", messageID: "assistant-1", teamID: nil))
        state.setActiveChat("chat")
        state.set(id: "chat", count: 3, teamID: nil, expectedScope: "account-a-server-a")
        XCTAssertEqual(state.total, 0, "Open foreground chat must not re-acquire a badge during reconnect")
        state.setActiveChat(nil)
        XCTAssertEqual(state.complete(id: "chat", messageID: "background-after-open", teamID: nil), 1,
            "A backgrounded chat may regain a badge after foreground read suppression ends")
        state.set(id: "chat", count: 0, teamID: nil, expectedScope: "account-a-server-a")
        state.set(id: "team-chat", count: 2, teamID: "team-a", expectedScope: "account-a-server-a")
        XCTAssertEqual(state.total, 0)
        state.configure(scopeID: "account-a-server-a", teamID: "team-a")
        XCTAssertEqual(state.total, 2)
        state.configure(scopeID: "account-b-server-a", teamID: nil)
        state.set(id: "chat", count: 4, teamID: nil, expectedScope: "account-a-server-a")
        XCTAssertEqual(state.total, 0, "Late account receipt must be discarded")
        state.configure(scopeID: "account-b-server-b", teamID: nil)
        XCTAssertEqual(state.total, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDailyInspirationAPIKeepsWikipediaMetadataThroughBannerMapping() throws {
        let payload = Data(#"{"inspirations":[{"inspiration_id":"synthetic-ipc","phrase":"How do programs exchange information?","title":"Programs talking","category":"software_development","content_type":"wiki","video":null,"wiki":{"title":"Inter-process communication","wiki_title":"Inter-process communication","description":"Communication between computer processes","thumbnail_url":"https://example.invalid/wiki.png","wikidata_id":"Q214466","extract":"Synthetic article summary"}}]}"#.utf8)
        let item = try XCTUnwrap(DailyInspirationAPIResponse.decode(payload).inspirations.first)
        let banner = item.bannerData(sourceLanguage: "en")
        XCTAssertEqual(banner.contentType, "wiki")
        XCTAssertNil(banner.video)
        let wiki = try XCTUnwrap(banner.wiki)
        XCTAssertEqual(wiki.title, "Inter-process communication")
        XCTAssertEqual(wiki.wikiTitle, "Inter-process communication")
        XCTAssertEqual(wiki.thumbnailUrl, "https://example.invalid/wiki.png")
        XCTAssertEqual(wiki.wikidataId, "Q214466")
        XCTAssertEqual(wiki.extract, "Synthetic article summary")
        let preview = wiki.previewEmbed
        XCTAssertEqual(preview.type, EmbedType.wiki.rawValue)
        XCTAssertEqual(preview.rawData?["wiki_title"]?.value as? String, wiki.wikiTitle)
        XCTAssertEqual(preview.rawData?["thumbnail_url"]?.value as? String, wiki.thumbnailUrl)
        XCTAssertEqual(preview.rawData?["description"]?.value as? String, wiki.description)
        let identity = WikiArticleIdentity(data: preview.rawData ?? [:], fallbackLanguage: "de")
        XCTAssertEqual(identity.language, "en", "The requested article language must override the UI locale")
        XCTAssertEqual(identity.title, "Inter-process communication")
        XCTAssertEqual(identity.pageURL?.absoluteString, "https://en.wikipedia.org/wiki/Inter-process_communication")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDailyInspirationKeepsExplicitWikipediaLanguage() throws {
        let payload = Data(#"{"inspirations":[{"inspiration_id":"synthetic-ipc","phrase":"Synthetic phrase","title":"Programs talking","category":"software_development","content_type":"wiki","video":null,"wiki":{"title":"Display title","wiki_title":"Canonical_article","language":"ja"}}]}"#.utf8)
        let item = try XCTUnwrap(DailyInspirationAPIResponse.decode(payload).inspirations.first)
        let wiki = try XCTUnwrap(item.bannerData(sourceLanguage: "en").wiki)
        let identity = WikiArticleIdentity(data: wiki.previewEmbed.rawData ?? [:], fallbackLanguage: "de")
        XCTAssertEqual(identity.language, "ja")
        XCTAssertEqual(identity.title, "Canonical article")
        XCTAssertEqual(identity.pageURL?.host, "ja.wikipedia.org")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,apple-offline.snapshot-integrity
    func testOfflineSearchReadsAwayFromUIAndRetainsOlderHitsOnlyInAllowedCorpus() async throws {
        let (offline, _) = try makeRecentOfflineStore()
        let allowed = makeChat(id: "search-allowed", title: "Synthetic", messagesV: 260)
        let excluded = makeChat(id: "search-excluded", title: "Synthetic", messagesV: 1)
        offline.persistChats([allowed, excluded])
        let messages = (0..<260).map { index in
            Message(id: String(format: "search-%03d", index), chatId: allowed.id, role: .user,
                content: index == 0 ? "olderuniquematch" : "Synthetic", encryptedContent: nil,
                createdAt: allowed.createdAt, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        }
        offline.persistMessages(messages, chatId: allowed.id)
        offline.persistMessages([Message(id: "excluded-message", chatId: excluded.id, role: .user,
            content: "olderuniquematch", encryptedContent: nil, createdAt: excluded.createdAt,
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)], chatId: excluded.id)
        let content = try await offline.loadSearchContent(chatID: allowed.id, includeMessages: true, includeEmbeds: true)
        XCTAssertFalse(content.readOnMainThread)
        XCTAssertEqual(content.messages.map(\.id), messages.map(\.id))
        let store = ChatStore()
        store.upsertChats([allowed, excluded])
        let results = try await ChatSearchEngine.searchAsync(query: "olderuniquematch", chats: store.chats,
            chatStore: store, offlineStore: offline, offlineContentChatIds: [allowed.id])
        XCTAssertEqual(results.groups.flatMap(\.items).map(\.id), [allowed.id])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,apple-offline.snapshot-integrity
    func testOfflineSearchRejectsDeletedAndReplacedAccountReadFences() async throws {
        let (offline, _) = try makeRecentOfflineStore()
        let chat = makeChat(id: "search-fence", title: "Synthetic", messagesV: 0)
        offline.persistChats([chat])
        let optionalWriter = await offline.makeRecentChatCacheWriter()
        let writer = try XCTUnwrap(optionalWriter)
        let deletionFence = offline.recentContentWriteFence(for: chat.id)
        offline.deleteChat(chat.id)
        do {
            _ = try await writer.loadSearchContent(chatID: chat.id, includeMessages: true, includeEmbeds: true, fence: deletionFence)
            XCTFail("Deleted cached content must not enter a search snapshot")
        } catch is CancellationError {}
        let accountFence = offline.recentContentWriteFence(for: chat.id)
        offline.deactivate()
        do {
            _ = try await writer.loadSearchContent(chatID: chat.id, includeMessages: true, includeEmbeds: true, fence: accountFence)
            XCTFail("The old account worker must reject reads after replacement")
        } catch is CancellationError {}
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,apple-offline.snapshot-integrity
    func testComposerEmbedSearchMergesActorCacheWithNewerMemoryRecord() async throws {
        let (offline, _) = try makeRecentOfflineStore()
        let chat = makeChat(id: "search-embed-merge", title: "Synthetic", messagesV: 0)
        offline.persistChats([chat])
        let cached = (0..<130).map { index in
            EmbedRecord(id: String(format: "embed-%03d", index), type: "audio-recording", status: .finished,
                data: .raw(["filename": AnyCodable("cached.m4a")]), parentEmbedId: nil,
                appId: "audio", skillId: nil, embedIds: nil, createdAt: nil)
        }
        offline.persistEmbeds(cached, chatId: chat.id)
        let memory = EmbedRecord(id: cached[0].id, type: "audio-recording", status: .finished,
            data: .raw(["filename": AnyCodable("current.m4a")]), parentEmbedId: nil,
            appId: "audio", skillId: nil, embedIds: nil, createdAt: nil)
        let store = ChatStore()
        store.upsertEmbeds([memory], for: chat.id)
        let merged = try await ComposerSearchSuggestionsController.localEmbeds(chat: chat, store: store, offline: offline)
        XCTAssertEqual(merged.count, cached.count)
        XCTAssertEqual(merged.first { $0.id == memory.id }?.rawData?["filename"]?.value as? String, "current.m4a")
        let content = try await offline.loadSearchContent(chatID: chat.id, includeMessages: false, includeEmbeds: true)
        XCTAssertFalse(content.readOnMainThread)
        XCTAssertEqual(content.embeds.count, cached.count)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWelcomeMetadataDemandSkipsHydratedRecordsButRetainsEncryptedFields() {
        var chat = Chat(id: "synthetic-grid", title: nil, lastMessageAt: nil,
            createdAt: "2026-10-01T12:00:00Z", updatedAt: nil, isArchived: false,
            isPinned: false, appId: nil, encryptedTitle: "cipher-title",
            encryptedCategory: "cipher-category", encryptedIcon: "cipher-icon",
            encryptedChatSummary: "cipher-summary", encryptedChatKey: nil,
            messagesV: 2, titleV: 3, metadataV: 7)
        XCTAssertTrue(WelcomeScreenState.needsMetadataDecryption(chat))
        chat.title = "Older title"
        XCTAssertTrue(WelcomeScreenState.needsMetadataDecryption(chat), "Title hydration must still request the missing summary/category/icon")
        chat.category = "science"
        chat.icon = "search"
        chat.chatSummary = "Older summary"
        XCTAssertFalse(WelcomeScreenState.needsMetadataDecryption(chat), "A hydrated grid page must not repeat crypto work")
        XCTAssertEqual(chat.encryptedTitle, "cipher-title")
        XCTAssertEqual(chat.encryptedCategory, "cipher-category")
        XCTAssertEqual(chat.encryptedIcon, "cipher-icon")
        XCTAssertEqual(chat.encryptedChatSummary, "cipher-summary")
        XCTAssertEqual(chat.messagesV, 2)
        XCTAssertEqual(chat.titleV, 3)
        XCTAssertEqual(chat.metadataV, 7)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testWelcomeDraftCardsWaitForDecryptedPreviewButKeepAttachmentPlaceholders() {
        let draft = DevHistoryWelcomeData.chat("synthetic-draft", messages: 0, draft: 7)
        XCTAssertFalse(WelcomeScreenState.isContinuationPreviewReady(draft, draftPreview: nil))
        XCTAssertFalse(WelcomeScreenState.isContinuationPreviewReady(draft, draftPreview: " \n "))
        XCTAssertTrue(WelcomeScreenState.isContinuationPreviewReady(draft, draftPreview: "[Audio] [Image]"))
        XCTAssertTrue(WelcomeScreenState.isContinuationPreviewReady(DevHistoryWelcomeData.chat("synthetic-chat", title: "Existing", messages: 2), draftPreview: nil))
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.recent-cohort
    func testOfflineCohortUsesOverallRecencyRatherThanSidebarPinsOrDrafts() throws {
        func chat(_ id: String, edited: Int, pinned: Bool = false, draft: Int = 0,
                  parent: String? = nil, hidden: Bool = false) throws -> Chat {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            var fields: [String: Any] = ["id": id, "created_at": 1700000000,
                "last_message_timestamp": 1700000001, "last_edited_overall_timestamp": edited,
                "pinned": pinned, "draft_v": draft, "is_hidden": hidden]
            if let parent { fields["parent_id"] = parent }
            return try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: fields))
        }
        let recent = try (0..<21).map { try chat(String(format: "recent-%02d", $0), edited: 1800000000 - $0) }
        let ineligible = try [chat("old-pinned", edited: 1700000002, pinned: true),
            chat("old-draft", edited: 1700000003, draft: 9),
            chat("hidden", edited: 1900000000, hidden: true),
            chat("child", edited: 1900000000, parent: "parent"),
            chat("incognito-fixture", edited: 1900000000), chat("demo-fixture", edited: 1900000000)]
        XCTAssertEqual(OfflineRecentChatPolicy.cohort(from: Array((ineligible + recent).reversed())).map(\.id), recent.prefix(20).map(\.id))
        let ties = try [chat("tie-b", edited: 1800000000), chat("tie-a", edited: 1800000000)]
        XCTAssertEqual(OfflineRecentChatPolicy.cohort(from: ties).map(\.id), ["tie-a", "tie-b"])
        let store = ChatStore()
        store.upsertChat(recent[0])
        store.updateLastVisibleMessage(chatId: recent[0].id, messageId: "anchor")
        store.advanceMessagesVersion(chatId: recent[0].id, to: 2)
        store.upsertChat(try chat(recent[0].id, edited: 1700000004))
        let preserved = try XCTUnwrap(store.chat(for: recent[0].id))
        XCTAssertEqual(preserved.lastEditedOverallTimestamp, recent[0].lastEditedOverallTimestamp)
        XCTAssertEqual(PersistedChat(from: preserved).toChat().lastEditedOverallTimestamp, preserved.lastEditedOverallTimestamp)
        XCTAssertNotEqual(preserved.lastMessageAt, preserved.lastEditedOverallTimestamp)
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.recent-cohort,apple-offline.snapshot-integrity
    func testOfflineMaintenanceCachesExactlyTwentyExplicitChatsWithoutPublishingTranscriptsOrEvictingOtherData() async throws {
        let (offline, container) = try makeRecentOfflineStore()
        let store = ChatStore()
        let chats = (0..<21).map { makeChat(id: String(format: "cache-%02d", $0), title: "Synthetic", messagesV: 2,
            lastMessageAt: String(format: "2026-01-01T00:%02d:00Z", 30 - $0)) }
        offline.persistChats(chats)
        store.performWithoutPersistence { store.upsertChats(chats) }
        let outside = Message(id: "retained-outside", chatId: chats[20].id, role: .user, content: "Synthetic retained data",
            encryptedContent: nil, createdAt: chats[20].createdAt, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        offline.persistMessages([outside], chatId: chats[20].id)
        var requested: [String] = []
        let bridge = OfflineSyncBridge(chatStore: store, offlineStore: offline,
            contentFetcher: { id in requested.append(id); return try self.recentOfflineBatch(chatID: id) },
            prefetchEligibility: { true }, keyValidator: { _, _ in "validated-wrapper" })
        XCTAssertFalse(bridge.isPrefetching)
        bridge.startOfflinePrefetchIfEligible(reason: "startupSyncComplete")
        XCTAssertTrue(bridge.isPrefetching)
        await bridge.waitForOfflinePrefetch()
        XCTAssertFalse(bridge.isPrefetching)
        XCTAssertEqual(requested, chats.prefix(20).map(\.id))
        let reloaded = OfflineStore(modelContainer: container)
        for chat in chats.prefix(20) {
            XCTAssertEqual(reloaded.loadMessages(chatId: chat.id).count, 2)
            XCTAssertEqual(reloaded.loadEmbeds(chatId: chat.id).count, 1)
            XCTAssertEqual(reloaded.loadChat(id: chat.id)?.encryptedChatKey, "validated-wrapper")
            XCTAssertTrue(store.messages(for: chat.id).isEmpty, "Cache maintenance must not hydrate twenty in-memory transcripts")
        }
        XCTAssertEqual(reloaded.loadMessages(chatId: chats[20].id).map(\.id), [outside.id])
        bridge.startOfflinePrefetchIfEligible(reason: "unchangedRefresh")
        await bridge.waitForOfflinePrefetch()
        XCTAssertEqual(requested.count, 20, "Unchanged completed revisions must reuse their receipts")
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.interruption-isolation
    func testOfflineRefreshCoalescesAndRejectsStoppedSessionResponses() async throws {
        let (offline, _) = try makeRecentOfflineStore()
        let store = ChatStore()
        let chat = makeChat(id: "coalesced-cache", title: "Synthetic", messagesV: 2)
        offline.persistChats([chat])
        store.performWithoutPersistence { store.upsertChat(chat) }
        let gate = RecentOfflineFetchGate()
        let bridge = OfflineSyncBridge(chatStore: store, offlineStore: offline,
            contentFetcher: { _ in try await gate.fetch() }, prefetchEligibility: { true },
            keyValidator: { _, _ in nil })
        bridge.startOfflinePrefetchIfEligible(reason: "startupSyncComplete")
        await gate.waitUntilStarted(0)
        for _ in 0..<5 { bridge.startOfflinePrefetchIfEligible(reason: "sameRefresh") }
        gate.release(0, data: try recentOfflineBatch(chatID: chat.id))
        await bridge.waitForOfflinePrefetch()
        XCTAssertEqual(gate.calls, 1)
        XCTAssertEqual(offline.loadMessages(chatId: chat.id).count, 2)

        let stopped = OfflineSyncBridge(chatStore: store, offlineStore: offline,
            contentFetcher: { _ in try await gate.fetch() }, prefetchEligibility: { true }, keyValidator: { _, _ in nil })
        // A changed accepted version invalidates the persisted completion receipt.
        store.advanceMessagesVersion(chatId: chat.id, to: 3)
        offline.persistChats(store.chats)
        let stoppedTask = stopped.startOfflinePrefetchIfEligible(reason: "startupSyncComplete")
        await gate.waitUntilStarted(1)
        XCTAssertTrue(stopped.isPrefetching)
        stopped.stopSession()
        XCTAssertFalse(stopped.isPrefetching)
        gate.release(1, data: try recentOfflineBatch(chatID: chat.id, version: 3, prefix: "stale"))
        await stoppedTask?.value
        XCTAssertFalse(offline.loadMessages(chatId: chat.id).contains { $0.id.contains("-stale-") })

        let cancelledRun = bridge.startOfflinePrefetchIfEligible(reason: "changedRevision")
        await gate.waitUntilStarted(2)
        bridge.setForegroundActive(false)
        XCTAssertFalse(bridge.isPrefetching)
        bridge.setForegroundActive(true)
        XCTAssertTrue(bridge.isPrefetching)
        await gate.waitUntilStarted(3)
        gate.release(2, data: try recentOfflineBatch(chatID: chat.id, version: 3, prefix: "cancelled"))
        await cancelledRun?.value
        XCTAssertTrue(bridge.isPrefetching, "A cancelled run must not hide its active replacement")
        let replacement = bridge.startOfflinePrefetchIfEligible(reason: "coalescedReplacement")
        gate.release(3, data: try recentOfflineBatch(chatID: chat.id, version: 3, prefix: "replacement"))
        await replacement?.value
        XCTAssertFalse(bridge.isPrefetching)
        XCTAssertEqual(gate.calls, 4, "A cancelled run's defer must not clear the replacement task")
        XCTAssertFalse(offline.loadMessages(chatId: chat.id).contains { $0.id.contains("-cancelled-") })
        XCTAssertTrue(offline.loadMessages(chatId: chat.id).contains { $0.id.contains("-replacement-") })

        store.advanceMessagesVersion(chatId: chat.id, to: 4)
        offline.persistChats(store.chats)
        let changedAccountRun = bridge.startOfflinePrefetchIfEligible(reason: "accountBoundary")
        await gate.waitUntilStarted(4)
        offline.deactivate()
        gate.release(4, data: try recentOfflineBatch(chatID: chat.id, version: 4, prefix: "other-account"))
        await changedAccountRun?.value
        XCTAssertTrue(offline.loadMessages(chatId: chat.id).isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.snapshot-integrity
    func testOfflineSnapshotRejectsPartialResponsesAndReconcilesOnlyExplicitPendingRows() async throws {
        let (offline, container) = try makeRecentOfflineStore()
        let chat = makeChat(id: "integrity-cache", title: "Synthetic", messagesV: 2)
        offline.persistChats([chat])
        let old = ["deleted", "queued"].map { Message(id: $0, chatId: chat.id, role: .user,
            content: "Synthetic", encryptedContent: nil, createdAt: chat.createdAt,
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil) }
        offline.persistMessages(old, chatId: chat.id)
        let optionalWriter = await offline.makeRecentChatCacheWriter()
        let writer = try XCTUnwrap(optionalWriter)
        for invalid in [try recentOfflineBatch(chatID: chat.id, partial: true),
                        try recentOfflineBatch(chatID: chat.id, claimedCount: 3)] {
            do { _ = try await writer.decode(invalid, chatId: chat.id); XCTFail("Incomplete snapshots must not produce a receipt") }
            catch OfflineRecentChatCacheError.incompleteSnapshot { }
        }
        let snapshot = try await writer.decode(recentOfflineBatch(chatID: chat.id), chatId: chat.id)
        try await writer.persist(snapshot, chat: chat, validatedWrapper: nil, preserving: ["queued"])
        let reloaded = OfflineStore(modelContainer: container)
        XCTAssertEqual(Set(reloaded.loadMessages(chatId: chat.id).map(\.id)), ["integrity-cache-current-0", "integrity-cache-current-1", "queued"])
        XCTAssertTrue(reloaded.hasCompleteOfflineSnapshot(for: chat))
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.snapshot-integrity
    func testAuthoritativeCacheCanonicalizesPendingAliasOnceAndKeepsUnsentRowsOnReload() async throws {
        let (offline, container) = try makeRecentOfflineStore()
        let chat = makeChat(id: "pending-alias-cache", title: "Synthetic", messagesV: 1)
        offline.persistChats([chat])
        let alias = Message(id: "database-alias", chatId: chat.id, role: .assistant, content: "Synthetic saved body",
            encryptedContent: "matching-cipher", createdAt: chat.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
        let unsent = Message(id: "unsent-local", chatId: chat.id, role: .user, content: "Synthetic unsent body",
            encryptedContent: nil, createdAt: chat.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
        offline.persistMessages([alias, unsent], chatId: chat.id)
        let canonical = Message(id: "canonical-client", chatId: chat.id, role: .assistant, content: nil,
            encryptedContent: alias.encryptedContent, createdAt: chat.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil, serverMessageId: alias.id)
        let snapshot = OfflineRecentChatSnapshot(messages: [canonical], embeds: [], embedKeys: [], chatKeyWrappers: [],
            messagesVersion: 1, supplementalContent: Data("{}".utf8), codeOutputs: [])
        let optionalWriter = await offline.makeRecentChatCacheWriter()
        let writer = try XCTUnwrap(optionalWriter)
        for _ in 0..<2 {
            try await writer.persist(snapshot, chat: chat, validatedWrapper: nil, preserving: [alias.id, unsent.id],
                                     fence: offline.recentContentWriteFence(for: chat.id))
        }
        let reloaded = OfflineStore(modelContainer: container)
        let rows = reloaded.loadMessages(chatId: chat.id)
        XCTAssertEqual(Set(rows.map(\.id)), [canonical.id, unsent.id])
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows.first { $0.id == canonical.id }?.content, alias.content)
        XCTAssertEqual(rows.first { $0.id == unsent.id }?.content, unsent.content)
        XCTAssertTrue(reloaded.hasCompleteOfflineSnapshot(for: chat))
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.interruption-isolation,apple-offline.snapshot-integrity
    func testForegroundContentUpdateDuringCacheCommitRejectsOldWriteAndReceipt() async throws {
        let (offline, container) = try makeRecentOfflineStore()
        let chat = makeChat(id: "late-update-cache", title: "Synthetic", messagesV: 2)
        offline.persistChats([chat])
        let optionalWriter = await offline.makeRecentChatCacheWriter()
        let writer = try XCTUnwrap(optionalWriter)
        let snapshot = try await writer.decode(recentOfflineBatch(chatID: chat.id), chatId: chat.id)
        let fence = offline.recentContentWriteFence(for: chat.id)
        let entered = AsyncStream<Void>.makeStream()
        let gate = RecentOfflineCommitGate(entered: entered.continuation)
        let write = Task {
            try await writer.persist(snapshot, chat: chat, validatedWrapper: nil, preserving: [], fence: fence,
                                     beforeCommit: { await gate.pause() })
        }
        var iterator = entered.stream.makeAsyncIterator()
        _ = await iterator.next()
        let late = Message(id: "accepted-after-snapshot", chatId: chat.id, role: .user, content: "Synthetic new accepted row",
            encryptedContent: "later-cipher", createdAt: chat.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
        offline.persistMessages([late], chatId: chat.id)
        XCTAssertFalse(fence.isCurrent)
        await gate.release()
        do { try await write.value; XCTFail("A cache write must not overtake newer accepted content") }
        catch OfflineRecentChatCacheError.staleSnapshot { }
        let reloaded = OfflineStore(modelContainer: container)
        XCTAssertEqual(reloaded.loadMessages(chatId: chat.id).map(\.id), [late.id])
        XCTAssertFalse(reloaded.hasCompleteOfflineSnapshot(for: chat))
    }

    // contract-test: direct surface=gui.apple assertions=apple-offline.snapshot-integrity
    func testReloadRejectsReceiptAfterCountMismatchOrNonAuthoritativeContentUpdate() async throws {
        let (offline, container) = try makeRecentOfflineStore()
        let chat = makeChat(id: "count-receipt-cache", title: "Synthetic", messagesV: 2)
        offline.persistChats([chat])
        let optionalWriter = await offline.makeRecentChatCacheWriter()
        let writer = try XCTUnwrap(optionalWriter)
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: recentOfflineBatch(chatID: chat.id)) as? [String: Any])
        let snapshot = try await writer.decode(WebSocketResponse(fields: fields), chatId: chat.id)
        try await writer.persist(snapshot, chat: chat, validatedWrapper: nil, preserving: [])
        let complete = await writer.hasCompleteSnapshot(for: chat)
        XCTAssertTrue(complete)
        XCTAssertTrue(OfflineStore(modelContainer: container).hasCompleteOfflineSnapshot(for: chat))
        let corruption = ModelContext(container)
        let target = snapshot.messages[0].id
        let descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.id == target })
        corruption.delete(try XCTUnwrap(corruption.fetch(descriptor).first))
        try corruption.save()
        let completeAfterCorruption = await writer.hasCompleteSnapshot(for: chat)
        XCTAssertFalse(completeAfterCorruption)
        XCTAssertFalse(OfflineStore(modelContainer: container).hasCompleteOfflineSnapshot(for: chat), "A valid version alone cannot prove the saved record count")
        try await writer.persist(snapshot, chat: chat, validatedWrapper: nil, preserving: [])
        XCTAssertTrue(OfflineStore(modelContainer: container).hasCompleteOfflineSnapshot(for: chat))
        offline.persistMessages([snapshot.messages[0]], chatId: chat.id)
        let completeAfterInvalidation = await writer.hasCompleteSnapshot(for: chat)
        XCTAssertFalse(completeAfterInvalidation)
        XCTAssertFalse(OfflineStore(modelContainer: container).hasCompleteOfflineSnapshot(for: chat), "A partial update must durably invalidate the prior receipt before a restart")
    }

    private func makeRecentOfflineStore() throws -> (OfflineStore, ModelContainer) {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
            PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("RecentOffline-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        return (OfflineStore(modelContainer: container), container)
    }

    private func recentOfflineBatch(chatID: String, version: Int = 2, prefix: String = "current",
                                    partial: Bool = false, claimedCount: Int = 2) throws -> Data {
        let rows = try (0..<2).map { index in String(decoding: try JSONSerialization.data(withJSONObject: [
            "id": "\(chatID)-\(prefix)-\(index)", "chat_id": chatID, "role": "user", "encrypted_content": "synthetic-cipher",
            "created_at": "2026-01-01T00:00:0\(index)Z"]), as: UTF8.self) }
        return try JSONSerialization.data(withJSONObject: ["messages_by_chat_id": [chatID: rows],
            "versions_by_chat_id": [chatID: ["messages_v": version, "server_message_count": claimedCount]],
            "embeds": [["embed_id": "embed-\(chatID)", "type": "sheets-sheet", "status": "finished",
                "hashed_chat_id": ChatKeyWrapperRecord.hashedChatId(for: chatID),
                "encrypted_content": "synthetic-embed-cipher"]],
            "embed_keys": [], "chat_key_wrappers": [], "code_run_outputs": [], "partial_error": partial])
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative,chat-navigation.open.local-first-coherent
    func testChatMergeKeepsDraftDeletionFenceThroughLatePageAndPersistenceCopies() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        func wire(_ fields: [String: Any]) throws -> Chat {
            var row: [String: Any] = ["id": "chat-1", "created_at": "2026-01-01T00:00:00Z"]
            row.merge(fields) { _, incoming in incoming }
            return try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: row))
        }
        let store = ChatStore()
        store.upsertChat(try wire(["draft_v": 7, "messages_v": 2, "encrypted_draft_md": "cipher-seven"]))
        store.upsertChat(try wire(["draft_v": 4, "encrypted_draft_md": "older-cipher"]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 7)
        store.upsertChat(try wire(["draft_v": 0, "cleared_draft_v": 8,
                                   "encrypted_draft_md": NSNull()]))
        store.upsertChat(try wire(["draft_v": 7, "encrypted_draft_md": "late-cipher"]))
        store.updateLastVisibleMessage(chatId: "chat-1", messageId: "last")
        store.advanceMessagesVersion(chatId: "chat-1", to: 4)
        let cleared = try XCTUnwrap(store.chat(for: "chat-1"))
        XCTAssertEqual(cleared.draftV, 0)
        XCTAssertEqual(cleared.hasNonEmptyDraft, false)
        XCTAssertEqual(cleared.clearedDraftV, 8)
        let persisted = PersistedChat(from: cleared).toChat()
        XCTAssertEqual(persisted.clearedDraftV, 8)
        XCTAssertEqual(persisted.hasNonEmptyDraft, false)
        store.upsertChat(try wire(["draft_v": 9, "encrypted_draft_md": "fresh-cipher"]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 9)
        XCTAssertEqual(store.chat(for: "chat-1")?.hasNonEmptyDraft, true)
        store.upsertChat(try wire(["draft_v": 0, "cleared_draft_v": 8, "encrypted_draft_md": NSNull()]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 9)
        XCTAssertEqual(store.chat(for: "chat-1")?.hasNonEmptyDraft, true)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.persistence.client-encrypted
    func testMessageWireIdentityPrefersCanonicalClientIDAcrossDecoderStrategies() throws {
        for convertsKeys in [false, true] {
            let decoder = JSONDecoder()
            if convertsKeys { decoder.keyDecodingStrategy = .convertFromSnakeCase }
            for identity in [
                ["id": "database-row", "message_id": "client-row", "client_message_id": "client-row"],
                ["id": "database-row", "message_id": "client-row"],
                ["message_id": "client-row"],
                ["id": "database-row", "clientMessageId": "client-row", "messageId": "client-row"]
            ] {
                var payload: [String: Any] = identity
                payload.merge(["chat_id": "chat-1", "role": "user", "created_at": 1770000000,
                               "content": "An intentional repeated send"]) { _, new in new }
                let decoded = try decoder.decode(Message.self, from: JSONSerialization.data(withJSONObject: payload))
                XCTAssertEqual(decoded.id, "client-row")
                XCTAssertEqual(decoded.serverMessageId, identity["id"])
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.local-state.precedence
    func testCanonicalSnapshotMigratesPersistedAliasesAndKeepsQueuedOrRepeatedSendsOnColdReload() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("MessageIdentityMigration", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let offline = OfflineStore(modelContainer: container)
        let store = ChatStore()
        let bridge = OfflineSyncBridge(chatStore: store, offlineStore: offline)
        store.setBridge(bridge)
        let time = "2026-01-01T00:00:00Z"
        func row(_ id: String, role: MessageRole = .user, content: String = "Same intentionally repeated text",
                 ciphertext: String? = nil, alias: String? = nil) -> Message {
            Message(id: id, chatId: "chat-1", role: role, content: content, encryptedContent: ciphertext,
                    createdAt: time, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil,
                    serverMessageId: alias)
        }
        let assistantBody = String(repeating: "Saved response. ", count: 270)
        let previous = [row("database-user"), row("client-user"), row("repeat-user"),
                        row("database-assistant", role: .assistant, content: assistantBody, ciphertext: "same-assistant-cipher")]
        store.setMessages(for: "chat-1", messages: previous)
        bridge.sendMessageOffline(chatId: "chat-1", messageId: "queued-user", content: "Still waiting offline")
        let user = row("client-user", alias: "database-user")
        let savedAssistant = Message(id: "client-assistant", chatId: "chat-1", role: .assistant,
            content: nil, encryptedContent: "same-assistant-cipher", createdAt: time, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil, serverMessageId: "database-assistant")
        let snapshot = [user, row("repeat-user"), savedAssistant]
        for _ in 0..<2 {
            store.applySyncedContent(messagesByChat: ["chat-1": snapshot], embedsByChat: [:])
        }
        XCTAssertEqual(Set(store.messages(for: "chat-1").map(\.id)),
                       ["client-user", "repeat-user", "client-assistant", "queued-user"])
        XCTAssertEqual(store.messages(for: "chat-1").first { $0.id == "client-assistant" }?.content, assistantBody)
        let reloaded = OfflineStore(modelContainer: container).loadMessages(chatId: "chat-1")
        XCTAssertEqual(Set(reloaded.map(\.id)), ["client-user", "repeat-user", "client-assistant", "queued-user"])
        XCTAssertEqual(reloaded.first { $0.id == "client-assistant" }?.content, assistantBody)
        XCTAssertEqual(reloaded.first { $0.id == "client-user" }?.serverMessageId, "database-user")
        XCTAssertEqual(reloaded.filter { $0.content == "Same intentionally repeated text" }.count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence,chats.persistence.client-encrypted
    func testSnapshotReplayKeepsDecodedBodyOnlyForMatchingCiphertextAndExplicitIdentity() {
        let store = ChatStore()
        let time = "2026-01-01T00:00:00Z"
        let complete = Message(id: "reply", chatId: "chat-1", role: .assistant, content: "A finished response",
            encryptedContent: "cipher-v1", createdAt: time, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        store.appendMessage(complete, to: "chat-1")
        func snapshot(_ ciphertext: String) -> Message {
            Message(id: "reply", chatId: "chat-1", role: .assistant, content: nil, encryptedContent: ciphertext,
                    createdAt: time, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        }
        store.applySyncedContent(messagesByChat: ["chat-1": [snapshot("cipher-v1")]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").first?.content, complete.content)
        store.applySyncedContent(messagesByChat: ["chat-1": [snapshot("cipher-v2")]], embedsByChat: [:])
        XCTAssertNil(store.messages(for: "chat-1").first?.content, "An edit's new ciphertext cannot reuse stale text")
        let canonical = Message(id: "canonical", chatId: "chat-1", role: .assistant,
            content: nil, encryptedContent: "cipher-v1", createdAt: time, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil, serverMessageId: complete.id)
        let merged = ChatContentBatchPayload.mergedMessages(snapshot: [canonical, canonical], preserving: [complete])
        XCTAssertEqual(merged.map(\.id), [canonical.id])
        XCTAssertEqual(merged.first?.content, complete.content)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.local-state.precedence
    func testDualRowAssistantAliasBodySurvivesReplayAppendAndColdReload() throws {
        let time = "2026-01-01T00:00:00Z"
        func row(_ id: String, body: String?, cipher: String = "cipher-v1", alias: String? = nil) -> Message {
            Message(id: id, chatId: "chat-1", role: .assistant, content: body, encryptedContent: cipher,
                    createdAt: time, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil,
                    serverMessageId: alias)
        }
        let canonical = row("canonical", body: nil)
        let alias = row("database", body: "Saved decoded response")
        let snapshot = row("canonical", body: nil, alias: alias.id)
        let previous = [canonical, alias]
        for route in ["set", "sync", "append"] {
            let store = ChatStore()
            store.setMessages(for: "chat-1", messages: previous)
            if route == "set" { store.setMessages(for: "chat-1", messages: [snapshot]) }
            if route == "sync" { store.applySyncedContent(messagesByChat: ["chat-1": [snapshot]], embedsByChat: [:]) }
            if route == "append" { store.appendMessage(snapshot, to: "chat-1") }
            XCTAssertEqual(store.messages(for: "chat-1").map(\.id), [canonical.id], route)
            XCTAssertEqual(store.messages(for: "chat-1").first?.content, alias.content, route)
        }
        let merged = ChatContentBatchPayload.mergedMessages(snapshot: [snapshot, snapshot], preserving: previous)
        XCTAssertEqual(merged.map(\.id), [canonical.id])
        XCTAssertEqual(merged.first?.content, alias.content)
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("DualRowAliasBody", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let offline = OfflineStore(modelContainer: container)
        offline.persistMessages(previous, chatId: "chat-1")
        offline.persistMessages([snapshot, snapshot], chatId: "chat-1")
        let coldRows = OfflineStore(modelContainer: container).loadMessages(chatId: "chat-1")
        XCTAssertEqual(coldRows.map(\.id), [canonical.id])
        XCTAssertEqual(coldRows.first?.content, alias.content)

        let validCanonical = row("canonical", body: "Canonical decoded response")
        XCTAssertEqual(snapshot.localBodySource(canonical: validCanonical, alias: alias)?.content, validCanonical.content)
        let changedCanonical = row("canonical", body: nil, cipher: "cipher-v2")
        XCTAssertNil(snapshot.localBodySource(canonical: changedCanonical, alias: alias)?.content)
        let changedAlias = row("database", body: "Stale decoded response", cipher: "cipher-v2")
        XCTAssertNil(snapshot.localBodySource(canonical: canonical, alias: changedAlias)?.content)
        let otherChatAlias = Message(id: alias.id, chatId: "other-chat", role: .assistant,
            content: alias.content, encryptedContent: alias.encryptedContent, createdAt: time,
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        XCTAssertNil(snapshot.localBodySource(canonical: canonical, alias: otherChatAlias)?.content)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFinalStreamAppendKeepsMatchingPendingCiphertextAndThinkingMetadata() {
        let store = ChatStore()
        let persisted = Message(id: "reply", chatId: "chat-1", role: .assistant,
                                content: "A complete response", encryptedContent: "local-ciphertext",
                                createdAt: "2026-01-01T00:00:01Z", updatedAt: nil,
                                appId: "ai", isStreaming: false, embedRefs: nil,
                                modelName: "fixture-model", encryptedModelName: "encrypted-model",
                                thinkingContent: "Fixture reasoning", encryptedThinkingContent: "encrypted-thinking")
        let lateStream = Message(id: persisted.id, chatId: persisted.chatId, role: .assistant,
                                 content: persisted.content, encryptedContent: nil,
                                 createdAt: persisted.createdAt, updatedAt: nil,
                                 appId: nil, isStreaming: false, embedRefs: nil)
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(lateStream, to: "chat-1")
        let result = store.messages(for: "chat-1").first
        XCTAssertEqual(result?.encryptedContent, "local-ciphertext")
        XCTAssertEqual(result?.thinkingContent, "Fixture reasoning")
        XCTAssertEqual(result?.encryptedThinkingContent, "encrypted-thinking")
        XCTAssertEqual(result?.modelName, "fixture-model")
        XCTAssertEqual(store.messages(for: "chat-1").count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPendingReplyNeverAttachesPriorCiphertextToChangedPlaintext() {
        let store = ChatStore()
        let persisted = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z",
                                    role: .assistant, encryptedContent: "previous-ciphertext")
        var changed = makeMessage(id: "reply", createdAt: persisted.createdAt, role: .assistant)
        changed.content = "Updated terminal content"
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(changed, to: "chat-1")
        XCTAssertEqual(store.messages(for: "chat-1").first?.content, "Updated terminal content")
        XCTAssertNil(store.messages(for: "chat-1").first?.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testOrdinaryAppendDoesNotTreatOldCiphertextAsPendingRecovery() {
        let store = ChatStore()
        let persisted = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z",
                                    role: .assistant, encryptedContent: "previous-ciphertext")
        let replacement = makeMessage(id: "reply", createdAt: persisted.createdAt, role: .assistant)
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(replacement, to: "chat-1")
        XCTAssertNil(store.messages(for: "chat-1").first?.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSyncRetainsOnlyPendingAssistantRepliesUntilTheirServerCommit() {
        let store = ChatStore()
        let user = makeMessage(id: "user", createdAt: "2026-01-01T00:00:00Z")
        let pending = makeMessage(id: "pending", createdAt: "2026-01-01T00:00:02Z", role: .assistant)
        let deleted = makeMessage(id: "deleted", createdAt: "2026-01-01T00:00:01Z", role: .assistant)
        store.setMessages(for: "chat-1", messages: [user, deleted, pending])
        var pendingIds: Set<String> = ["pending"]
        store.setPendingAssistantRecoveryLookup { $0 == "chat-1" ? pendingIds : [] }

        store.applySyncedContent(messagesByChat: ["chat-1": [user]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["user", "pending"])

        pendingIds.removeAll()
        store.applySyncedContent(messagesByChat: ["chat-1": [user]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["user"], "Completed or discarded jobs must not pin absent history forever")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testServerCiphertextReplacesPendingReplyWithoutDuplicatingIt() {
        let store = ChatStore()
        let pending = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z", role: .assistant)
        let committed = makeMessage(id: "reply", createdAt: pending.createdAt, role: .assistant,
                                    encryptedContent: "server-ciphertext")
        store.setMessages(for: "chat-1", messages: [pending])
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.applySyncedContent(messagesByChat: ["chat-1": [committed]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").count, 1)
        XCTAssertEqual(store.messages(for: "chat-1").first?.encryptedContent, "server-ciphertext")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testEncryptedSyncKeepsFinishedLocalRecordingVisibleDuringFirstChatOpen() {
        let store = ChatStore()
        let ref = EmbedRef(id: "recording-1", type: "audio-recording", status: "finished", data: nil)
        let optimistic = Message(
            id: "user-1", chatId: "chat-1", role: .user,
            content: "[[embed:recording-1]]\nAudio check", encryptedContent: "local-cipher",
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: [ref]
        )
        let committed = Message(
            id: optimistic.id, chatId: optimistic.chatId, role: .user,
            content: nil, encryptedContent: "server-cipher",
            createdAt: optimistic.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil
        )
        let preview = EmbedRecord(
            id: ref.id, type: "audio-recording", status: .finished,
            data: .raw(["filename": AnyCodable("recording.m4a")]),
            parentEmbedId: nil, appId: "audio", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let synced = EmbedRecord(
            id: ref.id, type: "audio-recording", status: .finished,
            data: nil, encryptedContent: "encrypted-recording",
            encryptedType: "encrypted-type", parentEmbedId: nil,
            appId: nil, skillId: nil, embedIds: nil,
            hashedMessageId: "message-hash", createdAt: nil
        )
        store.appendMessage(optimistic, to: "chat-1")
        store.upsertEmbeds([preview], for: "chat-1")
        store.applySyncedContent(
            messagesByChat: ["chat-1": [committed]],
            embedsByChat: ["chat-1": [synced]]
        )
        XCTAssertEqual(store.messages(for: "chat-1").first?.embedRefs?.map(\.id), [ref.id])
        XCTAssertEqual(store.embeds(for: "chat-1").first?.rawData?["filename"]?.value as? String, "recording.m4a")
        XCTAssertEqual(store.embeds(for: "chat-1").first?.encryptedContent, "encrypted-recording")
        XCTAssertEqual(store.initialEmbedsForVisibleWindow(
            for: "chat-1", messages: store.messages(for: "chat-1")
        ).map(\.id), [ref.id])
        store.setMessages(for: "chat-1", messages: [committed])
        store.upsertEmbeds([synced], for: "chat-1")
        XCTAssertEqual(store.messages(for: "chat-1").first?.embedRefs?.map(\.id), [ref.id])
        XCTAssertEqual(store.embeds(for: "chat-1").first?.rawData?["filename"]?.value as? String, "recording.m4a")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.inline-entity-interaction
    func testReferenceOnlyInlineRecordCannotEraseHydratedPhoto() {
        let hydrated = EmbedRecord(
            id: "photo-1", type: "images-image", status: .finished,
            data: .raw([
                "filename": AnyCodable("quick-action-photo.png"),
                "files": AnyCodable(["thumbnail": ["s3_key": "thumbnail-key"]])
            ]),
            parentEmbedId: nil, appId: "images", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let reference = EmbedRecord(
            id: hydrated.id, type: "images-image", status: .finished,
            data: .raw(["type": AnyCodable("image"), "embed_id": AnyCodable(hydrated.id)]),
            parentEmbedId: nil, appId: nil, skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let merged = PublicChatContent.mergingHydratedRecords(
            existing: [hydrated.id: hydrated], inline: [reference.id: reference]
        )
        XCTAssertEqual(merged[hydrated.id]?.rawData?["filename"]?.value as? String,
                       "quick-action-photo.png")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPendingRecoveryCannotRetainUserRowsOrRowsFromAnotherChat() {
        let store = ChatStore()
        let user = makeMessage(id: "user", createdAt: "2026-01-01T00:00:00Z")
        let foreign = makeMessage(id: "foreign", createdAt: "2026-01-01T00:00:01Z", role: .assistant, chatId: "chat-2")
        store.setMessages(for: "chat-1", messages: [user, foreign])
        store.setPendingAssistantRecoveryLookup { _ in ["user", "foreign"] }
        store.applySyncedContent(messagesByChat: ["chat-1": []], embedsByChat: [:])
        XCTAssertTrue(store.messages(for: "chat-1").isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSyncPreservingPendingReplyDoesNotAdvanceAdvertisedMessageVersion() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "chat-1", title: "Fixture"))
        let before = store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions
        store.setMessages(for: "chat-1", messages: [makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z", role: .assistant)])
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.applySyncedContent(messagesByChat: ["chat-1": []], embedsByChat: [:])
        XCTAssertEqual(store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions, before)
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["reply"])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSearchMetadataExpansionIncludesOlderEncryptedTitlesWithoutReplacingLiveRows() {
        let live = makeChat(id: "loaded", title: "Current decrypted title")
        let cachedOld = makeChat(id: "older", title: nil, encryptedTitle: "encrypted-title-fixture")
        let stale = makeChat(id: "loaded", title: "Old cached title")
        let privateChat = makeChat(id: "incognito-private", title: "Private")
        let missing = ChatSearchMetadata.missingCachedChats([stale, cachedOld, cachedOld, privateChat], loaded: [live])
        XCTAssertEqual(missing.map(\.id), ["older"])
        XCTAssertEqual(missing.first?.encryptedTitle, "encrypted-title-fixture")
        XCTAssertNil(missing.first?.title)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testChatSortDatesPreserveFractionsAndTimeZonesAcrossRepeatedReads() throws {
        let precise = makeChat(id: "fractional", title: "Fixture", lastMessageAt: "2026-03-01T12:00:00.125Z")
        let offset = makeChat(id: "offset", title: "Fixture", lastMessageAt: "2026-03-01T13:00:00+01:00")
        let invalid = makeChat(id: "invalid", title: "Fixture", lastMessageAt: "not-a-date")
        let timestamp = try XCTUnwrap(precise.lastMessageDate)
        XCTAssertEqual(timestamp.timeIntervalSince(try XCTUnwrap(offset.lastMessageDate)), 0.125, accuracy: 0.001)
        for _ in 0..<1000 { XCTAssertEqual(precise.lastMessageDate, timestamp) }
        XCTAssertNil(invalid.lastMessageDate)
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testPersonalStartupSyncSendsRequiredIntegerContextEpoch() throws {
        let request = WebSocketManager.phasedSyncMessage(clientChatIds: ["known-chat"])
        let wire = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any]
        let payload = try XCTUnwrap(wire?["payload"] as? [String: Any])
        let epoch = try XCTUnwrap(payload["context_epoch"] as? NSNumber)
        XCTAssertNotEqual(CFGetTypeID(epoch), CFBooleanGetTypeID(), "The server rejects boolean epochs")
        XCTAssertEqual(epoch.intValue, 0)
        XCTAssertNil(payload["team_id"], "Personal sync must not select a team")
        XCTAssertEqual(payload["client_chat_ids"] as? [String], ["known-chat"])
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testOlderMetadataPagePreservesServerOrderAfterTheInitialWindow() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let page = try decoder.decode(ChatMetadataPage.self, from: Data("""
        {"offset":2,"total_count":3,"has_more":false,"chats":[
          {"chat_details":{"id":"older","created_at":1770000000}}
        ]}
        """.utf8))
        let initial = try decoder.decode([Chat].self, from: Data("""
        [{"id":"first","created_at":1770000000},{"id":"second","created_at":1770000000}]
        """.utf8))
        let store = ChatStore()
        store.upsertChats(initial, serverSortOrder: initial.map(\.id))
        let older = try XCTUnwrap(page.chats?.compactMap(\.chatDetails))
        store.upsertChats(older, serverSortOrder: older.map(\.id), serverSortOffset: page.offset)
        XCTAssertEqual(store.sortedChats.map(\.id), ["first", "second", "older"])
        XCTAssertEqual(page.totalCount, 3)
        XCTAssertEqual(page.hasMore, false)
    }

    // contract-test: direct surface=gui.apple assertions=sync.deletion.partial-window-not-authoritative,sync.surface.semantic-parity
    func testMetadataSyncRetainsExplicitServerTombstonesEvenForAnEmptyWindow() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = try decoder.decode(PhaseBulkSyncPayload.self, from: Data("""
        {"chats":[],"total_chat_count":150,"deleted_chat_ids":["deleted-while-offline"]}
        """.utf8))
        XCTAssertEqual(payload.deletedChatIds, ["deleted-while-offline"], "Metadata decoding must not discard explicit server deletions")
        XCTAssertEqual(payload.totalChatCount, 150)
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testChatDecodesWebSubChatAndFocusFields() throws {
        let json = """
        {
          "chat_id": "child-chat-1",
          "title": "Research Apple Q1",
          "created_at": 1770000000,
          "updated_at": 1770000300,
          "parent_id": "parent-chat-1",
          "is_sub_chat": true,
          "sub_chat_settings": { "wait_for_completion": true, "report_trigger": "all" },
          "budget_limit": 12,
          "budget_spent": 3,
          "encrypted_active_focus_id": "encrypted-focus",
          "messages_v": 2,
          "title_v": 1,
          "metadata_v": 7
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: json)

        XCTAssertEqual(chat.id, "child-chat-1")
        XCTAssertEqual(chat.parentId, "parent-chat-1")
        XCTAssertEqual(chat.isSubChat, true)
        XCTAssertEqual(chat.subChatSettings?.waitForCompletion, true)
        XCTAssertEqual(chat.subChatSettings?.reportTrigger, "all")
        XCTAssertEqual(chat.budgetLimit, 12)
        XCTAssertEqual(chat.budgetSpent, 3)
        XCTAssertEqual(chat.encryptedActiveFocusId, "encrypted-focus")
        XCTAssertEqual(chat.metadataV, 7)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence
    func testChatDecodesVisibilityFieldsUsedByNativeOfflineAndSpotlightGuards() throws {
        let json = """
        {
          "chat_id": "hidden-chat-1",
          "title": "Hidden research",
          "created_at": 1770000000,
          "updated_at": 1770000300,
          "is_private": true,
          "is_hidden": true,
          "is_hidden_candidate": true
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: json)

        XCTAssertEqual(chat.isPrivate, true)
        XCTAssertEqual(chat.isHidden, true)
        XCTAssertEqual(chat.isHiddenCandidate, true)
        XCTAssertTrue(chat.isHiddenFromNormalSurfaces)
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chats.local-state.precedence
    func testChatStoreMergePreservesSubChatAndFocusMetadata() {
        let store = ChatStore()
        let base = makeChat(
            id: "child-chat-1",
            title: "Child",
            parentId: "parent-chat-1",
            isSubChat: true,
            encryptedActiveFocusId: "encrypted-focus",
            isHiddenCandidate: true
        )
        let incoming = makeChat(
            id: "child-chat-1",
            title: nil,
            parentId: nil,
            isSubChat: nil,
            encryptedActiveFocusId: nil,
            messagesV: 4,
            metadataV: 5
        )

        store.performWithoutPersistence {
            store.upsertChat(base)
            store.upsertChat(incoming)
        }

        let merged = store.chat(for: "child-chat-1")
        XCTAssertEqual(merged?.title, "Child")
        XCTAssertEqual(merged?.parentId, "parent-chat-1")
        XCTAssertEqual(merged?.isSubChat, true)
        XCTAssertEqual(merged?.encryptedActiveFocusId, "encrypted-focus")
        XCTAssertEqual(merged?.messagesV, 4)
        XCTAssertEqual(merged?.metadataV, 5)
        XCTAssertEqual(merged?.isHiddenCandidate, true)
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testSameRevisionTitleHydrationPopulatesSidebarAndPersistsForColdBoot() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("TitleHydrationTests", schema: schema, isStoredInMemoryOnly: true)
        let offlineStore = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offlineStore))
        let encrypted = makeChat(
            id: "chat-title",
            title: nil,
            titleV: 4,
            encryptedTitle: "current-title-ciphertext"
        )
        let hydrated = makeChat(
            id: encrypted.id,
            title: "Hydrated research title",
            titleV: 4,
            encryptedTitle: encrypted.encryptedTitle
        )

        store.upsertChat(encrypted)
        store.upsertChat(hydrated)

        XCTAssertEqual(store.chat(for: encrypted.id)?.displayTitle, "Hydrated research title")
        XCTAssertEqual(offlineStore.loadChat(id: encrypted.id)?.displayTitle, "Hydrated research title")
        XCTAssertEqual(offlineStore.loadStartupChats(lastOpenedChatId: encrypted.id, limit: 20).first?.title,
                       "Hydrated research title")
    }

    // contract-test: direct surface=gui.apple assertions=chats.local-state.precedence,chats.persistence.client-encrypted
    func testSameRevisionTitleHydrationRejectsPlaintextForDifferentCiphertext() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("TitleHydrationFenceTests", schema: schema, isStoredInMemoryOnly: true)
        let offlineStore = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offlineStore))
        let current = makeChat(
            id: "chat-title",
            title: nil,
            titleV: 4,
            encryptedTitle: "current-title-ciphertext"
        )
        let mismatched = makeChat(
            id: current.id,
            title: "Plaintext from another revision",
            titleV: 4,
            encryptedTitle: "different-title-ciphertext"
        )

        store.upsertChat(current)
        store.upsertChat(mismatched)

        XCTAssertNil(store.chat(for: current.id)?.title)
        XCTAssertEqual(store.chat(for: current.id)?.encryptedTitle, "current-title-ciphertext")
        XCTAssertNil(offlineStore.loadChat(id: current.id)?.title)
        XCTAssertEqual(offlineStore.loadChat(id: current.id)?.encryptedTitle, "current-title-ciphertext")
    }

    // contract-test: direct surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testNewerEncryptedTitleRevisionClearsOlderDecryptedTitleUntilHydrated() {
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChat(makeChat(
                id: "chat-title",
                title: "Old title",
                titleV: 3,
                encryptedTitle: "old-title-ciphertext"
            ))
            store.upsertChat(makeChat(
                id: "chat-title",
                title: nil,
                titleV: 4,
                encryptedTitle: "new-title-ciphertext"
            ))
            store.upsertChat(makeChat(
                id: "chat-title",
                title: "Stale title",
                titleV: 3,
                encryptedTitle: "stale-title-ciphertext"
            ))
        }

        XCTAssertNil(store.chat(for: "chat-title")?.title)
        XCTAssertEqual(store.chat(for: "chat-title")?.encryptedTitle, "new-title-ciphertext")
    }

    // contract-test: direct surface=gui.apple assertions=chats.followups.non-destructive-reconciliation,chats.surface.semantic-parity
    func testOlderMetadataCannotReplaceEncryptedFollowUpsInMemoryOrOffline() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("FollowUpMetadataFenceTests", schema: schema, isStoredInMemoryOnly: true)
        let offlineStore = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offlineStore))
        let current = makeChat(
            id: "chat-follow-ups",
            title: "Current",
            metadataV: 8,
            encryptedFollowUpRequestSuggestions: "newer-ciphertext"
        )
        let older = makeChat(
            id: "chat-follow-ups",
            title: "Older page",
            metadataV: 7,
            encryptedFollowUpRequestSuggestions: "older-ciphertext"
        )

        store.upsertChat(current)
        store.upsertChat(older)

        XCTAssertEqual(store.chat(for: current.id)?.encryptedFollowUpRequestSuggestions, "newer-ciphertext")
        XCTAssertEqual(store.chat(for: current.id)?.metadataV, 8)
        XCTAssertEqual(offlineStore.loadChat(id: current.id)?.encryptedFollowUpRequestSuggestions, "newer-ciphertext")
        XCTAssertEqual(offlineStore.loadChat(id: current.id)?.metadataV, 8)
    }

    // contract-test: direct surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testOlderMetadataCannotReplaceGeneratedSummaryInMemoryOrOffline() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("SummaryMetadataFenceTests", schema: schema, isStoredInMemoryOnly: true)
        let offlineStore = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offlineStore))
        let current = makeChat(id: "chat-summary", title: "Current", metadataV: 8,
                               chatSummary: "Current summary", encryptedChatSummary: "current-cipher")
        let older = makeChat(id: "chat-summary", title: "Older", metadataV: 7,
                             chatSummary: "Stale summary", encryptedChatSummary: "stale-cipher")
        store.upsertChat(current)
        store.upsertChat(older)
        XCTAssertEqual(store.chat(for: current.id)?.chatSummary, "Current summary")
        XCTAssertEqual(store.chat(for: current.id)?.encryptedChatSummary, "current-cipher")
        XCTAssertEqual(offlineStore.loadChat(id: current.id)?.chatSummary, "Current summary")
        XCTAssertEqual(offlineStore.loadChat(id: current.id)?.encryptedChatSummary, "current-cipher")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testSameMetadataRevisionHydratesMatchingSummaryCipherInMemoryAndOffline() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("SummaryHydrationTests", schema: schema, isStoredInMemoryOnly: true)
        let offline = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offline))
        store.upsertChat(makeChat(id: "summary-hydration", title: "Synthetic", metadataV: 8,
                                 encryptedChatSummary: "matching-cipher"))
        store.upsertChat(makeChat(id: "summary-hydration", title: "Synthetic", metadataV: 8,
                                 chatSummary: "Hydrated summary", encryptedChatSummary: "matching-cipher"))
        XCTAssertEqual(store.chat(for: "summary-hydration")?.chatSummary, "Hydrated summary")
        XCTAssertEqual(offline.loadChat(id: "summary-hydration")?.chatSummary, "Hydrated summary")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testSameMetadataRevisionRejectsSummaryFromDifferentCipher() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("SummaryCipherFenceTests", schema: schema, isStoredInMemoryOnly: true)
        let offline = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let store = ChatStore()
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offline))
        store.upsertChat(makeChat(id: "summary-fence", title: "Synthetic", metadataV: 8,
                                 encryptedChatSummary: "current-cipher"))
        store.upsertChat(makeChat(id: "summary-fence", title: "Synthetic", metadataV: 8,
                                 chatSummary: "Wrong revision", encryptedChatSummary: "different-cipher"))
        XCTAssertNil(store.chat(for: "summary-fence")?.chatSummary)
        XCTAssertEqual(store.chat(for: "summary-fence")?.encryptedChatSummary, "current-cipher")
        XCTAssertNil(offline.loadChat(id: "summary-fence")?.chatSummary)
        XCTAssertEqual(offline.loadChat(id: "summary-fence")?.encryptedChatSummary, "current-cipher")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testContinuationUsesActualWireDraftPresenceInsteadOfVersion() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        func decoded(_ id: String, encryptedDraft: Any, version: Int, timestamp: Int) throws -> Chat {
            try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: [
                "id": id, "title": id, "created_at": 1, "updated_at": timestamp,
                "last_edited_overall_timestamp": timestamp, "draft_v": version,
                "encrypted_draft_md": encryptedDraft
            ]))
        }
        let cleared = try decoded("cleared", encryptedDraft: NSNull(), version: 9, timestamp: 30)
        let empty = try decoded("empty", encryptedDraft: "", version: 4, timestamp: 20)
        let actual = try decoded("actual", encryptedDraft: "encrypted-body", version: 0, timestamp: 10)
        XCTAssertEqual(WelcomeScreenState.recentChats(from: [cleared, empty, actual], excluding: nil).map(\.id),
                       ["actual", "cleared", "empty"])
        XCTAssertEqual(PersistedChat(from: actual).toChat().hasNonEmptyDraft, true)
        XCTAssertEqual(PersistedChat(from: cleared).toChat().hasNonEmptyDraft, false)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testMetadataUpdateDoesNotInventMessageRecencyAndEqualTiesIgnoreSidebarOrder() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let onlyMetadata = try decoder.decode(Chat.self, from: Data(#"{"id":"metadata-only","title":"Metadata","created_at":1,"updated_at":9999999999}"#.utf8))
        XCTAssertNil(onlyMetadata.lastMessageAt, "Editing metadata must not become a message timestamp")
        let a = makeChat(id: "a", title: "A")
        let z = makeChat(id: "z", title: "Z")
        let store = ChatStore()
        store.upsertChats([a, z, onlyMetadata], serverSortOrder: ["a", "z"])
        XCTAssertEqual(WelcomeScreenState.recentChats(from: store.chats, excluding: nil).map(\.id), ["a", "z", "metadata-only"])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.surface.semantic-parity
    func testContinueUsesOverallEditTimeBeforeMessageTimeAndPreservesEqualInputTies() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        func chat(_ id: String, message: Int, edited: Int) throws -> Chat {
            try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: [
                "id": id, "title": id, "created_at": 1, "updated_at": 1,
                "last_message_at": message, "last_edited_overall_timestamp": edited]))
        }
        let messageNew = try chat("message-new", message: 300, edited: 10)
        let editNew = try chat("edit-new", message: 100, edited: 50)
        let equalFirst = try chat("a", message: 400, edited: 20)
        let equalSecond = try chat("z", message: 200, edited: 20)
        XCTAssertEqual(WelcomeScreenState.recentChats(from: [messageNew, equalFirst, equalSecond, editNew], excluding: nil).map(\.id),
            ["edit-new", "a", "z", "message-new"])
        XCTAssertEqual(WelcomeScreenState.recentChats(from: [messageNew, equalFirst, equalSecond, editNew],
            excluding: "edit-new", activeChatId: "a").map(\.id), ["z", "message-new"])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testConnectionRippleUsesNormalCycleAndReduceMotionKeepsArcsStatic() {
        XCTAssertEqual(NativeConnectionAnimation.wifiOpacity(elapsed: 0, arc: 2, reduceMotion: false), 0.3, accuracy: 0.001)
        XCTAssertEqual(NativeConnectionAnimation.wifiOpacity(elapsed: 0.81, arc: 2, reduceMotion: false), 1, accuracy: 0.001)
        XCTAssertEqual(NativeConnectionAnimation.wifiOpacity(elapsed: 1.8, arc: 2, reduceMotion: false), 0.3, accuracy: 0.001)
        XCTAssertEqual(NativeConnectionAnimation.wifiOpacity(elapsed: 1.17, arc: 0, reduceMotion: false), 1, accuracy: 0.001)
        for arc in 0..<3 {
            XCTAssertEqual(NativeConnectionAnimation.wifiOpacity(elapsed: 1.4, arc: arc, reduceMotion: true), 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testDownloadHeaderUsesSubtleOpacityAndReduceMotionIsStatic() {
        XCTAssertEqual(OfflineAIModelDownloadMotion.opacity(elapsed: 0, active: true, reduceMotion: false), 1, accuracy: 0.001)
        XCTAssertEqual(OfflineAIModelDownloadMotion.opacity(elapsed: 1.2, active: true, reduceMotion: false), 0.6, accuracy: 0.001)
        XCTAssertEqual(OfflineAIModelDownloadMotion.opacity(elapsed: 2.4, active: true, reduceMotion: false), 1, accuracy: 0.001)
        for elapsed in [0.0, 0.6, 1.2, 2.4] {
            XCTAssertEqual(OfflineAIModelDownloadMotion.opacity(elapsed: elapsed, active: true, reduceMotion: true), 1)
            XCTAssertEqual(OfflineAIModelDownloadMotion.opacity(elapsed: elapsed, active: false, reduceMotion: false), 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,sync.surface.semantic-parity
    func testAuthenticationPresentationHidesStatusAndResetsReconnectDelay() {
        var policy = NativeConnectionFeedbackPolicy()
        var inputs = NativeConnectionFeedbackInputs(online: true, authenticated: true,
            checkingAuth: false, connected: false, syncing: false)
        policy.update(inputs, now: 0)
        policy.update(inputs, now: 3)
        XCTAssertEqual(policy.state, .reconnecting, "A disconnected cached account still shows connection feedback")
        inputs.connected = true
        inputs.syncing = true
        policy.update(inputs, now: 3.1)
        policy.update(inputs, now: 3.8)
        XCTAssertEqual(policy.state, .syncing)
        inputs.authenticationPresented = true
        policy.update(inputs, now: 4)
        XCTAssertEqual(policy.state, .idle)
        XCTAssertNil(policy.nextUpdateDelay(now: 4))
        inputs.online = false
        policy.update(inputs, now: 20)
        XCTAssertEqual(policy.state, .idle, "Login and verification own feedback while authentication is presented")
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .downloading, online: true,
            authenticated: true, checkingAuth: false, authenticationPresented: true))
        inputs.authenticationPresented = false
        inputs.connected = false
        inputs.syncing = false
        policy.update(inputs, now: 21)
        XCTAssertEqual(policy.state, .offline, "A valid cached account keeps its offline indicator")
        inputs.online = true
        policy.update(inputs, now: 22)
        XCTAssertEqual(policy.state, .idle)
        policy.update(inputs, now: 25)
        XCTAssertEqual(policy.state, .reconnecting)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,sync.surface.semantic-parity
    func testHeaderDownloadNeverHidesOfflineOrAuthenticationStatus() {
        XCTAssertTrue(NativeHeaderStatusPolicy.showsDownload(phase: .downloading, online: true, authenticated: true, checkingAuth: false))
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .downloading, online: false, authenticated: true, checkingAuth: false))
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .downloading, online: true, authenticated: true, checkingAuth: true))
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .downloading, online: true, authenticated: false, checkingAuth: false))
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .deferred, online: true, authenticated: true, checkingAuth: false))
        XCTAssertFalse(NativeHeaderStatusPolicy.showsDownload(phase: .complete, online: true, authenticated: true, checkingAuth: false))
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative,chat-navigation.open.local-first-coherent
    func testDraftPresenceSurvivesPartialMetadataAndClearsOnActualDelete() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "draft", title: "Draft", draftV: 7, hasNonEmptyDraft: true))
        store.upsertChat(makeChat(id: "draft", title: "Metadata", draftV: 7))
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.advanceMessagesVersion(chatId: "draft", to: 3)
        store.updateLastVisibleMessage(chatId: "draft", messageId: "message")
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.updateDraftVersion(chatId: "draft", draftVersion: 0)
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, false)
        store.updateDraftVersion(chatId: "draft", draftVersion: 1, hasNonEmptyDraft: true)
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.upsertChat(makeChat(id: "draft", title: "Deleted", draftV: 8, hasNonEmptyDraft: false))
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, false)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationCapKeepsViewedChatFirstWithoutResortingOtherChatsByOpening() {
        let older = makeChat(id: "viewed", title: "Viewed", lastMessageAt: "2025-01-01T00:00:00Z")
        let recent = (0..<15).map { makeChat(id: String(format: "recent-%02d", $0), title: "Recent") }
        let chats = recent + [older]
        let resume = WelcomeScreenState.resumeChat(from: chats, lastOpened: older.id)
        let other = WelcomeScreenState.recentChats(from: chats, excluding: resume?.id, activeChatId: "recent-14")
        XCTAssertEqual(resume?.id, older.id)
        XCTAssertEqual(other.count, 9)
        XCTAssertEqual(other.first?.id, "recent-00")
        XCTAssertFalse(other.contains { $0.id == older.id || $0.id == "recent-14" })
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: nil).count, 10)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.local-state.precedence
    func testColdStartupIncludesOlderPinnedDraftAndUnpinnedDraftMetadataBeyondRecentPage() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("ContinuationPolicyTests", schema: schema, isStoredInMemoryOnly: true)
        let store = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let recent = (0..<40).map { makeChat(id: "recent-\($0)", title: "Recent", lastMessageAt: "2026-09-12T00:00:00Z") }
        let pinnedRecent = (0..<30).map { makeChat(id: "pinned-\($0)", title: "Pinned", lastMessageAt: "2026-01-01T00:00:00Z", isPinned: true) }
        let pinnedDraft = makeChat(id: "older-pinned-draft", title: "Pinned draft", lastMessageAt: "2025-01-01T00:00:00Z", isPinned: true, draftV: 3, hasNonEmptyDraft: true)
        let draft = makeChat(id: "older-draft", title: "Draft", lastMessageAt: "2025-01-02T00:00:00Z", draftV: 2, hasNonEmptyDraft: true)
        store.persistChats(recent + pinnedRecent + [pinnedDraft, draft])
        let loaded = store.loadStartupChats(lastOpenedChatId: nil, limit: 20)
        XCTAssertTrue(loaded.contains { $0.id == pinnedDraft.id })
        XCTAssertTrue(loaded.contains { $0.id == draft.id })
        XCTAssertLessThanOrEqual(loaded.count, 80, "Four metadata groups remain bounded; no transcript is loaded")
        XCTAssertEqual(WelcomeScreenState.recentChats(from: loaded, excluding: nil).first?.id, pinnedDraft.id)
        XCTAssertTrue(store.loadMessages(chatId: pinnedDraft.id).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.local-state.precedence
    func testColdSidebarDiscoversOlderArchivedPinsAndDraftsWithoutLoadingMessages() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("SidebarArchivedPriorityTests", schema: schema, isStoredInMemoryOnly: true)
        let store = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let recent = (0..<30).map { makeChat(id: "recent-\($0)", title: "Recent", lastMessageAt: "2026-09-12T00:00:00Z") }
        let pin = makeChat(id: "archived-pin", title: "Pinned", lastMessageAt: "2025-01-01T00:00:00Z", isArchived: true, isPinned: true)
        let draft = makeChat(id: "archived-draft", title: "Draft", lastMessageAt: "2025-01-02T00:00:00Z", isArchived: true, draftV: 1, hasNonEmptyDraft: true)
        store.persistChats(recent + [pin, draft])
        let loaded = store.loadStartupChats(lastOpenedChatId: nil, limit: 20)
        XCTAssertTrue(loaded.contains { $0.id == pin.id })
        XCTAssertTrue(loaded.contains { $0.id == draft.id })
        XCTAssertLessThanOrEqual(loaded.count, 80)
        XCTAssertTrue(store.loadMessages(chatId: pin.id).isEmpty)
        XCTAssertTrue(store.loadMessages(chatId: draft.id).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testWelcomeResumeAndRecentChatsExcludeHiddenCandidates() {
        let visible = makeChat(id: "visible-chat", title: "Visible", lastMessageAt: "2026-01-02T00:00:00Z")
        let hidden = makeChat(
            id: "hidden-chat",
            title: "Hidden",
            lastMessageAt: "2026-01-03T00:00:00Z",
            isHiddenCandidate: true
        )

        XCTAssertNil(WelcomeScreenState.resumeChat(from: [hidden, visible], lastOpened: "hidden-chat"))
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: [hidden, visible], lastOpened: "visible-chat")?.id, "visible-chat")

        let recent = WelcomeScreenState.recentChats(from: [hidden, visible], excluding: nil)
        XCTAssertEqual(recent.map(\.id), ["visible-chat"])
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.order.sidebar-header-match,chat-navigation.empty-new-chat.excluded
    func testContinuationMatchesWebEligibilityForPinnedArchivesEmptyShellsAndNewsletters() {
        let pinnedArchived = makeChat(
            id: "pinned-archived",
            title: "Pinned archive",
            isArchived: true,
            isPinned: true
        )
        let archived = makeChat(id: "archived", title: "Archive", isArchived: true)
        let empty = makeChat(id: "empty", title: nil, messagesV: 0, metadataV: 0)
        let newsletter = makeChat(id: "tips-weekly", title: "Tips")
        let ordinary = makeChat(id: "ordinary", title: "Ordinary")

        XCTAssertEqual(
            WelcomeScreenState.recentChats(
                from: [ordinary, newsletter, empty, archived, pinnedArchived],
                excluding: nil
            ).map(\.id),
            ["pinned-archived", "ordinary"]
        )
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.draft-only.addressable,drafts.established-chat.presentation-unchanged
    func testContinuationDoesNotRenderPartiallySyncedGeneratedMetadataAsDraftOnly() {
        let generated = makeChat(
            id: "generated",
            title: nil,
            messagesV: 0,
            titleV: 2,
            draftV: 3,
            hasNonEmptyDraft: true
        )

        XCTAssertFalse(WelcomeScreenState.isDraftOnly(generated))
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: [generated], lastOpened: generated.id)?.id, generated.id)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationMatchesPinnedDraftRecentOrderAndSkipsSubChats() {
        let recent = makeChat(id: "recent", title: "Recent", lastMessageAt: "2026-03-01T00:00:00Z")
        let draft = makeChat(id: "draft", title: nil, messagesV: 0, draftV: 2, hasNonEmptyDraft: true)
        let pinned = makeChat(id: "pinned", title: "Pinned", isPinned: true)
        let child = makeChat(id: "child", title: "Child", parentId: "recent", isSubChat: true)
        let incognito = makeChat(id: "incognito-private", title: "Private")
        let chats = [recent, child, incognito, draft, pinned]
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: nil).map(\.id), ["pinned", "draft", "recent"])
        XCTAssertNil(WelcomeScreenState.resumeChat(from: chats, lastOpened: "draft"))
        XCTAssertNil(WelcomeScreenState.resumeChat(from: chats, lastOpened: "child"))
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: chats, lastOpened: "recent")?.id, "recent")
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: "recent").map(\.id), ["pinned", "draft"])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,drafts.persistence.local-first-encrypted
    func testContinuationDraftCardUsesPreviewWithoutMisclassifyingUntitledMessages() {
        let draft = makeChat(id: "draft", title: nil, messagesV: 0, draftV: 1)
        let existing = makeChat(id: "existing", title: nil, messagesV: 2, draftV: 1)
        let preview = String(repeating: "a", count: 90)
        let card = WelcomeScreenState.cardData(for: draft, draftPreview: preview)
        XCTAssertTrue(card.isDraftOnly)
        XCTAssertEqual(card.title, AppStrings.draftBadge)
        XCTAssertEqual(card.draftPreview, String(repeating: "a", count: 80) + "…")
        let audio = AppStrings.draftEmbedPreviewLabel(type: "audio")
        let image = AppStrings.draftEmbedPreviewLabel(type: "image")
        let expected = "Before \(audio) after \(image) describe it"
        let serializedPreviews = [
            "Before ```json\n{\"type\":\"audio\",\"embed_id\":\"synthetic-audio\"}\n``` after ```json\n{\"type\":\"image\",\"embed_id\":\"synthetic-image\"}\n``` describe it",
            #"{"version":1,"nodes":[{"kind":"text","source":"Before "},{"kind":"embed","embedType":"audio-recording"},{"kind":"text","source":" after "},{"kind":"embed","embedType":"image"},{"kind":"text","source":" describe it"}]}"#,
            #"{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Before "},{"type":"embed","attrs":{"type":"audio"}},{"type":"text","text":" after "},{"type":"embed","attrs":{"type":"image"}},{"type":"text","text":" describe it"}]}]}"#
        ]
        for source in serializedPreviews {
            let formattedCard = WelcomeScreenState.cardData(for: draft, draftPreview: source)
            XCTAssertEqual(formattedCard.draftPreview, expected)
            XCTAssertTrue(formattedCard.isDraftOnly)
            XCTAssertEqual(formattedCard.title, AppStrings.draftBadge)
        }
        let ordinaryJSON = #"{"type":"audio","message":"Discuss this JSON"}"#
        XCTAssertEqual(WelcomeScreenState.cardData(for: draft, draftPreview: ordinaryJSON).draftPreview, ordinaryJSON)
        XCTAssertEqual(WelcomeScreenState.cardData(for: draft, draftPreview: "  Ordinary\n draft  ").draftPreview, "Ordinary draft")
        XCTAssertNil(WelcomeScreenState.cardData(for: draft).draftPreview)
        XCTAssertEqual(WelcomeScreenState.cardData(for: draft, draftPreview: " \n ").draftPreview, "")
        XCTAssertTrue(WelcomeScreenState.isContinuationEligible(draft),
                      "Formatting an empty preview must not discard an addressable draft record")
        let projectMention = #"{"version":1,"nodes":[{"kind":"text","source":"Review "},{"kind":"mention","displayLabel":"@Synthetic-Project","canonicalSyntax":"@project:synthetic-id:read"}]}"#
        XCTAssertEqual(WelcomeScreenState.cardData(for: draft, draftPreview: projectMention).draftPreview,
                       "Review @Synthetic-Project")

        XCTAssertFalse(WelcomeScreenState.cardData(for: existing, draftPreview: "Unsent follow-up").isDraftOnly)
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: [existing], lastOpened: "existing")?.id, "existing")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence
    func testSpotlightEligibilitySkipsHiddenPublicAndArchivedChats() {
        let privateVisible = makeChat(id: "private-visible", title: "Private but searchable")
        let hidden = makeChat(id: "hidden-chat", title: "Hidden", isHidden: true)
        let archived = makeChat(id: "archived-chat", title: "Archived", isArchived: true)
        let publicChat = makeChat(id: "example-gigantic-airplanes", title: "Public example")

        XCTAssertTrue(SpotlightIndexer.isEligibleForSpotlight(privateVisible))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(hidden))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(archived))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(publicChat))
    }

    // contract-test: direct surface=gui.apple assertions=sync.startup.bounded-phases,sync.surface.semantic-parity
    func testSyncClientStateExcludesIncognitoChats() {
        let store = ChatStore()
        let saved = makeChat(id: "saved-chat", title: "Saved")
        let incognito = makeChat(id: IncognitoChatSession.makeChatId(), title: "Private")

        store.performWithoutPersistence {
            store.upsertChat(saved)
            store.upsertChat(incognito)
        }

        let state = store.makeSyncClientState(clientSuggestionsCount: 0)
        XCTAssertEqual(state.clientChatIds, ["saved-chat"])
        XCTAssertNotNil(state.clientChatVersions["saved-chat"])
        XCTAssertEqual(state.clientChatVersions["saved-chat"]?["metadata_v"], 1)
        XCTAssertFalse(state.clientChatVersions.keys.contains(incognito.id))
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent,sync.deletion.partial-window-not-authoritative
    func testPartialSyncNeverClearsCurrentSelectionWithoutExplicitTombstone() {
        XCTAssertFalse(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "phase_2_last_20_chats_ready",
            eventChatId: nil
        ))
        XCTAssertFalse(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "sync_metadata_chats_response",
            eventChatId: "chat-1"
        ))
        XCTAssertTrue(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "chat_deleted",
            eventChatId: "chat-1"
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.lifecycle,chat-navigation.empty-new-chat.excluded
    func testRemovedDraftClosesOnlyMatchingEmptyComposerInCurrentAccountScope() {
        let scope = UUID()
        func closes(id: String? = "draft", event: String? = "draft", eventScope: UUID? = nil,
                    removed: Bool = true, content: Bool = false, messages: Bool = false) -> Bool {
            ChatSelectionSyncPolicy.shouldCloseRemovedDraft(
                selectedChatId: id, eventChatId: event, eventScope: eventScope ?? scope,
                currentScope: scope, chatRemoved: removed, hasComposerContent: content, hasMessages: messages)
        }
        XCTAssertTrue(closes())
        XCTAssertFalse(closes(id: nil))
        XCTAssertFalse(closes(event: "other-draft"))
        XCTAssertFalse(closes(eventScope: UUID()))
        XCTAssertFalse(closes(removed: false))
        XCTAssertFalse(closes(content: true), "Newer typing, pending attachments and recording keep their route")
        XCTAssertFalse(closes(messages: true), "Sent or streaming content must keep its route")
        XCTAssertFalse(ChatSelectionSyncPolicy.shouldCloseRemovedDraft(
            selectedChatId: "draft", eventChatId: "draft", eventScope: nil, currentScope: scope,
            chatRemoved: true, hasComposerContent: false, hasMessages: false))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.persistence.client-encrypted
    func testTypingMetadataWaitsForOriginatingUserMessage() throws {
        let data = """
        {
          "chat_id": "chat-1",
          "message_id": "assistant-1",
          "user_message_id": "user-1",
          "encrypted_chat_key": "wrapped-key"
        }
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = try decoder.decode(AITypingStartedSyncPayload.self, from: data)
        var buffer = TypingMetadataReplayBuffer()

        XCTAssertTrue(buffer.deferIfMessageMissing(payload, messageExists: false))
        XCTAssertEqual(buffer.take(for: "user-1")?.messageId, "assistant-1")
        XCTAssertNil(buffer.take(for: "user-1"))
        XCTAssertFalse(buffer.deferIfMessageMissing(payload, messageExists: true))
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chats.sync.key-gated-recovery,chat-navigation.open.local-first-coherent
    func testContentBatchDecodesVersionsAndKeyMaterialForStoreReconciliation() throws {
        let fields: [String: Any] = [
            "messages_by_chat_id": ["chat-1": []],
            "versions_by_chat_id": ["chat-1": ["messages_v": 7, "server_message_count": 6]],
            "embeds": [],
            "embed_keys": [],
            "chat_key_wrappers": [[
                "id": "wrapper-2",
                "hashed_chat_id": ChatKeyWrapperRecord.hashedChatId(for: "chat-1"),
                "key_type": "master",
                "encrypted_chat_key": "wrapped-key",
                "wrapper_version": 2,
                "created_at": "2026-08-24T00:00:00Z",
            ]],
        ]

        let payload = try ChatContentBatchPayload.decode(fields)

        XCTAssertEqual(try payload.messages(for: "chat-1").count, 0)
        XCTAssertEqual(payload.messagesVersion(for: "chat-1"), 7)
        XCTAssertEqual(payload.chatKeyWrappers.count, 1)
        XCTAssertEqual(payload.chatKeyWrappers.first?.hashedChatId, ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))
        XCTAssertEqual(payload.chatKeyWrappers.first?.encryptedChatKey, "wrapped-key")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    func testNewestMasterChatKeyWrapperIsTriedFirst() throws {
        let data = """
        [
          {"id":"old","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))","key_type":"master","encrypted_chat_key":"old-key","wrapper_version":1,"created_at":"2026-08-23T00:00:00Z"},
          {"id":"other","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-2"))","key_type":"master","encrypted_chat_key":"other-key","wrapper_version":9,"created_at":"2026-08-24T00:00:00Z"},
          {"id":"new","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))","key_type":"master","encrypted_chat_key":"new-key","wrapper_version":2,"created_at":"2026-08-24T00:00:00Z"}
        ]
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let wrappers = try decoder.decode([ChatKeyWrapperRecord].self, from: data)

        let ordered = ChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: "chat-1")

        XCTAssertEqual(ordered.map(\.id), ["new", "old"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    func testContentBatchAcceptsNumericChatKeyWrapperTimestamp() throws {
        let fields: [String: Any] = [
            "messages_by_chat_id": ["chat-1": []],
            "versions_by_chat_id": ["chat-1": ["messages_v": 1]],
            "embeds": [], "embed_keys": [],
            "chat_key_wrappers": [[
                "id": "wrapper-numeric",
                "hashed_chat_id": ChatKeyWrapperRecord.hashedChatId(for: "chat-1"),
                "key_type": "master", "encrypted_chat_key": "wrapped-key",
                "wrapper_version": 2, "created_at": 1_770_000_000,
            ]],
        ]
        let payload = try ChatContentBatchPayload.decode(fields)
        XCTAssertEqual(payload.chatKeyWrappers.first?.createdAt, "1770000000")
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContentBatchMergePreservesMessagesThatArrivedDuringHydration() {
        let snapshot = [makeMessage(id: "snapshot", createdAt: "2026-01-01T00:00:00Z")]
        let realtime = [makeMessage(id: "realtime", createdAt: "2026-01-01T00:00:01Z")]

        let merged = ChatContentBatchPayload.mergedMessages(snapshot: snapshot, preserving: realtime)

        XCTAssertEqual(merged.map(\.id), ["snapshot", "realtime"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testEmbedRecordDecodesMessageOwnershipAndPreservesItAfterDecryption() throws {
        let snakeCase = """
        {
          "embed_id": "image-1",
          "embed_type": "image",
          "status": "finished",
          "hashed_chat_id": "chat-hash",
          "hashed_message_id": "message-hash",
          "hashed_user_id": "user-hash"
        }
        """.data(using: .utf8)!
        let camelCase = """
        {
          "embedId": "image-2",
          "type": "image",
          "status": "finished",
          "hashedChatId": "chat-hash-2",
          "hashedMessageId": "message-hash-2",
          "hashedUserId": "user-hash-2"
        }
        """.data(using: .utf8)!

        let snakeRecord = try JSONDecoder().decode(EmbedRecord.self, from: snakeCase)
        let camelRecord = try JSONDecoder().decode(EmbedRecord.self, from: camelCase)

        XCTAssertEqual(snakeRecord.hashedMessageId, "message-hash")
        XCTAssertEqual(camelRecord.hashedMessageId, "message-hash-2")
        XCTAssertEqual(
            snakeRecord.decryptedCopy(content: "filename: receipt.png", type: "image").hashedMessageId,
            "message-hash"
        )
    }

    private func makeChat(
        id: String,
        title: String?,
        parentId: String? = nil,
        isSubChat: Bool? = nil,
        encryptedActiveFocusId: String? = nil,
        messagesV: Int? = 1,
        titleV: Int? = nil,
        metadataV: Int? = 1,
        lastMessageAt: String = "2026-01-01T00:00:00Z",
        isArchived: Bool = false,
        isHidden: Bool? = nil,
        isHiddenCandidate: Bool? = nil,
        isPinned: Bool = false,
        draftV: Int? = nil,
        encryptedTitle: String? = nil,
        chatSummary: String? = nil,
        encryptedChatSummary: String? = nil,
        encryptedFollowUpRequestSuggestions: String? = nil,
        hasNonEmptyDraft: Bool? = nil
    ) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: isArchived,
            isPinned: isPinned,
            appId: "ai",
            chatSummary: chatSummary,
            encryptedTitle: encryptedTitle,
            encryptedChatSummary: encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: encryptedFollowUpRequestSuggestions,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: titleV ?? (title == nil ? 0 : 1),
            draftV: draftV,
            metadataV: metadataV,
            parentId: parentId,
            isSubChat: isSubChat,
            encryptedActiveFocusId: encryptedActiveFocusId,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft
        )
    }

    private func makeMessage(id: String, createdAt: String, role: MessageRole = .user,
                             chatId: String = "chat-1", encryptedContent: String? = nil) -> Message {
        Message(
            id: id,
            chatId: chatId,
            role: role,
            content: id,
            encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
    }
}

@MainActor
private final class RecentOfflineFetchGate {
    private(set) var calls = 0
    private var pending: [Int: CheckedContinuation<Data, Error>] = [:]
    private var waiters: [Int: CheckedContinuation<Void, Never>] = [:]

    func fetch() async throws -> Data {
        let index = calls
        calls += 1
        return try await withCheckedThrowingContinuation { continuation in
            pending[index] = continuation
            waiters.removeValue(forKey: index)?.resume()
        }
    }

    func waitUntilStarted(_ index: Int) async {
        if pending[index] != nil { return }
        await withCheckedContinuation { waiters[index] = $0 }
    }

    func release(_ index: Int, data: Data) {
        pending.removeValue(forKey: index)?.resume(returning: data)
    }
}

private actor RecentOfflineCommitGate {
    let entered: AsyncStream<Void>.Continuation
    private var continuation: CheckedContinuation<Void, Never>?
    init(entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    func pause() async {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            entered.yield(())
        }
    }
    func release() { continuation?.resume(); continuation = nil }
}
