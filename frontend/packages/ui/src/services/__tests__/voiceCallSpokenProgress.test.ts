// Spoken-word progress for live call replies: dim while generated, reveal as
// spoken, release permanently on settle, new user speech, call end or no speech.
import { describe, expect, it } from 'vitest';
import { get, writable } from 'svelte/store';
import type { VoiceCallState } from '../voiceCall';
import { createVoiceCallSpokenProgress, SPOKEN_PROGRESS_START_GRACE_MS, type SpokenWordProgressSource } from '../voiceCallSpokenProgress';
import { unspokenRange } from '../../utils/spokenWordHighlight';

function harness() {
  const call = writable<VoiceCallState>({ status: 'live', chatId: 'chat', callId: 'call',
    assistantMessageId: 'reply', assistantGenerating: true } as VoiceCallState);
  const speech: { spokenWordProgress: SpokenWordProgressSource['spokenWordProgress'] } = { spokenWordProgress: null };
  let now = 0;
  const pending: Array<() => void> = [];
  const frames = { request: (callback: () => void) => pending.push(callback), cancel: () => undefined, now: () => now };
  const store = createVoiceCallSpokenProgress(call, speech, frames);
  const values: unknown[] = [];
  const stop = store.subscribe((value) => values.push(value));
  const frame = (ms = 16) => { now += ms; pending.splice(0).forEach((callback) => callback()); };
  return { call, speech, store, values, stop, frame, advance: (ms: number) => { now += ms; } };
}

describe('voiceCallSpokenProgress', () => {
  // contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response
  it('dims a generating reply, reveals spoken words, and releases it once playback settles', () => {
    const { call, speech, store, frame, stop } = harness();
    expect(get(store)).toEqual({ messageId: 'reply', words: 0 });
    speech.spokenWordProgress = { responseId: 'reply', words: 3, began: true, settled: false };
    frame();
    expect(get(store)).toEqual({ messageId: 'reply', words: 3 });
    speech.spokenWordProgress = { responseId: 'reply', words: 3, began: true, settled: true };
    frame();
    expect(get(store)).toBeNull();
    // Released replies stay fully visible even if progress is reported again.
    speech.spokenWordProgress = { responseId: 'reply', words: 4, began: true, settled: false };
    call.update((state) => ({ ...state }));
    expect(get(store)).toBeNull();
    stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption
  it('releases the previous reply when the caller speaks again or the call ends', () => {
    const { call, speech, store, stop } = harness();
    speech.spokenWordProgress = { responseId: 'reply', words: 1, began: true, settled: false };
    call.update((state) => ({ ...state, liveTranscript: { messageId: 'user-2', text: 'wait', submitted: false } }));
    expect(get(store)).toBeNull();
    call.update((state) => ({ ...state, liveTranscript: null }));
    expect(get(store)).toBeNull();
    call.update((state) => ({ ...state, assistantMessageId: 'reply-2' }));
    expect(get(store)).toEqual({ messageId: 'reply-2', words: 0 });
    call.update((state) => ({ ...state, status: 'ended' }));
    expect(get(store)).toBeNull();
    stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response
  it('releases a finished reply whose speech never started after the start grace', () => {
    const { call, store, frame, advance, stop } = harness();
    call.update((state) => ({ ...state, assistantGenerating: false }));
    frame();
    expect(get(store)).toEqual({ messageId: 'reply', words: 0 });
    advance(SPOKEN_PROGRESS_START_GRACE_MS);
    frame();
    expect(get(store)).toBeNull();
    stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response
  it('ranges from the first unspoken word across inline marks, skipping code', () => {
    const root = document.createElement('div');
    // Read-only messages mark the whole editor non-editable; only embeds and code are skipped.
    root.innerHTML = '<div class="ProseMirror" contenteditable="false"><p>Hello <strong>bri</strong>ght world</p>'
      + '<pre><code>skip me</code></pre><div data-embed-id="e1">embed card</div><p>Next line.</p></div>';
    expect(unspokenRange(root, 1)?.toString()).toBe('bright worldskip meembed cardNext line.');
    expect(unspokenRange(root, 3)?.toString()).toBe('Next line.');
    expect(unspokenRange(root, 0)?.startContainer.textContent).toBe('Hello ');
    expect(unspokenRange(root, 5)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response
  it('does not count the unspoken skill activity group, so later words stay aligned', () => {
    const root = document.createElement('div');
    root.innerHTML = '<div class="ProseMirror" contenteditable="false"><p>Let me check.</p></div>'
      + '<div class="assistant-activity-group" data-speech-skip><button><span>Used web search</span></button>'
      + '<span aria-hidden="true">Used web search</span></div>'
      + '<div class="ProseMirror" contenteditable="false"><p>It is sunny today.</p></div>';
    // Spoken words: Let(0) me(1) check.(2) It(3) is(4) sunny(5) today.(6)
    expect(unspokenRange(root, 3)?.toString()).toBe('It is sunny today.');
    expect(unspokenRange(root, 5)?.toString()).toBe('sunny today.');
    expect(unspokenRange(root, 7)).toBeNull();
  });
});
