// Chat timeline row for the "embed updated" system event (after an embed edit,
// restore or Enhance) and the placement of the folded runs in the transcript.
// The grouping is done by the Rust core (`embedUpdateTimeline`, pure); this file
// only decides where each folded run is drawn and renders its one line.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/EmbedUpdatedEventNotice.svelte
//          frontend/packages/ui/src/components/SystemMessageNotice.svelte
//          frontend/packages/ui/src/components/embedUpdatedHistory.ts (placement)
// CSS:     SystemMessageNotice.svelte <style> .system-message-notice
//          (max-width 80%, centred, padding spacing-4 / spacing-8, radius-5,
//          grey-10 background, xs font, grey-60 text)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/embed-user-edits/specification.yml
// Assertions: embed-user-edits.event.chat-notice, embed-user-edits.event.collapse

import SwiftUI

// MARK: - Placement

/// Where the folded "embed updated" runs of a chat window are drawn: a run is
/// shown at its newest message; the older messages of the run are not drawn.
struct EmbedUpdatedPlacement: Equatable {
    var shown: [String: EmbedUpdatedGroupRecord] = [:]
    var hidden: Set<String> = []

    static let empty = EmbedUpdatedPlacement()

    /// Cheap pre-check only; the core validates the event payload.
    static func isCandidate(_ message: Message) -> Bool {
        message.role == .system && (message.content ?? "").contains("\"embed_updated\"")
    }

    /// Changes only when a candidate row or its position changes, so the
    /// core fold runs once per change and not once per transcript evaluation.
    static func candidateKey(_ messages: [Message]) -> String {
        var parts: [String] = []
        for (index, message) in messages.enumerated() where isCandidate(message) {
            parts.append("\(message.id)@\(index):\((message.content ?? "").count)")
        }
        return parts.joined(separator: "|")
    }

    static func row(for message: Message) -> EmbedTimelineRowRecord {
        let role: MessageRoleRecord
        switch message.role {
        case .user: role = .user
        case .assistant: role = .assistant
        case .system: role = .system
        }
        return EmbedTimelineRowRecord(messageId: message.id, role: role,
                                      content: isCandidate(message) ? (message.content ?? "") : "")
    }

    init() {}

    /// `fold` is the core's `embedUpdateTimeline`; tests pass a scripted fold.
    init(messages: [Message],
         fold: ([EmbedTimelineRowRecord]) -> [EmbedTimelineItemRecord] = { embedUpdateTimeline(rows: $0) }) {
        guard messages.contains(where: Self.isCandidate) else { return }
        for item in fold(messages.map(Self.row(for:))) {
            switch item {
            case .message(_, _):
                continue
            case .embedUpdated(let group):
                guard let newest = group.messageIds.last else { continue }
                shown[newest] = group
                hidden.formUnion(group.messageIds.dropLast())
            }
        }
    }
}

// MARK: - Strings (existing web keys)

extension EmbedEditKind {
    init(record: EmbedKindRecord) {
        switch record {
        case .image: self = .image
        case .diagram: self = .diagram
        case .slides: self = .slides
        case .sheet: self = .sheet
        case .document: self = .document
        }
    }
}

extension AppStrings {
    /// "Image enhanced · version 3", "Slides edited 4 times · version 7"
    /// (web `EmbedUpdatedEventNotice.svelte` label).
    static func embedUpdatedLabel(_ group: EmbedUpdatedGroupRecord) -> String {
        let kind = embedEditKind(EmbedEditKind(record: group.embedKind))
        let version = String(group.latestVersion)
        if group.changeCount > 1 {
            let key = group.latestAction == .edit ? "edit_many" : "updated_many"
            return LocalizationManager.shared.text("embed_user_edits.event.\(key)",
                replacements: ["kind": kind, "count": String(group.changeCount), "version": version])
        }
        if group.latestAction == .restore {
            guard let from = group.restoredFrom else {
                return LocalizationManager.shared.text("embed_user_edits.event.restore_plain",
                    replacements: ["kind": kind, "version": version])
            }
            return LocalizationManager.shared.text("embed_user_edits.event.restore",
                replacements: ["kind": kind, "version": version, "from": String(from)])
        }
        return embedEditEvent(group.latestAction, kind: EmbedEditKind(record: group.embedKind),
                              version: group.latestVersion)
    }

    static var embedUpdatedOpen: String { LocalizationManager.shared.text("embed_user_edits.event.open") }
}

// MARK: - View

/// One quiet, centred line; tapping it opens the embed.
struct EmbedUpdatedNoticeView: View {
    let group: EmbedUpdatedGroupRecord
    let onOpen: () -> Void

    var body: some View {
        let label = AppStrings.embedUpdatedLabel(group)
        HStack(spacing: 0) {
            Spacer(minLength: 0)
            Button(action: onOpen) {
                Text(label)
                    .font(.omXs)
                    .foregroundStyle(Color.grey60)
                    .multilineTextAlignment(.center)
                    .padding(.vertical, .spacing4)
                    .padding(.horizontal, .spacing8)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(label). \(AppStrings.embedUpdatedOpen)")
            .accessibilityIdentifier("embed-updated-event")
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing2)
    }
}

// MARK: - Version change signal

extension Notification.Name {
    /// Posted by the embed fullscreen after Enhance, restore or edit made a new
    /// version (`userInfo["embedId"]`); the open chat refetches its embeds.
    static let embedVersionHeadChanged = Notification.Name("openmates.embedVersionHeadChanged")
}
