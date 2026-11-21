import { describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { isWaitingLine, playWaitingLine, replayLastAnswer, waitingLineClipUrl } from './voiceCallWaiting';

vi.mock('svelte-i18n', async () => {
  const { writable: store } = await import('svelte/store');
  return { locale: store('de') };
});
vi.mock('../i18n/translations', async () => {
  const { readable } = await import('svelte/store');
  return { text: readable((key: string) => key) };
});

describe('voice call waiting lines', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button,video-call.waiting.spoken-intent-and-merge
  it('maps lines to system clips by app language and has none for other languages', () => {
    expect(waitingLineClipUrl('waiting_start', 'de')).toBe('/audio/assistant-acknowledgements/system/de-DE/waiting_start-1.mp3');
    expect(waitingLineClipUrl('waiting_resume', 'en-GB')).toBe('/audio/assistant-acknowledgements/system/en-US/waiting_resume-1.mp3');
    expect(waitingLineClipUrl('waiting_start', 'ja')).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button,video-call.waiting.spoken-intent-and-merge
  it('accepts only known line ids', () => {
    expect(isWaitingLine('waiting_start')).toBe(true);
    expect(isWaitingLine('chat_start')).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button,video-call.waiting.spoken-intent-and-merge
  it('plays the clip and reports refusal as false', async () => {
    const played: string[] = [];
    expect(await playWaitingLine('waiting_start', async url => { played.push(url); })).toBe(true);
    expect(played).toHaveLength(1);
    expect(await playWaitingLine('waiting_start', async () => { throw new Error('blocked'); })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button,video-call.waiting.spoken-intent-and-merge
  it('replays the stored answer without a request, and does nothing without one', async () => {
    const play = vi.fn(async () => {});
    expect(await replayLastAnswer({ player: writable({ hasReplayableTracks: true }), play })).toBe(true);
    expect(play).toHaveBeenCalledTimes(1);
    expect(await replayLastAnswer({ player: writable({ hasReplayableTracks: false }), play })).toBe(false);
    expect(play).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.spoken-intent-and-merge
  it('does not report a replay when the consumed live answer ends as completed', async () => {
    const play = vi.fn(async () => {});
    expect(await replayLastAnswer({ player: writable({ hasReplayableTracks: true, status: 'completed' }), play })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button
  it('warns with the line key when no clip exists', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { locale } = await import('svelte-i18n');
    (locale as unknown as { set(v: string): void }).set('ja');
    expect(await playWaitingLine('waiting_resume', async () => {})).toBe(false);
    expect(warn.mock.calls[0][0]).toContain('waiting_resume');
    warn.mockRestore();
  });
});

import { parseVoiceCallHistoryEvent, voiceCallWaitingMessageId } from './voiceCallLifecycleEvent';

describe('waiting lines as call events', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button
  it('parses waiting actions and rejects unknown ones', () => {
    const base = { schema_version: 1, type: 'voice_call', call_id: 'call_12345678', created_at: 10, active_elapsed_seconds: 0 };
    expect(parseVoiceCallHistoryEvent(JSON.stringify({ ...base, action: 'waiting_start' }))?.action).toBe('waiting_start');
    expect(parseVoiceCallHistoryEvent(JSON.stringify({ ...base, action: 'waiting_resume' }))?.action).toBe('waiting_resume');
    expect(parseVoiceCallHistoryEvent(JSON.stringify({ ...base, action: 'dance' }))).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=video-call.waiting.hold-button
  it('gives each occurrence its own ID between the start and end events', () => {
    const a = voiceCallWaitingMessageId('call_12345678', 'waiting_start', 1000);
    const b = voiceCallWaitingMessageId('call_12345678', 'waiting_start', 2000);
    expect(a).not.toBe(b);
    expect(a > '00000000-voice-call-x' && a < 'ffffffff-voice-call-x').toBe(true);
  });
});
