// Incognito mode explainer — first-time activation confirmation screen.
// Mirrors the web app's incognito/SettingsIncognitoInfo.svelte.
// Shows what incognito mode does before the user confirms activation.

import SwiftUI

struct SettingsIncognitoInfoView: View {
    let onActivate: () -> Void
    let onCancel: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Image(systemName: "eye.slash.circle.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(Color.buttonPrimary)

                Text("Incognito Mode")
                    .font(.omH2).fontWeight(.bold)

                Text("Chat privately without saving history")
                    .font(.omP).foregroundStyle(Color.fontSecondary)

                VStack(alignment: .leading, spacing: .spacing5) {
                    IncognitoFeatureRow(
                        icon: "eye.slash",
                        title: "No Chat History",
                        description: "Messages are not saved to your account. When you close the chat, it's gone."
                    )

                    IncognitoFeatureRow(
                        icon: "brain.head.profile",
                        title: "No Memory Updates",
                        description: "The AI won't learn or remember anything from incognito conversations."
                    )

                    IncognitoFeatureRow(
                        icon: "lock.shield",
                        title: "Enhanced Privacy",
                        description: "No chat metadata, embeds, or attachments are stored on the server."
                    )

                    IncognitoFeatureRow(
                        icon: "exclamationmark.triangle",
                        title: "Not Recoverable",
                        description: "Once an incognito chat is closed, it cannot be recovered. Export important content before closing."
                    )
                }
                .padding(.horizontal)

                Spacer(minLength: .spacing8)

                VStack(spacing: .spacing4) {
                    Button {
                        onActivate()
                    } label: {
                        Text("Activate Incognito Mode")
                            .font(.omSmall).fontWeight(.medium)
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.buttonPrimary)

                    Button("Cancel") {
                        onCancel()
                    }
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                }
                .padding(.horizontal)
            }
            .padding(.spacing8)
        }
    }
}

// MARK: - Feature row

struct IncognitoFeatureRow: View {
    let icon: String
    let title: String
    let description: String

    var body: some View {
        HStack(alignment: .top, spacing: .spacing4) {
            Image(systemName: icon)
                .font(.system(size: 20))
                .foregroundStyle(Color.buttonPrimary)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(title)
                    .font(.omSmall).fontWeight(.medium)
                Text(description)
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
    }
}
