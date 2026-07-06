// OpenMates Watch app entry point.
// Defines the independent watchOS application scene for the standalone Watch
// client. The target intentionally starts with only app plumbing; pair login,
// chat sync, audio input, and embed previews are added by later spec tasks.
// Keep this file free of business logic so shared runtime can remain testable.
// User-visible copy belongs in localized view layers, never in the app entry.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@main
struct OpenMatesWatchApp: App {
    var body: some Scene {
        WindowGroup {
            WatchRootView()
        }
    }
}
