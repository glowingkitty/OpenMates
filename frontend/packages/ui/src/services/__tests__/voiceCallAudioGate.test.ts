// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VoiceCallAudioGate, type VoiceDetector, type VoiceDetectorCallbacks } from '../voiceCallAudioGate';

function pcm(value = 0, samples = 512): string {
  const bytes = new Uint8Array(samples * 2);
  const view = new DataView(bytes.buffer);
  for (let index = 0; index < samples; index++) view.setInt16(index * 2, value, true);
  return btoa(String.fromCharCode(...bytes));
}
function values(chunks: string[]): number[] {
  return chunks.flatMap((chunk) => {
    const bytes = atob(chunk);
    const buffer = Uint8Array.from(bytes, (value) => value.charCodeAt(0));
    const view = new DataView(buffer.buffer);
    return Array.from({ length: bytes.length / 2 }, (_, index) => view.getInt16(index * 2, true));
  });
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function harness() {
  const audio: string[] = [];
  const events: Array<string> = [];
  const states: Array<{ inputIdle: boolean; userSpeaking: boolean }> = [];
  const error = vi.fn();
  let callbacks!: VoiceDetectorCallbacks;
  let signal!: AbortSignal;
  let resolve!: (detector: VoiceDetector) => void;
  let reject!: (error: Error) => void;
  const detector: VoiceDetector = { push: vi.fn(), reset: vi.fn(), stop: vi.fn() };
  const createDetector = vi.fn((next: VoiceDetectorCallbacks, abort: AbortSignal) => {
    callbacks = next;
    signal = abort;
    return new Promise<VoiceDetector>((yes, no) => { resolve = yes; reject = no; });
  });
  const gate = new VoiceCallAudioGate({
    onAudio: (data) => { audio.push(data); events.push('audio'); },
    onAudioEnd: () => events.push('end'),
    onState: (state) => states.push(state), onError: error, createDetector,
  });
  const frame = (probability = 0, value = 0) => {
    gate.push(pcm(value));
    callbacks.onResult(probability, 512);
  };
  const ready = async () => {
    gate.start(); gate.setLive(true); await flush(); resolve(detector); await flush();
  };
  return { gate, audio, events, states, error, detector, createDetector, ready, frame,
    resolve: () => resolve(detector), reject: () => reject(new Error('offline')),
    callbacks: () => callbacks, signal: () => signal };
}

describe('VoiceCallAudioGate', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.spyOn(console, 'warn').mockImplementation(() => {}); });
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection
  it('connects and streams during an arbitrarily cold model download', async () => {
    const h = harness();
    h.gate.start(); expect(h.createDetector).not.toHaveBeenCalled();
    h.gate.setLive(true);
    h.gate.push(pcm(12));
    expect(h.audio).toEqual([pcm(12)]);
    await flush();
    expect(h.createDetector).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(29_000);
    h.gate.push(pcm(13));
    expect(h.events).toEqual(['audio', 'audio']);
    expect(h.states).toEqual([]);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('requires five full seconds after readiness and sends one ordered end marker', async () => {
    const h = harness();
    await h.ready();
    for (let i = 0; i < 156; i++) h.frame(); // 4.992 verified seconds
    expect(h.events.filter((event) => event === 'end')).toHaveLength(0);
    h.frame();
    expect(h.states.at(-1)).toEqual({ inputIdle: true, userSpeaking: false });
    expect(h.events.slice(-2)).toEqual(['audio', 'end']);
    for (let i = 0; i < 20; i++) h.frame();
    expect(h.events.filter((event) => event === 'end')).toHaveLength(1);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('flushes the 400ms unsent onset history exactly once and keeps sample order', async () => {
    const h = harness(); await h.ready();
    for (let i = 0; i < 157; i++) h.frame();
    const prior = h.audio.length;
    for (let i = 1; i <= 15; i++) h.frame(0, i);
    h.frame(0.9, 16); // one very short positive frame must resume
    const resumed = values(h.audio.slice(prior));
    expect(resumed).toHaveLength(6400);
    expect(resumed.slice(0, 256)).toEqual(Array(256).fill(4));
    expect(resumed.slice(-512)).toEqual(Array(512).fill(16));
    expect(resumed.every((value, index) => !index || value >= resumed[index - 1])).toBe(true);
    expect(h.states.at(-1)).toEqual({ inputIdle: false, userSpeaking: true });
    h.frame(0.9, 17);
    expect(values(h.audio.slice(prior))).toEqual([...resumed, ...Array(512).fill(17)]);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('keeps speech pauses streaming and restarts the full silence interval for ambiguous/short speech', async () => {
    const h = harness(); await h.ready();
    for (let i = 0; i < 150; i++) h.frame();
    h.frame(0.36); // ambiguous speech is never verified silence
    for (let i = 0; i < 156; i++) h.frame();
    expect(h.events).not.toContain('end');
    h.frame(0.95); // even one "stop" frame resets the timer
    for (let i = 0; i < 156; i++) h.frame();
    expect(h.events).not.toContain('end');
    h.frame();
    expect(h.events.filter((event) => event === 'end')).toHaveLength(1);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('requires a new full five seconds of verified quiet after uncertain frames', async () => {
    const h = harness(); await h.ready();
    h.frame(0.95);
    for (let i = 0; i < 153; i++) h.frame(0.1); // 4.896 seconds of verified quiet
    for (let i = 0; i < 10; i++) h.frame(0.27); // ambiguous audio cannot finish the interval
    expect(h.events).not.toContain('end');
    for (let i = 0; i < 156; i++) h.frame(0.1);
    expect(h.events).not.toContain('end');
    h.frame(0.1);
    expect(h.events.filter((event) => event === 'end')).toHaveLength(1);
    h.frame(0.35); // retain single-frame onset for very short speech
    expect(h.states.at(-1)).toEqual({ inputIdle: false, userSpeaking: true });
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer
  it('flushes startup PCM FIFO before live PCM and rejects a ten-second overflow visibly', async () => {
    const h = harness();
    h.gate.push(pcm(1)); h.gate.push(pcm(2));
    expect(h.audio).toEqual([]);
    h.gate.setLive(true); h.gate.push(pcm(3));
    expect(h.audio).toEqual([pcm(1), pcm(2), pcm(3)]);
    h.gate.stop();
    const overflow = harness();
    for (let i = 0; i < 312; i++) overflow.gate.push(pcm());
    overflow.gate.push(pcm(0, 256)); // exactly ten seconds
    expect(overflow.error).not.toHaveBeenCalled();
    overflow.gate.push(pcm(1, 1));
    expect(overflow.error).toHaveBeenCalledOnce();
    overflow.gate.setLive(true);
    expect(overflow.audio).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle,video-call.audio.startup-buffer
  it('manual mute drops startup and onset buffers and cannot unmute itself', async () => {
    const startup = harness();
    startup.gate.push(pcm(123)); startup.gate.setMuted(true); startup.gate.setLive(true);
    startup.gate.setMuted(false); startup.gate.push(pcm(456));
    expect(startup.audio).toEqual([pcm(456)]); startup.gate.stop();
    const h = harness(); await h.ready();
    for (let i = 0; i < 157; i++) h.frame();
    h.frame(0, 123);
    h.gate.setMuted(true);
    h.gate.push(pcm(555)); h.callbacks().onResult(1, 512);
    expect(h.states.at(-1)).toEqual({ inputIdle: false, userSpeaking: false });
    const prior = h.audio.length;
    h.gate.setMuted(false); h.frame(1, 456);
    expect(h.audio.slice(prior)).toEqual([pcm(456)]);
    expect(h.events.filter((event) => event === 'end')).toHaveLength(1);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('manual mute sends exactly one end for an open stream and ignores repeated mute', async () => {
    const h = harness(); await h.ready(); h.frame(1);
    h.gate.setMuted(true); h.gate.setMuted(true);
    expect(h.events).toEqual(['audio', 'end']);
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.automatic-idle
  it.each(['failed', 'stalled', 'overrun', 'invalid'] as const)('recovers continuous upload on %s detection without dropping buffered speech', async (failure) => {
    const h = harness(); await h.ready();
    for (let i = 0; i < 157; i++) h.frame();
    const prior = h.audio.length;
    h.gate.push(pcm(321));
    if (failure === 'failed') h.callbacks().onFailure();
    if (failure === 'stalled') await vi.advanceTimersByTimeAsync(300);
    if (failure === 'overrun') for (let i = 0; i < 8; i++) h.gate.push(pcm(322));
    if (failure === 'invalid') h.callbacks().onResult(NaN, 512);
    expect(h.states.at(-1)).toEqual({ inputIdle: false, userSpeaking: false });
    expect(h.detector.stop).toHaveBeenCalledOnce();
    expect(values(h.audio.slice(prior)).slice(0, 512)).toEqual(Array(512).fill(321));
    const current = h.audio.length;
    h.gate.push(pcm(999));
    expect(h.audio.slice(current)).toEqual([pcm(999)]);
    expect(h.error).not.toHaveBeenCalled();
    h.gate.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection
  it('handles failed loading and loading timeout without blocking or falsely idling', async () => {
    for (const fail of ['reject', 'timeout']) {
      const h = harness(); h.gate.start(); h.gate.setLive(true); await flush();
      if (fail === 'reject') { h.reject(); await flush(); }
      else await vi.advanceTimersByTimeAsync(30_001);
      h.gate.push(pcm(42));
      expect(h.audio).toEqual([pcm(42)]);
      expect(h.states).toEqual([]);
      expect(h.signal().aborted).toBe(true);
      expect(h.error).not.toHaveBeenCalled();
      h.gate.stop();
    }
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.single-owner
  it('aborts resources at hangup and releases late initialization without touching a later call', async () => {
    const old = harness(); old.gate.start(); old.gate.setLive(true); await flush();
    old.gate.stop(); expect(old.signal().aborted).toBe(true);
    const next = harness(); await next.ready();
    old.resolve(); await flush(); old.callbacks().onResult(1, 512);
    old.gate.push(pcm(99));
    expect(old.detector.stop).toHaveBeenCalledOnce();
    expect(old.audio).toEqual([]); expect(old.states).toEqual([]);
    next.frame(1, 42);
    expect(next.audio).toEqual([pcm(42)]);
    next.gate.stop(); expect(next.detector.stop).toHaveBeenCalledOnce();
  });
});
