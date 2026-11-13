// ProjectCreatedCardView — the card a chat shows when the assistant created a
// Project for the turn and activated its focus ("Created project <name>" +
// "Work on <name> · Focus activated"). It replaces the focus-mode bar of a
// focus-mode-activation embed whose decrypted content carries
// `project_created: true` and a `project_id` (FocusModeActivationRenderer.ts).
// Tapping the Project name opens that Project (openmates://projects/<id>).
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/focus_mode/FocusModeActivationEmbed.svelte
//          ({#if projectCreated} block, data-testid project-created-*)
//          frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/FocusModeActivationRenderer.ts
// CSS:     FocusModeActivationEmbed.svelte <style>: .project-created-card, .created-row,
//          .created-row + .created-row, .app-icon-circle, .focus-skill-icon, .row-text,
//          .row-label, .project-link, .status-value, .active-status
// Tokens:  ColorTokens.generated.swift (grey30, grey25, grey100, grey70, success, buttonPrimary),
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift,
//          GradientTokens.generated.swift (iconFocus)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.focus.inferred-consent, projects.creation.assistant-inferred
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12, assistant-created Projects card)
//
// Undo runs in the client core (`ViewModelCore.undoCreatedProject`, via
// `CoreChatActions.undoCreatedProject`); the card offers it only with a chat id.
// Gap: the web also shows the undone state after a reload by checking that the
// Project is gone; here the undone state lasts for the card's lifetime.

import SwiftUI

/// The assistant-created Project facts read from the decrypted activation embed.
struct ProjectCreatedFocus: Equatable {
    let projectID: String
    let projectName: String

    /// Mirrors FocusModeActivationRenderer.ts: `project_created === true` and a
    /// string `project_id`; the name falls back to the focus name without "Work on ".
    init?(data: [String: AnyCodable]?, focusName: String) {
        guard data?["project_created"]?.value as? Bool == true,
              let id = data?["project_id"]?.value as? String, !id.isEmpty else { return nil }
        projectID = id
        let name = data?["project_name"]?.value as? String ?? ""
        projectName = name.isEmpty
            ? (focusName.hasPrefix("Work on ") ? String(focusName.dropFirst("Work on ".count)) : focusName)
            : name
    }
}

/// Undo state of the card (`FocusModeActivationEmbed.svelte` undoing / undoError / creationUndone).
@MainActor
final class ProjectCreatedUndoModel: ObservableObject {
    @Published private(set) var isUndone = false
    @Published private(set) var isUndoing = false
    @Published private(set) var failed = false
    private let chatID: String?
    private let undo: (String) async throws -> Void

    init(chatID: String?,
         undo: @escaping (String) async throws -> Void = { _ = try await CoreChatActions.shared.undoCreatedProject(chatId: $0) }) {
        self.chatID = chatID
        self.undo = undo
    }

    /// Undo is offered while the chat is known and the Project is not undone.
    var canUndo: Bool { chatID != nil && !isUndone }

    func performUndo() async {
        guard let chatID, !isUndoing, !isUndone else { return }
        isUndoing = true
        failed = false
        do {
            try await undo(chatID)
            isUndone = true
        } catch {
            failed = true
        }
        isUndoing = false
    }
}

struct ProjectCreatedCardView: View {
    private enum Layout {
        /// `.project-created-card` width: 380px (max-width: 100%).
        static let maxWidth: CGFloat = 380
        /// `.created-row` min-height: 44px.
        static let rowMinHeight: CGFloat = 44
        /// `.app-icon-circle` 36px and its 20px glyph.
        static let appCircle: CGFloat = 36
        static let appGlyph: CGFloat = 20
        /// `.focus-skill-icon` 36 × 29px insight mask.
        static let focusIconWidth: CGFloat = 36
        static let focusIconHeight: CGFloat = 29
    }

    let created: ProjectCreatedFocus
    let focusID: String
    @StateObject private var undoModel: ProjectCreatedUndoModel

    init(created: ProjectCreatedFocus, focusID: String, chatID: String? = nil) {
        self.created = created
        self.focusID = focusID
        _undoModel = StateObject(wrappedValue: ProjectCreatedUndoModel(chatID: chatID))
    }

    var body: some View {
        // Card gap spacing2 between rows; the second row adds a 1px grey25
        // border-top and padding-top spacing3 (`.created-row + .created-row`).
        VStack(alignment: .leading, spacing: 0) {
            createdRow
            Rectangle().fill(Color.grey25).frame(height: 1)
                .padding(.top, .spacing2)
                .accessibilityHidden(true)
            focusRow
                .padding(.top, .spacing3)
        }
        .padding(.spacing4)
        .frame(maxWidth: Layout.maxWidth, alignment: .leading)
        .background(Color.grey30)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-created-card")
        .accessibilityValue(focusID)
    }

    private var createdRow: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            Circle()
                .fill(AppIconView.gradient(forAppId: "projects"))
                .frame(width: Layout.appCircle, height: Layout.appCircle)
                .overlay {
                    Icon(AppIconView.iconName(forAppId: "projects"), size: Layout.appGlyph)
                        .foregroundStyle(.white)
                }
                .accessibilityHidden(true)
                .accessibilityIdentifier("focus-app-icon")
            VStack(alignment: .leading, spacing: .spacing1) {
                if undoModel.isUndone {
                    Text(AppStrings.projectCreatedUndone)
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.grey100)
                        .accessibilityIdentifier("project-created-status")
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                        Text(AppStrings.projectCreatedLabel).foregroundStyle(Color.grey100)
                        projectLink(identifier: "project-created-name")
                    }
                    .font(.omP.weight(.semibold))
                }
                if undoModel.failed {
                    Text(AppStrings.projectCreatedUndoFailed)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .accessibilityIdentifier("project-created-undo-error")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if undoModel.canUndo {
                Button { Task { await undoModel.performUndo() } } label: {
                    Text(AppStrings.projectCreatedUndo)
                        .font(.omP)
                        .foregroundStyle(Color.grey100)
                        .padding(.horizontal, .spacing4)
                        .padding(.vertical, .spacing2)
                        .background(Color.grey25)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                }
                .buttonStyle(.plain)
                .disabled(undoModel.isUndoing)
                .opacity(undoModel.isUndoing ? 0.5 : 1)
                .accessibilityIdentifier("project-created-undo")
            }
        }
        .frame(minHeight: Layout.rowMinHeight)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-created-row")
        .accessibilityValue(undoModel.isUndone ? "undone" : "created")
    }

    private var focusRow: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            Icon("insight", size: Layout.focusIconHeight)
                .foregroundStyle(LinearGradient.iconFocus)
                .frame(width: Layout.focusIconWidth, height: Layout.focusIconHeight)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: .spacing1) {
                HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                    Text(AppStrings.projectWorkOnLabel).foregroundStyle(Color.grey100)
                    if undoModel.isUndone {
                        Text(created.projectName).foregroundStyle(Color.grey100)
                    } else {
                        projectLink(identifier: "project-focus-name")
                    }
                }
                .font(.omP.weight(.semibold))
                Text(undoModel.isUndone ? AppStrings.projectFocusNotActive : AppStrings.focusModeActivated)
                    .font(.omP)
                    .foregroundStyle(undoModel.isUndone ? Color.grey70 : Color.success)
                    .accessibilityIdentifier("focus-status-value")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(minHeight: Layout.rowMinHeight)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-focus-row")
        .accessibilityValue(undoModel.isUndone ? "inactive" : "activated")
    }

    /// `.project-link`: underlined primary-colored inline button with the Project name.
    private func projectLink(identifier: String) -> some View {
        Button(action: openProject) {
            Text(created.projectName)
                .underline()
                .foregroundStyle(Color.buttonPrimary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func openProject() {
        // DeepLinkHandler routes openmates://projects/<uuid> to the Project workspace.
        guard let url = URL(string: "openmates://projects/\(created.projectID)") else { return }
        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
    }
}
