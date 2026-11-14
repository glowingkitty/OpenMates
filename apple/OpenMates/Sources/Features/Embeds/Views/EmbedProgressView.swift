// EmbedProgressView — live status line of a running app-skill embed ("2/4 · 17 results").
// The server re-sends the "processing" embed with a `progress` object; the Rust core
// (`embed_read::progress`, UniFFI `embedProgressParse/Next/Line`) validates frames, keeps the
// highest `seq` and picks the translation key. This file only decodes the dictionary to JSON,
// translates the returned key and draws one line.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/embedProgress.ts
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte (status line)
//          frontend/packages/ui/src/components/embeds/EmbedProgressFixture.svelte
// CSS:     BasicInfosBar.svelte <style> status text
// Tokens:  ColorTokens.generated.swift (fontSecondary), TypographyTokens.generated.swift (omXs)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/architecture/app-skill-execution/specification.yml
// Assertions: app-skills.progress.live-status

import SwiftUI

/// Presentation of one progress frame: the translated text only.
struct EmbedProgressPresentation: Equatable, Sendable {
    let text: String
}

/// Keeps the newest progress frame of one embed across repeated "processing" updates.
@MainActor
struct EmbedProgressTracker {
    private(set) var current: EmbedProgressRecord?

    /// Feed the decoded embed content (`data["progress"]`); returns true when the frame changed.
    @discardableResult
    mutating func update(from data: [String: AnyCodable]?) -> Bool {
        guard let raw = data?["progress"]?.value,
              JSONSerialization.isValidJSONObject(raw),
              let json = try? JSONSerialization.data(withJSONObject: raw),
              let text = String(data: json, encoding: .utf8) else { return false }
        let next = embedProgressNext(current: current, incoming: embedProgressParse(progressJson: text))
        guard next != current else { return false }
        current = next
        return true
    }

    /// Translated status line, or nil while no valid frame arrived (skills that report nothing).
    var presentation: EmbedProgressPresentation? {
        guard let current else { return nil }
        return Self.present(embedProgressLine(progress: current))
    }

    /// Translate a core line: key through `LocalizationManager`, numeric values as replacements.
    static func present(_ line: EmbedProgressLineRecord) -> EmbedProgressPresentation {
        var replacements: [String: String] = [:]
        for (name, value) in zip(line.valueNames, line.valueNumbers) {
            replacements[name] = String(value)
        }
        let translated = LocalizationManager.shared.text(line.key, replacements: replacements)
        return EmbedProgressPresentation(text: line.prefix + translated)
    }
}

struct EmbedProgressView: View {
    let presentation: EmbedProgressPresentation

    var body: some View {
        Text(presentation.text)
            .font(.omXs)
            .foregroundStyle(Color.fontSecondary)
            .lineLimit(1)
            .accessibilityIdentifier("embed-progress-status")
    }
}
