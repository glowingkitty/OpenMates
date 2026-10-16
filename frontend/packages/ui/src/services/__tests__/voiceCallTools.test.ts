import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  request: vi.fn(async (_service: unknown, _payload: unknown, _respond: (entries: unknown[]) => Promise<void>) => {}), focus: vi.fn(async () => {}), pending: vi.fn(),
  embed: vi.fn(async () => {}), context: vi.fn(async () => {}), compression: vi.fn(async () => {}),
  dispatch: vi.fn(),
}));
vi.mock('../chatSyncService', () => ({ chatSyncService: {
  applyConfirmedFocusActivation: mocks.focus, dispatchEvent: mocks.dispatch,
} }));
vi.mock('../chatSyncServiceHandlersAppSettings', () => ({ handleRequestAppSettingsMemoriesImpl: mocks.request }));
vi.mock('../chatSyncServiceHandlersAI', () => ({ handleSendEmbedDataImpl: mocks.embed,
  persistClientEncryptedCompressionCheckpoint: mocks.compression }));
vi.mock('../chatSyncServiceHandlersAgentContext', () => ({ handleChatContextApplied: mocks.context }));
vi.mock('../../stores/pendingFocusActivationStore', () => ({ pendingFocusActivationStore: { set: mocks.pending } }));
import { applyVoiceCompression, applyVoiceToolEvent } from '../voiceCallTools';

const binding = () => ({ callId: 'call-one', chatId: 'chat-one', isCurrent: () => true, send: vi.fn(() => true) });
const event = (type: string, payload: Record<string, unknown>) => ({ type, call_id: 'call-one',
  function_call_id: 'function-one', assistant_message_id: 'assistant-one', user_message_id: 'user-one', payload });
beforeEach(() => { Object.values(mocks).forEach((fn) => fn.mockReset()); });

describe('voice Stage 2 shared client paths', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
  it('uses the shared approval UI and correlates its selected-only response to the call', async () => {
    const call = binding();
    await applyVoiceToolEvent(call, event('voice_memory', { request_id: 'request-one', requested_keys: ['code-preferred_tech'] }));
    expect(mocks.request).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      request_id: 'request-one', chat_id: 'chat-one', message_id: 'user-one', requested_keys: ['code-preferred_tech'],
    }), expect.any(Function));
    const respond = mocks.request.mock.calls[0][2] as (entries: unknown[]) => Promise<void>;
    await respond([{ app_id: 'code', item_key: 'preferred_tech', content: { preference: 'approved' } }]);
    expect(call.send).toHaveBeenCalledWith({ type: 'voice_memory_response', call_id: 'call-one',
      function_call_id: 'function-one', request_id: 'request-one', approved: true,
      settings_memories: [{ app_id: 'code', item_key: 'preferred_tech', content: { preference: 'approved' } }],
    });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
  it('checks the issuing call again after asynchronous selection and prevents duplicate responses', async () => {
    let active = true;
    const call = { ...binding(), isCurrent: () => active };
    await applyVoiceToolEvent(call, event('voice_memory', { request_id: 'request-one', requested_keys: ['code-preferred_tech'] }));
    const respond = mocks.request.mock.calls[0][2];
    active = false;
    await expect(respond([{ app_id: 'code', item_key: 'preferred_tech', content: 'private' }])).rejects.toThrow('no longer active');
    expect(call.send).not.toHaveBeenCalled();
    active = true;
    await respond([]);
    await expect(respond([])).rejects.toThrow('no longer active');
    expect(call.send).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.privacy
  it('stores full artifacts through shared encryption and attaches reference-only artifacts once', async () => {
    const call = binding();
    expect(await applyVoiceToolEvent(call, event('voice_embed', { embed_id: 'embed-one', type: 'code',
      content: 'plaintext skill result', status: 'finished' }))).toBe('embed-one');
    expect(mocks.embed).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ payload: expect.objectContaining({
      chat_id: 'chat-one', message_id: 'assistant-one', embed_id: 'embed-one',
    }) }));
    expect(await applyVoiceToolEvent(call, event('voice_embed', { embed_id: 'embed-two',
      embed_reference: '{"type":"diagram_html","embed_id":"embed-two"}' }))).toBe('embed-two');
    expect(mocks.embed).toHaveBeenCalledOnce();
    expect(await applyVoiceToolEvent(call, event('voice_embed', { embed_id: 'child-one', type: 'web_website',
      content: 'url: https://example.invalid', status: 'finished', parent_embed_id: 'embed-one' }))).toBeUndefined();
    expect(mocks.embed).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ payload: expect.objectContaining({
      embed_id: 'child-one', parent_embed_id: 'embed-one',
    }) }));
    await expect(applyVoiceToolEvent(call, event('voice_embed', { embed_id: 'embed-three',
      embed_reference: '{"type":"diagram_html","embed_id":"foreign-embed"}' }))).rejects.toThrow('Invalid call artifact reference');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.chat.project-context
  it('uses canonical focus persistence and preserves Project approval policy metadata', async () => {
    const call = binding();
    await applyVoiceToolEvent(call, event('voice_focus', { event: 'focus_mode_pending', focus_id: 'project-one',
      embed_id: 'focus-card', expires_at: 200, activation_policy: 'approval',
      selected_specialist: { focus_id: 'project-focus:one:specialist', item_id: 'specialist', title: 'Selected', revision: 'revision-one' } }));
    expect(mocks.pending).toHaveBeenCalledWith('focus-card', expect.objectContaining({
      chatId: 'chat-one', activationPolicy: 'approval', selectedSpecialist: expect.objectContaining({ item_id: 'specialist' }),
    }));
    await applyVoiceToolEvent(call, event('voice_focus', { event: 'focus_mode_activated', focus_id: 'web-research' }));
    expect(mocks.focus).toHaveBeenCalledExactlyOnceWith('chat-one', 'web-research', undefined);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.privacy
  it('ignores foreign or ended call events before touching shared chat storage', async () => {
    await applyVoiceToolEvent(binding(), { ...event('voice_embed', { embed_id: 'one' }), call_id: 'other-call' });
    await applyVoiceToolEvent({ ...binding(), isCurrent: () => false }, event('voice_memory', { request_id: 'one' }));
    expect(mocks.embed).not.toHaveBeenCalled(); expect(mocks.request).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it('acknowledges compression only after canonical encrypted checkpoint persistence finishes', async () => {
    const call = binding();
    let stored!: () => void;
    mocks.compression.mockImplementation(() => new Promise<void>((resolve) => { stored = resolve; }));
    const completion = applyVoiceCompression(call, { call_id: 'call-one', payload: {
      chat_id: 'chat-one', task_id: 'task-one', summary_message_id: 'checkpoint-one', summary_content: 'Complete meaning',
      covered_message_ids: ['user-one', 'assistant-one'], compressed_up_to_message_id: 'assistant-one', compressed_up_to_timestamp: 100,
    } });
    await vi.waitFor(() => expect(mocks.compression).toHaveBeenCalledOnce());
    expect(call.send).not.toHaveBeenCalled();
    stored(); await completion;
    expect(call.send).toHaveBeenCalledExactlyOnceWith({ type: 'voice_compression_confirmed', call_id: 'call-one', checkpoint_id: 'checkpoint-one' });
  });
});
