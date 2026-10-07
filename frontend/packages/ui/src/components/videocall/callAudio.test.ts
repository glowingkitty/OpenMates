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
  gains: Array<FakeNode & { gain: { value: number } }> = [];
  sources: FakeSource[] = [];
  close = vi.fn(async () => { this.state = 'closed'; });
  resume = vi.fn(async () => {});
  createMediaStreamSource = vi.fn(() => this.source);
  createScriptProcessor = vi.fn(() => this.processor);
  createGain = vi.fn(() => { const gain = Object.assign(new FakeNode(), { gain: { value: 1 } }); this.gains.push(gain); return gain; });
  decodeAudioData = vi.fn(async () => ({ duration: 1.5 }));
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
  it('unlocks audio before microphone permission and releases a late grant after hangup', async () => {
    let grant!: (stream: { getTracks: () => { stop: typeof trackStop }[] }) => void;
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => new Promise((resolve) => { grant = resolve; })) } });
    const audio = new CallAudio(vi.fn(), vi.fn());
    const starting = audio.start();
    expect(context.resume).not.toHaveBeenCalled();
    expect(context.createMediaStreamSource).not.toHaveBeenCalled();
    audio.stop();
    grant({ getTracks: () => [{ stop: trackStop }] });
    await starting;
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(context.createMediaStreamSource).not.toHaveBeenCalled();
    expect(context.close).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.audio-mix
  it('resumes a suspended output context in the Start gesture and keeps decoded ambience independent of interrupted voice', async () => {
    context.state = 'suspended';
    vi.stubGlobal('fetch', vi.fn(async () => ({ arrayBuffer: async () => new ArrayBuffer(8) })));
    const audio = new CallAudio(vi.fn(), vi.fn());
    const starting = audio.start();
    expect(context.resume).toHaveBeenCalledTimes(1);
    await starting;
    expect(context.createMediaStreamSource).toHaveBeenCalledTimes(1);
    const video = Object.assign(new EventTarget(), { src: 'blob:clip', currentSrc: '', paused: false, ended: false, currentTime: 0.5 }) as HTMLVideoElement;
    audio.setVideoElement(video);
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(context.sources).toHaveLength(1));
    expect(context.sources[0].start).toHaveBeenCalledWith(0, 0.5);
    audio.playPcm16(pcm16Base64(new Float32Array([0.3])));
    audio.setVideoGain(0.04);
    expect(context.gains[1].gain.value).toBe(0.04);
    expect(context.sources[1].connect).toHaveBeenCalledWith(context.destination);
    audio.interrupt();
    expect(context.sources[0].stop).not.toHaveBeenCalled();
    expect(context.sources[1].stop).toHaveBeenCalledTimes(1);
    video.currentTime = 0.8;
    video.dispatchEvent(new Event('seeked'));
    expect(context.sources[0].stop).toHaveBeenCalledTimes(1);
    expect(context.sources[2].start).toHaveBeenCalledWith(0, 0.8);
    const nextVideo = Object.assign(new EventTarget(), { src: 'blob:next', currentSrc: '', paused: false, ended: false, currentTime: 0 }) as HTMLVideoElement;
    audio.setVideoElement(nextVideo);
    expect(context.gains[2].gain.value).toBe(0.04);
    await vi.waitFor(() => expect(context.sources).toHaveLength(4));
    audio.setVideoElement(null);
    expect(context.sources[2].stop).toHaveBeenCalledTimes(1);
    expect(context.sources[3].stop).toHaveBeenCalledTimes(1);
    audio.stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.privacy,video-call.experiment.user-stop
  it('aborts old clip reads when the visual changes or the call ends', async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal('fetch', vi.fn((_url: string, options: { signal: AbortSignal }) => {
      signals.push(options.signal);
      return new Promise(() => {});
    }));
    const audio = new CallAudio(vi.fn(), vi.fn());
    await audio.start();
    const first = Object.assign(new EventTarget(), { src: 'blob:first', currentSrc: '', paused: true, ended: false, currentTime: 0 }) as HTMLVideoElement;
    const second = Object.assign(new EventTarget(), { src: 'blob:second', currentSrc: '', paused: true, ended: false, currentTime: 0 }) as HTMLVideoElement;
    audio.setVideoElement(first);
    audio.setVideoElement(second);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
    audio.stop();
    expect(signals[1].aborted).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice
  it('encodes clipped little-endian PCM and downsamples to the 16 kHz budget', () => {
    const encoded = pcm16Base64(new Float32Array([-2, 0, 2]));
    expect(Array.from(decodePcm16(encoded))).toEqual([-1, 0, 1]);
    expect(downsample(new Float32Array([1, 1, -1, -1, 0, 0]), 48_000)).toHaveLength(2);
    expect(() => decodePcm16(btoa('a'))).toThrow('Invalid PCM');
  });
});
