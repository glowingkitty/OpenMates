// Theme manager — mirrors the web app's theme.ts three-mode system.
// Supports auto (follows OS), light, and dark modes.
// Persists preference and syncs with backend user settings.

import SwiftUI

@MainActor
final class ThemeManager: ObservableObject {
    @AppStorage("themeMode") var themeMode: ThemeMode = .auto

    enum ThemeMode: String, CaseIterable {
        case auto
        case light
        case dark
    }

    var resolvedScheme: ColorScheme? {
        switch themeMode {
        case .auto: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }

    func setTheme(_ mode: ThemeMode) {
        themeMode = mode

        Task {
            let darkmode = mode == .dark || (mode == .auto && isDarkSystemAppearance())
            try? await APIClient.shared.request(
                .post,
                path: "/v1/settings/user/darkmode",
                body: ["darkmode": darkmode]
            ) as Data
        }
    }

    private func isDarkSystemAppearance() -> Bool {
        #if os(iOS)
        return UITraitCollection.current.userInterfaceStyle == .dark
        #elseif os(macOS)
        return NSApplication.shared.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        #else
        return false
        #endif
    }
}
