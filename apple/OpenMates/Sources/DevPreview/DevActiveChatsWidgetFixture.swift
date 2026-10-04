// Detached production widget content and real accepted processing lifecycle.
// All storage/key material belongs to this fixture's random defaults suite.
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.activity.global-running
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation
#if DEBUG
import CryptoKit
import SwiftUI
import WidgetKit

@MainActor
private final class ActiveChatsWidgetFixtureDriver: ObservableObject {
    @Published var snapshot: WidgetActiveChatsSnapshot?
    private let suite: String
    private let defaults: UserDefaults
    private let storage: WidgetActiveChatsStorage
    private let coordinator: ActiveChatsCoordinator
    private let bridge: ActiveChatsWidgetBridge
    private let time = Date()
    init() {
        suite = "DevActiveChatsWidgetFixture-" + UUID().uuidString
        defaults = UserDefaults(suiteName: suite)!
        let key = SymmetricKey(size: .bits256)
        storage = WidgetActiveChatsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: {})
        var acceptedScope: ActiveChatsScope?
        let localBridge = ActiveChatsWidgetBridge(storage: storage, reload: {}, currentScope: { acceptedScope })
        bridge = localBridge
        coordinator = ActiveChatsCoordinator(publishWidgetSnapshot: { policy, scope, evidence in
                acceptedScope = scope
                localBridge.publish(policy, scope: scope, authoritative: evidence)
            })
        coordinator.configure(accountID: "fixture-account", server: .development, scope: UUID(),
            team: .init(epoch: 1, teamID: "fixture-team"), authenticated: true)
        coordinator.reconcileActiveChats((1...9).map { .init(chatID: "fixture-\($0)", turnID: "turn-\($0)") },
            scope: coordinator.currentScope!, now: time)
        snapshot = storage.load()
    }
    func completeFirst() {
        guard let scope = coordinator.currentScope else { return }
        coordinator.finished(chatID: "fixture-1", turnID: "turn-1", scope: scope)
        snapshot = storage.load()
    }
    func logout() { coordinator.reset(); snapshot = storage.load() }
    func cleanup() { coordinator.reset(); defaults.removePersistentDomain(forName: suite) }
}

struct DevActiveChatsWidgetFixture: View {
    @StateObject private var driver = ActiveChatsWidgetFixtureDriver()
    @State private var route = "none"
    @State private var family: WidgetFamily = .systemMedium
    private var labels: WidgetActiveChatsLabels {
        .init(title: LocalizationManager.shared.text("chats.activity.heading"),
            total: AppStrings.activeChatsWidgetTotal(count: driver.snapshot?.chats.count ?? 0),
            empty: localized("empty"), openApp: localized("open_app"),
            viewAll: localized("view_all"), stale: localized("stale"))
    }
    var body: some View {
        VStack(spacing: .spacing4) {
            Group {
                #if os(iOS)
                if family == .accessoryCircular || family == .accessoryRectangular {
                    WidgetActiveChatsAccessoryView(snapshot: driver.snapshot, date: Date(), family: family, labels: labels)
                        .frame(width: family == .accessoryCircular ? 72 : 180, height: 72)
                } else {
                    homeContent
                }
                #else
                homeContent
                #endif
            }
                .environment(\.openURL, OpenURLAction { url in
                    if let link = WidgetActiveChatsLinks.route(url),
                       link.belongsTo(accountID: "fixture-account", apiBaseURL: ServerProfile.development.apiBaseURL, teamID: "fixture-team") {
                        switch link.destination {
                        case .chat(let id): route = "chat:" + id
                        case .all: route = "all"
                        }
                    } else { route = "app" }
                    return .handled
                })
            Text(route).accessibilityIdentifier("active-chats-fixture-route")
            Button("Complete first") { driver.completeFirst() }.accessibilityIdentifier("active-chats-fixture-complete")
            Button("Large family") { family = .systemLarge }.accessibilityIdentifier("active-chats-fixture-large")
            #if os(iOS)
            Button("Circular family") { family = .accessoryCircular }.accessibilityIdentifier("active-chats-fixture-circular")
            Button("Rectangular family") { family = .accessoryRectangular }.accessibilityIdentifier("active-chats-fixture-rectangular")
            #endif
            Button("Log out") { driver.logout() }.accessibilityIdentifier("active-chats-fixture-logout")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // Give the fixture its own AX container so its identifier does not
        // replace the production widget container or the rendered control IDs.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("active-chats-widget-fixture")
        .onDisappear { driver.cleanup() }
    }
    private var homeContent: some View {
        WidgetActiveChatsContentView(snapshot: driver.snapshot, date: Date(),
            rowLimit: WidgetActiveChatsProjection.rowLimit(for: family), labels: labels)
            .padding(.spacing4).frame(width: 320, height: family == .systemLarge ? 360 : 220)
            .background(Color.grey0)
    }
    private func localized(_ key: String) -> String { LocalizationManager.shared.text("apple.active_chats_widget." + key) }
}
#endif
