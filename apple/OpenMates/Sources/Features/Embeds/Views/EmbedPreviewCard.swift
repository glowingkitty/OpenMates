// Unified embed preview card — compact card shown inline in chat messages.
// Mirrors UnifiedEmbedPreview.svelte with app gradient header, content area,
// and status bar footer. Dispatches to per-type renderers via EmbedContentView.

import SwiftUI

struct EmbedPreviewCard: View {
    let embed: EmbedRecord
    let onTap: () -> Void

    @State private var isPressed = false

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
            .scaleEffect(isPressed ? 0.97 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: isPressed)
        }
        .buttonStyle(.plain)
        .disabled(embed.status == .processing)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("embed-preview")
        .accessibilityLabel("\(embed.title ?? embed.embedType) embed")
        .accessibilityValue(embed.status == .processing ? "Loading" : "Ready")
        .accessibilityHint("Double tap to open fullscreen")
        .accessibilityAddTraits(.isButton)
        .simultaneousGesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in isPressed = true }
                .onEnded { _ in isPressed = false }
        )
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
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 24))
                .foregroundStyle(Color.error)
            Text(LocalizationManager.shared.text("embed.failed_to_load"))
                .font(.omSmall)
                .foregroundStyle(Color.error)
        }
    }

    private var cancelledView: some View {
        VStack(spacing: .spacing3) {
            Image(systemName: "xmark.circle")
                .font(.system(size: 24))
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
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.horizontal, .spacing3)
        .frame(height: 44)
        .background(Color.grey10)
    }
}
