import XCTest
import UserNotifications
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

@MainActor
final class AppDeepLinkRoutingTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=notifications.workflow-run.run-target
    func testWorkflowCompletionCategoryOpensWithoutInlineReply() throws {
        let categories = PushNotificationManager.notificationCategories()
        let workflow = try XCTUnwrap(categories.first { $0.identifier == "OPENMATES_WORKFLOW_COMPLETED" })
        XCTAssertTrue(workflow.actions.isEmpty, "Workflow completion requires a destination tap, never an inline Reply")
        let chat = try XCTUnwrap(categories.first { $0.identifier == "OPENMATES_CHAT_MESSAGE" })
        XCTAssertEqual(chat.actions.map(\.identifier), ["OPENMATES_REPLY", "OPENMATES_OPEN_CHAT"])
        XCTAssertTrue(chat.actions.first is UNTextInputNotificationAction)
    }

    // contract-test: direct surface=gui.apple assertions=notifications.workflow-run.chat-target,notifications.workflow-run.run-target
    func testWorkflowCompletionLinkKeepsExactRunAndOptionalChatDestination() throws {
        let handler = DeepLinkHandler()
        let host = ServerProfile.current().displayDomain
        let workflow = "11111111-1111-4111-8111-111111111111"
        let run = "22222222-2222-4222-8222-222222222222"
        let chat = "33333333-3333-4333-8333-333333333333"
        let message = "44444444-4444-4444-8444-444444444444"
        let delivery = "55555555-5555-4555-8555-555555555555"
        let base = "https://\(host)/#workflow-id=\(workflow)&workflow-tab=runs&run-id=\(run)"
        let runURL = try XCTUnwrap(URL(string: base))
        XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(runURL, selectedDomain: host))
        handler.handle(url: runURL)
        XCTAssertEqual(handler.pendingWorkflowCompletion?.workflowID, workflow)
        XCTAssertEqual(handler.pendingWorkflowCompletion?.runID, run)
        XCTAssertNil(handler.pendingWorkflowCompletion?.chatID)
        handler.handle(url: try XCTUnwrap(URL(string: base + "&chat-id=\(chat)&message-id=\(message)&delivery-id=\(delivery)")))
        XCTAssertEqual(handler.pendingWorkflowCompletion?.chatID, chat)
        XCTAssertEqual(handler.pendingWorkflowCompletion?.messageID, message)
        XCTAssertEqual(handler.pendingWorkflowCompletion?.deliveryID, delivery)
        XCTAssertNil(handler.pendingChatId, "Pending Vault delivery must be committed before chat navigation")
        handler.clearPending()
        XCTAssertNil(handler.pendingWorkflowCompletion)
        handler.handle(url: try XCTUnwrap(URL(string: "https://foreign.example/#workflow-id=\(workflow)&run-id=\(run)")))
        XCTAssertNil(handler.pendingWorkflowCompletion)
        handler.handle(url: try XCTUnwrap(URL(string: base + "&chat-id=\(chat)")))
        XCTAssertNil(handler.pendingWorkflowCompletion, "Incomplete chat routing cannot bypass delivery persistence")
        XCTAssertNil(handler.pendingChatId, "Malformed completion links cannot become ordinary chat links")
    }

    // contract-test: supporting surface=gui.apple assertions=notifications.workflow-run.chat-target,notifications.workflow-run.run-target
    func testWorkflowCompletionPushRoutingRequiresCompleteOwnerDestination() {
        let workflow = "11111111-1111-4111-8111-111111111111"
        let run = "22222222-2222-4222-8222-222222222222"
        let chat = "33333333-3333-4333-8333-333333333333"
        let message = "44444444-4444-4444-8444-444444444444"
        let delivery = "55555555-5555-4555-8555-555555555555"
        let base = ["workflow_id": workflow, "run_id": run]
        XCTAssertEqual(WorkflowCompletionRoute.parse(base)?.runID, run)
        XCTAssertNil(WorkflowCompletionRoute.parse(base.merging(["chat_id": chat]) { _, new in new }))
        let complete = base.merging(["chat_id": chat, "message_id": message, "delivery_id": delivery]) { _, new in new }
        XCTAssertEqual(WorkflowCompletionRoute.parse(complete)?.deliveryID, delivery)
        XCTAssertNil(WorkflowCompletionRoute.parse(complete.merging(["run_id": "not-a-run"]) { _, new in new }))
    }

    // contract-test: direct surface=gui.apple assertions=notifications.workflow-run.chat-target
    func testCompetingDeviceFallbackRequiresRunOutputAssociation() throws {
        let workflow = "11111111-1111-4111-8111-111111111111"
        let run = "22222222-2222-4222-8222-222222222222"
        let chat = "33333333-3333-4333-8333-333333333333"
        let message = "44444444-4444-4444-8444-444444444444"
        let delivery = "55555555-5555-4555-8555-555555555555"
        let row: [String: Any] = ["id": run, "workflow_id": workflow, "version_id": "version",
            "trigger_type": "schedule", "status": "completed", "node_runs": [[
                "id": "node-run", "run_id": run, "workflow_id": workflow,
                "node_id": "send", "node_type": "send_chat_message", "status": "completed",
                "output_summary": ["delivery_id": delivery, "chat_id": chat, "message_id": message]
            ], [
                "id": "later-node-run", "run_id": run, "workflow_id": workflow,
                "node_id": "send-later", "node_type": "send_chat_message", "status": "completed",
                "output_summary": ["delivery_id": "66666666-6666-4666-8666-666666666666",
                                   "chat_id": chat, "message_id": "77777777-7777-4777-8777-777777777777"]
            ]]]
        let detail = try JSONDecoder().decode(WorkflowRunDetail.self,
            from: JSONSerialization.data(withJSONObject: row))
        let route = WorkflowCompletionRoute(workflowID: workflow, runID: run,
            chatID: chat, messageID: message, deliveryID: delivery)
        XCTAssertTrue(WorkflowCompletionDelivery.matchesCompletedRun(detail, route: route))
        XCTAssertFalse(WorkflowCompletionDelivery.matchesCompletedRun(detail,
            route: WorkflowCompletionRoute(workflowID: workflow, runID: run,
                chatID: chat, messageID: message, deliveryID: UUID().uuidString)))
        XCTAssertFalse(WorkflowCompletionDelivery.matchesCompletedRun(detail,
            route: WorkflowCompletionRoute(workflowID: workflow, runID: UUID().uuidString,
                chatID: chat, messageID: message, deliveryID: delivery)))
        XCTAssertFalse(WorkflowCompletionDelivery.matchesCompletedRun(detail,
            route: WorkflowCompletionRoute(workflowID: workflow, runID: run, chatID: chat,
                messageID: "77777777-7777-4777-8777-777777777777",
                deliveryID: "66666666-6666-4666-8666-666666666666")))
        var retained = row
        retained["node_runs"] = []
        retained["completion_notification"] = ["notification_id": UUID().uuidString,
            "chat_id": chat, "message_id": message, "delivery_id": delivery]
        let retainedDetail = try JSONDecoder().decode(WorkflowRunDetail.self,
            from: JSONSerialization.data(withJSONObject: retained))
        XCTAssertTrue(WorkflowCompletionDelivery.matchesCompletedRun(retainedDetail, route: route),
                      "Pinned owner routing survives pruned run content")
        retained["completion_notification"] = ["notification_id": UUID().uuidString,
            "chat_id": chat, "message_id": message, "delivery_id": UUID().uuidString]
        let mismatched = try JSONDecoder().decode(WorkflowRunDetail.self,
            from: JSONSerialization.data(withJSONObject: retained))
        XCTAssertFalse(WorkflowCompletionDelivery.matchesCompletedRun(mismatched, route: route))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.cold.shared-team-authorized,settings-ui.shell.lifecycle-and-routing
    func testTeamStorageEmailDestinationRetainsExactTeamAndAuthenticationGate() throws {
        let handler = DeepLinkHandler()
        let host = ServerConfiguration.current.selectedDomain
        let teamID = "00000000-0000-4000-8000-000000000132"
        // Exact first-party link issued by team_storage_billing_tasks._deliver_warning.
        let url = try XCTUnwrap(URL(string: "https://\(host)/#settings/teams/\(teamID)"))
        XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: host))
        handler.handle(url: url)
        XCTAssertEqual(handler.pendingSettingsPath, "teams/" + teamID)
        let route = SettingsDeepLinkRoute(try XCTUnwrap(handler.pendingSettingsPath))
        XCTAssertEqual(route.topLevel, "teams"); XCTAssertEqual(route.childID, teamID)
        XCTAssertTrue(route.hasNativeChild); XCTAssertTrue(route.requiresAuthentication)
        XCTAssertFalse(route.canOpen(authenticated: false, admin: false))
        XCTAssertTrue(route.canOpen(authenticated: true, admin: false))
        XCTAssertNil(handler.pendingChatId); XCTAssertNil(handler.pendingMessageText)
        XCTAssertNil(handler.pendingAppId)
        // Settings membership/billing role checks remain in the account-fenced
        // controller/service, rather than granting authority from this URL.
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.cold.shared-team-authorized,settings-ui.shell.lifecycle-and-routing
    func testTeamStorageRoutingTracksSuccessiveTeamIDsAndRejectsForeignHost() throws {
        let handler = DeepLinkHandler()
        let host = ServerConfiguration.current.selectedDomain
        for teamID in ["00000000-0000-4000-8000-000000000132", "00000000-0000-4000-8000-000000000133"] {
            handler.handle(url: try XCTUnwrap(URL(string: "https://\(host)/#settings/teams/\(teamID)")))
            XCTAssertEqual(SettingsDeepLinkRoute(try XCTUnwrap(handler.pendingSettingsPath)).childID, teamID)
            handler.clearPending()
            XCTAssertNil(handler.pendingSettingsPath)
        }
        let foreign = try XCTUnwrap(URL(string: "https://foreign.example/#settings/teams/00000000-0000-4000-8000-000000000132"))
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(foreign, selectedDomain: host))
        handler.handle(url: foreign)
        XCTAssertNil(handler.pendingSettingsPath)
        XCTAssertNil(handler.pendingSharedBrowserURL)
    }

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
