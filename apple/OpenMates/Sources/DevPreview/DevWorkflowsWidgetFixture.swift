// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// Detached production widget rendering and real foreground-intent delivery helper.
// Random synthetic storage and a fixture-only sink perform no network requests.
#if DEBUG
import CryptoKit
import SwiftUI

@MainActor
private final class WorkflowsWidgetFixtureDriver: ObservableObject {
    @Published var snapshot: WidgetWorkflowsSnapshot?
    @Published var route = "none"
    let identifier: String
    private let defaults: UserDefaults
    private let storage: WidgetWorkflowsStorage
    private let suite = "DevWorkflowsWidgetFixture-" + UUID().uuidString
    init() {
        defaults = UserDefaults(suiteName: suite)!
        let key = SymmetricKey(size: .bits256)
        storage = WidgetWorkflowsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: {})
        let owner = WidgetWorkflowsOwner.identity(accountID: suite, apiBaseURL: ServerProfile.development.apiBaseURL, teamID: "fixture-team")
        identifier = owner + ":fixture-workflow"
        storage.activate(owner: owner)
        try? storage.save(.init(owner: owner, teamID: "fixture-team", updatedAt: Date(), workflows: [
            .init(id: "fixture-workflow", title: "Synthetic morning report", versionID: "fixture-version")]))
        snapshot = storage.load()
        RunWidgetWorkflowIntent.fixtureActions[identifier] = { [weak self] in
            guard let self else { throw CancellationError() }
            try RunWidgetWorkflowIntent.deliver(identifier: self.identifier, storage: self.storage, receive: { url in
                guard let typed = WidgetWorkflowsLinks.route(url), self.storage.issuedVersion(typed) == "fixture-version" else { return }
                self.route = "run:fixture-workflow;issued=true"
            })
        }
    }
    func invalidate() { storage.clear(); snapshot = storage.load() }
    func cleanup() { RunWidgetWorkflowIntent.fixtureActions.removeValue(forKey: identifier); storage.clear(); defaults.removePersistentDomain(forName: suite) }
}
struct DevWorkflowsWidgetFixture: View {
    @StateObject private var driver = WorkflowsWidgetFixtureDriver()
    @State private var controlResult = "none"
    private var labels: WidgetWorkflowsLabels {
        .init(title: text("title"), choose: text("choose"), openApp: text("open_app"), run: text("run"))
    }
    var body: some View {
        VStack(spacing: .spacing4) {
            WidgetWorkflowsContentView(workflow: driver.snapshot?.workflows.first,
                identifier: driver.snapshot == nil ? nil : driver.identifier, hasSnapshot: driver.snapshot != nil,
                compact: false, labels: labels)
                .padding(.spacing4).frame(width: 300, height: 180).background(Color.grey0)
            Text(driver.route).accessibilityIdentifier("workflows-fixture-route")
            if ProcessInfo.processInfo.arguments.contains("--dev-controls-fixture") {
                ForEach(["ask", "newTask", "recordRequest", "askAboutPhoto", "search", "incognitoAsk"], id: \.self) { action in
                    Button(action) {
                        Task { @MainActor in
                            do {
                                _ = try await OpenMatesQuickControlIntent(action: action).perform()
                                controlResult = AppQuickActionCenter.shared.consumePendingAction()?.rawValue ?? "missing"
                            } catch { controlResult = "failed" }
                        }
                    }.buttonStyle(.plain).accessibilityIdentifier("control-fixture-" + action)
                }
                Button("Run configured workflow control") {
                    Task { @MainActor in
                        do { _ = try await OpenMatesWorkflowControlIntent(identifier: driver.identifier).perform() }
                        catch { controlResult = "unavailable" }
                    }
                }.buttonStyle(.plain).accessibilityIdentifier("control-fixture-workflow")
                Text(controlResult).accessibilityIdentifier("control-fixture-result")
            }
            Button("Invalidate fixture") { driver.invalidate() }.buttonStyle(.plain)
                .accessibilityIdentifier("workflows-fixture-invalidate")
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("workflows-widget-fixture")
            .onDisappear { driver.cleanup() }
    }
    private func text(_ key: String) -> String { LocalizationManager.shared.text("apple.workflows_widget." + key) }
}
#endif
