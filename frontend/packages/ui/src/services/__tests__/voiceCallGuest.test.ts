import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  sendTextMessage: vi.fn(),
  markExhausted: vi.fn(),
  refresh: vi.fn(async () => null),
  addNotification: vi.fn(() => 'n1'),
  micCallback: null as null | ((data: string) => void),
  audioStop: vi.fn(),
  audioStart: vi.fn(async () => {}),
}));

vi.mock('../anonymousChatStorage', () => ({
  anonymousChatStorage: { sendTextMessage: mocks.sendTextMessage, getAnonymousId: () => 'anon-1' },
}));
vi.mock('../../stores/serverStatusStore', () => ({
  markAnonymousFreeUsageExhausted: mocks.markExhausted,
  refreshAnonymousFreeUsageStatus: mocks.refresh,
}));
vi.mock('../../stores/notificationStore', () => ({
  notificationStore: {
    addNotificationWithOptions: mocks.addNotification, removeNotification: vi.fn(),
    subscribe: (run: (value: { notifications: unknown[] }) => void) => { run({ notifications: [] }); return () => {}; },
  },
}));
vi.mock('../../config/api', () => ({ getApiUrl: () => 'http://api.test' }));
vi.mock('../../i18n/translations', () => ({ text: { subscribe: (run: (v: (k: string) => string) => void) => { run(k => k); return () => {}; } } }));
vi.mock('../../components/videocall/callAudio', () => ({
  CallAudio: class {
    constructor(onMic: (data: string) => void) { mocks.micCallback = onMic; }
    unlock() {}
    start = mocks.audioStart;
    stop = mocks.audioStop;
  },
}));
vi.mock('../voiceCall', () => ({
  initialVoiceCallState: {
    status: 'idle', chatId: null, callId: null, minimized: false, muted: false, elapsedSeconds: 0,
    activeElapsedSeconds: 0, audioLevels: [], inputIdle: false, userSpeaking: false, assistantSpeaking: false,
    usage: null, billingActivity: null, error: null, cameraAvailable: false, cameraEnabled: false,
    cameraPending: false, cameraStream: null, cameraFacing: 'environment', cameraError: null,
    screenSharing: false, mediaExpanded: false, mediaItems: [], mediaIndex: 0, displayedMedia: null, liveTranscript: null,
  },
  voicePcmEnvelope: () => [0.1],
}));
vi.mock('../voiceCallGuestConsent', () => ({
  ensureGuestVoiceAck: vi.fn(),
}));
vi.mock('../rustCore/voice/guestVoiceClient', () => ({
  guestVoiceMicrophoneFrame: async (data: string) => JSON.stringify({ type: 'mic_audio', data }),
  guestVoicePlan: async (operation: string, payload: { frame?: string }) => {
    if (operation === 'connect') {
      return {
        url: 'ws://api.test/v1/voice-call/guest?anonymous_id=anon-1',
        start: '{"type":"start","privacy_ack_version":3}',
        pause: '{"type":"audio_stream_end"}',
        ping: '{"type":"ping"}',
        hangup: '{"type":"hangup"}',
      };
    }
    if (operation === 'speech') {
      return { url: 'http://api.test/v1/anonymous/speech', bodies: ['{"text":"Hello link"}'] };
    }
    const frame = JSON.parse(payload.frame!);
    if (frame.type === 'error') return { type: 'limit' };
    if (frame.type === 'transcript') {
      return { type: 'transcript', messageId: frame.turn_id, text: frame.text, submitted: frame.final };
    }
    return frame;
  },
}));

import { ensureGuestVoiceAck } from '../voiceCallGuestConsent';
import { guestVoiceCallController, isGuestVoiceCallSupported, setGuestCallTurnSink } from '../voiceCallGuest';
import { get } from 'svelte/store';

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket;
  static count = 0;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeSocket.last = this; FakeSocket.count++; }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(frame: Record<string, unknown>) { this.onmessage?.({ data: JSON.stringify(frame) }); }
}

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
let played: string[] = [];
let playResolve: (() => void) | null = null;

async function goLive() {
  const started = guestVoiceCallController.start();
  await started;
  FakeSocket.last.open();
  FakeSocket.last.receive({ type: 'ready' });
  await flush();
}

beforeEach(() => {
  guestVoiceCallController.hangup();
  FakeSocket.count = 0;
  played = [];
  vi.clearAllMocks();
  vi.mocked(ensureGuestVoiceAck).mockResolvedValue(true);
  mocks.sendTextMessage.mockResolvedValue({ assistantMessage: { content: '**Hello** [link](https://example.org)' } });
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.stubGlobal('AudioContext', class {});
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn() } });
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: { body: string }) => {
    played.push(JSON.parse(init.body).text);
    return { ok: true, status: 200, blob: async () => new Blob(['mp3']) };
  }));
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
  vi.stubGlobal('Audio', class {
    onended: (() => void) | null = null; onerror: (() => void) | null = null;
    pause() {}
    play() { playResolve = () => this.onended?.(); return Promise.resolve(); }
  });
});

describe('guest voice call controller', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('reports support', () => { expect(isGuestVoiceCallSupported()).toBe(true); });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('opens no socket and no microphone without the acknowledgement', async () => {
    vi.mocked(ensureGuestVoiceAck).mockResolvedValue(false);
    await guestVoiceCallController.start();
    expect(FakeSocket.count).toBe(0);
    expect(mocks.audioStart).not.toHaveBeenCalled();
    expect(get(guestVoiceCallController).status).toBe('idle');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('sends the start frame to the guest socket without credentials', async () => {
    await goLive();
    expect(FakeSocket.last.url).toBe('ws://api.test/v1/voice-call/guest?anonymous_id=anon-1');
    expect(FakeSocket.last.sent[0]).toEqual({ type: 'start', privacy_ack_version: 3 });
    expect(get(guestVoiceCallController).status).toBe('live');
    expect(get(guestVoiceCallController).cameraAvailable).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('turns a final transcript into one guest message, speaks the reply and mutes the mic meanwhile', async () => {
    const sink = vi.fn();
    setGuestCallTurnSink(sink);
    const bound = vi.fn();
    mocks.sendTextMessage.mockImplementation(async (params: { onPending: (p: unknown) => Promise<void> }) => {
      await params.onPending({ chat: { chat_id: 'chat-1' }, userMessage: {}, isNewChat: true });
      return { assistantMessage: { content: '**Hello** [link](https://example.org)' } };
    });
    const started = guestVoiceCallController.start(undefined, bound);
    await started;
    FakeSocket.last.open();
    FakeSocket.last.receive({ type: 'ready' });
    FakeSocket.last.receive({ type: 'transcript', final: true, text: 'Hi there', turn_id: 't1' });
    await flush();
    expect(mocks.sendTextMessage).toHaveBeenCalledTimes(1);
    expect(mocks.sendTextMessage.mock.calls[0][0]).toMatchObject({ markdown: 'Hi there', sourceDemoId: null });
    expect(bound).toHaveBeenCalledWith('chat-1');
    expect(sink).toHaveBeenCalledTimes(1);
    expect(played).toEqual(['Hello link']);
    expect(get(guestVoiceCallController).assistantSpeaking).toBe(true);
    const before = FakeSocket.last.sent.length;
    mocks.micCallback?.(btoa('\u0000\u0000\u0000\u0000'));
    expect(FakeSocket.last.sent.length).toBe(before);
    playResolve?.();
    await flush();
    expect(get(guestVoiceCallController).assistantSpeaking).toBe(false);
    mocks.micCallback?.(btoa('\u0000\u0000\u0000\u0000'));
    await flush();
    expect(FakeSocket.last.sent.at(-1)).toMatchObject({ type: 'mic_audio' });
    setGuestCallTurnSink(null);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('ends the call and shows the sign-up notice when the allowance is used', async () => {
    await goLive();
    FakeSocket.last.receive({ type: 'error', code: 'anonymous_usage_limit', signup_required: true });
    await flush();
    expect(mocks.markExhausted).toHaveBeenCalled();
    expect(mocks.addNotification).toHaveBeenCalled();
    expect(get(guestVoiceCallController).status).toBe('ended');
    expect(mocks.audioStop).toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('hangup sends hangup and releases the microphone', async () => {
    await goLive();
    const socket = FakeSocket.last;
    guestVoiceCallController.hangup();
    expect(socket.sent.at(-1)).toEqual({ type: 'hangup' });
    expect(mocks.audioStop).toHaveBeenCalled();
    expect(get(guestVoiceCallController).status).toBe('ended');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.guest-calls
  it('rejects camera and screen share', async () => {
    await expect(guestVoiceCallController.setCameraEnabled()).rejects.toThrow('guest_unavailable');
    await expect(guestVoiceCallController.setScreenShareEnabled()).rejects.toThrow('guest_unavailable');
    await expect(guestVoiceCallController.flipCamera()).rejects.toThrow('guest_unavailable');
  });
});
