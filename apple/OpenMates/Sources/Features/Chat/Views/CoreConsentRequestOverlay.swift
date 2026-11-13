// The consent dialog of a chat turn that runs through the Rust core: the
// assistant asks permission to use app settings / memories; the user picks the
// items and answers through `CoreChatActions.answerConsent`.
// Mounted by ChatView as `.overlay(alignment: .bottom) { CoreConsentRequestOverlay(chatId:) }`.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/AppSettingsMemoriesPermissionDialog.svelte
//          (ids app-settings-memories-permission-dialog, btn-include, btn-reject)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.selection.source-scoped

import SwiftUI

struct CoreConsentRequestOverlay: View {
    let chatId: String
    @ObservedObject private var actions = CoreChatActions.shared

    var body: some View {
        if let request = actions.pendingConsent[chatId] {
            CoreConsentRequestCard(chatId: chatId, request: request, actions: actions)
                .id(request.requestId)
                .padding(.horizontal, .spacing6)
                .padding(.bottom, .spacing6)
        }
    }
}

private struct CoreConsentRequestCard: View {
    let chatId: String
    let request: CoreConsentRequest
    let actions: CoreChatActions
    @State private var selected: Set<String>
    @State private var answering = false
    @State private var failureMessage: String?

    init(chatId: String, request: CoreConsentRequest, actions: CoreChatActions) {
        self.chatId = chatId
        self.request = request
        self.actions = actions
        _selected = State(initialValue: Set(request.items.map(\.id)))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.localized("chat.permissions.title"))
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            Text(AppStrings.localized("chat.permissions.question"))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            ForEach(request.items, id: \.id) { item in
                HStack(spacing: .spacing4) {
                    Text(item.title)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    OMToggle(isOn: binding(for: item.id), disabled: answering,
                             accessibilityIdentifier: "consent-item-toggle-\(item.id)")
                }
            }
            if failureMessage != nil {
                Text(AppStrings.genericProcessingError)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
            }
            HStack(spacing: .spacing4) {
                Button(AppStrings.localized("chat.permissions.reject_all")) { answer(approved: []) }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("btn-reject")
                Button(AppStrings.localized("chat.permissions.include_selected")) {
                    answer(approved: request.items.map(\.id).filter { selected.contains($0) })
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(selected.isEmpty)
                .accessibilityIdentifier("btn-include")
            }
            .disabled(answering)
        }
        .padding(.spacing6)
        .frame(maxWidth: 500)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("app-settings-memories-permission-dialog")
    }

    private func binding(for id: String) -> Binding<Bool> {
        Binding(
            get: { selected.contains(id) },
            set: { isOn in
                if isOn { selected.insert(id) } else { selected.remove(id) }
            })
    }

    private func answer(approved: [String]) {
        answering = true
        failureMessage = nil
        Task { @MainActor in
            do {
                try await actions.answerConsent(chatId: chatId, requestId: request.requestId, approvedItemIds: approved)
            } catch {
                failureMessage = CoreChatActions.userMessage(for: error)
            }
            answering = false
        }
    }
}
