import { describe, expect, it, vi } from 'vitest';
import { isComposerSendBusy, resolveSavedModelForAcceptedSend, shouldDismissComposerAfterSend } from '../sendReadiness';

describe('composer Send readiness shared by expanded and compact controls', () => {
    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,ai-model-routing.chat-selection.encrypted-user-chat-scope
    it('accepts an ordinary Send while a saved model preference restores', () => {
        expect(isComposerSendBusy(false, false)).toBe(false);
        expect(isComposerSendBusy(false, true)).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
    it('keeps pending sends busy and permits queued edits without model restoration', () => {
        expect(isComposerSendBusy(true, true)).toBe(true);
        expect(isComposerSendBusy(false, false, true)).toBe(false);
        expect(isComposerSendBusy(true, false, true)).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
    it('leaves a newer focused selector and newly typed draft open after the prior send finishes', () => {
        expect(shouldDismissComposerAfterSend({ focusGenerationAtSend: 1,
            currentFocusGeneration: 2, hasNewDraft: false, sameOwner: true })).toBe(false);
        expect(shouldDismissComposerAfterSend({ focusGenerationAtSend: 1,
            currentFocusGeneration: 1, hasNewDraft: true, sameOwner: true })).toBe(false);
        expect(shouldDismissComposerAfterSend({ focusGenerationAtSend: 1,
            currentFocusGeneration: 1, hasNewDraft: false, sameOwner: false })).toBe(false);
        expect(shouldDismissComposerAfterSend({ focusGenerationAtSend: 1,
            currentFocusGeneration: 1, hasNewDraft: false, sameOwner: true })).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,ai-model-routing.chat-selection.encrypted-user-chat-scope
    it('continues the admitted click with the exact restored model', async () => {
        let finishRestore!: (ready: boolean) => void;
        const settled = new Promise<boolean>((resolve) => { finishRestore = resolve; });
        let restored = 'auto';
        const recover = vi.fn(async (selection: string) => selection);
        const result = resolveSavedModelForAcceptedSend({
            settled, readyAtClick: false, selectionAtClick: 'auto',
            readRestoredSelection: () => restored, stillOwned: () => true, recover,
        });
        expect(recover).not.toHaveBeenCalled();
        restored = 'google/gemini-2.5-pro';
        finishRestore(true);
        await expect(result).resolves.toBe('google/gemini-2.5-pro');
        expect(recover).toHaveBeenCalledWith('google/gemini-2.5-pro');
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
    it('rejects restoration after chat ownership changes', async () => {
        await expect(resolveSavedModelForAcceptedSend({
            settled: Promise.resolve(true), readyAtClick: false, selectionAtClick: 'auto',
            readRestoredSelection: () => 'google/gemini-2.5-pro',
            stillOwned: () => false, recover: async (selection) => selection,
        })).rejects.toThrow('Composer owner changed');
    });
});
