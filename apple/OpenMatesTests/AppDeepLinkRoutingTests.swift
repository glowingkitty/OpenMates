import XCTest
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

@MainActor
final class AppDeepLinkRoutingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.links,tasks.detail.embed-responsive
    func testIssuedWidgetURLRetainsColdRequestAndCreatesFreshIdentityForRepeatedTaskTap() throws {
        let handler = DeepLinkHandler()
        let id = "00000000-0000-4000-8000-000000000001"
        let url = try XCTUnwrap(WidgetTasksLinks.task(id))
        XCTAssertEqual(url.absoluteString, "openmates://task/\(id)")
        handler.handle(url: url)
        let cold = try XCTUnwrap(handler.pendingTaskRequest)
        XCTAssertEqual(cold.taskID, id)
        XCTAssertFalse(handler.pendingTasksWorkspace)
        XCTAssertFalse(handler.pendingNewTask)
        let store = TasksWorkspaceStore()
        store.installPreview(widgetTaskID: id)
        store.openTaskWhenAvailable(cold.taskID)
        XCTAssertEqual(store.selectedTask?.id, id)
        XCTAssertNil(store.presentedTaskID, "Opening must not acknowledge a fullscreen reader before it mounts")
        store.taskDetailDidAppear(id)
        XCTAssertEqual(store.presentedTaskID, id)
        store.closeDetail()
        handler.handle(url: url)
        let repeatTap = try XCTUnwrap(handler.pendingTaskRequest)
        XCTAssertNotEqual(repeatTap.id, cold.id)
        store.openTaskWhenAvailable(repeatTap.taskID)
        XCTAssertEqual(store.selectedTask?.id, id)
        handler.handle(url: WidgetTasksLinks.newTask)
        XCTAssertNil(handler.pendingTaskRequest)
        XCTAssertNil(handler.pendingTaskID)
        XCTAssertTrue(handler.pendingNewTask)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.links,apple-workspaces.isolation
    func testPendingWidgetTaskCannotApplyAcrossResetOrPretendItsReaderMounted() {
        let store = TasksWorkspaceStore()
        let id = "00000000-0000-4000-8000-000000000001"
        store.openTaskWhenAvailable(id)
        XCTAssertNil(store.selectedTaskID)
        store.installPreview(accountID: "other-synthetic-owner", widgetTaskID: id)
        XCTAssertNil(store.selectedTaskID, "A new account/load generation clears an unfulfilled widget destination")
        store.taskDetailDidAppear(id)
        XCTAssertNil(store.presentedTaskID)
        store.openTaskWhenAvailable(id)
        store.reset(accountID: nil)
        XCTAssertNil(store.selectedTaskID)
        XCTAssertNil(store.presentedTaskID)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.links,apple-workspaces.isolation
    func testWidgetDestinationWaitsForMatchingInventoryAndReplacementWins() {
        let firstID = "00000000-0000-4000-8000-000000000001"
        let secondID = "00000000-0000-4000-8000-000000000002"
        let firstInventory = TasksWorkspaceStore()
        firstInventory.installPreview(widgetTaskID: firstID)
        let secondInventory = TasksWorkspaceStore()
        secondInventory.installPreview(widgetTaskID: secondID)
        let store = TasksWorkspaceStore()
        store.installPreview()
        let generation = store.debugLoadGeneration
        store.openTaskWhenAvailable(firstID)
        store.openTaskWhenAvailable(secondID)
        store.debugCompleteWidgetInventory(firstInventory.boardItems, generation: generation)
        XCTAssertNil(store.selectedTaskID, "The older inventory cannot replace the newest widget destination")
        store.debugCompleteWidgetInventory(secondInventory.boardItems, generation: generation)
        XCTAssertEqual(store.selectedTask?.id, secondID)
        XCTAssertNil(store.presentedTaskID)
        store.closeDetail()
        store.openTaskWhenAvailable(firstID)
        store.cancelPendingTaskDetail()
        store.debugCompleteWidgetInventory(firstInventory.boardItems, generation: generation)
        XCTAssertNil(store.selectedTaskID, "Closing or replacing the route cancels a pending destination")
        store.installPreview()
        store.openTaskWhenAvailable(firstID)
        store.debugCompleteWidgetInventory(firstInventory.boardItems, generation: generation)
        XCTAssertNil(store.selectedTaskID, "A stale load receipt cannot fulfill a newer context")
    }

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

    // contract-test: supporting surface=gui.apple assertions=focus-modes.history-events,focus-modes.history-side-effects,settings-ui.shell.lifecycle-and-routing
    func testCatalogFocusHistorySettingsLinkPreservesExactNativeDetailWithoutActivation() throws {
        let handler = DeepLinkHandler()
        for path in ["apps/jobs/focus/career_insights", "apps/weather/focus/travel_weather"] {
            handler.handle(url: try XCTUnwrap(URL(string: "openmates://settings/" + path)))
            let route = SettingsDeepLinkRoute(try XCTUnwrap(handler.pendingSettingsPath))
            XCTAssertEqual(route.path, path)
            XCTAssertTrue(route.isCatalogFocusDetail)
            XCTAssertTrue(route.hasNativeChild)
            XCTAssertTrue(route.canOpen(authenticated: false, admin: false))
            XCTAssertFalse(route.isMemoriesDiscovery)
            XCTAssertNil(route.memoryRoute)
            XCTAssertNil(handler.pendingAppsPath, "History opens settings rather than activating an App workspace")
            XCTAssertNil(handler.pendingChatId)
            XCTAssertNil(handler.pendingMessageText)
            handler.clearPending()
        }
        #if DEBUG
        XCTAssertEqual(DevFocusPhaseFixture.event().detailPath, "apps/weather/focus/travel_weather",
                       "The synthetic notice must target the mode exposed by the synthetic App catalog")
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.history-side-effects,settings-ui.shell.lifecycle-and-routing
    func testCatalogFocusHistorySettingsRouteRejectsMalformedAndUnsupportedChildren() {
        for path in ["apps", "apps/jobs", "apps/jobs/skills/search", "apps/jobs/focus",
                     "apps/jobs/focus/career_insights/extra", "apps/jobs//focus/career_insights",
                     "apps/jobs/focus/../career_insights", "apps/jobs/focus/%2Fforeign",
                     "apps/JOBS/focus/career_insights", "apps/jobs/focus-modes/career_insights"] {
            let route = SettingsDeepLinkRoute(path)
            XCTAssertFalse(route.isCatalogFocusDetail, path)
            XCTAssertFalse(route.hasNativeChild, path)
        }
        XCTAssertTrue(SettingsDeepLinkRoute("apps/all").hasNativeChild)
        XCTAssertTrue(SettingsDeepLinkRoute("apps/jobs/settings_memories/profile").hasNativeChild)
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

    // contract-test: supporting surface=gui.apple assertions=apple-controls.project,apple-controls.workflow
    func testSpecificProjectAndWorkflowLinksDoNotAlsoRequestWorkspace() throws {
        let handler = DeepLinkHandler(), id = "11111111-1111-4111-8111-111111111111"
        handler.handle(url: try XCTUnwrap(URL(string: "openmates://projects/\(id)")))
        XCTAssertEqual(handler.pendingProjectID, id)
        XCTAssertFalse(handler.pendingProjectsWorkspace)
        XCTAssertNil(handler.pendingWorkflowID)
        handler.handle(url: try XCTUnwrap(URL(string: "openmates://workflows/\(id)")))
        XCTAssertEqual(handler.pendingWorkflowID, id)
        XCTAssertFalse(handler.pendingWorkflowsWorkspace)
        XCTAssertNil(handler.pendingProjectID)
        handler.clearPending()
        XCTAssertNil(handler.pendingProjectID)
        XCTAssertNil(handler.pendingWorkflowID)
        XCTAssertFalse(handler.pendingProjectsWorkspace)
        XCTAssertFalse(handler.pendingWorkflowsWorkspace)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-controls.project,apple-controls.workflow
    func testAbsentOrInvalidProjectAndWorkflowGUIDsOpenOnlyTheirWorkspace() throws {
        let handler = DeepLinkHandler(), id = "11111111-1111-4111-8111-111111111111"
        for host in ["projects", "workflows"] {
            for suffix in ["", "/not-a-guid", "/\(id)/extra"] {
                handler.handle(url: try XCTUnwrap(URL(string: "openmates://projects/\(id)")))
                handler.handle(url: try XCTUnwrap(URL(string: "openmates://\(host)\(suffix)")))
                XCTAssertNil(handler.pendingProjectID)
                XCTAssertNil(handler.pendingWorkflowID)
                XCTAssertEqual(handler.pendingProjectsWorkspace, host == "projects")
                XCTAssertEqual(handler.pendingWorkflowsWorkspace, host == "workflows")
                handler.clearPending()
                XCTAssertFalse(handler.pendingProjectsWorkspace)
                XCTAssertFalse(handler.pendingWorkflowsWorkspace)
            }
        }
    }
}
