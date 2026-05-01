// Unified embed preview card — compact card shown inline in chat messages.
// Mirrors UnifiedEmbedPreview.svelte with app gradient header, content area,
// and status bar footer. Dispatches to per-type renderers via EmbedContentView.

import SwiftUI

struct EmbedPreviewCard: View {
    let embed: EmbedRecord
    let onTap: () -> Void

    private var embedType: EmbedType? {
        EmbedType(rawValue: embed.type)
    }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 0) {
                contentArea
                statusBar
            }
            .frame(width: 300, height: 200)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .overlay(
                RoundedRectangle(cornerRadius: .radius5)
                    .stroke(embed.status == .error ? Color.error : Color.grey20, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.08), radius: 4, y: 2)
        }
        .buttonStyle(EmbedPreviewButtonStyle())
        .disabled(embed.status == .processing)
        .accessibilityIdentifier("embed-preview")
        .accessibleEmbed(
            type: embedType?.displayName ?? embed.type,
            title: embedType?.displayName
        )
        .accessibilityValue(embed.status == .processing ? "Loading" : embed.status == .error ? "Failed to load" : embed.status == .cancelled ? "Cancelled" : "Ready")
    }

    // MARK: - Content area

    private var contentArea: some View {
        ZStack {
            Color.grey0

            if embed.status == .processing {
                processingView
            } else if embed.status == .error {
                errorView
            } else if embed.status == .cancelled {
                cancelledView
            } else {
                EmbedContentView(embed: embed, mode: .preview)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var processingView: some View {
        VStack(spacing: .spacing4) {
            ProgressView()
                .scaleEffect(1.2)
            Text(LocalizationManager.shared.text("embed.processing"))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        }
    }

    private var errorView: some View {
        VStack(spacing: .spacing3) {
            Icon("warning", size: 24)
                .foregroundStyle(Color.error)
            Text(LocalizationManager.shared.text("embed.failed_to_load"))
                .font(.omSmall)
                .foregroundStyle(Color.error)
        }
    }

    private var cancelledView: some View {
        VStack(spacing: .spacing3) {
            Icon("close", size: 24)
                .foregroundStyle(Color.fontTertiary)
            Text(LocalizationManager.shared.text("embed.cancelled"))
                .font(.omSmall)
                .foregroundStyle(Color.fontTertiary)
        }
        .opacity(0.6)
    }

    // MARK: - Status bar (mirrors BasicInfosBar.svelte)

    private var statusBar: some View {
        HStack(spacing: .spacing3) {
            if let appId = embedType?.appId {
                AppIconView(appId: appId, size: 26)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: 0) {
                Text(embedType?.displayName ?? embed.type)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                if embed.status == .processing {
                    Text(LocalizationManager.shared.text("embed.processing_short"))
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()

            if embed.status == .finished {
                Icon("back", size: 10)
                    .scaleEffect(x: -1, y: 1)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.horizontal, .spacing3)
        .frame(height: 44)
        .background(Color.grey10)
    }
}

private struct EmbedPreviewButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1.0)
            .animation(reduceMotion ? .none : .easeInOut(duration: 0.14), value: configuration.isPressed)
    }
}
