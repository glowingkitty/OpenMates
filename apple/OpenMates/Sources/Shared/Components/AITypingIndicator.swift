// AI typing indicator — shows which app/skill is currently processing.
// Mirrors aiTypingStore.ts: displays app icon with gradient and skill name.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//          (typing indicator block: app icon + skill name or "typing…")
// CSS:     frontend/packages/ui/src/styles/chat.css
//          .ai-typing-indicator (background, padding, layout)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct AITypingIndicator: View {
    let appId: String?
    let skillName: String?
    let isThinking: Bool
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    private var statusLabel: String {
        if isThinking {
            return LocalizationManager.shared.text("chat.thinking")
        } else if let skillName {
            return skillName
        } else {
            return LocalizationManager.shared.text("chat.typing")
        }
    }

    var body: some View {
        HStack(spacing: .spacing3) {
            if let appId {
                AppIconView(appId: appId, size: 24)
                    .pulse(isActive: !reduceMotion)
                    .accessibilityHidden(true)
            } else {
                Image("openmates-brand")
                    .renderingMode(.original)
                    .resizable()
                    .frame(width: 24, height: 24)
                    .clipShape(Circle())
                    .pulse(isActive: !reduceMotion)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: 0) {
                if isThinking {
                    Text(LocalizationManager.shared.text("chat.thinking"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                } else if let skillName {
                    Text(skillName)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                } else {
                    Text(LocalizationManager.shared.text("chat.typing"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }

            Spacer()
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey10)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(isThinking ? "AI is thinking" : skillName.map { "AI is running \($0)" } ?? "AI is typing")
    }
}

struct PulseModifier: ViewModifier {
    let isActive: Bool
    @State private var opacity: Double = 1.0
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    func body(content: Content) -> some View {
        content
            .opacity(opacity)
            .animation(
                (isActive && !reduceMotion) ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true) : .default,
                value: opacity
            )
            .onAppear { if isActive && !reduceMotion { opacity = 0.4 } }
    }
}

extension View {
    func pulse(isActive: Bool) -> some View {
        modifier(PulseModifier(isActive: isActive))
    }
}
