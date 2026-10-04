// Widget-local strings from generated web locale resources and the Widget string catalog.
import Foundation

enum WorkflowsWidgetStrings {
    private static func text(_ key: String) -> String { WidgetStrings.text(key, languageKey: WidgetWorkflowsStorage.languageKey) }
    static var title: String { text("apple.workflows_widget.title") }
    static var description: String { text("apple.workflows_widget.description") }
    static var choose: String { text("apple.workflows_widget.choose") }
    static var openApp: String { text("apple.workflows_widget.open_app") }
    static var run: String { text("apple.workflows_widget.run") }
}
