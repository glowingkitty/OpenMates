import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class AudioParamStub { setValueAtTime = vi.fn(); linearRampToValueAtTime = vi.fn(); }
class ContextStub {
  static instances: ContextStub[] = [];
  state = 'running';
  currentTime = 1;
  destination = {};
  started = 0;
  resume = vi.fn(async () => undefined);
  createOscillator = vi.fn(() => ({
    type: 'sine', frequency: new AudioParamStub(), connect: vi.fn(), disconnect: vi.fn(),
    start: vi.fn(() => { this.started++; }), stop: vi.fn(), onended: null,
  }));
  createGain = vi.fn(() => ({ gain: new AudioParamStub(), connect: vi.fn(), disconnect: vi.fn() }));
  constructor() { ContextStub.instances.push(this); }
}

type Sounds = typeof import('../eventSounds');

async function load(): Promise<{ sounds: Sounds; notice: ReturnType<typeof vi.fn> }> {
  vi.resetModules();
  const sounds = await import('../eventSounds');
  const notice = vi.fn();
  sounds.installEventSounds(notice);
  return { sounds, notice };
}

describe('event sounds', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-12T10:00:00Z'));
    localStorage.clear();
    ContextStub.instances.length = 0;
    vi.stubGlobal('AudioContext', ContextStub);
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  // contract-test: direct surface=gui.web assertions=notifications.sounds.quiet-window
  it('drops cues inside the quiet window instead of queueing them', async () => {
    const { sounds } = await load();
    const gate = new sounds.EventCueGate();
    expect(gate.admit('accepted', 0)).toBe(true);
    expect(gate.admit('error', 100)).toBe(false);
    expect(gate.admit('notification', sounds.EVENT_CUE_QUIET_WINDOW_MS)).toBe(false);
    // A dropped cue does not extend the silence.
    expect(gate.admit('notification', sounds.EVENT_CUE_QUIET_WINDOW_MS + 181)).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=notifications.sounds.important-events,notifications.sounds.first-cue-opt-out
  it('stays silent until a user gesture, then plays and shows the notice once', async () => {
    const { sounds, notice } = await load();
    expect(sounds.playEventCue('error')).toBe('audio_locked');
    expect(notice).not.toHaveBeenCalled();

    window.dispatchEvent(new Event('pointerdown'));
    expect(sounds.playEventCue('error')).toBe('played');
    // Earlier module instances keep their gesture listeners; only the current one plays.
    expect(ContextStub.instances.reduce((sum, context) => sum + context.started, 0))
      .toBe(sounds.EVENT_CUE_NOTES.error.length);
    expect(notice).toHaveBeenCalledTimes(1);

    expect(sounds.playEventCue('notification')).toBe('quiet_window');
    vi.advanceTimersByTime(10_000);
    expect(sounds.playEventCue('notification')).toBe('played');
    expect(notice).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(sounds.EVENT_SOUND_NOTICE_STORAGE_KEY)).toBe('true');
  });

  // contract-test: direct surface=gui.web assertions=notifications.sounds.silent-mode
  it('silent mode persists on the device and turns off sounds and vibrations', async () => {
    const vibrate = vi.fn();
    vi.stubGlobal('navigator', { vibrate });
    const { sounds, notice } = await load();
    window.dispatchEvent(new Event('pointerdown'));
    sounds.setSilentMode(true);
    expect(localStorage.getItem(sounds.SILENT_MODE_STORAGE_KEY)).toBe('true');
    expect(sounds.playEventCue('accepted')).toBe('silent_mode');
    sounds.vibrateDevice(50);
    expect(vibrate).not.toHaveBeenCalled();
    expect(notice).not.toHaveBeenCalled();

    const reloaded = await load();
    window.dispatchEvent(new Event('pointerdown'));
    expect(reloaded.sounds.playEventCue('accepted')).toBe('silent_mode');
    reloaded.sounds.setSilentMode(false);
    expect(reloaded.sounds.playEventCue('accepted')).toBe('played');
    expect(vibrate).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=notifications.sounds.important-events
  it('only a message sent from this device sounds when the server accepts it, and only once', async () => {
    const { sounds } = await load();
    window.dispatchEvent(new Event('pointerdown'));
    const outcomes: string[] = [];
    window.addEventListener(sounds.EVENT_CUE_EVENT, (event) => {
      outcomes.push((event as CustomEvent<{ outcome: string }>).detail.outcome);
    });
    sounds.messageAccepted('from-another-device');
    expect(outcomes).toEqual([]);
    sounds.noteLocalSend('local-message');
    sounds.messageAccepted('local-message');
    sounds.messageAccepted('local-message');
    expect(outcomes).toEqual(['played']);
  });
});
