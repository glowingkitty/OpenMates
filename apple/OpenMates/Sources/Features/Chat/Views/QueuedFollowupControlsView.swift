// Queue status and actions below the corresponding user message.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/chats/QueuedFollowupControls.svelte
// CSS: .queued-followup-controls, .queued-followup-actions, .queued-followup-action
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chat-queued-followups/specification.yml
// Assertions: chat-queued-followups.editing.stable-revision, chat-queued-followups.editing.cancel,
// chat-queued-followups.steering.safe-boundary
import SwiftUI

struct QueuedFollowupControlsView: View {
    let state: ChatQueuedFollowupState
    let busy: Bool
    let error: String?
    let onEdit: () -> Void
    let onSteer: () -> Void
    var body: some View {
        VStack(alignment: .trailing, spacing: .spacing1) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: .spacing2) { status; actions }
                VStack(alignment: .trailing, spacing: .spacing1) { status; HStack(spacing: .spacing2) { actions } }
            }.font(.omXs.weight(.semibold)).foregroundStyle(Color.buttonPrimary).disabled(busy)
            if let error {
                Text(error).font(.omXs).foregroundStyle(Color.error).multilineTextAlignment(.trailing)
                    .accessibilityIdentifier("queued-followup-error")
                    .accessibilityAddTraits(.updatesFrequently)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.top, .spacing2)
        .accessibilityIdentifier("queued-followup-controls")
        .accessibilityValue(state.mode.rawValue)
    }
    private var status: some View {
        HStack(spacing: .spacing1) {
            Circle().fill(Color.buttonPrimary).frame(width: .spacing3, height: .spacing3).accessibilityHidden(true)
            Text(busy ? AppStrings.queuedFollowupUpdating : state.mode == .steer ? AppStrings.queuedFollowupSteering : AppStrings.queuedFollowupQueued)
                .font(.omXs.weight(.semibold)).foregroundStyle(Color.fontSecondary)
        }.accessibilityIdentifier("queued-followup-status")
    }
    @ViewBuilder private var actions: some View {
        Button(AppStrings.edit, action: onEdit).buttonStyle(.plain)
            .padding(.vertical, .spacing1).padding(.horizontal, .spacing2)
            .accessibilityIdentifier("queued-followup-edit")
        if state.mode == .followUp {
            Button(AppStrings.queuedFollowupSteerInstead, action: onSteer).buttonStyle(.plain)
                .padding(.vertical, .spacing1).padding(.horizontal, .spacing2)
                .accessibilityIdentifier("queued-followup-steer")
        }
    }

}

struct QueuedFollowupEditBanner: View {
    let onCancel: () -> Void
    var body: some View {
        HStack(spacing: .spacing2) {
            Text(AppStrings.queuedFollowupEditing).font(.omSmall).foregroundStyle(Color.fontSecondary)
            Spacer(minLength: 0)
            Button(AppStrings.queuedFollowupCancelEdit, action: onCancel).buttonStyle(.plain)
                .font(.omSmall).foregroundStyle(Color.buttonPrimary)
                .accessibilityIdentifier("queued-followup-cancel-edit")
        }.accessibilityIdentifier("queued-followup-editing")
    }
}
