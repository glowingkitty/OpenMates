// Focused, account-free interaction coverage for the isolated preview host.
// Every scenario launches production components with synthetic fixture state.
// No test account, backend, notification injector, or saved draft is required.
// These checks prove local interaction wiring; visual parity still requires a
// rendered comparison against each registry URL and user approval of the web UI.

import XCTest
#if os(iOS)
import UIKit
#endif

@MainActor
final class DevComponentPreviewUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    override func tearDownWithError() throws {
        if let testRun, testRun.failureCount > 0 {
            attachScreenshot("Component preview failure — \(name)")
        }
        try super.tearDownWithError()
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testNotificationStackShowsThreeCardsAndRevealsRetainedNoticeAfterDismiss() {
        let app = launch(component: "notification", variant: "stack")
        let dismiss = app.buttons["notification-dismiss"]
        XCTAssertTrue(dismiss.waitForExistence(timeout: 10))
        XCTAssertTrue(dismiss.isHittable)
        XCTAssertTrue(app.staticTexts["Changes saved"].exists)
        attachScreenshot("Production three-card notification stack")
        dismiss.tap()
        XCTAssertTrue(app.staticTexts["Reconnecting..."].firstMatch.waitForExistence(timeout: 3))
        XCTAssertTrue(dismiss.isHittable)
        attachScreenshot("Dismissed success reveals existing processing connection")
        dismiss.tap()
        XCTAssertTrue(app.staticTexts["First notice"].waitForExistence(timeout: 3))
        XCTAssertTrue(dismiss.isHittable)
        XCTAssertTrue(dismiss.isEnabled, "A promoted retained card must enable its real dismiss button")
        dismiss.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: dismiss)
        waitForExpectations(timeout: 3)
        XCTAssertFalse(app.staticTexts["First notice"].exists)
        XCTAssertFalse(element(app, "notification").exists, "All three production cards must be removed")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testNotificationCardRendersAndDismissesProductionControl() {
        let app = launch(component: "notification", variant: "connection")
        let card = element(app, "notification")
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertGreaterThanOrEqual(card.frame.height, 90)
        XCTAssertLessThanOrEqual(card.frame.width, 430)
        let dismiss = app.buttons["notification-dismiss"]
        XCTAssertTrue(dismiss.isHittable)
        XCTAssertTrue(element(app, "notification-activity").exists)
        attachScreenshot("Production reconnect notification cloud card and activity")
        dismiss.tap()
        let removed = NSPredicate(format: "exists == false")
        expectation(for: removed, evaluatedWith: card)
        waitForExpectations(timeout: 3)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testNotificationCardProgressAndSuccessLayout() {
        let app = launch(component: "notification", variant: "progress")
        let card = element(app, "notification")
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Your settings have been updated successfully."].exists)
        let progress = element(app, "notification-progress")
        XCTAssertTrue(progress.exists)
        XCTAssertEqual(progress.frame.height, 4, accuracy: 0.5)
        let initialWidth = progress.frame.width
        XCTAssertGreaterThan(initialWidth, 0)
        XCTAssertLessThan(initialWidth, card.frame.width,
                          "The duration bar must expose its partially filled width")
        XCTAssertEqual(progress.frame.minX, card.frame.minX, accuracy: 1)
        let fillAdvances = NSPredicate { _, _ in
            progress.frame.width > initialWidth + card.frame.width * 0.05
                && progress.frame.width <= card.frame.width + 1
        }
        expectation(for: fillAdvances, evaluatedWith: progress)
        waitForExpectations(timeout: 3)
        XCTAssertEqual(progress.frame.maxY, card.frame.maxY, accuracy: 1)
        XCTAssertTrue(app.buttons["notification-dismiss"].isHittable)
        attachScreenshot("Production success notification with timed progress")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testBerlinResultsMapFitsCityMarkersAndKeepsSelectionCalendarFilters() {
        let app = launch(component: "message", variant: "results-berlin-map")
        let map = element(app, "embeds-results-view-panel-map")
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        let markers = app.buttons.matching(identifier: "embeds-map-view-endpoint-marker")
        XCTAssertEqual(markers.count, 3)
        let cityMarkers = markers.allElementsBoundByIndex
        cityMarkers.forEach {
            XCTAssertTrue($0.isHittable, "The city camera must expose all Berlin markers")
            XCTAssertTrue(map.frame.contains($0.frame), "Pins must fit completely inside the map")
        }
        let initialSpread = cityMarkers.map { $0.frame.midX }.max()! - cityMarkers.map { $0.frame.midX }.min()!
        XCTAssertGreaterThan(initialSpread, 70, "Nearby venues must be visibly separated at city scale")
        attachScreenshot("Berlin events city map with Apple Maps tiles")

        let zoomOut = app.buttons["embeds-map-view-zoom-out"]
        XCTAssertTrue(zoomOut.isHittable)
        zoomOut.tap()
        let spreadShrinks = NSPredicate { _, _ in
            let frames = markers.allElementsBoundByIndex.map { $0.frame.midX }
            guard let first = frames.min(), let last = frames.max() else { return false }
            return last - first < initialSpread * 0.8
        }
        expectation(for: spreadShrinks, evaluatedWith: app)
        waitForExpectations(timeout: 5)
        app.buttons["embeds-map-view-zoom-in"].tap()

        markers.allElementsBoundByIndex.first(where: { $0.isHittable })?.tap()
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 1,
                       "A map pin must select its actual event card")
        let showAll = app.buttons["embeds-map-view-show-all"]
        XCTAssertTrue(showAll.isHittable)
        showAll.tap()
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 3)

        app.buttons["embeds-results-view-tab-calendar"].tap()
        XCTAssertTrue(element(app, "embeds-results-view-panel-calendar").waitForExistence(timeout: 5))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-results-view-calendar-item").count, 3)
        attachScreenshot("Berlin events calendar after map selection")
        app.buttons["embeds-map-view-filter-button"].tap()
        XCTAssertTrue(element(app, "embeds-map-view-filter-price").exists)
        XCTAssertTrue(element(app, "embeds-map-view-filter-providers").exists)
        app.buttons["embeds-map-view-filter-button"].tap()
        app.buttons["embeds-results-view-tab-map"].tap()
        XCTAssertEqual(app.buttons.matching(identifier: "embeds-map-view-endpoint-marker").count, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testComposerEditsSubmitsAndRemovesLocalAttachment() throws {
        let app = launch(component: "composer", variant: "filled", props: ["text": "Synthetic preview draft"])
        let editor = element(app, "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        editor.typeText(" edited")
        XCTAssertTrue((editor.value as? String)?.contains("edited") == true)
        attachScreenshot("Production composer focused with edited text")
        app.buttons["send-button"].tap()
        assertAction("submitted-locally", in: app)

        app.terminate()
        let attachmentApp = launch(component: "composer", variant: "attachment")
        // Use the real translated control so missing catalog keys fail visibly.
        let remove = attachmentApp.buttons["Remove"].firstMatch
        XCTAssertTrue(remove.waitForExistence(timeout: 10))
        remove.tap()
        assertAction("attachment-removed", in: attachmentApp)
        XCTAssertFalse(remove.exists)
        XCTAssertFalse((element(attachmentApp, "message-editor").value as? String)?.contains("Synthetic preview draft") == true,
                       "Launching another fixture must not restore an earlier preview draft")
        attachScreenshot("Composer local attachment removed")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility
    func testComposerAttachmentMenuOpensAndSelectsLocalFileFixture() throws {
        let app = launch(component: "composer", variant: "focused")
        let toggle = app.buttons["composer-attachment-toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 10))
        XCTAssertTrue(toggle.isHittable)
        toggle.tap()

        for identifier in ["composer-attachment-drawing", "composer-attachment-location", "composer-attachment-camera", "composer-attachment-files"] {
            let action = app.buttons[identifier]
            XCTAssertTrue(action.waitForExistence(timeout: 5), "Missing menu action: \(identifier)")
            XCTAssertTrue(action.isHittable, "Menu action is covered: \(identifier)")
        }
        attachScreenshot("Isolated composer attachment menu open")

        app.buttons["composer-attachment-files"].tap()
        assertAction("attachment-added", in: app)
        XCTAssertFalse(app.buttons["composer-attachment-files"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageThinkingExpandsAndCollapses() {
        let app = launch(component: "message", variant: "thinking")
        let expand = app.buttons["Expand AI reasoning"]
        XCTAssertTrue(expand.waitForExistence(timeout: 10))
        expand.tap()
        let collapse = app.buttons["Collapse AI reasoning"]
        XCTAssertTrue(collapse.waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@",
                         "The user wants to migrate from Svelte 4 to Svelte 5.")).firstMatch.exists)
        attachScreenshot("Production message thinking expanded")
        collapse.tap()
        XCTAssertTrue(expand.waitForExistence(timeout: 3))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantResultsViewShowsMapCalendarAndDerivedFilters() {
        let app = launch(component: "message", variant: "results-map")
        let results = element(app, "embeds-map-view")
        XCTAssertTrue(results.waitForExistence(timeout: 10))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 5,
                       "The travel source must expand to all five web preview connection children")
        XCTAssertTrue(app.staticTexts["EUR 636"].exists, "The native preview must expose a flight price")
        XCTAssertTrue(app.staticTexts["Berlin (BER) → Bangkok (BKK)"].exists,
                      "The native preview must render the connection route instead of a generic Place card")
        XCTAssertTrue(element(app, "embeds-results-view-panel-map").exists)
        attachScreenshot("Assistant results map and cards")

        let calendar = app.buttons["embeds-results-view-tab-calendar"]
        XCTAssertTrue(calendar.isHittable)
        calendar.tap()
        XCTAssertTrue(element(app, "embeds-results-view-panel-calendar").waitForExistence(timeout: 5))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-results-view-calendar-day").count, 7)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-results-view-calendar-item").count, 10,
                       "Five overnight flights must render on both departure and arrival days")
        let visibleCalendarItem = app.descendants(matching: .any)
            .matching(identifier: "embeds-results-view-calendar-item")
            .allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertNotNil(visibleCalendarItem,
                        "The initial calendar viewport should show an overnight connection segment")
        if let visibleCalendarItem {
            XCTAssertGreaterThan(visibleCalendarItem.frame.height, 46,
                                 "An overnight connection spans more than one hourly time row")
        }
        attachScreenshot("Assistant results calendar week")

        let map = app.buttons["embeds-results-view-tab-map"]
        XCTAssertTrue(map.isHittable)
        map.tap()
        XCTAssertTrue(element(app, "embeds-results-view-panel-map").waitForExistence(timeout: 5))

        let filter = app.buttons["embeds-map-view-filter-button"]
        XCTAssertTrue(filter.isHittable)
        filter.tap()
        XCTAssertTrue(element(app, "embeds-map-view-filter-menu").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "embeds-map-view-filter-price").exists,
                      "Only facets exposed by the referenced embeds should appear")
        XCTAssertTrue(element(app, "embeds-map-view-filter-transferMinutes").exists,
                      "Layover durations nested under travel legs must become a derived filter")
        let lowerPrice = element(app, "embeds-map-view-filter-price-lower")
        let upperPrice = element(app, "embeds-map-view-filter-price-upper")
        let priceRail = element(app, "embeds-map-view-filter-price-rail")
        let filterScroll = element(app, "embeds-map-view-filter-scroll")
        for _ in 0..<4 where !lowerPrice.isHittable || !upperPrice.isHittable { filterScroll.swipeUp() }
        XCTAssertTrue(lowerPrice.isHittable)
        XCTAssertTrue(upperPrice.isHittable)
        XCTAssertTrue(priceRail.exists)
        XCTAssertEqual(lowerPrice.frame.midY, upperPrice.frame.midY, accuracy: 2,
                       "The lower and upper thumbs must share one range rail")
        let lowerBefore = lowerPrice.value as? String
        let upperBefore = upperPrice.value as? String
        lowerPrice.press(forDuration: 0.1, thenDragTo: upperPrice)
        XCTAssertNotEqual(lowerPrice.value as? String, lowerBefore,
                          "Dragging the minimum thumb must move the minimum bound")
        XCTAssertEqual(upperPrice.value as? String, upperBefore,
                       "Dragging the minimum thumb must leave the maximum bound unchanged")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 1)
        let clear = app.buttons["embeds-map-view-clear-filters"]
        for _ in 0..<4 where !clear.isHittable { filterScroll.swipeDown() }
        XCTAssertTrue(clear.isHittable)
        clear.tap()
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 5)
        attachScreenshot("Assistant results derived filter panel")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewVisualSurfaceAtWebPhoneWidth() {
        let app = launch(component: "message", variant: "results-visual")
        let carousel = element(app, "embeds-map-view-carousel")
        XCTAssertTrue(carousel.waitForExistence(timeout: 10))
        XCTAssertEqual(carousel.frame.width, 326, accuracy: 2,
                       "The visual fixture matches the deployed 390-point web preview's 326-point results panel")
        XCTAssertEqual(carousel.frame.minX, 32, accuracy: 2)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-endpoint-marker").count, 2)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-stop-marker").count, 4)
        attachScreenshot("Results map at deployed web phone width")
        app.buttons["embeds-results-view-tab-calendar"].tap()
        XCTAssertTrue(element(app, "embeds-results-view-calendar-week").waitForExistence(timeout: 5))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-results-view-calendar-item").count, 10)
        let highlightedSegments = app.descendants(matching: .any)
            .matching(identifier: "embeds-results-view-calendar-item")
            .allElementsBoundByIndex.filter { ($0.value as? String) == "highlighted" }
        XCTAssertEqual(highlightedSegments.count, 2,
                       "The highlighted connection must retain its accent border across both overnight segments")
        attachScreenshot("Results calendar at deployed web phone width")

        app.buttons["embeds-map-view-filter-button"].tap()
        XCTAssertTrue(element(app, "embeds-map-view-filter-menu").waitForExistence(timeout: 5))
        attachScreenshot("Results filters at deployed web phone width")
        app.buttons["embeds-map-view-filter-button"].tap()
        app.buttons["embeds-results-view-tab-map"].tap()
        app.buttons.matching(identifier: "embeds-map-view-stop-marker").firstMatch.tap()
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 2,
                       "Selecting the shared Doha stop scopes the carousel to its two connections")
        let showAll = app.buttons["embeds-map-view-show-all"]
        showAll.tap()
        XCTAssertTrue(showAll.waitForNonExistence(timeout: 5),
                      "Show all must clear the map selection before the full carousel returns")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "embeds-map-view-card").count, 5)
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.detail.embed-responsive
    func testTasksWorkspaceBoardAndTaskDetailAtWebPhoneWidth() {
        let app = launch(component: "tasks", variant: "default")
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "task-column-backlog").count, 1)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "task-card").count, 6,
                       "Five web preview tasks and one workflow projection must render")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "task-board-plan-card").count, 2)
        XCTAssertTrue(element(app, "task-workspace-composer").exists)
        XCTAssertTrue(app.buttons["task-workspace-mic"].exists)
        attachScreenshot("Tasks workspace deployed web phone fixture")

        let firstTask = app.buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(firstTask.isHittable)
        firstTask.tap()
        XCTAssertTrue(element(app, "task-detail-content").waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Research how expensive hoverboard motors are to carry 2–3 people"].exists)
        XCTAssertTrue(app.buttons["task-detail-report-issue"].exists,
                      "Task detail must expose the shared report-issue action in its header")
        XCTAssertTrue(app.staticTexts["High"].exists,
                      "Native detail must use the deployed preview task priority")
        XCTAssertTrue(element(app, "task-activity").exists)
        let statusSelect = element(app, "task-detail-status-select")
        XCTAssertTrue(statusSelect.isHittable)
        statusSelect.tap()
        let selectedStatus = app.buttons["Backlog"].firstMatch
        XCTAssertTrue(selectedStatus.waitForExistence(timeout: 3))
        selectedStatus.tap()
        let assigneeSelect = element(app, "task-detail-assignee-select")
        XCTAssertTrue(assigneeSelect.isHittable)
        assigneeSelect.tap()
        let selectedAssignee = app.buttons["OpenMates"].firstMatch
        XCTAssertTrue(selectedAssignee.waitForExistence(timeout: 3))
        selectedAssignee.tap()
        attachScreenshot("Tasks detail deployed web phone fixture")
    }

    // contract-test: supporting surface=gui.apple assertions=plans.surface.semantic-parity
    func testPlansWorkspaceBoardAndPlanReviewAtWebPhoneWidth() {
        let app = launch(component: "tasks", variant: "plans")
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "task-card").count, 0)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "task-board-plan-card").count, 2)
        attachScreenshot("Plans workspace deployed web phone fixture")

        let plan = app.buttons["Prepare the OpenMates launch plan"]
        XCTAssertTrue(plan.exists)
        let openPlan = app.buttons.matching(identifier: "task-board-open-plan").firstMatch
        XCTAssertTrue(openPlan.isHittable)
        openPlan.tap()
        XCTAssertTrue(element(app, "plan-detail-page").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "plan-assumptions-section").exists)
        XCTAssertTrue(element(app, "plan-criteria-section").exists)
        attachScreenshot("Plan detail deployed web phone fixture")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.search-scoped
    func testProjectsWorkspaceLandingOverviewAndFilesAtWebPhoneWidth() {
        let landing = launch(component: "projects", variant: "landing")
        XCTAssertTrue(landing.staticTexts["Hey there!"].waitForExistence(timeout: 10))
        let name = landing.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ OR placeholderValue == %@", "project-input-textarea", "Name a new project"
        )).firstMatch
        XCTAssertTrue(name.exists)
        let card = landing.buttons["project-card-preview-project"]
        XCTAssertTrue(card.isHittable)
        attachScreenshot("Projects deployed landing at phone width")
        XCTAssertTrue(name.isHittable)
        name.tap()
        name.typeText("Synthetic preview Project")
        XCTAssertTrue(landing.buttons["project-input-submit"].isHittable)
        XCTAssertEqual(element(landing, "project-input-composer").frame.height, 64, accuracy: 1)
        attachScreenshot("Projects typed composer at phone width")
        landing.buttons["project-input-submit"].tap()
        XCTAssertTrue(element(landing, "project-write-policy-setup").waitForExistence(timeout: 3))
        landing.buttons["Cancel"].tap()
        XCTAssertTrue(element(landing, "project-write-policy-setup").waitForNonExistence(timeout: 5))
        XCTAssertFalse(landing.keyboards.firstMatch.exists)
        XCTAssertTrue(card.isHittable)
        card.tap()
        XCTAssertTrue(landing.buttons["project-header-edit"].waitForExistence(timeout: 5))
        XCTAssertTrue(element(landing, "project-readme-empty").exists)
        attachScreenshot("Projects deployed overview at phone width")
        let create = landing.buttons["project-overview-create"]
        XCTAssertTrue(create.isHittable)
        create.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        let createChat = landing.buttons["project-create-chat"]
        XCTAssertTrue(createChat.waitForExistence(timeout: 3))
        XCTAssertTrue(createChat.isHittable)
        XCTAssertTrue(landing.buttons["project-create-workflow"].isHittable)
        XCTAssertTrue(landing.buttons["project-create-plan"].isHittable)
        attachScreenshot("Projects expanded custom create menu")
        createChat.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        assertAction("opened-chat-preview-project", in: landing)
        landing.buttons["project-tab-files"].tap()
        XCTAssertTrue(landing.textFields["project-files-search"].waitForExistence(timeout: 5))
        XCTAssertEqual(landing.buttons["project-file-select"].frame.height, 41, accuracy: 1)
        XCTAssertTrue(landing.buttons["project-files-view-tile"].isSelected)
        landing.buttons["project-files-view-list"].tap()
        XCTAssertTrue(landing.buttons["project-files-view-list"].isSelected)
        landing.buttons["project-files-view-tile"].tap()
        XCTAssertEqual(landing.buttons.matching(NSPredicate(
            format: "identifier BEGINSWITH %@", "project-folder-")).count, 2)
        XCTAssertTrue(landing.buttons["project-files-sync"].exists)
        attachScreenshot("Projects deployed files at phone width")

        let search = landing.textFields["project-files-search"]
        XCTAssertTrue(search.isHittable)
        search.tap()
        let searchFocused = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "hasKeyboardFocus == true"), object: search
        )
        XCTAssertEqual(XCTWaiter.wait(for: [searchFocused], timeout: 3), .completed)
        search.typeText("architecture")
        XCTAssertTrue(element(landing, "project-item-project-file").waitForExistence(timeout: 3))
        XCTAssertFalse(element(landing, "project-folder-backend").exists)
        attachScreenshot("Projects scoped stored-file search")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testProjectsInspirationCyclesToFeatureAtWebPhoneWidth() {
        let app = launch(component: "projects", variant: "landing")
        let banner = app.buttons["daily-inspiration-card"]
        XCTAssertTrue(banner.waitForExistence(timeout: 10))
        XCTAssertTrue((banner.value as? String ?? "").contains("Start every project"))
        attachScreenshot("Projects inspiration phrase at phone width")

        let featurePhase = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "Project planning tip"),
            object: banner
        )
        XCTAssertEqual(XCTWaiter.wait(for: [featurePhase], timeout: 13), .completed)
        attachScreenshot("Projects inspiration feature at phone width")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.search-scoped
    func testProjectsConnectedSourceAndSidebarAtWebPhoneWidth() {
        let connected = launch(component: "projects", variant: "connectedSource")
        XCTAssertTrue(connected.textFields["project-files-search"].waitForExistence(timeout: 10))
        let source = connected.buttons["project-source-source-preview"]
        let page = connected.scrollViews.firstMatch
        for _ in 0..<3 where !source.isHittable { page.swipeUp() }
        XCTAssertTrue(source.isHittable)
        attachScreenshot("Projects connected source at phone width")
        source.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(element(connected, "project-remote-entry-frontend").waitForExistence(timeout: 5))
        XCTAssertTrue(connected.buttons["project-remote-entry-frontend"].exists)
        attachScreenshot("Projects source browser at phone width")
        let readme = connected.buttons["project-remote-entry-README.md"]
        for _ in 0..<3 where !readme.isHittable { page.swipeUp() }
        XCTAssertTrue(readme.isHittable)
        readme.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(element(connected, "project-remote-file-detail").waitForExistence(timeout: 5))
        XCTAssertTrue(connected.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "A private workspace")).firstMatch.waitForExistence(timeout: 5))
        attachScreenshot("Projects connected README detail")
        connected.terminate()

        let sidebar = launch(component: "projects", variant: "sidebar")
        XCTAssertTrue(element(sidebar, "projects-sidebar").waitForExistence(timeout: 10))
        XCTAssertTrue(sidebar.buttons["project-sidebar-card-preview-project"].exists)
        attachScreenshot("Projects sidebar at phone width")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.search-scoped
    func testProjectsSearchAcrossNestedStoredFilesAndConnectedSource() {
        let app = launch(component: "projects", variant: "largeConnectedSource")
        XCTAssertTrue(app.textFields["project-files-search"].waitForExistence(timeout: 10))
        let search = app.textFields["project-files-search"]
        let page = app.scrollViews.firstMatch
        for _ in 0..<2 where !search.isHittable { page.swipeUp() }
        XCTAssertTrue(search.isHittable)
        search.tap()
        search.typeText("needle")
        XCTAssertTrue(element(app, "project-search-across-heading").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "project-search-current-heading").exists)
        XCTAssertTrue(element(app, "project-search-across-heading").exists)
        let stored = element(app, "project-item-large-stored-nested")
        for _ in 0..<4 where !stored.exists { page.swipeUp() }
        XCTAssertTrue(stored.waitForExistence(timeout: 3))
        let remote = element(app, "project-search-result-remote:source-preview:nested/needle-child.ts")
        for _ in 0..<4 where !remote.exists { page.swipeUp() }
        XCTAssertTrue(remote.waitForExistence(timeout: 3))
        attachScreenshot("Projects deployed cross-folder search at phone width")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testProjectsOverviewAndFilesAtDeployedIPadWidth() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("1376-point Projects reference is an iPad landscape viewport")
        }
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        #endif
        let landing = launch(component: "projects", variant: "landing")
        XCTAssertTrue(landing.buttons["project-card-preview-project"].waitForExistence(timeout: 10))
        XCTAssertTrue(landing.buttons["daily-inspiration-card"].label.contains("Project planning tip"))
        XCTAssertEqual(element(landing, "project-input-composer").frame.height, 64, accuracy: 1)
        attachScreenshot("Projects deployed landing at 1376 by 1032")
        landing.terminate()
        let app = launch(component: "projects", variant: "default")
        XCTAssertEqual(app.windows.firstMatch.frame.width, 1376, accuracy: 6)
        XCTAssertEqual(app.windows.firstMatch.frame.height, 1032, accuracy: 6)
        XCTAssertTrue(app.buttons["project-header-edit"].waitForExistence(timeout: 10))
        let panel = element(app, "project-overview-panel")
        XCTAssertTrue(panel.waitForExistence(timeout: 5))
        XCTAssertEqual(panel.frame.width, 1024, accuracy: 2)
        let more = app.buttons["project-more-button"]
        if !more.exists || !more.isHittable {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Projects wide More control accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        XCTAssertTrue(more.isHittable)
        XCTAssertEqual(more.frame.width, 44, accuracy: 1)
        XCTAssertEqual(more.frame.height, 44, accuracy: 1)
        XCTAssertEqual(more.value as? String, "collapsed")
        more.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["project-menu-settings"].waitForExistence(timeout: 3))
        XCTAssertEqual(more.value as? String, "expanded")
        XCTAssertTrue(app.buttons["project-menu-settings"].isHittable)
        more.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        let create = app.buttons["project-overview-create"]
        XCTAssertTrue(create.isHittable)
        create.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["project-create-workflow"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["project-create-workflow"].isHittable)
        attachScreenshot("Projects deployed overview at 1376 by 1032")
        create.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        app.buttons["project-tab-files"].tap()
        XCTAssertTrue(app.textFields["project-files-search"].waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "project-folder-backend").exists)
        XCTAssertEqual(element(app, "project-files-panel").frame.width, 1024, accuracy: 2)
        let search = app.textFields["project-files-search"]
        let sort = app.buttons["project-files-sort"]
        XCTAssertEqual(search.frame.midY, sort.frame.midY, accuracy: 1,
                       "Wide file count, compact Search and sort share one row")
        XCTAssertLessThanOrEqual(search.frame.width, 81)
        XCTAssertEqual(app.buttons["project-file-select"].frame.midY,
                       app.buttons["project-files-view-tile"].frame.midY, accuracy: 1,
                       "Wide Select and view mode controls share the entries row")
        let filesCreate = app.buttons["project-files-create"]
        XCTAssertTrue(filesCreate.isHittable)
        filesCreate.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["project-create-plan"].waitForExistence(timeout: 3))
        // The expanded Files actions remain in the Project's scrolling content.
        // At this viewport the tray starts near the bottom, so reveal its menu.
        for _ in 0..<3 where !app.buttons["project-create-plan"].isHittable { app.swipeUp() }
        XCTAssertTrue(app.buttons["project-create-plan"].isHittable)
        let chatOption = app.buttons["project-create-chat"]
        let workflowOption = app.buttons["project-create-workflow"]
        let planOption = app.buttons["project-create-plan"]
        for option in [chatOption, workflowOption, planOption] {
            XCTAssertTrue(option.isHittable)
            XCTAssertEqual(option.frame.height, 160, accuracy: 1)
            XCTAssertEqual(option.frame.midY, filesCreate.frame.midY, accuracy: 1,
                           "Wide expanded Create options stay beside the action tray")
        }
        XCTAssertEqual(chatOption.frame.width, workflowOption.frame.width, accuracy: 1)
        XCTAssertEqual(workflowOption.frame.width, planOption.frame.width, accuracy: 1)
        XCTAssertEqual(chatOption.frame.maxX, workflowOption.frame.minX, accuracy: 1)
        XCTAssertEqual(workflowOption.frame.maxX, planOption.frame.minX, accuracy: 1)
        attachScreenshot("Projects expanded Files tray at deployed wide width")
        app.buttons["project-create-plan"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        assertAction("opened-plan-preview-project", in: app)
        attachScreenshot("Projects deployed files at 1376 by 1032")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.workspace.contract-plan-task-check-chain
    func testProjectTasksTabEmbedsLinkedBoardAtWebPhoneWidth() {
        let app = launch(component: "projects", variant: "tasks")
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "project-task-workspace-composer").exists)
        XCTAssertTrue(app.buttons["project-task-workspace-mic"].exists)
        XCTAssertTrue(element(app, "task-board").exists)
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(
            format: "label CONTAINS[c] %@", "Teams feature")).firstMatch.exists)
        XCTAssertFalse(element(app, "project-open-tasks").exists)
        attachScreenshot("Project linked Tasks board at phone width")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantResultsViewDateOnlyAndInvalidReferences() {
        let dateOnly = launch(component: "message", variant: "results-date-only")
        XCTAssertTrue(element(dateOnly, "embeds-map-view").waitForExistence(timeout: 10))
        let week = element(dateOnly, "embeds-results-view-calendar-week")
        XCTAssertTrue(week.waitForExistence(timeout: 5))
        week.swipeLeft()
        XCTAssertTrue(element(dateOnly, "embeds-results-view-calendar-date-only").waitForExistence(timeout: 5),
                      "The Sunday date-only result must appear when the calendar scrolls to its day")
        XCTAssertFalse(element(dateOnly, "embeds-results-view-panel-map").exists)
        attachScreenshot("Assistant date-only results calendar")
        dateOnly.terminate()

        let invalid = launch(component: "message", variant: "results-invalid")
        XCTAssertFalse(element(invalid, "embeds-map-view").exists)
        XCTAssertFalse(element(invalid, "embeds-map-view-card").exists)
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testAssistantSubChatBatchRendersCardsAndOpensChild() {
        let app = launch(component: "message", variant: "sub-chat-batch")
        let carousel = element(app, "sub-chats-carousel")
        XCTAssertTrue(carousel.waitForExistence(timeout: 10))
        let first = app.buttons.matching(identifier: "sub-chat-card").firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        // XCUI's Button frame includes the card's outer shadow. The nominal
        // visual box is the exact 260×188 web mobile CSS card size.
        XCTAssertEqual(first.value as? String, "260x188")
        XCTAssertGreaterThan(first.frame.width, 260)
        XCTAssertTrue(element(app, "sub-chat-status-completed").exists)
        XCTAssertTrue(first.label.contains("Research US egg supply recover"))
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(
            format: "label CONTAINS %@", "sub_chat_batch"
        )).firstMatch.exists, "The internal JSON marker must not appear as a code fence")
        attachScreenshot("Assistant sub-chat batch at phone width")
        first.tap()
        assertAction("opened-sub-chat-preview-egg-supply", in: app)
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,chats.surface.semantic-parity
    func testFollowUpSuggestionsRenderAsRightAlignedQuickSendActions() {
        let app = launch(component: "follow-up-suggestions", variant: "legacy-markup")
        let wrapper = element(app, "suggestions-wrapper")
        XCTAssertTrue(wrapper.waitForExistence(timeout: 10))

        let actions = app.buttons.matching(identifier: "follow-up-suggestion-item")
        XCTAssertEqual(actions.count, 4, "Web limits the visible quick-send list to four unique actions")
        let first = actions.element(boundBy: 0)
        XCTAssertEqual(first.label, "Compare the sources")
        XCTAssertFalse(first.label.contains("[web-search]"))
        XCTAssertFalse(first.label.contains("<strong>"))

        let rightEdges = (0..<actions.count).map { actions.element(boundBy: $0).frame.maxX }
        XCTAssertLessThanOrEqual(
            (rightEdges.max() ?? 0) - (rightEdges.min() ?? 0),
            2,
            "Quick-send actions should share the web list's trailing alignment"
        )
        attachScreenshot("Follow-up quick-send actions")

        XCTAssertTrue(first.isHittable)
        first.tap()
        assertAction("quick-sent-Compare the sources", in: app)
        XCTAssertTrue(first.waitForNonExistence(timeout: 2), "The selected list should fade out immediately")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEmbedPreviewOpensChildAndMinimizesBackToCard() {
        let app = launch(component: "embed-preview")
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        XCTAssertEqual(preview.frame.width, 300, accuracy: 2, "Regular cards retain their web width on phones and tablets")
        XCTAssertEqual(preview.frame.height, 200, accuracy: 2)
        preview.tap()
        let fullscreen = element(app, "dev-preview-embed-fullscreen")
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        waitForEmbedPresentation(app)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        waitForEmbedPresentation(app)
        assertAction("opened-preview-web-search-result-1", in: app)
        let title = app.staticTexts["Top 10 Restaurants in Berlin - Local Guide"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        let websiteBody = element(app, "website-fullscreen-body")
        let description = app.staticTexts["website-description"].firstMatch
        XCTAssertTrue(description.waitForExistence(timeout: 5))
        let bodyWidth = websiteBody.frame.width
        if bodyWidth <= 400 {
            XCTAssertEqual(description.frame.width, bodyWidth - 32, accuracy: 2,
                           "Phone source body must use the rendered web's 16pt side padding")
        }
        XCTAssertFalse(app.buttons["embed-previous"].exists,
                       "The first result has no previous result; its parent is a separate route")
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertTrue(app.staticTexts["Berlin Food Scene: A Complete Guide"].firstMatch.waitForExistence(timeout: 5))
        let previous = app.buttons["embed-previous"]
        XCTAssertTrue(previous.isHittable)
        previous.tap()
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        attachScreenshot("Production child embed fullscreen")
        let minimize = app.buttons["embed-minimize"].firstMatch
        XCTAssertTrue(minimize.isHittable, "Fullscreen controls must remain outside the system status area")
        XCTAssertGreaterThanOrEqual(title.frame.minY, minimize.frame.maxY,
                                    "The embed title must appear below the fullscreen controls")
        minimize.tap()
        XCTAssertTrue(child.waitForExistence(timeout: 5), "Minimizing a child must restore its parent results")
        waitForEmbedPresentation(app)
        XCTAssertTrue(minimize.isHittable)
        minimize.tap()
        XCTAssertTrue(fullscreen.waitForNonExistence(timeout: 5))
        XCTAssertTrue(preview.exists)
        assertAction("embed-minimized", in: app)
    }

    // Local state changes model a sibling hydration update while a result is open.
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testEmbedSelectionSurvivesInsertedAndRemovedResults() {
        let app = launch(component: "embed-preview", extraArguments: ["--ui-test-embed-navigation-mutations"])
        app.buttons["embed-preview"].firstMatch.tap()
        waitForEmbedPresentation(app)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        waitForEmbedPresentation(app)
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        assertFullscreenSelection("preview-web-search-result-2", title: "Berlin Food Scene: A Complete Guide", app: app)
        app.buttons["dev-preview-insert-result"].tap()
        assertFullscreenSelection("preview-web-search-result-2", title: "Berlin Food Scene: A Complete Guide", app: app)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-result-3", title: "Where to Eat in Berlin - Travel Blog", app: app)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-result-4", title: "Berlin Restaurant Guide 2026", app: app)
        XCTAssertFalse(app.buttons["embed-next"].exists)
        app.buttons["embed-previous"].tap()
        app.buttons["embed-previous"].tap()
        app.buttons["dev-preview-remove-result-2"].tap()
        assertFullscreenSelection("preview-web-search-result-1", title: "Top 10 Restaurants in Berlin - Local Guide", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(app.buttons["embed-preview-preview-web-search-result-inserted"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(element(app, "dev-preview-embed-fullscreen").waitForNonExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenPeerNavigationRestoresActualParentAfterChildClose() {
        let app = launch(component: "embed-fullscreen", variant: "withNavigation")
        XCTAssertTrue(app.buttons["embed-previous"].isHittable)
        XCTAssertTrue(app.buttons["embed-next"].isHittable)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-1-next", title: "Next search fixture", app: app)
        XCTAssertFalse(app.buttons["embed-next"].exists)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        assertFullscreenSelection("preview-web-search-result-1", title: "Top 10 Restaurants in Berlin - Local Guide", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        assertFullscreenSelection("preview-web-search-1-next", title: "Next search fixture", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(app.buttons["embed-preview"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(element(app, "embed-fullscreen-header").exists)
    }

    private func waitForEmbedPresentation(_ app: XCUIApplication,
                                          file: StaticString = #filePath, line: UInt = #line) {
        let state = element(app, "embed-presentation-state")
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: state)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed,
                       "Wait for the actual slide animation before resolving tap coordinates", file: file, line: line)
    }

    private func assertFullscreenSelection(_ id: String, title: String, app: XCUIApplication,
                                           file: StaticString = #filePath, line: UInt = #line) {
        waitForEmbedPresentation(app, file: file, line: line)
        let header = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "embed-fullscreen-header", id)).firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 5), file: file, line: line)
        let actualTitle = header.descendants(matching: .staticText).matching(identifier: "embed-header-title").firstMatch
        XCTAssertTrue(actualTitle.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertEqual(actualTitle.label, title, file: file, line: line)
        XCTAssertTrue(actualTitle.isHittable, "Assert real rendered content, not only a callback/route metric", file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenHeaderUsesWebBreakpointInRegularWidthEnvironment() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("Run the 730/731 width boundary on iPad Simulator so both viewports fit")
        }
        #endif
        var heights: [CGFloat] = []
        var titleHeights: [CGFloat] = []
        for width in [730, 731] {
            let app = launch(component: "embed-fullscreen", extraArguments: ["--dev-preview-width", "\(width)"])
            let header = element(app, "embed-fullscreen-header")
            XCTAssertTrue(header.waitForExistence(timeout: 5))
            XCTAssertEqual(header.frame.width, CGFloat(width), accuracy: 1)
            let title = app.staticTexts.matching(identifier: "embed-header-title").firstMatch
            XCTAssertTrue(title.isHittable)
            let minimize = app.buttons["embed-minimize"].firstMatch
            XCTAssertTrue(minimize.isHittable)
            XCTAssertGreaterThanOrEqual(title.frame.minY, minimize.frame.maxY)
            heights.append(header.frame.height)
            titleHeights.append(title.frame.height)
            attachScreenshot("Embed header at width \(width)")
            app.terminate()
        }
        XCTAssertEqual(heights[1] - heights[0], 50, accuracy: 1,
                       "Web body height changes from 190 to 240; native system insets remain unchanged")
        XCTAssertGreaterThan(titleHeights[1], titleHeights[0], "The title must use the corresponding larger web type size")
    }

    // Matches WebSearchEmbedFullscreen.preview.ts and SearchResultsTemplate's
    // real card-open/child-close flow, not a fixture-only callback counter.
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSearchResultsUseResponsiveWebGridAndOpenFourthSource() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("Run both 390/730 preview widths on iPad Simulator")
        }
        #endif
        for width in [390, 730] {
            let app = launch(component: "embed-fullscreen", extraArguments: ["--dev-preview-width", "\(width)"])
            let header = element(app, "embed-fullscreen-header")
            let first = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
            let second = app.buttons["embed-preview-preview-web-search-result-2"].firstMatch
            XCTAssertTrue(first.waitForExistence(timeout: 5))
            XCTAssertTrue(second.waitForExistence(timeout: 5))
            XCTAssertEqual(first.frame.width, 320, accuracy: 1)
            XCTAssertEqual(first.frame.height, 200, accuracy: 1)
            if width == 730 {
                XCTAssertEqual(first.frame.minX - header.frame.minX, 23.5, accuracy: 1)
                XCTAssertEqual(second.frame.minX - first.frame.minX, 363, accuracy: 1)
                XCTAssertEqual(second.frame.minY, first.frame.minY, accuracy: 1)
            } else {
                XCTAssertEqual(first.frame.minX - header.frame.minX, 35, accuracy: 1)
                XCTAssertEqual(second.frame.minX, first.frame.minX, accuracy: 1)
                XCTAssertEqual(second.frame.minY - first.frame.minY, 210, accuracy: 1)
            }
            attachScreenshot("Website result cards at width \(width)")
            let fourth = app.buttons["embed-preview-preview-web-search-result-4"].firstMatch
            let scroll = element(app, "dev-preview-embed-fullscreen").scrollViews.firstMatch
            for _ in 0..<5 where !fourth.isHittable { scroll.swipeUp() }
            XCTAssertTrue(fourth.isHittable)
            fourth.tap()
            assertFullscreenSelection("preview-web-search-result-4", title: "Berlin Restaurant Guide 2026", app: app)
            XCTAssertFalse(app.buttons["embed-next"].exists)
            app.buttons["embed-previous"].tap()
            assertFullscreenSelection("preview-web-search-result-3", title: "Where to Eat in Berlin - Travel Blog", app: app)
            app.buttons["embed-minimize"].firstMatch.tap()
            XCTAssertTrue(first.waitForExistence(timeout: 5), "Closing the source returns to the actual search results")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testInvalidPreviewPropsStayInPreviewErrorSurface() {
        let app = launch(component: "composer", props: ["notAComposerProp": "invalid"])
        XCTAssertTrue(element(app, "dev-preview-error").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "message-composer").exists)
        XCTAssertFalse(app.buttons["auth-login-tab"].exists,
                       "An invalid requested preview must never fall through to account UI")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTasksSupplementaryLoadFailuresKeepBoardVisible() {
        let app = launch(component: "tasks", variant: "supplementary-load-failure")
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "tasks-plans-load-error").exists)
        XCTAssertTrue(element(app, "tasks-project-names-load-error").exists)
        XCTAssertFalse(element(app, "tasks-load-error").exists)
        XCTAssertTrue(app.buttons.matching(identifier: "task-card-open").firstMatch.isHittable)
        attachScreenshot("Task board remains visible after supplementary loads fail")
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible,chats.surface.semantic-parity
    func testWorkspaceHomeComposersFocusTypeAndSelectText() {
        let fixtures = [
            ("tasks", "default", "task-workspace-input", "task-workspace-submit"),
            ("projects", "landing", "project-input-textarea", "project-input-submit"),
            ("workflows", "home", "workflow-input-textarea", "workflow-input-submit"),
        ]
        for (component, variant, inputID, submitID) in fixtures {
            let app = launch(component: component, variant: variant)
            let editor = element(app, inputID)
            XCTAssertTrue(editor.waitForExistence(timeout: 10), "Missing \(component) editor")
            XCTAssertTrue(editor.isHittable, "The \(component) editor must accept pointer input")
            let hitRegion = element(app, "\(inputID)-hit-region")
            XCTAssertTrue(hitRegion.exists)
            XCTAssertGreaterThanOrEqual(hitRegion.frame.height, 64)
            // Clicking the empty top portion of the field must focus the editor.
            hitRegion.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.15)).tap()
            editor.typeText("Synthetic editable prompt")
            XCTAssertEqual(editor.value as? String, "Synthetic editable prompt")
            XCTAssertTrue(app.buttons[submitID].isHittable)
            #if os(macOS)
            editor.typeKey("a", modifierFlags: .command)
            #else
            editor.press(forDuration: 1.2)
            let selectAll = app.menuItems["Select All"]
            XCTAssertTrue(selectAll.waitForExistence(timeout: 5), "Text selection must be available")
            selectAll.tap()
            #endif
            editor.typeText("Replacement prompt")
            XCTAssertEqual(editor.value as? String, "Replacement prompt")
            attachScreenshot("\(component) home composer focused with selected text replaced")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLargeContinuationCardIncludesSummaryAndCompactCardOmitsIt() {
        let tall = launch(component: "welcome", variant: "continuation",
                          extraArguments: ["--dev-preview-height", "744"])
        let largeCard = element(tall, "welcome-chat-card-fixture-resume")
        XCTAssertTrue(largeCard.waitForExistence(timeout: 10))
        XCTAssertEqual(largeCard.frame.height, 200, accuracy: 1)
        XCTAssertTrue(largeCard.label.contains("A synthetic summary of the research and its next steps."))
        attachScreenshot("Large continuation card with decrypted summary")
        tall.terminate()

        let short = launch(component: "welcome", variant: "continuation",
                           extraArguments: ["--dev-preview-height", "620"])
        let compactCard = element(short, "welcome-chat-compact-card-fixture-resume")
        XCTAssertTrue(compactCard.waitForExistence(timeout: 10))
        XCTAssertFalse(compactCard.label.contains("A synthetic summary"))
        attachScreenshot("Compact continuation card with title")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testSourceQuoteClickHighlightsVisibleExcerptAndOrdinaryOpenClearsIt() throws {
        let app = launch(component: "message", variant: "quote-scroll")
        let quote = app.buttons["source-quote-block"].firstMatch
        XCTAssertTrue(quote.waitForExistence(timeout: 10))
        XCTAssertTrue(quote.isHittable)
        quote.tap()
        waitForEmbedPresentation(app)
        let highlight = element(app, "embed-source-text-highlight")
        XCTAssertTrue(highlight.waitForExistence(timeout: 5))
        let centered = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let frame = highlight.frame
            return frame.height > 0 && frame.minY >= app.frame.minY + 70 && frame.maxY <= app.frame.maxY - 40
                && abs(frame.midY - app.frame.midY) <= app.frame.height * 0.15
        }, object: highlight)
        XCTAssertEqual(XCTWaiter.wait(for: [centered], timeout: 5), .completed,
                       "The quoted excerpt below twelve context paragraphs must scroll into the visible fullscreen viewport")
        XCTAssertTrue(highlight.label.contains("Svelte writes code that updates the DOM when state changes"))
        #if os(iOS)
        try assertSourceQuoteYellowPixels(in: highlight.frame)
        #endif
        attachScreenshot("Source quote visibly highlighted and centered in fullscreen")
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(element(app, "dev-preview-embed-fullscreen").waitForNonExistence(timeout: 5))
        let ordinaryLink = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Open source without quote")).firstMatch
        XCTAssertTrue(ordinaryLink.waitForExistence(timeout: 5))
        XCTAssertTrue(ordinaryLink.isHittable)
        ordinaryLink.tap()
        waitForEmbedPresentation(app)
        XCTAssertFalse(element(app, "embed-source-text-highlight").exists,
                       "An ordinary embed click must not inherit an earlier source excerpt")
    }

    #if os(iOS)
    private func assertSourceQuoteYellowPixels(in frame: CGRect) throws {
        let image = XCUIScreen.main.screenshot().image
        let cgImage = try XCTUnwrap(image.cgImage)
        let scale = CGFloat(cgImage.width) / image.size.width
        let region = frame.applying(CGAffineTransform(scaleX: scale, y: scale))
        let crop = try XCTUnwrap(cgImage.cropping(to: region))
        var bytes = [UInt8](repeating: 0, count: crop.width * crop.height * 4)
        let yellowPixels = try bytes.withUnsafeMutableBytes { buffer -> Int in
            let context = try XCTUnwrap(CGContext(data: buffer.baseAddress, width: crop.width, height: crop.height,
                bitsPerComponent: 8, bytesPerRow: crop.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.draw(crop, in: CGRect(x: 0, y: 0, width: CGFloat(crop.width), height: CGFloat(crop.height)))
            let pixels = buffer.bindMemory(to: UInt8.self)
            var count = 0
            for offset in stride(from: 0, to: pixels.count, by: 4) {
                // Web mark is rgba(255,213,0,.4); blended yellow has strong
                // red/green and a materially lower blue channel than the card.
                let red = Int(pixels[offset])
                let green = Int(pixels[offset + 1])
                let blue = Int(pixels[offset + 2])
                if red > 190, green > 170, red - blue > 55, green - blue > 35 {
                    count += 1
                }
            }
            return count
        }
        XCTAssertGreaterThan(yellowPixels, 80, "The visible excerpt must have painted yellow highlight pixels")
    }
    #endif

    private func launch(component: String, variant: String = "default", props: [String: String] = [:],
                        extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
                               "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"] + extraArguments
        if !props.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: props, options: [.sortedKeys]),
           let json = String(data: data, encoding: .utf8) {
            app.launchArguments += ["--dev-preview-props", json]
        }
        app.launch()
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected",
                       "Preview startup must leave the real account runtime inactive")
        if component == "embed-fullscreen" { waitForEmbedPresentation(app) }
        return app
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func assertAction(_ action: String, in app: XCUIApplication,
                              file: StaticString = #filePath, line: UInt = #line) {
        let actionProbe = element(app, "dev-preview-local-action")
        let delivered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", action), object: actionProbe)
        XCTAssertEqual(XCTWaiter.wait(for: [delivered], timeout: 5), .completed, file: file, line: line)
    }

    nonisolated private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

@MainActor
final class EmbedHeaderActionComponentUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPhoneCodeMoreUsesRealCopyAndCloseActions() {
        let app = launchHeader(variant: "actions-code", width: 390)
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.waitForExistence(timeout: 8)); more.tap()
        let copy = app.buttons["embed-copy-button"]
        XCTAssertTrue(copy.waitForExistence(timeout: 3))
        XCTAssertEqual(copy.value as? String, "content-control", "Overflow pills must opt out of header-white styling")
        copy.tap()
        XCTAssertTrue(app.staticTexts["Code copied to clipboard"].waitForExistence(timeout: 3),
                      "The production copy action must complete, not only dismiss More")
        XCTAssertFalse(copy.exists, "A real menu action closes More")
        // The real toast auto-dismisses after three seconds. Waiting for its
        // removal avoids tapping a disappearing dismiss control (hit point -1,-1)
        // or reopening More while its full-screen overlay still intercepts hits.
        XCTAssertTrue(app.staticTexts["Code copied to clipboard"].waitForNonExistence(timeout: 5))
        let moreReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            more.exists && more.isHittable && more.value as? String == "collapsed"
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [moreReady], timeout: 3), .completed)
        more.tap()
        let reopened = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            more.value as? String == "expanded"
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [reopened], timeout: 3), .completed)
        XCTAssertTrue(app.buttons["embed-download-button"].waitForExistence(timeout: 3))
        app.buttons["embed-minimize"].tap()
        XCTAssertTrue(app.buttons["embed-more-button"].waitForNonExistence(timeout: 3))
    }
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testHeaderControlsSwitchStyleWhenScrolledAwayAtNarrowAndWideWidths() {
        for width in [390, 800] {
            let app = launchHeader(variant: "default", width: width, height: 400)
            let close = app.buttons["embed-minimize"]
            XCTAssertTrue(close.waitForExistence(timeout: 8))
            XCTAssertEqual(close.value as? String, "header-overlay")
            XCTAssertFalse(app.buttons["embed-more-button"].exists)
            let fullscreen = app.descendants(matching: .any)["dev-preview-embed-fullscreen"].firstMatch
            let scroll = fullscreen.scrollViews.firstMatch
            for _ in 0..<8 {
                if close.value as? String == "content-control" { break }
                scroll.swipeUp()
            }
            XCTAssertEqual(close.value as? String, "content-control")
            app.terminate()
        }
    }
    private func launchHeader(variant: String, width: Int, height: Int = 844) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-fullscreen", "--dev-preview-variant", variant,
            "--dev-preview-width", String(width), "--dev-preview-height", String(height),
            "--ui-test-embed-presentation", "-AppleLanguages", "(en)"]
        app.launch()
        return app
    }
}

@MainActor
final class SearchSheetComponentPreviewUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testSearchQueryProviderAndThreeLineQueryRemainVisible() {
        for variant in ["default", "search-long"] {
            let app = launch(variant: variant)
            let card = app.buttons["embed-preview"].firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 10))
            XCTAssertEqual(card.frame.width, 300, accuracy: 2)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2)
            let query = element(app, "web-search-query")
            let provider = element(app, "web-search-provider")
            XCTAssertTrue(query.exists)
            XCTAssertTrue(query.isHittable, "The real query must remain visible in the card")
            XCTAssertTrue(provider.isHittable)
            XCTAssertTrue(query.label.hasPrefix("best restaurants in Berlin"))
            XCTAssertEqual(provider.label, "via Brave Search")
            XCTAssertGreaterThan(query.frame.height, 16)
            screenshot("Search query and provider — " + variant)
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testSheetsRenderCellsTitleAndDeclaredDimensions() {
        for variant in ["sheet", "sheet-wide"] {
            let app = launch(variant: variant)
            let card = app.buttons["embed-preview"].firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 10))
            XCTAssertEqual(card.frame.width, 300, accuracy: 2)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2)
            XCTAssertTrue(element(app, "sheet-preview-table").exists)
            if variant == "sheet" {
                XCTAssertTrue(app.staticTexts["Alice Johnson"].exists)
                XCTAssertTrue(app.staticTexts["Senior Engineer"].exists)
                XCTAssertTrue(app.staticTexts["Team Directory"].exists)
                XCTAssertTrue(app.staticTexts["5 rows × 4 columns"].exists)
                XCTAssertTrue(app.staticTexts["+2"].exists)
            } else {
                XCTAssertTrue(app.staticTexts["Widget A"].exists)
                XCTAssertTrue(app.staticTexts["12400"].exists)
                XCTAssertTrue(app.staticTexts["Sales Report Q4 2025"].exists)
                XCTAssertTrue(app.staticTexts["150 rows × 8 columns"].exists)
                XCTAssertTrue(app.staticTexts["+4"].exists)
            }
            card.tap()
            XCTAssertTrue(element(app, "sheet-fullscreen-table").waitForExistence(timeout: 5))
            screenshot("Sheet actual cells and fullscreen — " + variant)
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testLargeSheetUsesExpandedColumnAndRowBudget() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else { throw XCTSkip("930-point reference requires iPad Simulator") }
        #endif
        let app = launch(variant: "sheet-large", width: 930)
        let card = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertEqual(card.frame.width, 930, accuracy: 2)
        XCTAssertGreaterThanOrEqual(card.frame.height, 400)
        XCTAssertTrue(app.staticTexts["Department"].exists)
        XCTAssertTrue(app.staticTexts["Start Date"].exists)
        XCTAssertTrue(app.staticTexts["Eva Martinez"].exists)
        screenshot("Large Sheet matches deployed full-column group")
        app.terminate()
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity,chats.surface.semantic-parity
    func testSearchGroupUsesRegularCardsAndTwelvePointGap() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else { throw XCTSkip("Two regular group cards require iPad Simulator") }
        #endif
        let app = launch(variant: "search-group", width: 730)
        let newest = element(app, "embed-preview-preview-search-group-3")
        let second = element(app, "embed-preview-preview-search-group-2")
        XCTAssertTrue(newest.waitForExistence(timeout: 10))
        XCTAssertTrue(second.exists)
        XCTAssertEqual(newest.frame.width, 300, accuracy: 2)
        XCTAssertEqual(newest.frame.height, 200, accuracy: 2)
        XCTAssertEqual(second.frame.minX - newest.frame.maxX, 12, accuracy: 2)
        XCTAssertEqual(second.frame.minY, newest.frame.minY, accuracy: 2)
        let newestButton = newest.buttons["embed-preview"].firstMatch
        let secondButton = second.buttons["embed-preview"].firstMatch
        XCTAssertTrue(newestButton.isHittable, "The newest card's production button must be visible and clickable")
        XCTAssertTrue(secondButton.isHittable, "The second card's production button must be visible and clickable")
        XCTAssertEqual(newest.staticTexts["web-search-query"].label, "Berlin restaurant search 3")
        XCTAssertEqual(second.staticTexts["web-search-query"].label, "Berlin restaurant search 2")
        screenshot("Grouped Search regular cards and 12-point gap")
        newestButton.tap()
        let fullscreen = element(app, "dev-preview-embed-fullscreen")
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        let presented = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"),
                                                  object: element(app, "embed-presentation-state"))
        XCTAssertEqual(XCTWaiter.wait(for: [presented], timeout: 5), .completed)
        XCTAssertEqual(fullscreen.value as? String, "preview-search-group-3")
        let title = app.staticTexts["embed-header-title"].firstMatch
        XCTAssertTrue(title.isHittable)
        XCTAssertTrue(title.label.contains("Berlin restaurant search 3"))
        screenshot("Grouped Search newest card opens its production fullscreen")
        let minimize = app.buttons["embed-minimize"].firstMatch
        XCTAssertTrue(minimize.isHittable)
        minimize.tap()
        XCTAssertTrue(fullscreen.waitForNonExistence(timeout: 5))
        XCTAssertTrue(newestButton.isHittable, "Minimize must restore the same actionable group card")
        app.terminate()
    }

    private func launch(variant: String, width: Int? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-preview", "--dev-preview-variant", variant,
                               "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        if let width { app.launchArguments += ["--dev-preview-width", String(width)] }
        app.launch()
        return app
    }
    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
