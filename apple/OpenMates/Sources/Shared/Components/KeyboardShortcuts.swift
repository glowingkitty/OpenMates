// Keyboard shortcuts — global keyboard command bindings for iPad and Mac.
// Mirrors the web app's KeyboardShortcuts.svelte: new chat, search, settings,
// send message, close fullscreen, and navigation shortcuts.

import SwiftUI

struct KeyboardShortcutModifier: ViewModifier {
    let onNewChat: () -> Void
    let onSearch: () -> Void
    let onSettings: () -> Void

    func body(content: Content) -> some View {
        content
            .keyboardShortcut("n", modifiers: .command)
            .onKeyPress(.init("n"), modifiers: .command) {
                onNewChat()
                return .handled
            }
            .onKeyPress(.init("k"), modifiers: .command) {
                onSearch()
                return .handled
            }
            .onKeyPress(.init(","), modifiers: .command) {
                onSettings()
                return .handled
            }
    }
}

extension View {
    func appKeyboardShortcuts(
        onNewChat: @escaping () -> Void,
        onSearch: @escaping () -> Void,
        onSettings: @escaping () -> Void
    ) -> some View {
        self.modifier(KeyboardShortcutModifier(
            onNewChat: onNewChat,
            onSearch: onSearch,
            onSettings: onSettings
        ))
    }
}

// MARK: - Shortcuts help overlay

struct KeyboardShortcutsHelp: View {
    @Environment(\.dismiss) var dismiss

    private let shortcuts: [(String, String)] = [
        ("⌘ N", "New chat"),
        ("⌘ K", "Search chats"),
        ("⌘ ,", "Settings"),
        ("⌘ ↩", "Send message"),
        ("Esc", "Close fullscreen / dismiss"),
        ("⌘ ⇧ I", "Toggle incognito mode"),
        ("⌘ .", "Stop AI response"),
    ]

    var body: some View {
        NavigationStack {
            List {
                Section("Keyboard Shortcuts") {
                    ForEach(shortcuts, id: \.0) { shortcut, description in
                        HStack {
                            Text(shortcut)
                                .font(.system(.body, design: .monospaced))
                                .fontWeight(.medium)
                                .foregroundStyle(Color.buttonPrimary)
                                .frame(width: 80, alignment: .leading)
                            Text(description)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontPrimary)
                        }
                    }
                }
            }
            .navigationTitle("Shortcuts")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
