/** Keep a live edit while a saved chat's no-draft restore finishes binding. */
export function shouldKeepComposerDuringNoDraftRestore(input: {
    restoredChatId: string;
    activeChatId: string | null;
    boundDraftChatId: string | null;
    hasText: boolean;
    isWarmComposerContinuation: boolean;
    hasLiveUserEditForChat: boolean;
}): boolean {
    if (!input.hasText || input.activeChatId !== input.restoredChatId) return false;
    return !input.isWarmComposerContinuation ||
        input.boundDraftChatId === input.restoredChatId ||
        input.hasLiveUserEditForChat;
}
