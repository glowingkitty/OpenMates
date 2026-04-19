// Chat context menu — long-press/right-click actions on chat list items.
// Mirrors ChatContextMenu.svelte: pin, hide, share, archive, delete, rename.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/chats/ChatContextMenu.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatContextMenuActions: View {
    let chat: Chat
    let onPin: () -> Void
    let onHide: () -> Void
    let onShare: () -> Void
    let onArchive: () -> Void
    let onRename: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Group {
            Button { onPin() } label: {
                Label(
                    chat.isPinned == true ? "Unpin" : "Pin",
                    systemImage: chat.isPinned == true ? "pin.slash" : "pin"
                )
            }

            Button { onRename() } label: {
                Label("Rename", systemImage: "pencil")
            }

            Button { onShare() } label: {
                Label("Share Chat", systemImage: SFSymbol.share2)
            }

            Divider()

            Button { onHide() } label: {
                Label("Hide Chat", systemImage: "eye.slash")
            }

            Button { onArchive() } label: {
                Label("Archive", systemImage: "archivebox")
            }

            Divider()

            Button(role: .destructive) { onDelete() } label: {
                Label("Delete", systemImage: "trash")
            }
        }
    }
}
