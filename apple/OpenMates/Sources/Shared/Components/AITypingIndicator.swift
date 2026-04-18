// AI typing indicator — shows which app/skill is currently processing.
// Mirrors aiTypingStore.ts: displays app icon with gradient and skill name.

import SwiftUI

struct AITypingIndicator: View {
    let appId: String?
    let skillName: String?
    let isThinking: Bool

    var body: some View {
        HStack(spacing: .spacing3) {
            if let appId {
                AppIconView(appId: appId, size: 24)
                    .pulse(isActive: true)
            } else {
                Image.iconOpenmates
                    .resizable()
                    .frame(width: 24, height: 24)
                    .pulse(isActive: true)
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
    }
}

struct PulseModifier: ViewModifier {
    let isActive: Bool
    @State private var opacity: Double = 1.0

    func body(content: Content) -> some View {
        content
            .opacity(opacity)
            .animation(
                isActive ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true) : .default,
                value: opacity
            )
            .onAppear { if isActive { opacity = 0.4 } }
    }
}

extension View {
    func pulse(isActive: Bool) -> some View {
        modifier(PulseModifier(isActive: isActive))
    }
}
