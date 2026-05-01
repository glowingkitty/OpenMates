// Localization manager — loads and serves translated strings from the web app's i18n JSON files.
// Supports 21 languages with on-demand loading. Falls back to English for missing keys.
// Handles RTL layout direction for Arabic and Hebrew.

import SwiftUI

@MainActor
final class LocalizationManager: ObservableObject {
    static let shared = LocalizationManager()

    @Published private(set) var currentLanguage: SupportedLanguage = .en
    @Published private(set) var isRTL: Bool = false
    @Published private(set) var isLoading: Bool = false

    private var translations: [String: Any] = [:]
    private var fallbackTranslations: [String: Any] = [:]
    private var loadedLocale: String?

    private init() {
        if let bundled = loadBundledJSON(locale: "en") {
            fallbackTranslations = bundled
            translations = bundled
            loadedLocale = "en"
        }
    }

    // MARK: - Language switching

    func setLanguage(_ language: SupportedLanguage) async {
        guard language != currentLanguage || loadedLocale != language.code else { return }
        isLoading = true

        if language.code == "en" {
            translations = fallbackTranslations
        } else {
            if let loaded = await fetchTranslations(locale: language.code) {
                translations = loaded
            } else if let bundled = loadBundledJSON(locale: language.code) {
                translations = bundled
            }
        }

        currentLanguage = language
        isRTL = language.isRTL
        loadedLocale = language.code

        UserDefaults.standard.set(language.code, forKey: "app_language")
        isLoading = false
    }

    func restoreSavedLanguage() async {
        if let saved = UserDefaults.standard.string(forKey: "app_language"),
           let language = SupportedLanguage.from(code: saved) {
            await setLanguage(language)
        }
    }

    // MARK: - Translation lookup

    func text(_ keyPath: String) -> String {
        if let value = resolveKeyPath(keyPath, in: translations) {
            return value
        }
        if let value = resolveKeyPath(keyPath, in: fallbackTranslations) {
            return value
        }
        return keyPath
    }

    func text(_ keyPath: String, replacements: [String: String]) -> String {
        var result = text(keyPath)
        for (placeholder, value) in replacements {
            result = result.replacingOccurrences(of: "{\(placeholder)}", with: value)
        }
        return result
    }

    // MARK: - Key path resolution

    private func resolveKeyPath(_ keyPath: String, in dict: [String: Any]) -> String? {
        let components = keyPath.split(separator: ".").map(String.init)
        var current: Any = dict

        for component in components {
            guard let dict = current as? [String: Any],
                  let next = dict[component] else { return nil }
            current = next
        }

        // The web app JSON uses {"text": "..."} wrappers
        if let textDict = current as? [String: Any], let text = textDict["text"] as? String {
            return text
        }
        if let text = current as? String {
            return text
        }
        return nil
    }

    // MARK: - JSON loading

    private func loadBundledJSON(locale: String) -> [String: Any]? {
        for url in candidateTranslationURLs(locale: locale) {
            guard let data = try? Data(contentsOf: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue
            }
            return json
        }
        return nil
    }

    private func candidateTranslationURLs(locale: String) -> [URL] {
        var urls: [URL] = []

        // 1. Bundle resource (for release builds — copied by Xcode build phase)
        if let bundled = Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: "i18n") {
            urls.append(bundled)
        }
        if let flatBundled = Bundle.main.url(forResource: locale, withExtension: "json") {
            urls.append(flatBundled)
        }

        // 2. Web app generated locales (for dev/simulator — built from YML sources by npm run build:translations)
        let sourceFile = URL(fileURLWithPath: #filePath)
        let repoRoot = sourceFile
            .deletingLastPathComponent() // I18n/
            .deletingLastPathComponent() // Core/
            .deletingLastPathComponent() // Sources/
            .deletingLastPathComponent() // OpenMates/
            .deletingLastPathComponent() // apple/
        urls.append(repoRoot.appendingPathComponent("frontend/packages/ui/src/i18n/locales/\(locale).json"))

        return urls
    }

    private func fetchTranslations(locale: String) async -> [String: Any]? {
        do {
            let url = await APIClient.shared.webAppURL
                .appendingPathComponent("i18n/locales/\(locale).json")
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else { return nil }
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        } catch {
            print("[I18n] Failed to fetch \(locale): \(error)")
            return nil
        }
    }
}

// MARK: - SwiftUI Environment

private struct LocalizationManagerKey: @preconcurrency EnvironmentKey {
    @MainActor static let defaultValue = LocalizationManager.shared
}

extension EnvironmentValues {
    var localization: LocalizationManager {
        get { self[LocalizationManagerKey.self] }
        set { self[LocalizationManagerKey.self] = newValue }
    }
}

// MARK: - View helper

extension View {
    func localized(_ keyPath: String) -> String {
        LocalizationManager.shared.text(keyPath)
    }
}
