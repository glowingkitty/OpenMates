import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  token: 'test-ws-token',
  checkAuth: vi.fn(async () => true),
}));

vi.mock('../../config/api', () => ({ getApiUrl: () => 'https://api.dev.openmates.org' }));
vi.mock('../../utils/cookies', () => ({ getWebSocketToken: () => authMocks.token }));
vi.mock('../../utils/sessionId', () => ({ getSessionId: () => 'test-session' }));
vi.mock('../../stores/authSessionActions', () => ({ checkAuth: authMocks.checkAuth }));

import {
  downsampleAudio,
  startAudioRealtimeTranscription,
} from '../audioRealtimeTranscription';

class FakeWebSocket {
  static last: FakeWebSocket;
  static readonly OPEN = 1;
  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];
  closeCalls: Array<{ code?: number; reason?: string }> = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.last = this;
  }

  send(value: string) { this.sent.push(value); }
  close(code?: number, reason?: string) {
    this.closeCalls.push({ code, reason });
    this.readyState = 3;
    this.onclose?.();
  }
  emit(value: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }
}

class FakeAudioContext {
  state = 'running';
  sampleRate = 48_000;
  destination = {};
  processor = {
    onaudioprocess: null as ((event: AudioProcessingEvent) => void) | null,
    connect: vi.fn(),
    disconnect: vi.fn(),
  };
  source = { connect: vi.fn(), disconnect: vi.fn() };
  gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
  createMediaStreamSource() { return this.source; }
  createScriptProcessor() { return this.processor; }
  createGain() { return this.gain; }
  close = vi.fn(async () => undefined);
  resume = vi.fn(async () => undefined);
}

describe('audio realtime transcription', () => {
  let context: FakeAudioContext;

  beforeEach(() => {
    authMocks.token = 'test-ws-token';
    authMocks.checkAuth.mockClear();
    context = new FakeAudioContext();
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('AudioContext', class { constructor() { return context; } });
  });

  afterEach(() => vi.unstubAllGlobals());

  // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
  it('downsamples browser audio to the provider sample rate', () => {
    const source = Float32Array.from({ length: 480 }, (_, index) => index / 480);
    const result = downsampleAudio(source, 48_000);
    expect(result).toHaveLength(160);
    expect(result[0]).toBeCloseTo((source[0] + source[1] + source[2]) / 3);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it('streams PCM deltas and resolves raw then corrected transcript', async () => {
    const updates: string[] = [];
    const handle = startAudioRealtimeTranscription({} as MediaStream, {
      onTranscript: (value) => updates.push(value),
    });
    const socket = FakeWebSocket.last;
    expect(socket.url).toContain('/v1/apps/audio/realtime-transcription');
    socket.emit({ type: 'session.ready', model: 'voxtral-mini-transcribe-realtime-2602' });

    context.processor.onaudioprocess?.({
      inputBuffer: {
        sampleRate: 48_000,
        getChannelData: () => Float32Array.from([0, 0.5, -0.5, 0, 0.25, -0.25]),
      },
    } as unknown as AudioProcessingEvent);
    expect(JSON.parse(socket.sent[0])).toMatchObject({ type: 'input_audio.append' });

    socket.emit({ type: 'transcription.text.delta', text: 'Please schedule ' });
    socket.emit({ type: 'transcription.text.delta', text: 'the review.' });
    handle.finish();
    expect(socket.sent.map((entry) => JSON.parse(entry).type)).toContain('input_audio.end');

    socket.emit({
      type: 'transcription.done',
      transcript: 'Please schedule the review.',
      language: 'en',
      model: 'voxtral-mini-transcribe-realtime-2602',
    });
    socket.emit({ type: 'correction.started', model: 'gemini-3.5-flash' });
    await expect(handle.transcription).resolves.toMatchObject({
      transcript: 'Please schedule the review.',
    });

    socket.emit({
      type: 'correction.done',
      title: 'Schedule the review',
      transcript: 'Please schedule the review.',
      correction_model: 'gemini-3.5-flash',
    });
    await expect(handle.correction).resolves.toMatchObject({
      title: 'Schedule the review',
      useCorrected: true,
      transcriptOriginal: 'Please schedule the review.',
    });
    expect(updates).toEqual([
      'Please schedule',
      'Please schedule the review.',
      'Please schedule the review.',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
  it('flushes queued audio and the finish signal when readiness arrives late', () => {
    const handle = startAudioRealtimeTranscription({} as MediaStream);
    const socket = FakeWebSocket.last;

    context.processor.onaudioprocess?.({
      inputBuffer: {
        sampleRate: 48_000,
        getChannelData: () => Float32Array.from([0.25, -0.25, 0.5]),
      },
    } as unknown as AudioProcessingEvent);
    expect(socket.sent).toHaveLength(0);

    handle.finish();
    socket.emit({ type: 'session.ready' });
    expect(socket.sent.map((entry) => JSON.parse(entry).type)).toEqual([
      'input_audio.append',
      'input_audio.end',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
  it('refreshes an expired iOS WebSocket token before opening the audio stream', async () => {
    authMocks.token = `hash:${Math.floor(Date.now() / 1000) - 1}:expired-signature`;
    authMocks.checkAuth.mockImplementationOnce(async () => {
      authMocks.token = `hash:${Math.floor(Date.now() / 1000) + 300}:fresh-signature`;
      return true;
    });

    startAudioRealtimeTranscription({} as MediaStream);

    await vi.waitFor(() => expect(authMocks.checkAuth).toHaveBeenCalledWith(undefined, true));
    await vi.waitFor(() => expect(FakeWebSocket.last.url).toContain('fresh-signature'));
    expect(FakeWebSocket.last.url).not.toContain('expired-signature');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
  it('rejects both realtime results and closes cleanly on a server error', async () => {
    const handle = startAudioRealtimeTranscription({} as MediaStream);
    const socket = FakeWebSocket.last;
    socket.emit({ type: 'session.error', message: 'Provider unavailable' });

    await expect(handle.transcription).rejects.toThrow('Provider unavailable');
    await expect(handle.correction).rejects.toThrow('Provider unavailable');
    expect(socket.closeCalls).toEqual([{ code: 1011, reason: 'realtime failed' }]);
  });
});
