// Debug-only, account-independent hosts for production Apple UI components.
// Fixtures and all editable state live in this view tree; no auth session,
// draft repository, upload service, or send pipeline is constructed. The
// sub-chat fixture uses an isolated ChatStore without a persistence bridge.
// Recreating the configuration identity resets local interactions predictably.
// The bare canvas exposes its last local action through accessibility for tests.
//
// Web sources: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//              frontend/packages/ui/src/components/ChatHeader.svelte
//              frontend/packages/ui/src/components/ChatMessage.svelte
//              frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte
//              frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//              frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
// Exact bare comparison URLs are in DevPreviewComponentRegistry.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

#if DEBUG
import SwiftUI
import UniformTypeIdentifiers
import ZIPFoundation
import Yams

struct DevComponentPreviewView: View {
    let configuration: DevPreviewLaunchConfiguration

    var body: some View {
        Group {
            if let error = configuration.error ?? fixtureError {
                Text(error)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing8)
                    .accessibilityIdentifier("dev-preview-error")
            } else {
                DevComponentPreviewCanvas(configuration: configuration)
                    .id(configuration)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey0.ignoresSafeArea())
        // Production actions (for example Copy) keep their real user feedback
        // in the isolated host as well as in MainAppView.
        .overlay(alignment: .top) { ToastOverlay() }
    }

    private var fixtureError: String? {
        guard let component = configuration.component else { return "Select a component preview." }
        let allowedKeys: Set<String>
        switch component {
        case .login, .signup, .history, .sidebar, .welcome, .followUpSuggestions, .tasks, .projects: allowedKeys = []
        case .notification, .sharedRecipient: allowedKeys = []
        case .workflows:
            allowedKeys = []
            guard ["short-template", "home"].contains(configuration.variant) else {
                return "The isolated Workflow host supports the short-template and home variants."
            }
        case .composer: allowedKeys = ["text", "placeholder"]
        case .chatHeader: allowedKeys = ["title", "summary", "appId"]
        case .message: allowedKeys = configuration.variant.hasPrefix("streaming") ? [] : ["content", "thinkingContent"]
        case .embedPreview, .embedFullscreen:
            allowedKeys = []
            guard configuration.appSlug == .web else {
                return "Isolated embed interaction currently supports the web fixture only."
            }
        default:
            return "This component does not yet have an isolated preview host."
        }
        guard configuration.props.keys.allSatisfy(allowedKeys.contains) else {
            return "Unsupported prop for this component. Supported props: \(allowedKeys.sorted().joined(separator: ", "))."
        }
        guard configuration.props.values.allSatisfy({ $0.string != nil }) else {
            return "This component's fixture props must be strings."
        }
        return nil
    }
}

private struct DevComponentPreviewCanvas: View {
    let configuration: DevPreviewLaunchConfiguration
    @State private var lastAction = "ready"
    @StateObject private var notificationFixtureManager = ToastManager()
    @State private var notificationDismissed = false
    @Environment(\.accessibilityReduceMotion) private var notificationReduceMotion
    @State private var embedRoute: [EmbedRecord] = []
    @State private var sourceQuoteTarget: SourceQuoteTarget?
    @State private var headerIndex = 0
    @State private var standaloneFullscreenMinimized = false
    @State private var standaloneParent: EmbedRecord?
    @State private var insertedFixtureResult = false
    @State private var removedSecondFixtureResult = false
    @StateObject private var subChatFixtureStore = ChatStore()
    @StateObject private var tasksFixtureStore = TasksWorkspaceStore()
    @StateObject private var projectsFixtureStore = ProjectsWorkspaceStore()
    @StateObject private var projectTasksFixtureStore = TasksWorkspaceStore()
    @StateObject private var workflowFixtureStore = WorkflowStore()
    @EnvironmentObject private var authManager: AuthManager

    private var skill: DevEmbedPreviewSkill {
        // This curated fixture is complete in memory. Other gallery families can
        // contain service-backed media/actions and require separate isolation.
        configuration.variant == "actions-code"
            ? DevEmbedPreviewFixtures.skills(for: .code)[0]
            : DevEmbedPreviewFixtures.isolatedEmbedSkill(variant: configuration.variant)
    }

    private var primaryEmbed: EmbedRecord {
        let source = skill.primaryEmbed
        let status = EmbedStatus(rawValue: configuration.variant) ?? .finished
        var data = source.rawData ?? [:]
        data["result_count"] = AnyCodable(fixtureChildren.count)
        return EmbedRecord(id: source.id, type: source.type, status: status, data: .raw(data),
                           parentEmbedId: source.parentEmbedId, appId: source.appId,
                           skillId: source.skillId, embedIds: fixtureChildren.map(\.id).joined(separator: "|"),
                           createdAt: source.createdAt)
    }

    private var fixtureChildren: [EmbedRecord] {
        var result = skill.childEmbeds.filter { !removedSecondFixtureResult || $0.id != "preview-web-search-result-2" }
        if insertedFixtureResult, let template = skill.childEmbeds.first {
            var data = template.rawData ?? [:]
            data["title"] = AnyCodable("Earlier hydrated result")
            result.insert(EmbedRecord(id: "preview-web-search-result-inserted", type: template.type,
                status: template.status, data: .raw(data), parentEmbedId: primaryFixtureID,
                appId: template.appId, skillId: template.skillId, embedIds: nil, createdAt: template.createdAt), at: 0)
        }
        return result
    }

    private var primaryFixtureID: String { skill.primaryEmbed.id }

    // The web withNavigation variant means peer parent embeds, not a parent
    // followed by its own results. Local peers make the actions observable.
    private var parentNavigationEmbeds: [EmbedRecord] {
        guard configuration.variant == "withNavigation" else { return [primaryEmbed] }
        func peer(_ suffix: String, query: String) -> EmbedRecord {
            let source = primaryEmbed
            var data = source.rawData ?? [:]
            data["query"] = AnyCodable(query)
            return EmbedRecord(id: source.id + suffix, type: source.type, status: source.status,
                data: .raw(data), parentEmbedId: nil, appId: source.appId, skillId: source.skillId,
                embedIds: source.embedIds, createdAt: source.createdAt)
        }
        return [peer("-previous", query: "Previous search fixture"), primaryEmbed,
                peer("-next", query: "Next search fixture")]
    }

    private var fixtureRecords: [String: EmbedRecord] {
        if configuration.component == .message, configuration.variant.hasPrefix("quote-") {
            return [quoteFixture.id: quoteFixture]
        }
        if configuration.component == .message, configuration.variant.hasPrefix("results-") {
            return Dictionary(resultViewRecords.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        }
        return Dictionary((parentNavigationEmbeds + fixtureChildren).map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
    }

    private static let quoteExcerpt = "Svelte writes code that updates the DOM when state changes"
    private var quoteFixture: EmbedRecord {
        Self.makeQuoteFixture(longContext: configuration.variant == "quote-scroll")
    }
    private static func makeQuoteFixture(longContext: Bool) -> EmbedRecord {
        EmbedRecord(
        id: "preview-source-quote-website", type: "web-website", status: .finished,
        data: .raw([
            "url": AnyCodable("https://github.com/sveltejs/svelte"),
            "title": AnyCodable("sveltejs/svelte: Cybernetically enhanced web apps"),
            "description": AnyCodable("Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps."),
            "extra_snippets": AnyCodable(
                (longContext
                    ? (0..<12).map { "Synthetic source context paragraph \($0). This deliberately places the cited excerpt below the initial fullscreen viewport." }
                    : ["Svelte shifts work from the browser to a compile step that happens when you build your app."])
                + ["Instead of using techniques like virtual DOM diffing, \(quoteExcerpt)."]
                + (longContext ? (0..<8).map { "Synthetic trailing source paragraph \($0). The excerpt above has enough following source content for a centered scroll target." } : [])
            )
        ]), parentEmbedId: nil, appId: "web", skillId: "website", embedIds: nil, createdAt: nil
        )
    }

    private func berlinMapEvent(id: String, title: String, venue: String, latitude: Double,
                                longitude: Double, time: String, price: Int, provider: String) -> EmbedRecord {
        EmbedRecord(id: id, type: "event", status: .finished,
                    data: .raw(["title": AnyCodable(title), "venue_name": AnyCodable(venue),
                                "venue_address": AnyCodable("Berlin, Germany"),
                                "venue_latitude": AnyCodable(latitude), "venue_longitude": AnyCodable(longitude),
                                "date_start": AnyCodable("2026-09-30T\(time):00"),
                                "event_type": AnyCodable("in_person"), "price": AnyCodable(price),
                                "provider": AnyCodable(provider), "url": AnyCodable("https://example.com/events/\(id)")]),
                    parentEmbedId: nil, appId: "events", skillId: "search", embedIds: nil, createdAt: nil)
    }

    private var resultViewRecords: [EmbedRecord] {
        if configuration.variant == "results-berlin-map" {
            // Public city landmarks, synthetic titles and dates; never geocode
            // or request user location in this account-independent preview.
            return [
                berlinMapEvent(id: "preview-berlin-event-1", title: "Berlin AI Builders", venue: "Alexanderplatz",
                               latitude: 52.5219, longitude: 13.4132, time: "18:00", price: 0, provider: "Community"),
                berlinMapEvent(id: "preview-berlin-event-2", title: "Software Demo Evening", venue: "Brandenburg Gate",
                               latitude: 52.5163, longitude: 13.3777, time: "19:00", price: 15, provider: "Community"),
                berlinMapEvent(id: "preview-berlin-event-3", title: "AI Research Meetup", venue: "Museum Island",
                               latitude: 52.5207, longitude: 13.4010, time: "20:00", price: 30, provider: "Research"),
            ]
        }
        // Mirrors the five local connection children and source relationship in
        // EmbedsMapView.preview.ts, using only fields the production renderers read.
        let sourceId = "preview-results-flight-source"
        let childIds = [
            "c0328462-5112-4ef2-ac54-3e359f1b625e",
            "3159a788-4f2e-4951-b165-dd9ef253cf8f",
            "a79e18e2-a4a3-4331-aa8e-3792fda0d053",
            "fde6eba7-280f-4672-aafb-834051fb14d8",
            "220ff6a9-7ead-415a-9055-a84436b907d9",
        ]
        func connection(_ id: String, carrier: String, code: String, price: String,
                        departure: String, arrival: String, duration: String,
                        via: String, viaLatitude: Double, viaLongitude: Double,
                        firstArrival: String, secondDeparture: String, layoverMinutes: Int) -> EmbedRecord {
            let berlinLatitude = 52.362877, berlinLongitude = 13.503722
            let bangkokLatitude = 13.6811, bangkokLongitude = 100.7472
            let segments: [[String: Any]] = [
                ["carrier": carrier, "carrier_code": code, "number": "\(code) 1",
                 "departure_station": "BER", "departure_time": departure,
                 "departure_latitude": berlinLatitude, "departure_longitude": berlinLongitude,
                 "arrival_station": via, "arrival_time": firstArrival,
                 "arrival_latitude": viaLatitude, "arrival_longitude": viaLongitude],
                ["carrier": carrier, "carrier_code": code, "number": "\(code) 2",
                 "departure_station": via, "departure_time": secondDeparture,
                 "departure_latitude": viaLatitude, "departure_longitude": viaLongitude,
                 "arrival_station": "BKK", "arrival_time": arrival,
                 "arrival_latitude": bangkokLatitude, "arrival_longitude": bangkokLongitude],
            ]
            let layovers: [[String: Any]] = [["airport_code": via, "duration_minutes": layoverMinutes]]
            let leg: [String: Any] = ["origin": "Berlin (BER)", "destination": "Bangkok (BKK)",
                                      "departure": departure, "arrival": arrival,
                                      "duration": duration, "stops": 1,
                                      "segments": segments, "layovers": layovers]
            let raw: [String: AnyCodable] = [
                "type": AnyCodable("connection"), "transport_method": AnyCodable("airplane"),
                "trip_type": AnyCodable("one_way"), "total_price": AnyCodable(price),
                "currency": AnyCodable("EUR"), "legs": AnyCodable([leg]),
                "origin": AnyCodable("Berlin (BER)"), "destination": AnyCodable("Bangkok (BKK)"),
                "departure": AnyCodable(departure), "arrival": AnyCodable(arrival),
                "duration": AnyCodable(duration), "stops": AnyCodable(1),
                "carriers": AnyCodable(carrier), "carrier_codes": AnyCodable(code),
            ]
            // The web static embed type is `connection`; Apple routes the same
            // child through its normalized `travel-connection` renderer key.
            return EmbedRecord(id: id, type: "travel-connection", status: .finished,
                               data: .raw(raw), parentEmbedId: sourceId, appId: "travel",
                               skillId: "search_connections", embedIds: nil, createdAt: nil)
        }
        let source = EmbedRecord(
            id: sourceId, type: "app_skill_use", status: .finished,
            data: .raw(["type": AnyCodable("app_skill_use"), "app_id": AnyCodable("travel"),
                        "skill_id": AnyCodable("search_connections"),
                        "result_count": AnyCodable(5), "embed_ids": AnyCodable(childIds.joined(separator: "|"))]),
            parentEmbedId: nil, appId: "travel", skillId: "search_connections",
            embedIds: childIds.joined(separator: "|"), createdAt: nil
        )
        return [
            source,
            connection(childIds[0], carrier: "Qatar Airways", code: "QR", price: "636",
                       departure: "2026-04-14 10:00", arrival: "2026-04-15 06:20", duration: "15h 20m",
                       via: "DOH", viaLatitude: 25.272524, viaLongitude: 51.608604,
                       firstArrival: "2026-04-14 17:05", secondDeparture: "2026-04-14 19:35", layoverMinutes: 150),
            connection(childIds[1], carrier: "Qatar Airways", code: "QR", price: "636",
                       departure: "2026-04-14 16:45", arrival: "2026-04-15 12:20", duration: "14h 35m",
                       via: "DOH", viaLatitude: 25.272524, viaLongitude: 51.608604,
                       firstArrival: "2026-04-14 23:40", secondDeparture: "2026-04-15 01:35", layoverMinutes: 115),
            connection(childIds[2], carrier: "Air France", code: "AF", price: "715",
                       departure: "2026-04-14 12:50", arrival: "2026-04-15 09:15", duration: "15h 25m",
                       via: "CDG", viaLatitude: 49.012516, viaLongitude: 2.555752,
                       firstArrival: "2026-04-14 14:40", secondDeparture: "2026-04-14 16:45", layoverMinutes: 125),
            connection(childIds[3], carrier: "KLM", code: "KL", price: "725",
                       departure: "2026-04-14 14:15", arrival: "2026-04-15 09:30", duration: "14h 15m",
                       via: "AMS", viaLatitude: 52.308609, viaLongitude: 4.763889,
                       firstArrival: "2026-04-14 15:35", secondDeparture: "2026-04-14 17:15", layoverMinutes: 100),
            connection(childIds[4], carrier: "Turkish Airlines", code: "TK", price: "741",
                       departure: "2026-04-14 10:40", arrival: "2026-04-15 05:05", duration: "13h 25m",
                       via: "IST", viaLatitude: 41.270149, viaLongitude: 28.733362,
                       firstArrival: "2026-04-14 14:40", secondDeparture: "2026-04-14 15:50", layoverMinutes: 70),
            EmbedRecord(id: "preview-results-date-only", type: "event", status: .finished,
                        data: .raw(["title": AnyCodable("Date-only event"), "date": AnyCodable("2026-09-20")]),
                        parentEmbedId: nil, appId: "events", skillId: nil, embedIds: nil, createdAt: nil),
            EmbedRecord(id: "preview-results-invalid", type: "event", status: .finished,
                        data: .raw(["title": AnyCodable("Invalid entry"), "date": AnyCodable("2026-02-30"),
                                    "lat": AnyCodable(100), "lon": AnyCodable(200)]),
                        parentEmbedId: nil, appId: "events", skillId: nil, embedIds: nil, createdAt: nil),
        ]
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                component(viewport: proxy.size)
                    .frame(maxWidth: .infinity, maxHeight: .infinity,
                           alignment: configuration.component == .chatHeader ? .top : .center)
                    .allowsHitTesting(embedRoute.isEmpty)
                    .accessibilityHidden(!embedRoute.isEmpty)
                if let active = embedRoute.last {
                    fullscreen(active)
                        .id(active.id)
                        .background(Color.grey0)
                }
                if ProcessInfo.processInfo.arguments.contains("--ui-test-embed-navigation-mutations") {
                    VStack {
                        Spacer()
                        HStack {
                            Button("Insert fixture result") { insertedFixtureResult = true }
                                .accessibilityIdentifier("dev-preview-insert-result")
                            Button("Remove fixture result 2") { removedSecondFixtureResult = true }
                                .accessibilityIdentifier("dev-preview-remove-result-2")
                        }
                        .buttonStyle(.bordered)
                        .padding(8)
                        .background(Color.grey0)
                    }
                }
                // A separate leaf survives SwiftUI collapsing the root/canvas
                // containers into one accessibility element. It changes no
                // visible chrome and cannot intercept component interactions.
                Color.clear
                    .frame(width: 1, height: 1)
                    .accessibilityElement()
                    .accessibilityLabel(lastAction)
                    .accessibilityIdentifier("dev-preview-local-action")
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .allowsHitTesting(false)
            }
            .environment(\.openURL, OpenURLAction { _ in
                lastAction = "external-link-intercepted"
                return .handled
            })
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-component-preview-\(configuration.component?.rawValue ?? "unknown")")
            .accessibilityValue(lastAction)
        }
    }

    @ViewBuilder
    private func component(viewport: CGSize) -> some View {
        switch configuration.component {
        case .sharedRecipient:
            SharedChatRecipientView.preview(state: configuration.variant)
        case .sidebar:
            DevSidebarComponentFixture(variant: configuration.variant)
        case .history:
            DevHistoryComponentFixture(workspace: configuration.variant == "workspace")
        case .welcome:
            DevWelcomeComponentFixture(empty: configuration.variant == "empty", onAction: { lastAction = $0 })
        case .login, .signup:
            DevAuthFormFixture(configuration: configuration)
        case .composer where configuration.variant == "assistant-speech":
            DevAssistantSpeechPreview()
        case .composer where configuration.variant == "assistant-speech-public":
            DevAssistantSpeechPreview(variant: "publicExample")
        case .composer where configuration.variant == "chat-settings":
            ChatSettingsView.preview()
        case .composer where configuration.variant == "chat-settings-usage":
            ChatSettingsView.preview(populatedUsage: true)
        case .composer where configuration.variant == "chat-settings-plans":
            ChatSettingsView.preview(allPlans: true)
        case .composer where configuration.variant == "chat-settings-shared":
            ChatSettingsView.preview(shared: true)
        case .composer where configuration.variant == "chat-settings-public":
            ChatSettingsView.preview(example: true)
        case .composer where configuration.variant == "chat-settings-export-control":
            DevNativeJSONExportControl()
        case .composer where configuration.variant == "model":
            DevComposerModelFixture()
        case .composer where configuration.variant == "search-suggestions":
            DevComposerSearchPreview()
        case .composer:
            DevComposerComponentFixture(configuration: configuration, onAction: { lastAction = $0 })
                .padding(.horizontal, viewport.width > 730 ? 32 : 16)
        case .chatHeader:
            ChatBannerView(state: bannerState,
                           createdAt: Date(timeIntervalSince1970: 1_783_684_800),
                           viewportHeight: viewport.height,
                           onPrevious: { headerIndex -= 1; lastAction = "previous-chat" },
                           onNext: { headerIndex += 1; lastAction = "next-chat" })
        case .followUpSuggestions:
            FollowUpSuggestions(
                suggestions: followUpSuggestionFixture,
                compact: viewport.width <= 500
            ) { suggestion in
                lastAction = "quick-sent-\(suggestion)"
            }
        case .tasks:
            TasksWorkspaceView(store: tasksFixtureStore,
                               showPlansOnly: configuration.variant == "plans",
                               inspiration: DailyInspirationData(
                                   inspirationId: configuration.variant == "plans" ? "hardcoded-plan-timeline" : "hardcoded-task-next-action",
                                   text: configuration.variant == "plans"
                                       ? AppStrings.plansInspirationTimeline : AppStrings.tasksInspirationNextAction,
                                   title: configuration.variant == "plans"
                                       ? AppStrings.plansInspirationTimelineTitle : AppStrings.tasksInspirationNextActionTitle,
                                   category: "productivity"),
                               onStartInspiration: { _ in lastAction = "tasks-inspiration-started" },
                               onOpenProject: { lastAction = "opened-project-\($0)" },
                               onOpenChat: { lastAction = "opened-chat-\($0)" })
                .onAppear {
                    tasksFixtureStore.installPreview()
                    if configuration.variant == "task-load-failure" {
                        let failure = NSError(domain: "SyntheticTasksPreview", code: 1,
                            userInfo: [NSLocalizedDescriptionKey: "Synthetic task data is unavailable."])
                        tasksFixtureStore.debugApplyLoadFailure(failure, stage: "tasks",
                            generation: tasksFixtureStore.debugLoadGeneration)
                    }
                    if configuration.variant == "supplementary-load-failure" {
                        let failure = NSError(domain: "SyntheticTasksPreview", code: 1,
                            userInfo: [NSLocalizedDescriptionKey: "Synthetic supplementary data is unavailable."])
                        let generation = tasksFixtureStore.debugLoadGeneration
                        tasksFixtureStore.debugApplyLoadFailure(failure, stage: "plans", generation: generation)
                        tasksFixtureStore.debugApplyLoadFailure(failure, stage: "project_names", generation: generation)
                    }
                }
        case .projects:
            if configuration.variant == "sidebar" {
                ProjectsSidebarView(store: projectsFixtureStore,
                    onClose: { lastAction = "projects-sidebar-closed" },
                    onOpenProject: { lastAction = "opened-project-\($0)" })
                    .onAppear { projectsFixtureStore.installPreview(variant: "sidebar") }
            } else {
                ProjectsWorkspaceView(store: projectsFixtureStore,
                    tasksStore: projectTasksFixtureStore,
                    previewInitialTab: ["folders", "connectedSource", "localFolderSource",
                        "multipleSources", "largeConnectedSource", "legacyConnectedSource", "rootFiles", "truncatedConnectedSource", "offlineConnectedSource"]
                        .contains(configuration.variant) ? .files
                        : configuration.variant == "tasks" ? .tasks : .overview,
                    onOpenChat: { lastAction = "opened-chat-\($0)" },
                    onOpenWorkflow: { lastAction = "opened-workflow-\($0)" },
                    onOpenPlan: { lastAction = "opened-plan-\($0)" },
                    onOpenTasks: { lastAction = "opened-tasks-\($0)" },
                    onOpenEmbed: { lastAction = "opened-embed-\($0.id)" },
                    onOpenSettings: { lastAction = "opened-settings-\($0)" },
                    onReportIssue: { lastAction = "reported-project-\($0)" })
                    .onAppear {
                        projectsFixtureStore.installPreview(variant: configuration.variant)
                        projectTasksFixtureStore.installPreview(projectID: "preview-project")
                    }
            }
        case .notification:
            if configuration.variant == "stack" {
                ToastOverlay(manager: notificationFixtureManager)
                    .task {
                        notificationFixtureManager.show("First retained notice", duration: 0, title: "First notice")
                        notificationFixtureManager.show("Reconnecting...", type: .connection, duration: 0,
                            title: "Reconnecting...", isProcessing: true)
                        notificationFixtureManager.show("Your settings have been updated successfully.",
                            type: .success, duration: 0, title: "Changes saved")
                    }
            } else if !notificationDismissed {
                InAppNotificationCard(
                    title: configuration.variant == "connection" ? "Reconnecting..." : "Changes saved",
                    message: configuration.variant == "connection" ? "Reconnecting..." : "Your settings have been updated successfully.",
                    type: configuration.variant == "connection" ? .connection : .success,
                    duration: configuration.variant == "progress" ? 10 : 0,
                    isProcessing: configuration.variant == "connection", compact: viewport.width <= 450,
                    onDismiss: { withAnimation { notificationDismissed = true } })
                    .frame(width: min(430, max(0, viewport.width - (viewport.width <= 450 ? 20 : 40))))
                    .transition(NotificationMotion.transition(reduceMotion: notificationReduceMotion))
            }
        case .workflows:
            if configuration.variant == "home" {
                WorkflowHomeView(store: workflowFixtureStore, authManager: authManager,
                    authoring: workflowFixtureStore.authoring,
                    onReportIssue: { lastAction = "workflow-report-issue" })
                    .onAppear { workflowFixtureStore.showFixture("home") }
            } else {
                WorkflowShortTemplatePreviewHost()
            }
        case .message:
            if configuration.variant.hasPrefix("streaming") {
                DevProgressiveMessageFixture(variant: configuration.variant)
            } else if configuration.variant == "sub-chat-batch" {
                ScrollView {
                    MessageBubble(message: message, chatId: message.chatId, appId: "finance",
                                  embeds: [], allEmbedRecords: [:], streamingContent: nil,
                                  thinkingContent: nil, isThinkingStreaming: false,
                                  piiMappings: [], isPIIRevealed: false, containerWidth: viewport.width,
                                  isSearchTarget: false, searchHighlightQuery: nil,
                                  onEmbedTap: { _ in }, onOpenPublicChat: nil,
                                  subChatStore: subChatFixtureStore,
                                  onOpenSubChat: { lastAction = "opened-sub-chat-\($0)" },
                                  onInteractiveQuestionSubmit: nil, onShowActions: nil)
                        .padding(.spacing5)
                }
                .onAppear {
                    subChatFixtureStore.performWithoutPersistence {
                        subChatFixtureStore.upsertChats(Self.subChatFixtureChildren)
                    }
                }
            } else if ["results-visual", "results-berlin-map"].contains(configuration.variant) {
                // Match EmbedsMapView.preview.ts: show the virtual results node
                // at the 390-point phone viewport without message-bubble chrome.
                ScrollView {
                    RichMarkdownView(content: message.content ?? "", isUserMessage: false,
                                     allEmbedRecords: fixtureRecords,
                                     onEmbedTap: { open($0) })
                        .frame(width: min(652, max(0, (configuration.variant == "results-visual" ? min(viewport.width, 390) : viewport.width) - 64)))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.leading, 32)
                        .padding(.top, 70)
                }
            } else {
            ScrollView {
                MessageBubble(message: message, chatId: message.chatId, appId: "code",
                              embeds: configuration.variant == "citations" ? Array(fixtureRecords.values) : [],
                              allEmbedRecords: fixtureRecords, streamingContent: nil,
                              thinkingContent: message.thinkingContent, isThinkingStreaming: false,
                              piiMappings: [], isPIIRevealed: false, containerWidth: viewport.width,
                              isSearchTarget: false, searchHighlightQuery: nil,
                              onEmbedTap: { open($0) },
                              onOpenPublicChat: { _ in lastAction = "public-chat-intercepted" },
                              onInteractiveQuestionSubmit: { _ in lastAction = "question-submitted-locally" },
                              onShowActions: { lastAction = "message-actions-requested" })
                    .padding(.spacing5)
                    .environment(\.sourceQuoteOpenAction, { embed, quote in
                        open(embed)
                        sourceQuoteTarget = SourceQuoteTarget(embedID: embed.id, text: quote)
                    })
            }
            }
        case .embedPreview:
            if configuration.variant == "search-group" {
                ForEach(EmbedGrouper.groupForInlineDisplay(DevEmbedPreviewFixtures.isolatedSearchGroup)) { group in
                    GroupedEmbedView(group: group) { open($0) }
                }
            } else {
                EmbedPreviewCard(embed: primaryEmbed, allEmbedRecords: fixtureRecords,
                                 variant: configuration.variant == "sheet-large" ? .large : .compact) { open(primaryEmbed) }
            }
        case .embedFullscreen:
            if standaloneFullscreenMinimized {
                EmbedPreviewCard(embed: primaryEmbed, allEmbedRecords: fixtureRecords) { open(primaryEmbed) }
            } else {
                fullscreen(standaloneParent ?? primaryEmbed)
            }
        default:
            EmptyView()
        }
    }

    private var followUpSuggestionFixture: [String] {
        switch configuration.variant {
        case "legacy-markup":
            return [
                "[web-search] <strong>Compare</strong> the sources",
                "Explain the result in simpler terms",
                "Plan the next step",
                "Show a practical example",
                "This fifth action stays outside the visible limit",
            ]
        case "long":
            return [
                "Explain how this recommendation changes when the available space becomes narrow",
                "Compare the tradeoffs with a different approach",
                "Show a concise practical example",
                "What should I verify next?",
            ]
        default:
            return [
                "Explain this in simpler terms",
                "Compare the main options",
                "Show a practical example",
                "What should I do next?",
            ]
        }
    }

    private var bannerState: ChatBannerState {
        switch configuration.variant {
        case "loading": return .loading
        case "incognito": return .incognito
        case "draft": return .draftOnly(preview: configuration.props["title"]?.string ?? "Plan a weekend in Berlin")
        default:
            let defaultTitle = configuration.variant == "long-title"
                ? "A detailed weekend guide to Berlin with restaurants, museums, parks, and places to explore"
                : "A weekend in Berlin"
            let title = configuration.props["title"]?.string ?? defaultTitle
            return .loaded(title: headerIndex == 0 ? title : "\(title) (\(headerIndex))",
                           appId: configuration.props["appId"]?.string ?? "travel",
                           summary: configuration.props["summary"]?.string ?? "Restaurants, museums, and a relaxed itinerary.")
        }
    }

    private var message: Message {
        let variant = configuration.variant
        let role: MessageRole = variant == "default" || variant == "user" || variant == "mentions" ? .user : .assistant
        let defaultContent: String
        switch variant {
        case "mentions":
            defaultContent = "Use @focus:workflows:clarify_workflows with @skill:web:search and @mate:software_development. Route to @best-model:best or @ai-model:claude-sonnet-4-5:anthropic."
        case "default", "user":
            defaultContent = "Can you help me understand how Svelte 5 runes work? I want to migrate my app from Svelte 4."
        case "thinking":
            defaultContent = "Based on my analysis, the best approach would be to start by converting your reactive declarations first."
        case "quote-open", "quote-scroll":
            defaultContent = "> [\(Self.quoteExcerpt)](embed:\(quoteFixture.id))\n\n[Open source without quote](embed:\(quoteFixture.id))"
        case "citations":
            defaultContent = "Here are some places to start: [Berlin restaurants](embed:\(skill.childEmbeds[0].id)).\n\n[[embed:\(primaryEmbed.id)]]"
        case "results-berlin-map":
            defaultContent = """
                ```embeds_results_view
                title: Berlin AI Meetups
                embeds: preview-berlin-event-1, preview-berlin-event-2, preview-berlin-event-3
                ```
                """
        case "results-map", "results-visual":
            defaultContent = """
                ```embeds_results_view
                title: Berlin to Bangkok flight options
                sources: preview-results-flight-source
                highlight: c0328462-5112-4ef2-ac54-3e359f1b625e
                ```
                """
        case "sub-chat-batch":
            defaultContent = """
                ```json
                {"type":"sub_chat_batch","batch_id":"preview-egg-batch","chat_id":"preview-chat","status":"finished","sub_chat_ids":["preview-egg-supply","preview-egg-costs","preview-egg-market"]}
                ```
                """
        case "results-date-only":
            defaultContent = """
                ```embeds_results_view
                title: Date only
                embeds: preview-results-date-only
                ```
                """
        case "results-invalid":
            defaultContent = """
                ```embeds_results_view
                title: Unavailable results
                embeds: missing-ref, preview-results-invalid
                ```
                """
        default:
            defaultContent = "Svelte 5 runes are a new reactivity system that replaces the old `$:` reactive declarations.\n\n- **$state()** — Declares reactive state variables\n- **$derived()** — Creates computed values that update automatically\n- **$effect()** — Runs side effects when dependencies change\n- **$props()** — Declares component props\n\nThe migration is incremental — your existing Svelte 4 code will continue to work in compatibility mode."
        }
        let thinking = configuration.props["thinkingContent"]?.string ?? (variant == "thinking"
            ? "The user wants to migrate from Svelte 4 to Svelte 5. I should explain the key differences and provide a step-by-step migration approach. The most important change is the runes system."
            : nil)
        return Message(id: "preview-message", chatId: "preview-chat", role: role,
                       content: configuration.props["content"]?.string ?? defaultContent,
                       encryptedContent: nil, createdAt: "2026-07-09T12:00:00Z", updatedAt: nil,
                       appId: "code", isStreaming: false, embedRefs: nil,
                       modelName: role == .assistant ? "claude-sonnet-4-20250514" : nil,
                       thinkingContent: thinking)
    }

    private static let subChatFixtureChildren: [Chat] = {
        let created = "2026-07-09T12:00:15Z"
        func child(_ id: String, title: String, summary: String) -> Chat {
            Chat(id: id, title: title, lastMessageAt: created, createdAt: created,
                 updatedAt: created, isArchived: false, isPinned: false, appId: "finance",
                 category: "finance", icon: "dollar-sign", chatSummary: summary,
                 encryptedTitle: nil, encryptedChatKey: nil,
                 parentId: "preview-chat", isSubChat: true)
        }
        return [
            child("preview-egg-supply", title: "Research US egg supply recover",
                  summary: "Reviews avian-flu flock losses, slow repopulation timelines, and cage-free mandates as confirmed supply and regulatory cost drivers behind higher egg prices."),
            child("preview-egg-costs", title: "Research alternative economic",
                  summary: "Compares counterarguments around feed, labor, transport, and broad inflation, separating confirmed input-cost pressure from inferred explanations for sticky retail prices."),
            child("preview-egg-market", title: "Research market concentration",
                  summary: "Examines producer concentration, Cal-Maine margins, price-fixing allegations, and retailer markups to weigh confirmed profit data against inferred market-power claims."),
        ]
    }()

    private func fullscreen(_ active: EmbedRecord) -> some View {
        let resolvedActive = fixtureRecords[active.id] ?? active
        let siblings = EmbedGrouper.fullscreenNavigationEmbeds(
            selected: resolvedActive,
            messageEmbeds: configuration.variant == "withNavigation" ? parentNavigationEmbeds : [active],
            allRecords: fixtureRecords,
            parent: embedRoute.dropLast().last ?? (configuration.component == .embedFullscreen ? standaloneParent : nil)
        )
        return EmbedFullscreenContainer(embeds: siblings, initialEmbedId: active.id,
                                        allEmbedRecords: fixtureRecords, chatId: nil,
                                        onOpenEmbed: { child, parent in openChild(child, from: parent) },
                                        onClose: closeEmbed,
                                        highlightQuoteText: sourceQuoteTarget?.embedID == active.id ? sourceQuoteTarget?.text : nil)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-preview-embed-fullscreen")
            .accessibilityValue(active.id)
    }

    private func open(_ embed: EmbedRecord) {
        sourceQuoteTarget = nil
        embedRoute.append(embed)
        lastAction = "opened-\(embed.id)"
    }

    private func openChild(_ child: EmbedRecord, from parent: EmbedRecord) {
        if embedRoute.isEmpty && configuration.component == .embedFullscreen {
            standaloneParent = parent
        } else if !embedRoute.isEmpty {
            // The container may have navigated to a peer since this route was
            // opened. Minimize must restore that actual parent, not its seed.
            embedRoute[embedRoute.count - 1] = parent
        }
        open(child)
    }

    private func closeEmbed() {
        sourceQuoteTarget = nil
        if !embedRoute.isEmpty {
            embedRoute.removeLast()
        } else {
            standaloneFullscreenMinimized = true
        }
        lastAction = "embed-minimized"
    }
}

private struct DevComposerComponentFixture: View {
    let configuration: DevPreviewLaunchConfiguration
    let onAction: (String) -> Void
    @StateObject private var session: NativeComposerSession
    @State private var focused: Bool
    @State private var fixtureError: String?
    @StateObject private var focusModeManager = FocusModeManager()
    @State private var attachmentInstalled = false
    @State private var drawingOpen = false
    @State private var drawingFullscreen = false
    @State private var localDrawing: Data?

    init(configuration: DevPreviewLaunchConfiguration, onAction: @escaping (String) -> Void) {
        self.configuration = configuration
        self.onAction = onAction
        let text = configuration.props["text"]?.string
            ?? (configuration.variant == "filled" ? "Help me plan a weekend in Berlin." : "")
        _session = StateObject(wrappedValue: NativeComposerSession(canonicalMarkdown: text))
        _focused = State(initialValue: configuration.variant == "focused")
    }

    private var compact: Bool {
        configuration.variant == "default" && !focused && session.canonicalMarkdown.isEmpty
    }

    var body: some View {
        VStack {
            MessageComposerView(session: session, isFocused: $focused, compact: compact,
                                placeholder: configuration.props["placeholder"]?.string ?? AppStrings.whatDoYouNeedHelpWith,
                                compactHeight: 64, compactCornerRadius: 32,
                                showActionButtonsWhenCompact: false, maxWidth: nil,
                                isComposerEditable: configuration.variant != "disabled",
                                onSubmit: submit, preFieldContent: { EmptyView() },
                                overlayContent: {
                    #if os(iOS)
                    if drawingOpen {
                        SketchComposerOverlay(isFullscreen: $drawingFullscreen, onSave: saveDrawing,
                                              onCancel: { drawingOpen = false })
                            .accessibilityIdentifier("dev-preview-drawing-overlay")
                    }
                    #endif
                }) {
                ComposerAttachmentActionRow(viewportWidth: 390,
                    onDrawing: { drawingOpen = true; focused = false },
                    onLocation: { fixtureError = AppStrings.shareLocation },
                    onCamera: { fixtureError = AppStrings.takePhoto },
                    onFiles: addAttachment,
                    model: { EmptyView() }, speech: { EmptyView() }, record: { EmptyView() },
                    submit: { MessageComposerSendButton(title: AppStrings.sendAction,
                        disabled: session.canonicalMarkdown.isEmpty, action: submit) })
            }
            .overlay(alignment: .top) {
                FocusModePill(focusModeManager: focusModeManager,
                    onDeactivate: { _ in onAction("focus-deactivated") },
                    onOpen: { _ in onAction("focus-settings-opened") })
                    .offset(y: -30)
            }
            .padding(.top, configuration.variant == "focus" ? 15 : 0)

            if let fixtureError {
                Text(fixtureError).accessibilityIdentifier("dev-preview-action-error")
            }
        }
        .onAppear {
            if configuration.variant == "attachment" && !attachmentInstalled { addAttachment() }
            if configuration.variant == "focus", let focus = FocusModeManager.FocusModeInfo.resolve("workflows-clarify_workflows") {
                focusModeManager.activate(focus)
            }
            if configuration.variant == "recording-error" && !attachmentInstalled {
                attachmentInstalled = true
                let url = FileManager.default.temporaryDirectory.appendingPathComponent("audio-retry-preview-\(UUID().uuidString).m4a")
                defer { try? FileManager.default.removeItem(at: url) }
                do {
                    guard VoiceRecorder.writeUITestRecording(to: url) else { throw CocoaError(.fileWriteUnknown) }
                    let data = try Data(contentsOf: url)
                    try session.insertPendingEmbed(nodeID: "preview-failed-recording", embedType: "recording",
                        title: AppStrings.audioRecording, localPreviewData: data)
                    try session.updateEmbed(nodeID: "preview-failed-recording", status: AppleComposerEmbedLifecycleState.error.rawValue)
                    try session.configureEmbedActions(nodeID: "preview-failed-recording", onOpen: { _ in },
                        onRetry: { _ in
                            try? session.updateEmbed(nodeID: "preview-failed-recording", status: AppleComposerEmbedLifecycleState.finished.rawValue)
                            onAction("audio-retry-finished")
                        }, onRemove: { _ in onAction("audio-removed") })
                } catch { fixtureError = String(describing: error) }
            }
            if configuration.variant == "mentions" && !attachmentInstalled {
                attachmentInstalled = true
                do {
                    try session.controller.insertMention(.mention(id: "preview-focus-mention", mentionKind: "focus", targetId: "clarify_workflows", canonicalSyntax: "@focus:workflows:clarify_workflows", displayLabel: "Workflows-Clarify-Workflows"))
                    session.publishControllerState()
                } catch { fixtureError = String(describing: error) }
            }
        }
    }

    private func saveDrawing(_ data: Data, _ filename: String) {
        guard !data.isEmpty else { return }
        drawingOpen = false
        localDrawing = data
        do {
            try session.insertPendingEmbed(nodeID: "preview-drawing", embedType: "image", title: filename)
            try session.configureEmbedActions(nodeID: "preview-drawing", onOpen: { _ in drawingOpen = true },
                onRetry: { _ in }, onRemove: { _ in localDrawing = nil; onAction("drawing-removed") })
            onAction("drawing-attached-locally")
        } catch { fixtureError = "Unable to attach local drawing." }
    }

    private func addAttachment() {
        let id = "preview-composer-attachment"
        guard !session.controller.document.nodes.contains(where: { $0.id == id }) else { return }
        do {
            let record = DevEmbedPreviewFixtures.skills(for: .web)[0].primaryEmbed
            try session.insertPendingEmbed(nodeID: id, embedType: "app-skill-use", title: "Search")
            try session.resolveEmbed(nodeID: id, durableEmbedID: record.id, referenceType: "app-skill-use",
                                     status: "finished", embedRecord: record)
            try session.configureEmbedActions(nodeID: id,
                                              onOpen: { _ in onAction("attachment-opened-locally") },
                                              onRetry: { _ in onAction("attachment-retried-locally") },
                                              onRemove: { _ in onAction("attachment-removed") })
            attachmentInstalled = true
            onAction("attachment-added")
        } catch {
            fixtureError = "The local attachment fixture could not be created."
        }
    }

    private func submit() {
        guard configuration.variant != "disabled", !session.canonicalMarkdown.isEmpty else { return }
        session.clear()
        focused = false
        onAction("submitted-locally")
    }
}
// A small system capability control isolates Simulator Files-provider failures
// from the public MP3 download/export path. Uses no account or network data.
private struct DevNativeJSONExportControl: View {
    @State private var document: DevNativeJSONExportDocument?
    @State private var presented = false
    @State private var phase = "idle"
    private var zip: Bool { ProcessInfo.processInfo.environment["UI_TEST_NATIVE_EXPORT_FORMAT"] == "zip" }
    private var filename: String { zip ? "parity-export-control.zip" : "parity-export-control.json" }
    private static let messageContent = "Native ZIP Save fixture"
    private static let fileContent = "Native ZIP attachment fixture\n"
    var body: some View {
        Button(AppStrings.chatSettingsDownloadFiles) {
            Task { @MainActor in
                do {
                    let data = zip ? try await Self.makeZIP() : Data("{\"fixture\":\"parity-export-control\"}".utf8)
                    document = .init(data: data)
                    phase = zip ? "presenting;expected-bytes=\(data.count)" : "presenting"
                    presented = true
                } catch { phase = "failed" }
            }
        }.buttonStyle(OMPrimaryButtonStyle()).accessibilityIdentifier("native-export-control-open")
            .fileExporter(isPresented: $presented, document: document, contentType: zip ? .zip : .json, defaultFilename: filename) { result in
                switch result {
                case .success(let url):
                    let scoped = url.startAccessingSecurityScopedResource()
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    do {
                        let saved = try Data(contentsOf: url)
                        let matches = document.map { saved == $0.data } ?? false
                        phase = "saved=\(url.lastPathComponent);bytes=\(saved.count);content=\(matches ? "verified" : "mismatch")"
                        if zip {
                            let valid = try Self.validateZIP(saved)
                            phase += ";members=chat.md,chat.yaml,fixture.txt;archive-content=\(valid ? "verified" : "mismatch")"
                        } else {
                            let json = try JSONSerialization.jsonObject(with: saved) as? [String: String]
                            phase += ";json=\(json == ["fixture": "parity-export-control"] ? "verified" : "mismatch")"
                        }
                    } catch { phase = "failed" }
                case .failure: phase = "finished"
                }
                document = nil
            }
            .accessibilityValue(phase)
    }

    @MainActor
    private static func makeZIP() async throws -> Data {
        let chat = Chat(id: "native-export-fixture", title: "Native ZIP fixture", lastMessageAt: nil,
                        createdAt: "2026-01-01", updatedAt: nil, isArchived: false, isPinned: false,
                        appId: nil, encryptedTitle: nil, encryptedChatKey: nil)
        let message = Message(id: "native-export-message", chatId: chat.id, role: .user,
                              content: messageContent, encryptedContent: nil, createdAt: "2026-01-01",
                              updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        let file = EmbedRecord(id: "native-export-file", type: "code-code", status: .finished,
                               data: .raw(["filename": AnyCodable("fixture.txt"), "code": AnyCodable(fileContent)]),
                               parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
        return try await ChatSettingsExport.zip(chat: chat, messages: [message], embeds: [file],
                                                scope: nil, check: {})
    }

    private static func validateZIP(_ data: Data) throws -> Bool {
        let archive = try Archive(data: data, accessMode: .read)
        guard Set(archive.map(\.path)) == Set(["chat.md", "chat.yaml", "fixture.txt"]) else { return false }
        func content(_ name: String) throws -> Data {
            guard let entry = archive[name] else { throw CocoaError(.fileReadCorruptFile) }
            var bytes = Data()
            _ = try archive.extract(entry) { bytes.append($0) }
            return bytes
        }
        guard try content("fixture.txt") == Data(fileContent.utf8),
              try content("chat.md") == Data("## User\n\n\(messageContent)".utf8),
              let yaml = try Yams.load(yaml: String(decoding: content("chat.yaml"), as: UTF8.self)) as? [String: Any],
              yaml["chat_id"] as? String == "native-export-fixture",
              yaml["title"] as? String == "Native ZIP fixture",
              let messages = yaml["messages"] as? [[String: Any]], messages.count == 1 else { return false }
        return messages[0]["content"] as? String == messageContent && messages[0]["role"] as? String == "user"
    }
}
private struct DevNativeJSONExportDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json, .zip] }
    let data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadCorruptFile) }
        self.data = data
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}
#endif
