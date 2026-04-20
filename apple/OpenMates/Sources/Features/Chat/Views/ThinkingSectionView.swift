// Thinking section — expandable display of AI reasoning/thinking content.
// Mirrors the web app's ThinkingSection.svelte: collapsible section that shows
// the AI's chain-of-thought when the model returns thinking blocks.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ThinkingSection.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ThinkingSectionView: View {
    let content: String
    @State private var isExpanded = false
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(reduceMotion ? .none : .easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: .spacing2) {
                    Icon("reasoning", size: 14)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)

                    Text(LocalizationManager.shared.text("chat.thinking.header_done"))
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontTertiary)

                    Spacer()

                    Icon(isExpanded ? "up" : "down", size: 12)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing2)
            }
            .buttonStyle(.plain)
            .accessibleButton(
                isExpanded ? "Collapse AI reasoning" : "Expand AI reasoning",
                hint: isExpanded ? "Hides the chain-of-thought" : "Shows the AI's reasoning steps"
            )

            if isExpanded {
                Text(content)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing3)
                    .padding(.bottom, .spacing3)
                    .textSelection(.enabled)
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

// MARK: - Streaming thinking indicator

struct ThinkingIndicator: View {
    @State private var dotCount = 0
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: .spacing2) {
            Icon("reasoning", size: 14)
                .foregroundStyle(Color.fontTertiary)
                .accessibilityHidden(true)

            Text(LocalizationManager.shared.text("chat.thinking.header_streaming") + String(repeating: ".", count: dotCount))
                .font(.omXs).fontWeight(.medium)
                .foregroundStyle(Color.fontTertiary)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing2)
        .background(Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("AI is thinking")
        .onReceive(timer) { _ in
            if !reduceMotion {
                dotCount = (dotCount + 1) % 4
            }
        }
    }
}
