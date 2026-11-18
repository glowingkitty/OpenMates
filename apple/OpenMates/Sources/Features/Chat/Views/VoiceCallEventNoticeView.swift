// Voice-call start/end notice shown inline in the chat transcript.
// Web counterpart: frontend/packages/ui/src/components/VoiceCallEventNotice.svelte
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-events
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/VoiceCallEventNotice.svelte,
//         frontend/packages/ui/src/components/ChatMessage.svelte (.system-message-text)
// CSS:    inline row, gap 8px, 16px audiocall icon in primary start colour, xs grey-60 text
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/VoiceCallEventNotice.svelte (rendered by ChatMessage.svelte system message)
// CSS: .voice-call-event (inline-flex, gap spacing-2, grey-60), .call-icon (16px audiocall mask, primary-start),
//      ChatMessage .system-message-text (font-size xs, line-height 1.4).
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-events
import SwiftUI

/// Plain value model; the Rust core produces it from the synced call event.
/// Web shows no duration, so `activeElapsedSeconds` is carried but not rendered.
struct VoiceCallEventNoticeModel: Equatable {
    enum Action: String { case started, ended }
    let action: Action
    let createdAt: Date
    let activeElapsedSeconds: Int?

    /// Web: `i18n voice_call_events.<action>` followed by " – " and the locale time (2-digit hour/minute).
    /// The transcript notice for a stored system message, or nil when it is
    /// not a call notice. Parsing and validation live in the shared core.
    static func systemMessage(_ content: String) -> Self? {
        guard let notice = voiceCallNoticeFromMessage(role: "system", content: content) else { return nil }
        return .init(action: notice.action == .started ? .started : .ended,
                     createdAt: Date(timeIntervalSince1970: TimeInterval(notice.createdAt)),
                     activeElapsedSeconds: notice.activeElapsedSeconds.map { Int(clamping: $0) })
    }

    @MainActor var text: String {
        action == .started ? AppStrings.voiceCallEventStarted : AppStrings.voiceCallEventEnded
    }

    func timeText(locale: Locale = .current, timeZone: TimeZone = .current) -> String {
        // Matches web toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}).
        createdAt.formatted(Date.FormatStyle(locale: locale, timeZone: timeZone)
            .hour(.twoDigits(amPM: .abbreviated)).minute(.twoDigits))
    }

    @MainActor func line(locale: Locale = .current, timeZone: TimeZone = .current) -> String {
        "\(text) – \(timeText(locale: locale, timeZone: timeZone))"
    }
}

struct VoiceCallEventNoticeView: View {
    let model: VoiceCallEventNoticeModel

    var body: some View {
        HStack(spacing: .spacing2) {
            Icon("audiocall", size: 16)
                .foregroundStyle(Color.settingsPrimaryStart)
                .accessibilityHidden(true)
            // Web inherits body --font-weight-p (500) for the notice text.
            Text(model.line())
                .font(.omXs.weight(.medium))
        }
        .foregroundStyle(Color.grey60)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("voice-call-event-notice-\(model.action.rawValue)")
    }
}
