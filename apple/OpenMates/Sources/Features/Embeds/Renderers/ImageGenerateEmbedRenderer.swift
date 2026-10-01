// ImageGenerateEmbedRenderer — native counterpart for image generation embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct ImageGenerateEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    #if DEBUG && os(iOS)
    @State private var previewCopiedPrompt: String?
    #endif

    private var prompt: String? { data?["prompt"]?.value as? String }
    private var model: String? { data?["model"]?.value as? String }
    private var modelDisplayName: String? { model }
    private var s3BaseUrl: String? { data?["s3_base_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }
    private var encryption: String? { EmbedMediaPayload.encryption(from: data) }

    var body: some View {
        switch mode {
        case .preview:
            if let s3BaseUrl, let aesKey {
                EncryptedImageView(
                    s3Url: s3BaseUrl, s3Key: nil, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(alignment: .leading, spacing: .spacing2) {
                    if let prompt {
                        if let modelDisplayName {
                            HStack(alignment: .center, spacing: .spacing3) {
                                Text("\(AppStrings.imageGenerateGeneratingVia) \(modelDisplayName):")
                                    .font(.omXxs)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(Color.grey50)
                                    .lineLimit(1)
                            }
                            .padding(.bottom, .spacing1)
                        }
                        Text(prompt).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(3)
                    } else {
                        VStack(alignment: .leading, spacing: .spacing3) {
                            RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20).frame(width: 160, height: 12)
                            RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20).frame(width: 96, height: 12)
                        }
                    }
                }
                .padding(.horizontal, .spacing10)
                .padding(.vertical, .spacing8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }

        case .fullscreen:
            HStack(alignment: .center, spacing: 0) {
                if let s3BaseUrl, let aesKey {
                    EncryptedImageView(
                        s3Url: s3BaseUrl, s3Key: nil, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                        contentMode: .fit
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }

                if prompt != nil || modelDisplayName != nil {
                    VStack(alignment: .leading, spacing: .spacing6) {
                        if let modelDisplayName {
                            HStack(alignment: .center, spacing: .spacing3) {
                                Text("\(AppStrings.imageGenerateGeneratedBy) \(modelDisplayName)")
                                    .font(.omSmall)
                                    .fontWeight(.medium)
                                    .foregroundStyle(Color.grey60)
                            }
                        }

                        if let prompt {
                            ZStack {
                                RoundedRectangle(cornerRadius: 30)
                                    .fill(Color.grey0)

                                Text(prompt)
                                    .font(.omP)
                                    .fontWeight(.medium)
                                    .foregroundStyle(Color.grey80)
                                    .lineLimit(nil)
                                    .padding(.horizontal, 50)
                                    .padding(.vertical, 24)
                                    .frame(maxWidth: .infinity, alignment: .leading)

                                Icon("quote", size: 20)
                                    .foregroundStyle(Color.grey100)
                                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                                    .padding(12)

                                Icon("quote", size: 20)
                                    .foregroundStyle(Color.grey100)
                                    .rotationEffect(.degrees(180))
                                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                                    .padding(12)

                                Button { copyPrompt(prompt) } label: {
                                    Icon("copy", size: 20)
                                        .foregroundStyle(Color.grey40)
                                        .frame(width: 28, height: 28)
                                }
                                .buttonStyle(.plain)
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                                .padding(8)
                                .accessibilityLabel(AppStrings.copy)
                                .accessibilityIdentifier("image-generate-copy-prompt")
                                #if DEBUG && os(iOS)
                                .accessibilityValue(previewCopiedPrompt ?? "")
                                #endif
                            }
                        }
                    }
                    .frame(maxWidth: 380, alignment: .leading)
                    .padding(.leading, s3BaseUrl == nil ? 0 : .spacing8)
                    .padding(.vertical, 24)
                }
            }
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private func copyPrompt(_ prompt: String) {
        #if os(iOS)
        UIPasteboard.general.string = prompt
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--dev-preview") {
            previewCopiedPrompt = UIPasteboard.general.string
        }
        #endif
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(prompt, forType: .string)
        #endif
    }
}
