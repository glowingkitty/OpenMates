// Widget-local typed localization bridge using the generated web JSON resources.
// No network requests, private account content or main-app dependencies.

import Foundation

private final class TasksWidgetTranslationCache: @unchecked Sendable {
    static let shared = TasksWidgetTranslationCache()
    private let lock = NSLock()
    private var locales: [String: [String: String]] = [:]

    func text(_ key: String, locale: String) -> String? {
        lock.lock()
        defer { lock.unlock() }
        if locales[locale] == nil { locales[locale] = load(locale) }
        return locales[locale]?[key]
    }

    private func load(_ locale: String) -> [String: String] {
        let folders: [String?] = ["i18n", "locales", "i18n/locales", nil]
        for folder in folders {
            guard let url = Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: folder),
                  let data = try? Data(contentsOf: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            var result: [String: String] = [:]
            func visit(_ dictionary: [String: Any], prefix: String) {
                for (key, value) in dictionary {
                    let path = prefix.isEmpty ? key : "\(prefix).\(key)"
                    if let wrapper = value as? [String: Any], let text = wrapper["text"] as? String { result[path] = text }
                    else if let child = value as? [String: Any] { visit(child, prefix: path) }
                    else if let text = value as? String { result[path] = text }
                }
            }
            visit(json, prefix: "")
            return result
        }
        return [:]
    }
}

enum WidgetStrings {
    static func text(_ key: String, languageKey: String) -> String {
        let preferred = UserDefaults(suiteName: "group.org.openmates.app.shared")?.string(forKey: languageKey)
            ?? Locale.preferredLanguages.first ?? "en"
        let locale = preferred.split(whereSeparator: { $0 == "-" || $0 == "_" }).first.map(String.init) ?? "en"
        if let text = TasksWidgetTranslationCache.shared.text(key, locale: locale)
            ?? TasksWidgetTranslationCache.shared.text(key, locale: "en") { return text }
        // Canonical additions are also authored in the Widget String Catalog;
        // use its compiled locale while the web locale build is deferred.
        for candidate in [locale, "en"] {
            if let path = Bundle.main.path(forResource: candidate, ofType: "lproj"), let bundle = Bundle(path: path) {
                let translated = bundle.localizedString(forKey: key, value: nil, table: nil)
                if translated != key { return translated }
            }
        }
        return Bundle.main.localizedString(forKey: key, value: nil, table: nil)
    }
}
enum TasksWidgetStrings {
    private static func text(_ key: String) -> String { WidgetStrings.text(key, languageKey: "widget_tasks_language") }
    static var title: String { text("apple.tasks_widget.title") }
    static var description: String { text("apple.tasks_widget.description") }
    static var statusParameter: String { text("apple.tasks_widget.status_parameter") }
    static var empty: String { text("apple.tasks_widget.empty") }
    static var openApp: String { text("apple.tasks_widget.open_app") }
    static var newTask: String { text("apple.tasks_widget.new_task") }
    static func status(_ status: WidgetTaskFilter) -> String {
        status == .all ? text("apple.tasks_widget.all") : text("tasks.workspace.\(status.rawValue)")
    }
}
