// ImageGenerateEmbedRenderer — native counterpart for image generation embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ImageGenerateEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var prompt: String? { data?["prompt"]?.value as? String }
    private var model: String? { data?["model"]?.value as? String }
    private var modelDisplayName: String? { model.map(Self.displayName) }
    private var s3BaseUrl: String? { data?["s3_base_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            if let s3BaseUrl, let aesKey {
                EncryptedImageView(
                    s3Url: s3BaseUrl, aesKey: aesKey, aesNonce: aesNonce,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(alignment: .leading, spacing: .spacing2) {
                    if let prompt {
                        if let modelDisplayName {
                            HStack(alignment: .center, spacing: .spacing3) {
                                Icon("ai", size: 16)
                                    .foregroundStyle(Color.grey50)
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
                        s3Url: s3BaseUrl, aesKey: aesKey, aesNonce: aesNonce,
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
                                Icon("ai", size: 19)
                                    .foregroundStyle(Color.grey60)
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
                            }
                        }
                    }
                    .frame(maxWidth: 380, alignment: .leading)
                    .padding(.leading, s3BaseUrl == nil ? 0 : .spacing8)
                    .padding(.vertical, .spacing12)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }

    private static func displayName(for model: String) -> String {
        switch model {
        case "flux-schnell":
            return "FLUX Schnell"
        default:
            return model
        }
    }
}

