/**
 * Which chat-selection events close an open chat embed fullscreen.
 *
 * Selecting another chat closes the view; selecting the chat it was opened in
 * does not. After a page load the chat is announced again once its load
 * finishes (`globalChatSelected` for the same chat); without an owner that
 * echo closed a fullscreen the user had just opened (recipe proof, 22 Nov:
 * the application preview closed right after Start preview).
 */

/** The chat a fullscreen belongs to: the embed's explicit owner, else the chat active when it opened. */
export function fullscreenOwnerChatId(
  owningChatId: string | null | undefined,
  activeChatIdAtOpen: string | null | undefined,
  sourceChatId: string | null | undefined,
): string | null {
  return owningChatId || activeChatIdAtOpen || sourceChatId || null;
}

/** Whether selecting `selectedChatId` closes a fullscreen owned by `ownerChatId`. */
export function chatSelectionClosesFullscreen(selectedChatId: unknown, ownerChatId: string | null): boolean {
  return !(ownerChatId && selectedChatId === ownerChatId);
}
