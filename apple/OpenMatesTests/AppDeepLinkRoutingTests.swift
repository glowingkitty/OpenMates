import XCTest
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

@MainActor
final class AppDeepLinkRoutingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testWorkflowWidgetRouteIsTypedBeforeGenericOwnerRoutingAndClearsOnReplacement() throws {
        let handler = DeepLinkHandler()
        let owner = String(repeating: "a", count: 64)
        let request = UUID()
        let url = try XCTUnwrap(WidgetWorkflowsLinks.run("workflow-synthetic", owner: owner, teamID: "team-synthetic", requestID: request))
        handler.handle(url: url)
        XCTAssertEqual(handler.pendingWorkflowWidgetRun?.workflowID, "workflow-synthetic")
        XCTAssertEqual(handler.pendingWorkflowWidgetRun?.requestID, request)
        XCTAssertNil(handler.pendingActiveChatsWidgetLink)
        XCTAssertNil(handler.pendingChatId)
        handler.handle(url: try XCTUnwrap(URL(string: "openmates://run-workflow/forged?owner=bad&request=\(request)")))
        XCTAssertNil(handler.pendingWorkflowWidgetRun)
        XCTAssertNil(handler.pendingActiveChatsWidgetLink)
        handler.handle(url: try XCTUnwrap(URL(string: "openmates://workflows")))
        XCTAssertTrue(handler.pendingWorkflowsWorkspace)
        handler.clearPending()
        XCTAssertFalse(handler.pendingWorkflowsWorkspace)
        XCTAssertNil(handler.pendingWorkflowWidgetRun)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testNewTaskDeepLinksRequestComposerWithoutNewChatOrDispatch() throws {
        let handler = DeepLinkHandler()
        let host = ServerProfile.current().displayDomain
        for value in ["openmates://new-task", "openmates://newtask", "https://\(host)/new-task", "https://\(host)/#new-task"] {
            let url = try XCTUnwrap(URL(string: value))
            XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: host))
            handler.handle(url: url)
            XCTAssertTrue(handler.pendingNewTask)
            XCTAssertFalse(handler.pendingNewChat)
            XCTAssertNil(handler.pendingMessageText)
            XCTAssertNil(handler.pendingChatId)
            handler.clearPending()
            XCTAssertFalse(handler.pendingNewTask)
        }
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(
            try XCTUnwrap(URL(string: "https://foreign.example/new-task")), selectedDomain: host))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts,apple-tasks-widget.links
    func testTasksWidgetWorkspaceLinksDoNotRequestCreationOrFocus() throws {
        let handler = DeepLinkHandler()
        let host = ServerProfile.current().displayDomain
        for value in ["openmates://tasks", "https://\(host)/tasks", "https://\(host)/#tasks"] {
            let url = try XCTUnwrap(URL(string: value))
            XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: host))
            handler.handle(url: url)
            XCTAssertTrue(handler.pendingTasksWorkspace)
            XCTAssertFalse(handler.pendingNewTask)
            XCTAssertNil(handler.pendingTaskID)
            handler.clearPending()
            XCTAssertFalse(handler.pendingTasksWorkspace)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts,apple-tasks-widget.links
    func testWidgetTaskLinkRequiresValidIdentifierAndClearsConsumedDestination() throws {
        let handler = DeepLinkHandler()
        let host = ServerProfile.current().displayDomain
        let id = "00000000-0000-0000-0000-000000000001"
        for value in ["openmates://task/\(id)", "https://\(host)/task/\(id)", "https://\(host)/#task-id=\(id)"] {
            handler.handle(url: try XCTUnwrap(URL(string: value)))
            XCTAssertEqual(handler.pendingTaskID, id)
            XCTAssertFalse(handler.pendingNewTask)
            handler.clearPending()
            XCTAssertNil(handler.pendingTaskID)
        }
        for value in ["openmates://task/not-a-task", "openmates://task/\(id)/extra", "https://foreign.example/task/\(id)"] {
            handler.handle(url: try XCTUnwrap(URL(string: value)))
            XCTAssertNil(handler.pendingTaskID)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apps.navigation.hash-and-forwarding
    func testAppsRoutesPreserveAppAndSkillPathAndSelectedServer() throws {
        let handler = DeepLinkHandler()
        let host = ServerProfile.current().displayDomain
        for (suffix, expected) in [("", ""), ("/ai", "ai"), ("/ai/ask", "ai/ask")] {
            for value in ["openmates://apps\(suffix)", "https://\(host)/apps\(suffix)", "https://\(host)/#apps\(suffix)"] {
                let url = try XCTUnwrap(URL(string: value))
                XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: host))
                handler.handle(url: url)
                XCTAssertEqual(handler.pendingAppsPath, expected)
                XCTAssertNil(handler.pendingAppId)
                handler.clearPending()
                XCTAssertNil(handler.pendingAppsPath)
            }
        }
        handler.handle(url: try XCTUnwrap(URL(string: "openmates://app/ai")))
        XCTAssertEqual(handler.pendingAppId, "ai", "Keep legacy app detail routing")
        handler.clearPending()
        handler.handle(url: try XCTUnwrap(URL(string: "https://foreign.example/apps/ai")))
        XCTAssertNil(handler.pendingAppsPath)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testNewTaskQuickActionRemainsPendingUntilConsumed() {
        // The live app host consumes singleton notifications synchronously.
        // Exercise the same router with an isolated bus and pending slot.
        let center = AppQuickActionCenter(notificationCenter: NotificationCenter())
        center.perform(.newTask)
        XCTAssertEqual(center.consumePendingAction(), .newTask)
        XCTAssertNil(center.consumePendingAction())
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testQuickActionClearingOnlyConsumesTheMatchingPendingAction() {
        let center = AppQuickActionCenter(notificationCenter: NotificationCenter())
        center.perform(.ask)
        center.clearPendingAction(.newTask)
        XCTAssertEqual(center.consumePendingAction(), .ask,
            "Clearing a New task notification must preserve another pending destination")
        XCTAssertNil(center.consumePendingAction())
        center.perform(.newTask)
        center.clearPendingAction(.newTask)
        XCTAssertNil(center.consumePendingAction(), "An acknowledged action is consumed exactly once")
    }

    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testNewTaskIsAVisibleHomeScreenShortcutAndDecodesToExactAction() throws {
        let item = try XCTUnwrap(AppQuickAction.shortcutItems.first)
        XCTAssertEqual(item.type, AppQuickAction.newTaskType)
        XCTAssertEqual(item.localizedTitle, AppStrings.tasksNew)
        XCTAssertEqual(AppQuickAction(shortcutItem: item), .newTask)
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testEncryptedChatShareUsesNativeRecipientWithoutOwnerRouting() throws {
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            XCTFail("A long chat share must not use short-link resolution")
            throw ShareLinkCryptoError.invalidShortURL
        })
        for host in ["openmates.org", "app.openmates.org", "app.dev.openmates.org"] {
            let url = try XCTUnwrap(URL(string: "https://\(host)/share/chat/synthetic_shared#key=synthetic_blob&messageid=synthetic_message"))
            XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: ServerProfile.current().displayDomain))
            handler.handle(url: url)
            XCTAssertEqual(handler.pendingSharedChatURL, url)
            XCTAssertNil(handler.pendingSharedBrowserURL)
            XCTAssertNil(handler.pendingChatId)
            XCTAssertNil(handler.pendingShareChatId)
            XCTAssertNil(handler.shortLinkResolutionTask)
            handler.clearPending()
            XCTAssertNil(handler.pendingSharedChatURL)
        }
        for url in ["https://app.dev.openmates.org.evil.example/share/chat/x#key=x",
                    "http://app.dev.openmates.org/share/chat/x#key=x",
                    "https://user:secret@app.dev.openmates.org/share/chat/x#key=x"] {
            XCTAssertFalse(DeepLinkHandler.isNativeChatShareURL(try XCTUnwrap(URL(string: url))))
        }
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageLinkPrefillsDraftWithoutSendingAndSettingsRemainNative() throws {
        let host = ServerProfile.current().displayDomain
        let handler = DeepLinkHandler()
        let message = try XCTUnwrap(URL(string: "https://\(host)/#message=Compare%20API%20costs%20%26%20subscriptions"))
        XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(message, selectedDomain: host))
        handler.handle(url: message)
        XCTAssertEqual(handler.pendingMessageText, "Compare API costs & subscriptions")
        XCTAssertFalse(handler.pendingNewChat)
        handler.clearPending()
        handler.handle(url: try XCTUnwrap(URL(string: "https://\(host)/#settings/privacy")))
        XCTAssertEqual(handler.pendingSettingsPath, "privacy")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMarketingDocsAndForeignProfilesRetainWebsiteRouting() throws {
        for path in ["/news", "/docs/getting-started", "/privacy"] {
            let url = try XCTUnwrap(URL(string: "https://app.dev.openmates.org\(path)"))
            XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: "app.dev.openmates.org"))
        }
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(
            try XCTUnwrap(URL(string: "https://app.openmates.org/#chat-id=synthetic")), selectedDomain: "app.dev.openmates.org"))
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(
            try XCTUnwrap(URL(string: "https://app.dev.openmates.org.evil.example/#message=hello")), selectedDomain: "app.dev.openmates.org"))
    }
}
