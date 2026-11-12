// Embed version list with restore and the image Enhance header action in the
// embed fullscreen, over `EmbedVersionEditModel` (Rust core calls in
// Core/CoreBridge/CoreEmbedVersions.swift). The image fullscreen lists every
// version newest first with who made it and restores one as the next version
// after a second tap; other embed types keep the existing REST timeline
// (`EmbedVersionHistoryTimeline`, which can show the content of an older
// version) and add the restore bar for the selected older version. Error
// messages are shown as error notifications, like the web.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/shared/EmbedVersionTimeline.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/EmbedTopBar.svelte (enhanceButton snippet)
//          frontend/packages/ui/src/components/embeds/images/imageEnhance.svelte.ts
// CSS:     EmbedVersionTimeline.svelte <style>: .version-timeline, .timeline-header,
//          .timeline-label, .version-count, .timeline-footer, .restore-btn, .timeline-error
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/embed-user-edits/specification.yml
// Assertions: embed-user-edits.enhance.button, embed-user-edits.restore.creates-version, embed-user-edits.edit.next-version

import SwiftUI

// MARK: - Strings (existing web keys)

extension AppStrings {
    static var embedEditEnhance: String { LocalizationManager.shared.text("embed_user_edits.enhance") }
    static var embedEditEnhanceRunning: String { LocalizationManager.shared.text("embed_user_edits.enhance_running") }
    static var embedEditEnhanceFailed: String { LocalizationManager.shared.text("embed_user_edits.enhance_failed") }
    static var embedEditEnhanceUnavailable: String { LocalizationManager.shared.text("embed_user_edits.enhance_unavailable") }
    static var embedEditEnhanceUnavailableTeam: String { LocalizationManager.shared.text("embed_user_edits.enhance_unavailable_team") }
    static var embedEditInsufficientCredits: String { LocalizationManager.shared.text("embed_user_edits.enhance_insufficient_credits") }
    static var embedEditVersionConflict: String { LocalizationManager.shared.text("embed_user_edits.version_conflict") }
    static var embedEditRestoreFailed: String { LocalizationManager.shared.text("embed_user_edits.restore_failed") }
    static var embedEditHistoryTitle: String { LocalizationManager.shared.text("artifact_history.title") }
    static var embedEditHistoryEmpty: String { LocalizationManager.shared.text("artifact_history.empty") }
    static var embedEditHistoryFailed: String { LocalizationManager.shared.text("artifact_history.failed") }
    static var embedEditCurrent: String { LocalizationManager.shared.text("workflows.version_history.current") }
    static var embedEditConfirmRestore: String { LocalizationManager.shared.text("workflows.version_history.confirm_restore") }
    static var embedEditRestoring: String { LocalizationManager.shared.text("workflows.version_history.restoring") }
    static var embedEditRestoreExplanation: String { LocalizationManager.shared.text("workflows.version_history.restore_explanation") }
    static func embedEditVersion(_ version: Int64) -> String {
        LocalizationManager.shared.text("workflows.version_history.version", replacements: ["version": String(version)])
    }
    static func embedEditRestoreAsNew(_ version: Int64) -> String {
        LocalizationManager.shared.text("workflows.version_history.restore_as_new", replacements: ["version": String(version)])
    }
    static func embedEditRestored(_ version: Int64) -> String {
        LocalizationManager.shared.text("workflows.version_history.restore_success", replacements: ["version": String(version)])
    }
    static func embedEditCost(_ credits: Int64) -> String {
        LocalizationManager.shared.text("chat.generated_by_cost", replacements: ["credits": String(credits)])
    }
    static func embedEditKind(_ kind: EmbedEditKind) -> String {
        LocalizationManager.shared.text("embed_user_edits.kind.\(kind.rawValue)")
    }
    /// "Image enhanced · version 3" and the other user actions.
    static func embedEditEvent(_ action: EmbedUpdateActionRecord, kind: EmbedEditKind, version: Int64) -> String {
        let key: String
        switch action {
        case .edit: key = "edit"
        case .enhance: key = "enhance"
        case .crop: key = "crop"
        case .restore: key = "restore_plain"
        }
        return LocalizationManager.shared.text("embed_user_edits.event.\(key)",
                                               replacements: ["kind": embedEditKind(kind), "version": String(version)])
    }
}

/// Embed kind noun of the web `embed_user_edits.kind.*` keys.
enum EmbedEditKind: String {
    case image, diagram, slides, sheet, document

    init?(embedType: EmbedType?) {
        switch embedType {
        case .imagesGenerate?, .image?, .imagesImageResult?: self = .image
        case .sheetsSheet?: self = .sheet
        case .docsDoc?: self = .document
        case .diagramsMermaid?: self = .diagram
        default: return nil
        }
    }
}

extension EmbedEditMessage {
    @MainActor var text: String {
        switch self {
        case .enhanceFailed: return AppStrings.embedEditEnhanceFailed
        case .insufficientCredits: return AppStrings.embedEditInsufficientCredits
        case .teamUnavailable: return AppStrings.embedEditEnhanceUnavailableTeam
        case .versionConflict: return AppStrings.embedEditVersionConflict
        case .restoreFailed: return AppStrings.embedEditRestoreFailed
        case .enhanced(let version): return AppStrings.embedEditEvent(.enhance, kind: .image, version: version)
        case .restored(let version): return AppStrings.embedEditRestored(version)
        }
    }
}

// MARK: - Enhance header action

/// The round Enhance button of the fullscreen top bar (web `enhanceButton`,
/// `data-testid="embed-enhance-button"`, progress `embed-enhance-progress`).
struct EmbedEnhanceHeaderAction {
    let label: String
    let running: Bool
    let disabled: Bool
    /// Web `data-enhance-state`: idle, running, failed or unavailable.
    let state: String
    let perform: () -> Void

    @MainActor
    init(model: EmbedVersionEditModel) {
        let phase = model.phase
        running = phase == .running
        disabled = !phase.canStart
        state = phase.buttonState
        switch phase {
        case .running: label = AppStrings.embedEditEnhanceRunning
        case .unavailable(.team): label = AppStrings.embedEditEnhanceUnavailableTeam
        case .unavailable(.readOnly): label = AppStrings.embedEditEnhanceUnavailable
        case .failed, .expired: label = model.message?.text ?? AppStrings.embedEditEnhanceFailed
        case .insufficientCredits: label = AppStrings.embedEditInsufficientCredits
        case .idle, .saved: label = AppStrings.embedEditEnhance
        }
        perform = { [weak model] in _ = model?.startEnhance() }
    }
}

/// Web `data-enhance-state` as the accessibility value of the Enhance pill only.
struct EmbedEnhanceStateValue: ViewModifier {
    let state: String?

    @ViewBuilder
    func body(content: Content) -> some View {
        if let state { content.accessibilityValue(state) } else { content }
    }
}

// MARK: - Messages

/// Shows each new error or success message of `model` once as a notification
/// (web `notificationStore.error`).
struct EmbedEditMessageNotifier: ViewModifier {
    @ObservedObject var model: EmbedVersionEditModel

    func body(content: Content) -> some View {
        content.onChange(of: model.message) { _, message in
            guard let message else { return }
            ToastManager.shared.show(message.text, type: message.isError ? .error : .success,
                                     dedupeKey: "embed-edit-message")
        }
    }
}

// MARK: - Core version list (image fullscreen)

/// Every version of the embed, newest first, with who made it; each older
/// version can be restored as the next version. The core cannot read the
/// content of an older version, so rows have no preview.
struct EmbedCoreVersionList: View {
    @ObservedObject var model: EmbedVersionEditModel
    let kind: EmbedEditKind?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack {
                Text(AppStrings.embedEditHistoryTitle)
                    .font(.omXs.weight(.medium)).foregroundStyle(Color.fontSecondary)
                Spacer()
                if model.historyLoading { ProgressView().controlSize(.small) }
            }
            if model.historyFailed && model.history == nil {
                Text(AppStrings.embedEditHistoryFailed).font(.omTiny).foregroundStyle(Color.error)
                    .accessibilityIdentifier("embed-version-error")
                Button { Task { await model.loadHistory() } } label: {
                    Text(AppStrings.retry).font(.omTiny.weight(.medium))
                }.buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("embed-version-history-retry")
            } else if !model.showsVersionList && !model.historyLoading {
                Text(AppStrings.embedEditHistoryEmpty).font(.omTiny).foregroundStyle(Color.fontTertiary)
                    .accessibilityIdentifier("embed-version-timeline-empty")
            } else {
                ForEach(model.versionsNewestFirst, id: \.version) { version in
                    row(version)
                }
            }
        }
        .padding(.vertical, .spacing6).padding(.horizontal, .spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey5)
        .overlay(alignment: .top) { Rectangle().fill(Color.grey20).frame(height: 1) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embed-version-timeline")
    }

    private func row(_ version: EmbedVersionRecord) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing4) {
                Circle().fill(version.isCurrent ? Color.success : Color.grey30).frame(width: 10, height: 10)
                Text(title(version)).font(.omTiny).foregroundStyle(Color.fontPrimary)
                if let createdAt = version.createdAt, createdAt > 0 {
                    Text(Date(timeIntervalSince1970: TimeInterval(createdAt)), style: .date)
                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                }
                Spacer(minLength: .spacing4)
                if version.isCurrent {
                    Text(AppStrings.embedEditCurrent).font(.omTiny.weight(.medium)).foregroundStyle(Color.success)
                        .accessibilityIdentifier("embed-version-current")
                } else if model.canRestore {
                    EmbedVersionRestoreButton(model: model, version: version.version)
                }
            }
            if model.restoreConfirmVersion == version.version {
                EmbedVersionRestoreConfirmNote(model: model)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("version-dot-\(version.version)")
    }

    private func title(_ version: EmbedVersionRecord) -> String {
        if let action = version.action, let kind {
            return AppStrings.embedEditEvent(action, kind: kind, version: version.version)
        }
        return AppStrings.embedEditVersion(version.version)
    }
}

// MARK: - Restore bar (other embed types)

/// Restore of the version selected in the REST timeline (web `.timeline-footer`).
struct EmbedVersionRestoreBar: View {
    @ObservedObject var model: EmbedVersionEditModel
    let selectedVersion: Int
    let currentVersion: Int

    var body: some View {
        if model.canRestore, selectedVersion != currentVersion, selectedVersion > 0 {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack {
                    Spacer()
                    EmbedVersionRestoreButton(model: model, version: Int64(selectedVersion))
                }
                if model.restoreConfirmVersion == Int64(selectedVersion) {
                    EmbedVersionRestoreConfirmNote(model: model)
                }
            }
            .padding(.horizontal, .spacing8).padding(.bottom, .spacing4)
        }
    }
}

/// Web `.restore-btn`: "Restore" first, "Confirm" on the second tap.
private struct EmbedVersionRestoreButton: View {
    @ObservedObject var model: EmbedVersionEditModel
    let version: Int64

    private var label: String {
        if model.restoringVersion == version { return AppStrings.embedEditRestoring }
        if model.restoreConfirmVersion == version { return AppStrings.embedEditConfirmRestore }
        return AppStrings.embedEditRestoreAsNew(version)
    }

    var body: some View {
        Button { _ = model.requestRestore(version) } label: {
            Text(label).font(.omTiny.weight(.medium))
                .padding(.vertical, .spacing2).padding(.horizontal, .spacing5)
                .overlay(RoundedRectangle(cornerRadius: .radius2).stroke(Color.buttonPrimary, lineWidth: 1))
                .contentShape(RoundedRectangle(cornerRadius: .radius2))
        }
        .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
        .disabled(model.restoringVersion != nil)
        .opacity(model.restoringVersion != nil ? 0.6 : 1)
        .accessibilityIdentifier("restore-version-btn")
    }
}

private struct EmbedVersionRestoreConfirmNote: View {
    @ObservedObject var model: EmbedVersionEditModel

    var body: some View {
        HStack(alignment: .top, spacing: .spacing4) {
            Text(AppStrings.embedEditRestoreExplanation).font(.omTiny).foregroundStyle(Color.fontTertiary)
            Spacer(minLength: .spacing4)
            Button { model.cancelRestore() } label: { Text(AppStrings.cancel).font(.omTiny.weight(.medium)) }
                .buttonStyle(.plain).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("restore-version-cancel")
        }
    }
}
