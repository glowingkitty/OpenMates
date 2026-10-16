// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createVoiceCallDetector, type DetectorReply } from '../voiceCallDetector';

class FakeWorker {
  static last: FakeWorker;
  onmessage: ((event: MessageEvent<DetectorReply>) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessageerror: (() => void) | null = null;
  postMessage = vi.fn();
  terminate = vi.fn();
  constructor() { FakeWorker.last = this; }
  reply(data: DetectorReply): void { this.onmessage?.({ data } as MessageEvent<DetectorReply>); }
}

function start() {
  vi.stubGlobal('Worker', FakeWorker);
  const onResult = vi.fn();
  const onFailure = vi.fn();
  const abort = new AbortController();
  const promise = createVoiceCallDetector({ onResult, onFailure }, abort.signal);
  return { onResult, onFailure, abort, promise, worker: FakeWorker.last };
}

afterEach(() => vi.unstubAllGlobals());

describe('voice call worker lifecycle', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.single-owner
  it('terminates a cold worker immediately at hangup', async () => {
    const h = start();
    h.abort.abort();
    await expect(h.promise).rejects.toThrow('cancelled');
    expect(h.worker.terminate).toHaveBeenCalledOnce();
    expect(h.worker.onmessage).toBeNull();
    expect(h.onFailure).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.automatic-idle
  it('serializes processing and ignores pre-mute results after reset', async () => {
    const h = start(); h.worker.reply({ type: 'ready' });
    const detector = await h.promise;
    detector.push(new Float32Array(512));
    detector.push(new Float32Array(512));
    expect(h.worker.postMessage).toHaveBeenCalledTimes(1);
    detector.reset();
    detector.push(new Float32Array(512));
    h.worker.reply({ type: 'result', epoch: 0, probabilities: [1] });
    expect(h.onResult).not.toHaveBeenCalled();
    h.worker.reply({ type: 'result', epoch: 1, probabilities: [0.9] });
    expect(h.onResult).toHaveBeenCalledExactlyOnceWith(0.9, 512);
    expect(h.worker.postMessage).toHaveBeenCalledTimes(3); // first audio, reset, new audio
    detector.stop();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.background-detection
  it('bounds queued PCM and reports worker crashes once', async () => {
    const h = start(); h.worker.reply({ type: 'ready' });
    const detector = await h.promise;
    for (let i = 0; i < 10; i++) detector.push(new Float32Array(512));
    expect(h.onFailure).toHaveBeenCalledOnce();
    expect(h.worker.terminate).toHaveBeenCalledOnce();
    detector.stop(); h.worker.reply({ type: 'result', epoch: 0, probabilities: [1] });
    expect(h.onResult).not.toHaveBeenCalled();
    const crash = start(); crash.worker.reply({ type: 'ready' }); await crash.promise;
    crash.worker.onerror?.(); crash.worker.onerror?.();
    expect(crash.onFailure).toHaveBeenCalledOnce();
  });
});
