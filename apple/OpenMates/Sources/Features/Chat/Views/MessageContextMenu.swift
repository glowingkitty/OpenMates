// Message context menu — long-press/right-click actions on individual messages.
// Mirrors MessageContextMenu.svelte: copy, edit, delete, fork.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/chats/MessageContextMenu.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct MessageContextMenu: View {
    let message: Message
    let onCopy: () -> Void
    let onEdit: () -> Void
    let onDelete: () -> Void
    let onFork: () -> Void

    var isUser: Bool { message.role == .user }

    var body: some View {
        Group {
            Button { onCopy() } label: {
                Label("Copy", systemImage: "doc.on.doc")
            }

            if isUser {
                Button { onEdit() } label: {
                    Label("Edit Message", systemImage: "pencil")
                }
            }

            Button { onFork() } label: {
                Label("Fork Conversation", systemImage: "arrow.triangle.branch")
            }

            Divider()

            Button(role: .destructive) { onDelete() } label: {
                Label("Delete Message", systemImage: "trash")
            }
        }
    }
}
