// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// OS-owned controls use SF Symbols and system layout per Apple Controls guidance.
import AppIntents
import SwiftUI
import WidgetKit

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesNewChatControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.ask") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "ask")) {
                Label(WidgetStrings.text("activity.quick_action_ask", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "square.and.pencil")
            }
        }.displayName("activity.quick_action_ask")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesNewTaskControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.newTask") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "newTask")) {
                Label(WidgetStrings.text("tasks.workspace.new_task", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "checklist")
            }
        }.displayName("tasks.workspace.new_task")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesPhotoControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.askAboutPhoto") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "askAboutPhoto")) {
                Label(WidgetStrings.text("activity.quick_action_ask_about_photo", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "camera")
            }
        }.displayName("activity.quick_action_ask_about_photo")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesRecordingControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.recordRequest") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "recordRequest")) {
                Label(WidgetStrings.text("activity.quick_action_record_request", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "mic")
            }
        }.displayName("activity.quick_action_record_request")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesSearchControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.search") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "search")) {
                Label(WidgetStrings.text("activity.search", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "magnifyingglass")
            }
        }.displayName("activity.search")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesIncognitoControl: ControlWidget {
    // Each concrete type has its own parameterless system factory and fixed route.
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "org.openmates.control.incognitoAsk") {
            ControlWidgetButton(action: OpenMatesQuickControlIntent(action: "incognitoAsk")) {
                Label(WidgetStrings.text("activity.quick_action_incognito_ask", languageKey: WidgetWorkflowsStorage.languageKey), systemImage: "eye.slash")
            }
        }.displayName("activity.quick_action_incognito_ask")
    }
}
@available(iOS 18.0, macOS 26.0, *)
struct WorkflowControlConfiguration: ControlConfigurationIntent {
    static let title: LocalizedStringResource = "apple.workflows_widget.title"
    @Parameter(title: "apple.workflows_widget.workflow_parameter") var workflow: WidgetWorkflowEntity?
}
@available(iOS 18.0, macOS 26.0, *)
struct ProjectControlConfiguration: ControlConfigurationIntent {
    static let title: LocalizedStringResource = "navigation.projects"
    @Parameter(title: "navigation.projects") var project: ControlProjectEntity?
}
struct OpenMatesControlValue: Sendable { let identifier: String; let title: String }
@available(iOS 18.0, macOS 26.0, *)
struct WorkflowControlProvider: AppIntentControlValueProvider {
    func previewValue(configuration: WorkflowControlConfiguration) -> OpenMatesControlValue {
        .init(identifier: "", title: WorkflowsWidgetStrings.title)
    }
    func currentValue(configuration: WorkflowControlConfiguration) async throws -> OpenMatesControlValue {
        let id = configuration.workflow?.id ?? ""
        let item = try await WidgetWorkflowEntityQuery().entities(for: [id]).first
        // Preserve a stale configured identifier so a missing choice can never run a fallback workflow.
        return .init(identifier: id, title: item?.title ?? WorkflowsWidgetStrings.title)
    }
}
@available(iOS 18.0, macOS 26.0, *)
struct ProjectControlProvider: AppIntentControlValueProvider {
    func previewValue(configuration: ProjectControlConfiguration) -> OpenMatesControlValue {
        .init(identifier: "", title: WidgetStrings.text("navigation.projects", languageKey: WidgetWorkflowsStorage.languageKey))
    }
    func currentValue(configuration: ProjectControlConfiguration) async throws -> OpenMatesControlValue {
        let id = configuration.project?.id ?? ""
        let item = try await ControlProjectQuery().entities(for: [id]).first
        return .init(identifier: id, title: item?.title ?? previewValue(configuration: configuration).title)
    }
}
@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesWorkflowControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        AppIntentControlConfiguration(kind: "org.openmates.control.workflow", provider: WorkflowControlProvider()) { value in
            ControlWidgetButton(action: OpenMatesWorkflowControlIntent(identifier: value.identifier)) {
                Label(value.title, systemImage: "play.fill")
            }.privacySensitive()
        }.displayName("apple.workflows_widget.title")
    }
}
@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesProjectControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        AppIntentControlConfiguration(kind: "org.openmates.control.project", provider: ProjectControlProvider()) { value in
            ControlWidgetButton(action: OpenMatesProjectControlIntent(identifier: value.identifier)) {
                Label(value.title, systemImage: "folder")
            }.privacySensitive()
        }.displayName("navigation.projects")
    }
}

@available(iOS 18.0, macOS 26.0, *)
struct OpenMatesControlsBundle: WidgetBundle {
    var body: some Widget {
            OpenMatesNewChatControl()
            OpenMatesNewTaskControl()
            OpenMatesPhotoControl()
            OpenMatesRecordingControl()
            OpenMatesSearchControl()
            OpenMatesIncognitoControl()
            OpenMatesWorkflowControl()
            OpenMatesProjectControl()
    }
}
