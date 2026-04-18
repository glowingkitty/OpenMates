// Fork progress banner — shown during conversation fork operation.
// Mirrors the web app's chats/ForkProgressBanner.svelte: progress indicator
// displayed while the backend copies messages to the new forked chat.

import SwiftUI

struct ForkProgressBanner: View {
    let isForking: Bool
    let progress: Double?
    let onCancel: (() -> Void)?
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        if isForking {
            HStack(spacing: .spacing3) {
                ProgressView()
                    .scaleEffect(0.8)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 0) {
                    Text(LocalizationManager.shared.text("chats.fork.forking_banner"))
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)

                    if let progress, progress > 0 {
                        Text("\(Int(progress * 100))% complete")
                            .font(.omTiny).foregroundStyle(Color.fontTertiary)
                    }
                }

                Spacer()

                if let onCancel {
                    Button("Cancel", action: onCancel)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                        .accessibleButton("Cancel fork", hint: "Cancels the conversation fork in progress")
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .background(Color.buttonPrimary.opacity(0.08))
            .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
            .accessibilityElement(children: .combine)
            .accessibilityLabel(
                progress.map { "Forking conversation, \(Int($0 * 100)) percent complete" }
                ?? "Forking conversation"
            )
        }
    }
}
