// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// System Control actions share target membership with the app and widget extension.
// Uses existing quick actions and workflow capability issuance; no inference in the extension.
import AppIntents
import Foundation

struct OpenMatesQuickControlIntent: AppIntent {
    static let title: LocalizedStringResource = "OpenMates"
    static let openAppWhenRun = true
    static let authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication
    @Parameter(title: "apple.controls.action") var action: String
    init() {}
    init(action: String) { self.action = action }
    @MainActor func perform() async throws -> some IntentResult {
        #if !OPENMATES_WIDGET_EXTENSION
        guard let action = AppQuickAction(rawValue: action) else { throw CancellationError() }
        AppQuickActionCenter.shared.perform(action)
        #if os(macOS)
        if !AppWindowCommandCenter.shared.restoreMainWindow() { AppWindowCommandCenter.shared.openNewWindow() }
        #endif
        #endif
        return .result()
    }
}
struct OpenMatesWorkflowControlIntent: AppIntent {
    static let title: LocalizedStringResource = "apple.workflows_widget.run"
    static let openAppWhenRun = true
    static let authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication
    @Parameter(title: "apple.workflows_widget.workflow_parameter") var identifier: String
    init() {}
    init(identifier: String) { self.identifier = identifier }
    @MainActor func perform() async throws -> some IntentResult {
        #if !OPENMATES_WIDGET_EXTENSION
        if identifier.isEmpty { ExternalLinkDeliveryCenter.shared.receive(WidgetWorkflowsLinks.workspace) }
        else { _ = try await RunWidgetWorkflowIntent(identifier: identifier).perform() }
        #if os(macOS)
        if !AppWindowCommandCenter.shared.restoreMainWindow() { AppWindowCommandCenter.shared.openNewWindow() }
        #endif
        #endif
        return .result()
    }
}
struct OpenMatesProjectControlIntent: AppIntent {
    static let title: LocalizedStringResource = "navigation.projects"
    static let openAppWhenRun = true
    static let authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication
    @Parameter(title: "navigation.projects") var identifier: String
    init() {}
    init(identifier: String) { self.identifier = identifier }
    @MainActor func perform() async throws -> some IntentResult {
        #if !OPENMATES_WIDGET_EXTENSION
        let url: URL
        if identifier.isEmpty { url = URL(string: "openmates://projects")! }
        else {
            let route = ControlProjectRoute(identifier: identifier)
            guard let snapshot = ControlProjectsStorage.shared.load(), route.project(in: snapshot) != nil,
                  let target = route.url else { throw CancellationError() }
            url = target
        }
        ExternalLinkDeliveryCenter.shared.receive(url)
        #if os(macOS)
        if !AppWindowCommandCenter.shared.restoreMainWindow() { AppWindowCommandCenter.shared.openNewWindow() }
        #endif
        #endif
        return .result()
    }
}
