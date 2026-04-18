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
                Text(LocalizationManager.shared.text("settings.incognito_mode_active"))
                    .font(.omXs)
                Spacer()
                Button {
                    incognitoManager.toggle()
                } label: {
                    Text(AppStrings.close)
                        .font(.omXs).fontWeight(.medium)
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .background(Color.grey80)
        }
    }
}
