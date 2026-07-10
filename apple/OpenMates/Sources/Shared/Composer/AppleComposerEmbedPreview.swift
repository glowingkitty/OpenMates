// Native inline preview surface for atomic composer embed nodes.
// Uses the explicit AppleComposerRendererRegistry and never a generic fallback.
// Finished supported records reuse existing native read renderers inside web-parity chrome.
// Pending and summary-only families use deterministic lifecycle presentation.
// Required callbacks keep host behavior explicit across iOS and macOS.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// CSS:     UnifiedEmbedPreview.svelte — .unified-embed-preview, .desktop-layout
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct AppleComposerEmbedActions {
    let onOpen: (String) -> Void
    let onRetry: (String) -> Void
    let onRemove: (String) -> Void
}

struct AppleComposerEmbedPreview: View {
    private enum Constants {
        static let width: CGFloat = 300
        static let height: CGFloat = 200
        static let cornerRadius: CGFloat = 30
    }

    let descriptor: AppleComposerPreviewDescriptor
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let embedRecord: EmbedRecord?
    let allEmbedRecords: [String: EmbedRecord]
    let actions: AppleComposerEmbedActions

    var body: some View {
        ZStack(alignment: .topTrailing) {
            if lifecycle == .finished, let embedRecord, usesReadRenderer {
                EmbedPreviewCard(embed: embedRecord, allEmbedRecords: allEmbedRecords) {
                    actions.onOpen(node.id)
                }
            } else {
                summaryPreview
            }
            actionBar
                .padding(.spacing4)
        }
        .frame(width: Constants.width, height: Constants.height)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("native-composer-preview-\(descriptor.embedType)-\(lifecycle.rawValue)")
    }

    private var summaryPreview: some View {
        VStack(spacing: 0) {
            VStack(spacing: .spacing5) {
                AppIconView(appId: appId, size: 60)
                Text(title)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                lifecycleContent
            }
            .padding(.horizontal, .spacing10)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            EmbedBasicInfoBar(
                appId: appId,
                skillIconName: AppIconView.iconName(forAppId: appId),
                title: title,
                subtitle: lifecycleLabel,
                faviconURL: nil,
                showSkillIcon: false
            )
        }
        .frame(width: Constants.width, height: Constants.height)
        .background(lifecycle == .error ? Color.error.opacity(0.1) : Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: Constants.cornerRadius))
        .overlay {
            if lifecycle == .error {
                RoundedRectangle(cornerRadius: Constants.cornerRadius)
                    .stroke(Color.error, lineWidth: 1)
            }
        }
        .shadow(color: .black.opacity(0.16), radius: 24, x: 0, y: 8)
        .shadow(color: .black.opacity(0.10), radius: 6, x: 0, y: 2)
    }

    @ViewBuilder
    private var lifecycleContent: some View {
        switch lifecycle {
        case .queued, .uploading, .transcribing:
            ProgressView()
                .tint(Color.buttonPrimary)
        case .finished:
            Icon("check", size: 22)
                .foregroundStyle(Color.buttonPrimary)
        case .error:
            Icon("warning", size: 22)
                .foregroundStyle(Color.error)
        case .cancelled:
            Icon("close", size: 22)
                .foregroundStyle(Color.fontTertiary)
        }
    }

    private var actionBar: some View {
        HStack(spacing: .spacing2) {
            if lifecycle == .finished {
                previewAction(icon: "visible", label: openLabel) {
                    actions.onOpen(node.id)
                }
            }
            if lifecycle == .error {
                previewAction(icon: "refresh", label: AppStrings.retry) {
                    actions.onRetry(node.id)
                }
            }
            previewAction(icon: "close", label: AppStrings.remove) {
                actions.onRemove(node.id)
            }
        }
    }

    private func previewAction(
        icon: String,
        label: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Icon(icon, size: 14)
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 30, height: 30)
                .background(Color.grey10)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private var title: String {
        node.display?.title ?? AppStrings.uploadProgressProcessing
    }

    private var openLabel: String {
        #if os(macOS)
        AppStrings.embedClickToShowDetails
        #else
        AppStrings.embedTapToShowDetails
        #endif
    }

    private var lifecycleLabel: String {
        switch lifecycle {
        case .queued: AppStrings.waitingForUpload
        case .uploading: AppStrings.uploadProgressUploading(percent: "0")
        case .transcribing: AppStrings.uploadProgressTranscribing
        case .finished: openLabel
        case .error: AppStrings.uploadProgressError
        case .cancelled: AppStrings.cancel
        }
    }

    private var usesReadRenderer: Bool {
        switch descriptor.family {
        case .appSkillUse, .repository, .pcbSchematic, .electronicsComponent,
             .fitnessLocation, .fitnessClass, .socialPost, .weatherDay, .group:
            false
        default:
            true
        }
    }

    private var appId: String {
        switch descriptor.family {
        case .recording: "audio"
        case .appSkillUse: "openmates"
        case .repository, .code: "code"
        case .document: "docs"
        case .pcbSchematic, .electronicsComponent: "electronics"
        case .event: "events"
        case .fitnessLocation, .fitnessClass: "fitness"
        case .appointment: "health"
        case .homeListing: "home"
        case .image, .imageResult: "images"
        case .email: "mail"
        case .place, .map: "maps"
        case .mathPlot: "math"
        case .mindMap: "mindmaps"
        case .website: "web"
        case .recipe: "nutrition"
        case .pdf: "pdf"
        case .product: "shopping"
        case .socialPost: "social_media"
        case .travelConnection, .travelStay: "travel"
        case .video: "videos"
        case .weatherDay: "weather"
        case .sheet: "sheets"
        case .group(let childType):
            AppleComposerRendererRegistry.shared.descriptor(for: childType)
                .map { appId(for: $0.family) } ?? "openmates"
        }
    }

    private func appId(for family: AppleComposerPreviewFamily) -> String {
        switch family {
        case .repository, .code: "code"
        case .document: "docs"
        case .pcbSchematic, .electronicsComponent: "electronics"
        case .event: "events"
        case .fitnessLocation, .fitnessClass: "fitness"
        case .appointment: "health"
        case .homeListing: "home"
        case .image, .imageResult: "images"
        case .email: "mail"
        case .place, .map: "maps"
        case .mathPlot: "math"
        case .mindMap: "mindmaps"
        case .website: "web"
        case .recipe: "nutrition"
        case .pdf: "pdf"
        case .product: "shopping"
        case .socialPost: "social_media"
        case .travelConnection, .travelStay: "travel"
        case .video: "videos"
        case .weatherDay: "weather"
        case .sheet: "sheets"
        case .recording: "audio"
        case .appSkillUse, .group: "openmates"
        }
    }
}
