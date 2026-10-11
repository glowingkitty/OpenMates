import { describe, expect, it } from 'vitest';
import { isComposerSendBusy } from '../sendReadiness';

describe('composer Send readiness shared by expanded and compact controls', () => {
    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,ai-model-routing.chat-selection.encrypted-user-chat-scope
    it('waits for model restoration, then enables an ordinary send', () => {
        expect(isComposerSendBusy(false, false)).toBe(true);
        expect(isComposerSendBusy(false, true)).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
    it('keeps pending sends busy and permits queued edits without model restoration', () => {
        expect(isComposerSendBusy(true, true)).toBe(true);
        expect(isComposerSendBusy(false, false, true)).toBe(false);
        expect(isComposerSendBusy(true, false, true)).toBe(true);
    });
});
