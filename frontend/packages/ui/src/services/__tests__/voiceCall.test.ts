import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const persistence = vi.hoisted(() => ({
  persist: vi.fn(async (_callId: string, _chatId: string, _id: string, _text: string, _createdAt: number) => {}), rollback: vi.fn(async () => {}),
  upsert: vi.fn(async () => {}), prepare: vi.fn(async () => ({ chatId: 'chat-1', history: [] })),
}));
vi.mock('../voiceCallMessages', () => ({
  persistTypedCallMessage: persistence.persist,
  markTypedCallMessageFailed: persistence.rollback,
  upsertCallTranscript: persistence.upsert,
  prepareVoiceCallChat: persistence.prepare,
}));
vi.mock('../../stores/authStore', () => ({
  authStore: { subscribe: (run: (value: { isAuthenticated: boolean }) => void) => {
    run({ isAuthenticated: false });
    return () => {};
  } },
}));
vi.mock('../../stores/authSessionActions', () => ({ checkAuth: vi.fn(async () => true) }));
vi.mock('../audioRealtimeTranscription', () => ({ websocketTokenNeedsRefresh: () => false }));
vi.mock('../../config/api', () => ({ getApiUrl: () => 'https://api.dev.openmates.org' }));
vi.mock('../../utils/cookies', () => ({ getWebSocketToken: () => 'test-token' }));
vi.mock('../../utils/sessionId', () => ({ getSessionId: () => 'test-session' }));
vi.mock('../assistantSpeechController', () => ({ assistantSpeechController: { stop: vi.fn(async () => {}) } }));

import { VoiceCallController } from '../voiceCall';

type Harness = {
  update: (state: Record<string, unknown>) => void;
  handleMessage: (message: Record<string, unknown>) => void;
  socket: { readyState: number; send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> };
};

function liveController() {
  const controller = new VoiceCallController();
  const socket = { readyState: 1, send: vi.fn(), close: vi.fn() };
  const harness = controller as unknown as Harness;
  harness.socket = socket;
  harness.update({ status: 'live', chatId: 'chat-1', callId: 'call-1' });
  return { controller, harness, socket };
}

async function submittedId(socket: { send: ReturnType<typeof vi.fn> }): Promise<string> {
  await vi.waitFor(() => expect(socket.send).toHaveBeenCalledOnce());
  const sent = JSON.parse(socket.send.mock.calls[0][0] as string) as { type: string; message_id: string; created_at: number };
  expect(sent.type).toBe('text_input');
  expect(sent.message_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(Number.isInteger(sent.created_at)).toBe(true);
  expect(persistence.persist).toHaveBeenCalledWith('call-1', 'chat-1', sent.message_id, 'Please explain ramen', sent.created_at);
  return sent.message_id;
}

describe('integrated voice call typed turns', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', { OPEN: 1, CLOSING: 2 });
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(0x2a) });
    Object.values(persistence).forEach((mock) => mock.mockClear());
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
  it('rejects stale and oversized sends before any encrypted local write', async () => {
    const { controller, harness, socket } = liveController();
    socket.readyState = 3;
    expect(await controller.submitText('chat-1', 'Please explain ramen')).toBe(false);
    socket.readyState = 1;
    expect(await controller.submitText('chat-1', 'x'.repeat(8_001))).toBe(false);
    harness.update({ status: 'connecting' });
    expect(await controller.submitText('chat-1', 'Please explain ramen')).toBe(false);
    expect(persistence.persist).not.toHaveBeenCalled();
    expect(socket.send).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.chat.transcripts
  it('accepts only the matching final server echo and persists the encrypted transcript', async () => {
    const { controller, harness, socket } = liveController();
    const submitted = controller.submitText('chat-1', 'Please explain ramen');
    const id = await submittedId(socket);
    harness.handleMessage({ type: 'transcript', role: 'assistant', message_id: 'another-turn', text: 'Other', final: true });
    harness.handleMessage({ type: 'transcript', role: 'user', message_id: id, text: 'Please explain ramen', created_at: persistence.persist.mock.calls[0][4], final: true });
    expect(await submitted).toBe(true);
    await vi.waitFor(() => expect(persistence.upsert).toHaveBeenCalledWith(expect.objectContaining({ callId: 'call-1', chatId: 'chat-1', messageId: id, final: true })));
    expect(persistence.rollback).not.toHaveBeenCalled();
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
  it('rolls back a server refusal and leaves the draft unaccepted', async () => {
    const { controller, harness, socket } = liveController();
    const submitted = controller.submitText('chat-1', 'Please explain ramen');
    const id = await submittedId(socket);
    harness.handleMessage({ type: 'text_input_rejected', message_id: id, code: 'invalid_text_input' });
    expect(await submitted).toBe(false);
    expect(persistence.rollback).toHaveBeenCalledWith('call-1', 'chat-1', id);
    expect(get(controller).status).toBe('live');
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
  it('rolls back an unacknowledged turn when the connection ends', async () => {
    const { controller, harness, socket } = liveController();
    const submitted = controller.submitText('chat-1', 'Please explain ramen');
    const id = await submittedId(socket);
    harness.handleMessage({ type: 'error', code: 'call_unavailable' });
    expect(await submitted).toBe(false);
    expect(persistence.rollback).toHaveBeenCalledWith('call-1', 'chat-1', id);
    expect(get(controller).status).toBe('error');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
  it('times out an unacknowledged turn without leaving a sending bubble', async () => {
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const { controller, socket } = liveController();
    const submitted = controller.submitText('chat-1', 'Please explain ramen');
    const id = await submittedId(socket);
    const callback = timers.mock.calls.find((call) => call[1] === 20_000)?.[0];
    expect(typeof callback).toBe('function');
    (callback as () => void)();
    expect(await submitted).toBe(false);
    expect(persistence.rollback).toHaveBeenCalledWith('call-1', 'chat-1', id);
    expect(get(controller).status).toBe('error');
  });
});
