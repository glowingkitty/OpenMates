// LocalizedText — SwiftUI view that reactively displays translated strings.
// Subscribes to LocalizationManager so text updates when language changes.

import SwiftUI

struct LocalizedText: View {
    let keyPath: String
    let replacements: [String: String]
    @ObservedObject private var manager = LocalizationManager.shared

    init(_ keyPath: String, replacements: [String: String] = [:]) {
        self.keyPath = keyPath
        self.replacements = replacements
    }

    var body: some View {
        Text(manager.text(keyPath, replacements: replacements))
    }
}

// MARK: - Convenience initializer for common patterns

extension LocalizedText {
    init(_ keyPath: String, _ singleReplacement: (String, String)) {
        self.keyPath = keyPath
        self.replacements = [singleReplacement.0: singleReplacement.1]
    }
}

// MARK: - Environment-based layout direction modifier

struct RTLAwareModifier: ViewModifier {
    @ObservedObject private var manager = LocalizationManager.shared

    func body(content: Content) -> some View {
        content
            .environment(\.layoutDirection, manager.currentLanguage.layoutDirection)
    }
}

extension View {
    func rtlAware() -> some View {
        modifier(RTLAwareModifier())
    }
}
