// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VOICE_CALL_AWAY_GRACE_MS, VoiceCallBackground } from '../voiceCallBackground';

type MediaSessionStub = {
  metadata: unknown; playbackState: string; setActionHandler: ReturnType<typeof vi.fn>;
};

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('voice call background keep-alive', () => {
  let play: ReturnType<typeof vi.spyOn>;
  let pause: ReturnType<typeof vi.spyOn>;
  let session: MediaSessionStub;
  const callbacks = { onAway: vi.fn(), onReturn: vi.fn(), onHangup: vi.fn(), title: 'Voice call' };

  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
    play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    URL.createObjectURL = vi.fn(() => 'blob:keepalive');
    URL.revokeObjectURL = vi.fn();
    session = { metadata: null, playbackState: 'none', setActionHandler: vi.fn() };
    vi.stubGlobal('MediaMetadata', class { constructor(readonly init: unknown) {} });
    Object.defineProperty(navigator, 'mediaSession', { configurable: true, value: session });
    Object.values(callbacks).forEach((value) => { if (typeof value === 'function') (value as ReturnType<typeof vi.fn>).mockClear(); });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-resume
  it('primes one looping inaudible clip inside the start gesture', () => {
    const background = new VoiceCallBackground(callbacks);
    background.prime();
    background.prime();
    expect(play).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    background.stop();
    expect(pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:keepalive');
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-resume
  it('registers lock-screen controls that hang up and clears them on stop', () => {
    const background = new VoiceCallBackground(callbacks);
    background.start();
    expect(session.playbackState).toBe('playing');
    const pauseHandler = session.setActionHandler.mock.calls.find(([action]) => action === 'pause')?.[1] as () => void;
    pauseHandler();
    expect(callbacks.onHangup).toHaveBeenCalledOnce();
    background.stop();
    expect(session.setActionHandler).toHaveBeenCalledWith('pause', null);
    expect(session.playbackState).toBe('none');
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-resume
  it('reports away and return once each and keeps a grace window after returning', () => {
    const background = new VoiceCallBackground(callbacks);
    background.start();
    expect(background.awayRecently).toBe(false);
    setVisibility('hidden');
    setVisibility('hidden');
    expect(callbacks.onAway).toHaveBeenCalledOnce();
    expect(background.away).toBe(true);
    vi.advanceTimersByTime(5_000);
    setVisibility('visible');
    expect(callbacks.onReturn).toHaveBeenCalledOnce();
    expect(callbacks.onReturn.mock.calls[0][0]).toBeGreaterThanOrEqual(5_000);
    expect(background.away).toBe(false);
    expect(background.awayRecently).toBe(true);
    vi.advanceTimersByTime(VOICE_CALL_AWAY_GRACE_MS + 1);
    expect(background.awayRecently).toBe(false);
    background.stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-resume
  it('treats pagehide and pageshow like leaving and returning', () => {
    const background = new VoiceCallBackground(callbacks);
    background.start();
    window.dispatchEvent(new Event('pagehide'));
    expect(callbacks.onAway).toHaveBeenCalledOnce();
    window.dispatchEvent(new Event('pageshow'));
    expect(callbacks.onReturn).toHaveBeenCalledOnce();
    background.stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-resume
  it('stops listening after stop', () => {
    const background = new VoiceCallBackground(callbacks);
    background.start();
    background.stop();
    setVisibility('hidden');
    expect(callbacks.onAway).not.toHaveBeenCalled();
  });
});
