// ImageGenerateEmbedRenderer — native counterpart for image generation embeds
// (images/generate, images/generate_draft and images/modify).
// The preview shows the web card states: finished picture (whole card,
// letterboxed), skeleton while processing or waiting for the picture, stage
// label while a generator script is written, live vector drawing, the
// images.modify step over its draft picture, and the failed state. The
// fullscreen shows the picture using the available width and height (a tap
// opens only the image in the system previewer), the same progress/failed
// states and the prompt panel.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageModifyProgress.svelte
//          frontend/packages/ui/src/components/embeds/ResultEmbedFullscreen.svelte
// CSS:     ImageGenerateEmbedPreview.svelte <style>: .prompt-content, .skeleton-line,
//          .svg-draft, .svg-draft-stage, .draft-status-label, .image-container,
//          .error-state, .error-icon, .error-text
//          ImageGenerateEmbedFullscreen.svelte <style>: .error-container, .error-icon, .error-message
//          ImageModifyProgress.svelte <style>: .modify-step, .modify-step.over-draft
// Tokens:  ColorTokens.generated.swift (mediaLetterbox, grey20, error, fontButton),
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12, image-generate card states)
//
// Not rendered natively yet (data or renderer missing, stated in the plan):
// - the live partial SVG drawing (needs a sanitized streaming SVG renderer; the
//   card shows the letterbox surface and stage label instead),
// - the message-scoped version resolution (which version a chat message pins)
//   is done by the core on the web; here the caller passes `version` and
//   `headVersion`, and ImageVersionBadge draws the "vN" pill. The version list
//   and restore live in the fullscreen container (EmbedVersionEditControls).

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct ImageGenerateEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let status: EmbedStatus
    let skillId: String
    /// Version this card shows and the head version (both from the core's embed
    /// head); the "vN" badge appears only when the head is above one.
    let version: Int?
    let headVersion: Int?
    private let state: ImageGenerateCardState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var skeletonDimmed = false
    #if DEBUG && os(iOS)
    @State private var previewCopiedPrompt: String?
    #endif

    init(data: [String: AnyCodable]?, mode: EmbedDisplayMode, status: EmbedStatus = .finished, skillId: String = "generate",
         version: Int? = nil, headVersion: Int? = nil) {
        self.version = version
        self.headVersion = headVersion
        self.data = data
        self.mode = mode
        self.status = status
        self.skillId = skillId
        // Resolved once per input, not inside body.
        self.state = ImageGenerateCardState.resolve(data: data, status: status, skillId: skillId)
    }

    private var prompt: String? { data?["prompt"]?.value as? String }
    private var model: String? { data?["model"]?.value as? String }
    private var modelDisplayName: String? { skillId == "modify" ? nil : model }
    private var s3BaseUrl: String? { data?["s3_base_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }
    private var encryption: String? { EmbedMediaPayload.encryption(from: data) }

    /// Stable state name for UI tests (`data-state` equivalent).
    private var stateName: String {
        switch state {
        case .image: return "finished"
        case .modifyProgress: return "modify"
        case .svgDraft: return "svg-draft"
        case .pending(let stage): return stage == nil ? "processing" : "draft-status"
        case .failed: return "error"
        }
    }

    var body: some View {
        Group {
            switch mode {
            case .preview: preview
            case .fullscreen: fullscreen
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(mode == .preview ? "image-generate-preview" : "image-generate-fullscreen")
        .accessibilityValue(stateName)
    }

    // MARK: - Preview

    @ViewBuilder
    private var preview: some View {
        if case .image = state, let s3BaseUrl, let aesKey {
            // hasFullWidthImage: the picture fills the whole card, under the info bar.
            ZStack {
                Color.mediaLetterbox
                EncryptedImageView(
                    s3Url: s3BaseUrl, s3Key: nil, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                    contentMode: .fit
                )
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .overlay { ImageVersionBadge(version: version, headVersion: headVersion) }
            .clipped()
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(prompt ?? AppStrings.imageGenerateSkillGenerate)
            .accessibilityIdentifier("image-generate-preview-image")
        } else {
            VStack(alignment: .leading, spacing: .spacing4) {
                previewMedia
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                if !isFailed, let prompt {
                    Text(prompt).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("image-generate-preview-prompt")
                }
                if !isFailed, let modelDisplayName {
                    Text(modelDisplayName).font(.omXxs).foregroundStyle(Color.grey50).lineLimit(1)
                        .accessibilityIdentifier("image-generate-preview-model")
                }
            }
            // The info bar overlays the bottom of this full-width card.
            .padding(.top, .spacing8)
            .padding(.horizontal, .spacing10)
            .padding(.bottom, EmbedPreviewFooterLayout.height + .spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var isFailed: Bool {
        if case .failed = state { return true }
        return false
    }

    @ViewBuilder
    private var previewMedia: some View {
        switch state {
        case .image:
            // Finished, but the image keys are missing: the web keeps the skeleton.
            skeleton(stageLabel: nil)
        case .pending(let stage):
            skeleton(stageLabel: stage.flatMap(AppStrings.imageGenerateDraftStage))
        case .svgDraft(let stage):
            drawingSurface(stageLabel: stage.flatMap(AppStrings.imageGenerateDraftStage))
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
        case .modifyProgress(let stage, let attempt, let draft):
            ImageModifyProgressView(step: stage.flatMap { AppStrings.imageModifyStep($0, attempt: attempt) },
                                    draftBase64: draft, title: prompt ?? AppStrings.imageModifyTitle, fit: .fill)
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
                .accessibilityIdentifier("image-modify-card")
        case .failed(let message):
            HStack(alignment: .center, spacing: .spacing4) {
                errorGlyph(size: 20)
                Text(message ?? AppStrings.imageGenerateFailed)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("image-generate-error-text")
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, alignment: .leading)
            // .error-state background --color-error-5 has no generated token;
            // a light tint of the error token stands in for it.
            .background(Color.error.opacity(0.06))
            .clipShape(RoundedRectangle(cornerRadius: .radius2))
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("image-generate-error-state")
        }
    }

    /// `.skeleton-lines`: 80% and 50% wide 12pt lines that pulse 0.6 ↔ 1.
    private func skeleton(stageLabel: String?) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            GeometryReader { proxy in
                VStack(alignment: .leading, spacing: .spacing3) {
                    RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20)
                        .frame(width: proxy.size.width * 0.8, height: 12)
                    RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20)
                        .frame(width: proxy.size.width * 0.5, height: 12)
                }
            }
            .frame(height: 30)
            .opacity(skeletonDimmed ? 0.6 : 1)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.easeInOut(duration: 0.75).repeatForever(autoreverses: true)) { skeletonDimmed = true }
            }
            .accessibilityHidden(true)
            .accessibilityIdentifier("image-generate-skeleton")
            if let stageLabel {
                stagePill(stageLabel)
                    .accessibilityIdentifier("image-generate-draft-status")
            }
        }
    }

    /// `.svg-draft`: letterbox surface with the stage label in the bottom-left corner.
    private func drawingSurface(stageLabel: String?) -> some View {
        ZStack(alignment: .bottomLeading) {
            Color.mediaLetterbox
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityHidden(true)
            if let stageLabel {
                stagePill(stageLabel)
                    .padding(.spacing4)
                    .accessibilityIdentifier("image-generate-svg-draft-stage")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("image-generate-svg-draft")
    }

    /// `.svg-draft-stage` / `.draft-status-label`: white tiny text on a 55% black pill.
    private func stagePill(_ text: String) -> some View {
        Text(text)
            .font(.omTiny)
            .foregroundStyle(Color.fontButton)
            .padding(.vertical, .spacing1)
            .padding(.horizontal, .spacing4)
            .background(Color.black.opacity(0.55))
            .clipShape(RoundedRectangle(cornerRadius: .radius2))
    }

    /// `.error-icon`: "!" on an error-tinted circle.
    private func errorGlyph(size: CGFloat) -> some View {
        Circle()
            .fill(Color.error.opacity(0.2))
            .frame(width: size, height: size)
            .overlay {
                Text(verbatim: "!")
                    .font(size > 30 ? .omH3 : .omXxs)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.error)
            }
            .accessibilityHidden(true)
    }

    // MARK: - Fullscreen

    @ViewBuilder
    private var fullscreen: some View {
        if case .failed(let message) = state {
            // The web hides the image and the prompt panel while failed.
            VStack(spacing: .spacing6) {
                errorGlyph(size: 48)
                Text(AppStrings.imageGenerateFailed)
                    .font(.omH4).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                if let message {
                    Text(message)
                        .font(.omSmall)
                        .foregroundStyle(Color.grey60)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 400)
                        .accessibilityIdentifier("image-generate-fullscreen-error-message")
                }
            }
            .padding(.spacing8)
            .frame(maxWidth: .infinity, minHeight: 200)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("image-generate-fullscreen-error")
        } else {
            HStack(alignment: .center, spacing: 0) {
                fullscreenMedia
                promptPanel
            }
            .padding(.horizontal, .spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    @ViewBuilder
    private var fullscreenMedia: some View {
        switch state {
        case .image:
            if let s3BaseUrl, let aesKey {
                TappableEncryptedImageView(
                    s3Url: s3BaseUrl, s3Key: nil, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                    filename: nil
                )
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                .frame(maxWidth: .infinity, maxHeight: ImageFullscreenSizing.maxImageHeight)
                .accessibilityIdentifier("image-generate-fullscreen-image")
            }
        case .modifyProgress(let stage, let attempt, let draft):
            ImageModifyProgressView(step: stage.flatMap { AppStrings.imageModifyStep($0, attempt: attempt) },
                                    draftBase64: draft, title: prompt ?? AppStrings.imageModifyTitle, fit: .fit)
                .frame(maxWidth: .infinity, minHeight: 200, maxHeight: ImageFullscreenSizing.maxImageHeight)
                .accessibilityIdentifier("image-modify-opened")
        case .svgDraft(let stage):
            drawingSurface(stageLabel: stage.flatMap(AppStrings.imageGenerateDraftStage))
                .frame(minHeight: 200, maxHeight: ImageFullscreenSizing.maxImageHeight)
        case .pending(let stage):
            if let label = stage.flatMap(AppStrings.imageGenerateDraftStage) {
                ZStack(alignment: .bottomLeading) {
                    Color.mediaLetterbox
                    stagePill(label).padding(.spacing4)
                        .accessibilityIdentifier("image-generate-svg-draft-stage")
                }
                .frame(maxWidth: .infinity, minHeight: 200, maxHeight: ImageFullscreenSizing.maxImageHeight)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("image-generate-draft-status")
            } else if status == .finished {
                // Finished without a picture yet: `.image-loading`.
                VStack(spacing: .spacing4) {
                    ProgressView()
                    Text(AppStrings.imageGenerateLoading).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
                .frame(maxWidth: .infinity, minHeight: 200)
                .accessibilityIdentifier("image-generate-fullscreen-loading")
            }
        case .failed:
            EmptyView()
        }
    }

    @ViewBuilder
    private var promptPanel: some View {
        if prompt != nil || modelDisplayName != nil {
            VStack(alignment: .leading, spacing: .spacing6) {
                if let modelDisplayName {
                    Text("\(AppStrings.imageGenerateGeneratedBy) \(modelDisplayName)")
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey60)
                }
                if let prompt {
                    promptQuote(prompt)
                }
            }
            .frame(maxWidth: 380, alignment: .leading)
            .padding(.leading, hasFullscreenMedia ? .spacing8 : 0)
            .padding(.vertical, .spacing12)
        }
    }

    private var hasFullscreenMedia: Bool {
        switch state {
        case .image: return s3BaseUrl != nil
        case .modifyProgress, .svgDraft: return true
        case .pending(let stage): return stage.flatMap(AppStrings.imageGenerateDraftStage) != nil || status == .finished
        case .failed: return false
        }
    }

    /// `.prompt-container` border-radius (30px, the shared embed card corner).
    private static let promptCornerRadius: CGFloat = 30

    private func promptQuote(_ prompt: String) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: Self.promptCornerRadius)
                .fill(Color.grey0)

            Text(prompt)
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.grey80)
                .lineLimit(nil)
                .padding(.horizontal, .spacing24 + .spacing1)
                .padding(.vertical, .spacing12)
                .frame(maxWidth: .infinity, alignment: .leading)

            Icon("quote", size: 20)
                .foregroundStyle(Color.grey100)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                .padding(.spacing6)

            Icon("quote", size: 20)
                .foregroundStyle(Color.grey100)
                .rotationEffect(.degrees(180))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(.spacing6)

            Button { copyPrompt(prompt) } label: {
                Icon("copy", size: 20)
                    .foregroundStyle(Color.grey40)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
            .padding(.spacing4)
            .accessibilityLabel(AppStrings.copy)
            .accessibilityIdentifier("image-generate-copy-prompt")
            #if DEBUG && os(iOS)
            .accessibilityValue(previewCopiedPrompt ?? "")
            #endif
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

/// ImageModifyProgress.svelte: the computed draft picture (when one exists)
/// with the current step over it, or the step text alone. The draft is decoded
/// off the body path once per value.
struct ImageModifyProgressView: View {
    let step: String?
    let draftBase64: String?
    let title: String
    let fit: ContentMode
    @State private var draftImage: CGImage?

    var body: some View {
        ZStack(alignment: draftImage == nil ? .center : .topTrailing) {
            Color.mediaLetterbox
            if let draftImage {
                Image(decorative: draftImage, scale: 1)
                    .resizable()
                    .aspectRatio(contentMode: fit)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()
                    .accessibilityLabel(title)
                    .accessibilityIdentifier("image-modify-draft")
            }
            if let step {
                Text(step)
                    .font(draftImage == nil ? .omTiny : .omSmall)
                    .fontWeight(draftImage == nil ? .regular : .semibold)
                    .foregroundStyle(Color.fontButton)
                    .padding(.vertical, .spacing1)
                    .padding(.horizontal, .spacing4)
                    .background(Color.black.opacity(0.55))
                    .clipShape(RoundedRectangle(cornerRadius: .radius2))
                    .padding(draftImage == nil ? 0 : .spacing4)
                    .accessibilityIdentifier("image-modify-step")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .task(id: draftBase64) {
            draftImage = draftBase64.flatMap { Data(base64Encoded: $0) }.flatMap { NativeImageRaster.uprightImage(from: $0) }
        }
    }
}

/// Web `ResultEmbedFullscreen` budget for app images: all height left after
/// header, facts and composer (viewport minus 18rem), side gutters of spacing-4.
@MainActor
enum ImageFullscreenSizing {
    static let reservedHeight: CGFloat = 288

    static var maxImageHeight: CGFloat {
        #if os(iOS)
        let viewport = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.windows.first(where: { $0.isKeyWindow })?.bounds.size }
            .first ?? UIScreen.main.bounds.size
        #elseif os(macOS)
        let viewport = NSApp.keyWindow?.contentView?.bounds.size
            ?? NSScreen.main?.visibleFrame.size ?? CGSize(width: 900, height: 900)
        #endif
        return max(16, viewport.height - reservedHeight)
    }
}
