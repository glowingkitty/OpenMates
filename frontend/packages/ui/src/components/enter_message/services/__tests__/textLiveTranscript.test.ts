import { describe, expect, it } from 'vitest';
import { createTextLiveTranscript, type TextComposerAccess } from '../textLiveTranscript';

function field(value = '', caret = value.length) {
    const state = { value, selectionStart: caret, selectionEnd: caret };
    const access: TextComposerAccess = {
        read: () => ({ ...state }),
        write: (next, at) => { state.value = next; state.selectionStart = at; state.selectionEnd = at; },
    };
    return { state, access, type(next: string, at = next.length) { state.value = next; state.selectionStart = at; state.selectionEnd = at; } };
}

describe('textLiveTranscript', () => {
    // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
    it('streams cumulative words in at the caret with separator spaces', () => {
        const f = field('Plan a trip', 6);
        const live = createTextLiveTranscript(f.access);
        expect(live.apply('great')).toBe(true);
        expect(live.apply('great weekend')).toBe(true);
        expect(f.state.value).toBe('Plan a great weekend trip');
        expect(f.state.selectionStart).toBe('Plan a great weekend'.length);
        expect(live.hasText()).toBe(true);
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
    it('replaces one untouched segment with the corrected transcript', () => {
        const f = field();
        const live = createTextLiveTranscript(f.access);
        live.apply('um book a table');
        expect(live.applyCorrection('Book a table.')).toBe('replaced');
        expect(f.state.value).toBe('Book a table.');
        expect(live.hasText()).toBe(true);
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
    it('keeps the corrected segment after typed text when the correction changes its edges', () => {
        const f = field('Keep the mountain.');
        const live = createTextLiveTranscript(f.access);
        live.apply('make the sky brighter');
        expect(live.applyCorrection('Make the sky brighter.')).toBe('replaced');
        expect(f.state.value).toBe('Keep the mountain. Make the sky brighter.');
        expect(live.hasText()).toBe(true);
        live.discard();
        expect(f.state.value).toBe('Keep the mountain.');
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
    it('follows user edits before the segment and keeps edited dictation', () => {
        const f = field();
        const live = createTextLiveTranscript(f.access);
        live.apply('book a table');
        f.type('Please book a table', 'Please book a table'.length);
        live.observe(f.state.value);
        expect(live.applyCorrection('Book a table.')).toBe('replaced');
        expect(f.state.value).toBe('Please Book a table.');
        f.type('Please Book a big table.');
        live.observe(f.state.value);
        expect(live.applyCorrection('Something else')).toBe('kept');
        expect(f.state.value).toBe('Please Book a big table.');
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
    it('inserts the correction when nothing streamed and discards untouched text on cancel', () => {
        const empty = field('Hi');
        expect(createTextLiveTranscript(empty.access).applyCorrection('there')).toBe('inserted');
        expect(empty.state.value).toBe('Hi there');

        const f = field('Keep this');
        const live = createTextLiveTranscript(f.access);
        live.apply('dictated words');
        live.discard();
        expect(f.state.value).toBe('Keep this');
        expect(live.hasText()).toBe(false);
    });
});
