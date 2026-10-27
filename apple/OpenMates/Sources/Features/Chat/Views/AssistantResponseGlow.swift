// Web: frontend/packages/ui/src/components/ChatMessage.svelte
// CSS: .assistant-response-active::after; response-rainbow-flow
// Rendered reference: .runtime/followups123/web-reference362.json
// Tokens: ColorTokens.generated.swift (responseGlow*), SpacingTokens.generated.swift
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation, chats.surface.semantic-parity

import SwiftUI

struct AssistantResponseGlow: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.progressiveMarkdownReducedMotion) private var requestedReduceMotion
    @State private var startedAt = Date()
    private var reduceMotion: Bool { systemReduceMotion || requestedReduceMotion }
    private var colors: [Color] {
        [.responseGlowPink, .responseGlowAmber, .responseGlowGreen, .responseGlowBlue, .responseGlowPurple, .responseGlowPink]
    }

    var body: some View {
        Group {
            if reduceMotion {
                band(phase: 0)
            } else {
                TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
                    band(phase: timeline.date.timeIntervalSince(startedAt).truncatingRemainder(dividingBy: 3) / 3)
                }
            }
        }
        .frame(height: .spacing8)
        .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: .radius4, bottomTrailingRadius: .radius4))
        .blur(radius: 5)
        .opacity(0.7)
        .mask(LinearGradient(colors: [.clear, .grey100], startPoint: .top, endPoint: .bottom))
        .padding(.horizontal, .spacing5)
        .padding(.bottom, .spacing1 + 1)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func band(phase: Double) -> some View {
        Canvas { context, size in
            // CSS background-size 200%; background-position 200% -> 0%.
            // Repeating adjacent copies keeps the entire response bottom filled.
            let width = size.width * 2
            guard width > 0 else { return }
            let offset = -width + width * CGFloat(phase)
            for copy in 0...2 {
                let x = offset + CGFloat(copy) * width
                let rect = CGRect(x: x, y: 0, width: width, height: size.height)
                context.fill(Path(rect), with: .linearGradient(Gradient(colors: colors),
                    startPoint: CGPoint(x: x, y: 0), endPoint: CGPoint(x: x + width, y: 0)))
            }
        }
    }
}
