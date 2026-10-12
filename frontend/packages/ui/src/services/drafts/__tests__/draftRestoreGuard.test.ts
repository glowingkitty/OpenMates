// contract-test-file: tooling
import { describe, expect, it } from 'vitest';
import { shouldKeepComposerDuringNoDraftRestore } from '../draftRestoreGuard';

describe('saved-chat no-draft restore', () => {
    const input = {
        restoredChatId: 'saved-chat',
        activeChatId: 'saved-chat',
        boundDraftChatId: null,
        hasText: true,
        isWarmComposerContinuation: true,
        hasLiveUserEditForChat: true,
    };

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,drafts.persistence.local-first-encrypted
    it('keeps text typed in the restored chat before the draft service binds it', () => {
        expect(shouldKeepComposerDuringNoDraftRestore(input)).toBe(true);
        expect(shouldKeepComposerDuringNoDraftRestore({ ...input, boundDraftChatId: 'old-chat' })).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
    it('clears old or unowned text when switching chats', () => {
        expect(shouldKeepComposerDuringNoDraftRestore({ ...input, hasLiveUserEditForChat: false })).toBe(false);
        expect(shouldKeepComposerDuringNoDraftRestore({ ...input, activeChatId: 'other-chat' })).toBe(false);
        expect(shouldKeepComposerDuringNoDraftRestore({ ...input, hasText: false })).toBe(false);
    });

    it('keeps an already bound chat draft during a repeated restore', () => {
        expect(shouldKeepComposerDuringNoDraftRestore({
            ...input, boundDraftChatId: 'saved-chat', hasLiveUserEditForChat: false,
        })).toBe(true);
    });
});
