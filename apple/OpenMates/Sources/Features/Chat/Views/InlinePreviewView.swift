// Inline attachment previews — shows uploaded composer embeds before sending.
// Mirrors web enter_message embed previews inside MessageInput.svelte.
// Uses OpenMates tokens/primitives only: no native context menu or SF Symbols.
// Supports image thumbnails, PDF/audio/file app icons, and remove actions.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/EmbeddPreview.styles.css
//          .embed-unified-container, .embed-app-icon, .embed-content
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct PendingComposerEmbedPreview: View {
    let embed: ComposerPendingEmbed
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            iconContent
                .frame(width: 60, height: 60)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(embed.filename)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                Text(formattedSize)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
                    .lineLimit(1)
            }
            .frame(height: 60)
            .padding(.horizontal, .spacing6)
            .accessibilityIdentifier("pending-composer-embed")

            Spacer(minLength: .spacing2)

            Button(action: onRemove) {
                Icon("close", size: 16)
                    .foregroundStyle(Color.fontTertiary)
                    .frame(width: 32, height: 32)
                    .background(Color.grey20)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.delete)
            .accessibilityIdentifier("pending-composer-embed-remove")
            .padding(.trailing, .spacing4)
        }
        .frame(width: 300, height: 60)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 30))
        .shadow(color: .black.opacity(0.10), radius: 8, x: 0, y: 4)
        .accessibilityIdentifier("embed-full-width-wrapper")
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var iconContent: some View {
        switch previewKind {
        case .image:
            if let data = embed.localData {
                #if os(iOS)
                if let image = UIImage(data: data) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    AppIconView(appId: appId, size: 60)
                }
                #elseif os(macOS)
                if let image = NSImage(data: data) {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    AppIconView(appId: appId, size: 60)
                }
                #endif
            } else {
                AppIconView(appId: appId, size: 60)
            }
        case .pdf, .audio, .file:
            AppIconView(appId: appId, size: 60)
        }
    }

    private var formattedSize: String {
        guard embed.size > 0 else { return AppStrings.uploadProgressProcessing }
        return ByteCountFormatter.string(fromByteCount: Int64(embed.size), countStyle: .file)
    }

    private var appId: String {
        switch previewKind {
        case .image:
            return "images"
        case .pdf:
            return "pdf"
        case .audio:
            return "audio"
        case .file:
            switch fileExtension {
            case "xls", "xlsx", "csv": return "sheets"
            case "mp4", "mov", "avi": return "videos"
            default: return "docs"
            }
        }
    }

    private var fileExtension: String {
        (embed.filename as NSString).pathExtension.lowercased()
    }

    private var previewKind: PreviewKind {
        if embed.type == "images-image" { return .image }
        if embed.type == "audio-recording" { return .audio }
        if embed.type == "pdf" { return .pdf }
        return .file
    }

    private enum PreviewKind {
        case image
        case pdf
        case audio
        case file
    }
}

struct PendingComposerEmbedsList: View {
    let embeds: [ComposerPendingEmbed]
    let onRemove: (ComposerPendingEmbed) -> Void

    var body: some View {
        if !embeds.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(embeds) { embed in
                        PendingComposerEmbedPreview(embed: embed) {
                            onRemove(embed)
                        }
                    }
                }
                .padding(.horizontal, .spacing4)
            }
            .padding(.vertical, .spacing2)
        }
    }
}
