// Incognito mode — messages not saved to history or synced to server.
// Mirrors incognitoChatService.ts and incognitoModeStore.ts.

import SwiftUI

@MainActor
final class IncognitoManager: ObservableObject {
    @Published var isEnabled = false
    @Published var sessionMessages: [Message] = []

    func toggle() {
        isEnabled.toggle()
        if !isEnabled {
            sessionMessages.removeAll()
        }
    }

    func addMessage(_ message: Message) {
        sessionMessages.append(message)
    }

    func clear() {
        sessionMessages.removeAll()
    }
}

struct IncognitoBanner: View {
    @ObservedObject var incognitoManager: IncognitoManager

    var body: some View {
        if incognitoManager.isEnabled {
            HStack(spacing: .spacing3) {
                Image(systemName: "eye.slash.fill")
                    .font(.caption)
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text("settings.incognito_mode_active"))
                    .font(.omXs)
                Spacer()
                Button {
                    incognitoManager.toggle()
                    AccessibilityAnnouncement.announce("Incognito mode disabled")
                } label: {
                    Text(AppStrings.close)
                        .font(.omXs).fontWeight(.medium)
                }
                .accessibleButton("Disable incognito mode", hint: "Turns off incognito mode and clears the session")
            }
            .foregroundStyle(.white)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .background(Color.grey80)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Incognito mode active — messages are not saved or synced")
        }
    }
}
