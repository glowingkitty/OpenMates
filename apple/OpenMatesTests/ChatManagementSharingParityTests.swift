// Unit coverage for native chat management metadata parity.
// These tests are deterministic and do not use network calls, credentials,
// private chat content, share URLs, or webhook secrets. They protect the local
// chat ordering and merge behavior that backs the Apple chat-management UI.

import XCTest
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

@MainActor
final class ChatManagementSharingParityTests: XCTestCase {
    func testHomeScreenQuickActionDefinitionsMatchChatActions() {
        #if os(iOS)
        let items = AppQuickAction.shortcutItems
        let typesAndTitles = items.map { "\($0.type)|\($0.localizedTitle)" }

        XCTAssertEqual(
            typesAndTitles,
            [
                "org.openmates.ask|\(AppStrings.quickActionAsk)",
                "org.openmates.ask-about-photo|\(AppStrings.quickActionAskAboutPhoto)",
                "org.openmates.search|\(AppStrings.search)",
                "org.openmates.incognito-ask|\(AppStrings.quickActionIncognitoAsk)"
            ]
        )

        XCTAssertEqual(AppQuickAction(shortcutItem: UIApplicationShortcutItem(type: "org.openmates.newchat", localizedTitle: "New Chat")), .ask)
        XCTAssertEqual(AppQuickAction(shortcutItem: items[0]), .ask)
        XCTAssertEqual(AppQuickAction(shortcutItem: items[1]), .askAboutPhoto)
        XCTAssertEqual(AppQuickAction(shortcutItem: items[2]), .search)
        XCTAssertEqual(AppQuickAction(shortcutItem: items[3]), .incognitoAsk)
        #endif
    }

    func testInfoPlistRegistersInstallTimeHomeScreenQuickActions() throws {
        #if os(iOS)
        let bundle = Bundle(for: AppDelegate.self)
        let items = try XCTUnwrap(
            bundle.object(forInfoDictionaryKey: "UIApplicationShortcutItems") as? [[String: String]],
            "Expected static UIApplicationShortcutItems in the app bundle Info.plist"
        )

        let typesAndTitles = items.map { item in
            "\(item["UIApplicationShortcutItemType"] ?? "")|\(item["UIApplicationShortcutItemTitle"] ?? "")"
        }

        XCTAssertEqual(
            typesAndTitles,
            [
                "org.openmates.ask|Ask",
                "org.openmates.ask-about-photo|Ask About Photo",
                "org.openmates.search|Search",
                "org.openmates.incognito-ask|Incognito Ask"
            ]
        )

        XCTAssertEqual(
            bundle.object(forInfoDictionaryKey: "NSCameraUsageDescription") as? String,
            "OpenMates uses the camera when you choose to attach a photo to a chat."
        )
        XCTAssertEqual(
            bundle.object(forInfoDictionaryKey: "NSPhotoLibraryUsageDescription") as? String,
            "OpenMates uses your photo library when you choose an image to attach to a chat."
        )
        #endif
    }

    func testMacMenuBarQuickCaptureUsesGlyphOnlyStatusIcon() {
        #if os(macOS)
        XCTAssertFalse(
            OpenMatesMenuBarGlyph.includesAppIconContainerForTests,
            "The menu bar icon must be the OpenMates person/sparkles glyph only, not the full blue app icon container."
        )
        #endif
    }

    func testMacMenuBarQuickCaptureRefreshesOfflineAuthenticatedSessionBeforeSend() {
        #if os(macOS)
        XCTAssertTrue(
            MacMenuBarQuickCaptureAuthPolicy.shouldRefreshSession(
                state: .authenticated,
                hasCurrentUser: true,
                hasWebSocketToken: false
            ),
            "Quick Capture must refresh the shared native session when the main app restored an authenticated user without a WebSocket token."
        )
        XCTAssertFalse(
            MacMenuBarQuickCaptureAuthPolicy.shouldRefreshSession(
                state: .authenticated,
                hasCurrentUser: true,
                hasWebSocketToken: true
            )
        )
        XCTAssertFalse(MacMenuBarQuickCaptureAuthPolicy.canUseQuickCapture(state: .unauthenticated))
        XCTAssertTrue(MacMenuBarQuickCaptureAuthPolicy.canUseQuickCapture(state: .authenticated))
        #endif
    }

    func testQuickActionTitlesResolveForEverySupportedLanguage() async {
        #if os(iOS)
        let manager = LocalizationManager.shared
        for language in SupportedLanguage.allCases {
            await manager.setLanguage(language)
            let titles = [
                AppStrings.quickActionAsk,
                AppStrings.quickActionAskAboutPhoto,
                AppStrings.quickActionIncognitoAsk
            ]
            XCTAssertFalse(
                titles.contains { $0.contains("quick_action") || $0.hasPrefix("activity.") },
                "Expected translated quick action titles for \(language.code), got \(titles)"
            )
        }
        await manager.setLanguage(.en)
        #endif
    }

    func testPinnedAndArchivedChatsMatchSidebarBuckets() {
        let store = ChatStore()
        let pinned = makeChat(id: "pinned", title: "Pinned", isArchived: false, isPinned: true, updatedAt: "2026-01-03T00:00:00Z")
        let visible = makeChat(id: "visible", title: "Visible", isArchived: false, isPinned: false, updatedAt: "2026-01-02T00:00:00Z")
        let archived = makeChat(id: "archived", title: "Archived", isArchived: true, isPinned: false, updatedAt: "2026-01-04T00:00:00Z")

        store.performWithoutPersistence {
            store.upsertChat(visible)
            store.upsertChat(archived)
            store.upsertChat(pinned)
        }

        XCTAssertEqual(store.pinnedChats.map(\.id), ["pinned"])
        XCTAssertEqual(store.unpinnedChats.map(\.id), ["visible"])
    }

    func testChatManagementMergePreservesLocalFlagsWhenSyncPatchOmitsThem() {
        let store = ChatStore()
        let base = makeChat(id: "managed-chat", title: "Managed", isArchived: false, isPinned: true, updatedAt: "2026-01-01T00:00:00Z")
        let patch = Chat(
            id: "managed-chat",
            title: "Managed remote title",
            lastMessageAt: "2026-01-02T00:00:00Z",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-02T00:00:00Z",
            isArchived: nil,
            isPinned: nil,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 2,
            titleV: 2
        )

        store.performWithoutPersistence {
            store.upsertChat(base)
            store.upsertChat(patch)
        }

        let merged = store.chat(for: "managed-chat")
        XCTAssertEqual(merged?.title, "Managed remote title")
        XCTAssertEqual(merged?.isPinned, true)
        XCTAssertEqual(merged?.isArchived, false)
        XCTAssertEqual(merged?.messagesV, 2)
    }

    private func makeChat(
        id: String,
        title: String,
        isArchived: Bool,
        isPinned: Bool,
        updatedAt: String
    ) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: updatedAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: updatedAt,
            isArchived: isArchived,
            isPinned: isPinned,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 1,
            titleV: 1
        )
    }
}
