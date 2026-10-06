/**
 * Focused call media lifecycle tests with fake browser audio primitives.
 * Proves microphone permission races, PCM conversion and playback cleanup.
 * No real capture, network connection or provider usage occurs here.
 * Specification metadata links each behavior to the trial contract.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CallAudio, decodePcm16, downsample, pcm16Base64 } from './callAudio';

class FakeNode {
  connect = vi.fn();
  disconnect = vi.fn();
}
class FakeSource extends FakeNode {
  buffer: unknown;
  onended: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
}
class FakeContext {
  state = 'running';
  currentTime = 10;
  destination = new FakeNode();
  source = new FakeNode();
  processor = Object.assign(new FakeNode(), { onaudioprocess: null as ((event: { inputBuffer: { getChannelData: () => Float32Array; sampleRate: number } }) => void) | null });
  gain = Object.assign(new FakeNode(), { gain: { value: 1 } });
  sources: FakeSource[] = [];
  close = vi.fn(async () => { this.state = 'closed'; });
  resume = vi.fn(async () => {});
  createMediaStreamSource = vi.fn(() => this.source);
  createScriptProcessor = vi.fn(() => this.processor);
  createGain = vi.fn(() => this.gain);
  createBuffer = vi.fn((_channels: number, length: number, sampleRate: number) => ({ duration: length / sampleRate, copyToChannel: vi.fn() }));
  createBufferSource = vi.fn(() => { const source = new FakeSource(); this.sources.push(source); return source; });
}

describe('call audio lifecycle', () => {
  let context: FakeContext;
  let trackStop: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    context = new FakeContext();
    trackStop = vi.fn();
    vi.stubGlobal('AudioContext', class { constructor() { return context; } });
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: trackStop }] })) } });
  });
  afterEach(() => vi.unstubAllGlobals());

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.audio-mix,video-call.experiment.user-stop
  it('requests echo cancellation and releases microphone, graph and playback on hangup', async () => {
    const onMic = vi.fn();
    const audio = new CallAudio(onMic, vi.fn());
    await audio.start();
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
    context.processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array([0.5, -0.5]), sampleRate: 16_000 } });
    expect(decodePcm16(onMic.mock.calls[0][0])).toHaveLength(2);
    audio.playPcm16(pcm16Base64(new Float32Array([0.2, -0.2])));
    audio.playPcm16(pcm16Base64(new Float32Array([0.1, -0.1])));
    expect(context.sources[1].start.mock.calls[0][0]).toBeGreaterThan(context.sources[0].start.mock.calls[0][0]);
    audio.interrupt();
    expect(context.sources.every((source) => source.stop.mock.calls.length === 1)).toBe(true);
    audio.stop();
    audio.stop();
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(context.close).toHaveBeenCalledTimes(1);
    expect(context.processor.onaudioprocess).toBeNull();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.user-stop,video-call.experiment.privacy
  it('releases a late permission grant after hangup without opening an AudioContext', async () => {
    let grant!: (stream: { getTracks: () => { stop: typeof trackStop }[] }) => void;
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => new Promise((resolve) => { grant = resolve; })) } });
    const audio = new CallAudio(vi.fn(), vi.fn());
    const starting = audio.start();
    audio.stop();
    grant({ getTracks: () => [{ stop: trackStop }] });
    await starting;
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(context.createMediaStreamSource).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice
  it('encodes clipped little-endian PCM and downsamples to the 16 kHz budget', () => {
    const encoded = pcm16Base64(new Float32Array([-2, 0, 2]));
    expect(Array.from(decodePcm16(encoded))).toEqual([-1, 0, 1]);
    expect(downsample(new Float32Array([1, 1, -1, -1, 0, 0]), 48_000)).toHaveLength(2);
    expect(() => decodePcm16(btoa('a'))).toThrow('Invalid PCM');
  });
});
