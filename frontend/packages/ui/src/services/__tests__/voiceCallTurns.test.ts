import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.identity }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => mocks.epoch }));
const mocks = vi.hoisted(() => ({ identity:'owner-1',epoch:1,connected:true, send:vi.fn(), row:vi.fn(), save:vi.fn(), updateChat:vi.fn(), event:vi.fn() }));
vi.mock('../db', () => ({chatDB:{getMessage:mocks.row,saveMessage:mocks.save,updateChat:mocks.updateChat,getChat:vi.fn(async()=>({chat_id:'chat-1',team_id:null,messages_v:3}))}}));
vi.mock('../chatSyncService', () => ({chatSyncService:{
  get webSocketConnected_FOR_SENDERS_ONLY() { return mocks.connected; }, sendNewMessage:mocks.send, dispatchEvent:mocks.event,
}}));
import { createVoiceCallSendDiagnostics, sendVoiceCallTurn } from '../voiceCallTurns';
const turn = {callId:'call-1',chatId:'chat-1',turnId:'turn-1',text:'Explain this image',createdAt:1700000000};
beforeEach(()=>{mocks.identity='owner-1';mocks.epoch=1;mocks.connected=true;mocks.save.mockReset().mockResolvedValue(undefined);mocks.event.mockClear();mocks.updateChat.mockReset().mockResolvedValue(undefined);mocks.send.mockReset().mockResolvedValue(undefined);mocks.row.mockReset().mockResolvedValue({status:'sending'});});

// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
it('records only fixed canonical prerequisite stages for exact voice delivery identities', () => {
  const events: Array<Record<string, unknown>> = [];
  const observe = (event: Event) => events.push((event as CustomEvent).detail);
  window.addEventListener('voiceCallTurnDelivery', observe);
  try {
    const message = { chat_id: turn.chatId, message_id: turn.turnId, voice_mode: true,
      voice_call_id: turn.callId, voice_turn_id: turn.turnId, content: 'PRIVATE text and key' };
    const diagnostics = createVoiceCallSendDiagnostics(message);
    diagnostics.enter('predecessor');
    diagnostics.enter('personal_privacy');
    diagnostics.enter('PRIVATE stage' as 'sender');
    diagnostics.failed();
    expect(events).toEqual([
      { callId: 'call-1', chatId: 'chat-1', turnId: 'turn-1', phase: 'canonical_prerequisite', reason: 'predecessor' },
      { callId: 'call-1', chatId: 'chat-1', turnId: 'turn-1', phase: 'canonical_prerequisite', reason: 'personal_privacy' },
      { callId: 'call-1', chatId: 'chat-1', turnId: 'turn-1', phase: 'canonical_prerequisite_failed', reason: 'personal_privacy' },
    ]);
    for (const overrides of [{ voice_mode: false }, { voice_call_id: undefined },
      { voice_turn_id: 'other-turn' }, { chat_id: 'PRIVATE\ninvalid' }]) {
      const invalid = createVoiceCallSendDiagnostics({ ...message, ...overrides });
      invalid.enter('sender'); invalid.failed();
    }
    expect(events).toHaveLength(3);
    expect(JSON.stringify(events)).not.toMatch(/PRIVATE|content|stack|key/);
  } finally { window.removeEventListener('voiceCallTurnDelivery', observe); }
});
describe('canonical call turn adapter',()=>{
  // contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.audio.spoken-rich-response,video-call.chat.typed-input
  it('uses the ordinary encrypted sender with voice delivery and one canonical source reference',async()=>{
    const ref={type:'image',embed_id:'source-1'};
    expect(await sendVoiceCallTurn({...turn,embedReferences:[ref,ref]})).toBe(true);
    expect(mocks.send).toHaveBeenCalledExactlyOnceWith({message_id:'turn-1',chat_id:'chat-1',role:'user',
      content:'Explain this image\n\n```json\n{"type":"image","embed_id":"source-1"}\n```',created_at:1700000000,status:'sending',
      voice_call_id:'call-1',voice_turn_id:'turn-1',voice_mode:true,auto_speak:true,preserve_draft:true});
    expect(mocks.save).toHaveBeenCalledOnce();
    expect(mocks.updateChat).toHaveBeenCalledWith(expect.objectContaining({messages_v:4}));
    for(const field of ['voice_call_id','voice_turn_id','voice_mode','auto_speak','preserve_draft']) expect(mocks.save.mock.calls[0][0]).not.toHaveProperty(field);
    expect(mocks.send.mock.calls[0][0]).not.toHaveProperty('model');
    expect(mocks.send.mock.calls[0][0]).not.toHaveProperty('provider');
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.audio.complete-turn-admission
  it('keeps draft acceptance false before connection, on send error, or when canonical admission fails',async()=>{
    mocks.connected=false;expect(await sendVoiceCallTurn(turn)).toBe(false);expect(mocks.send).not.toHaveBeenCalled();
    mocks.identity='owner-1';mocks.epoch=1;mocks.connected=true;mocks.save.mockReset().mockResolvedValue(undefined);mocks.event.mockClear();mocks.updateChat.mockReset().mockResolvedValue(undefined);mocks.send.mockRejectedValueOnce(new Error('admission failed'));
    await expect(sendVoiceCallTurn(turn)).rejects.toThrow('admission failed');
    for(const status of ['failed','waiting_for_internet']) {mocks.row.mockResolvedValueOnce({status});expect(await sendVoiceCallTurn(turn)).toBe(false);}
    mocks.row.mockResolvedValueOnce(null);expect(await sendVoiceCallTurn(turn)).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
  it('fences a cancelled call or changed workspace before encrypted admission',async()=>{
    expect(await sendVoiceCallTurn({...turn,isCurrent:()=>false})).toBe(false);
    expect(mocks.save).not.toHaveBeenCalled();expect(mocks.send).not.toHaveBeenCalled();
    mocks.save.mockImplementationOnce(async()=>{mocks.epoch++;});
    expect(await sendVoiceCallTurn(turn)).toBe(false);
    expect(mocks.send).not.toHaveBeenCalled();expect(mocks.event).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption,video-call.privacy
  it('sends the measured heard boundary as ephemeral delivery context without truncating or persisting rich text',async()=>{
    const heardBoundary={assistant_message_id:'assistant-prior',completed_sequences:[0,1],active_sequence:2,active_offset_ms:1200};
    const text='## Continue\nKeep [the source](https://example.org) available.';
    expect(await sendVoiceCallTurn({...turn,text,heardBoundary})).toBe(true);
    expect(mocks.send.mock.calls[0][0]).toMatchObject({content:text,voice_heard_boundary:heardBoundary,voice_call_id:'call-1'});
    expect(mocks.save.mock.calls[0][0]).toMatchObject({content:text});
    expect(mocks.save.mock.calls[0][0]).not.toHaveProperty('voice_heard_boundary');
  });

});

// contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.audio.complete-turn-admission
it('reports the exact failed admission phase without disclosing transcript or exception bodies', async () => {
  const events: Array<Record<string, unknown>> = [];
  const observe = (event: Event) => events.push((event as CustomEvent).detail);
  window.addEventListener('voiceCallTurnDelivery', observe);
  const privateText = 'PRIVATE transcript';
  mocks.send.mockRejectedValueOnce(new Error('The previous encrypted reply has not been saved. Retry this message after recovery.'));
  try {
    await expect(sendVoiceCallTurn({ ...turn, text: privateText })).rejects.toThrow('previous encrypted reply');
    expect(events.at(-1)).toEqual({callId:'call-1',chatId:'chat-1',turnId:'turn-1',phase:'failed',reason:'canonical_sending:predecessor_not_saved',failure:{errorClass:'Error'}});
    expect(events.length).toBeLessThanOrEqual(12);
    expect(JSON.stringify(events)).not.toContain(privateText);
    expect(events.every(event => Object.keys(event).every(key => ['callId','chatId','turnId','phase','reason','failure'].includes(key)))).toBe(true);
    events.length = 0;
    mocks.send.mockRejectedValueOnce(new Error('PRIVATE provider error and credentials'));
    await expect(sendVoiceCallTurn(turn)).rejects.toThrow('PRIVATE');
    expect(events.at(-1)?.reason).toBe('canonical_sending:operation_failed');
    expect(JSON.stringify(events)).not.toContain('PRIVATE');
  } finally {
    window.removeEventListener('voiceCallTurnDelivery', observe);
  }
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
it('identifies a disconnected or changed call scope before optimistic persistence', async () => {
  const events: Array<Record<string, unknown>> = [];
  const observe = (event: Event) => events.push((event as CustomEvent).detail);
  window.addEventListener('voiceCallTurnDelivery', observe);
  try {
    mocks.connected = false;
    expect(await sendVoiceCallTurn(turn)).toBe(false);
    expect(events.at(-1)?.reason).toBe('disconnected');
    expect(mocks.save).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener('voiceCallTurnDelivery', observe);
  }
});


// contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.audio.complete-turn-admission
it('reports only allowlisted error categories and static source locations from sender failures', async () => {
  const events: Array<Record<string, unknown>> = [];
  const observe = (event: Event) => events.push((event as CustomEvent).detail);
  window.addEventListener('voiceCallTurnDelivery', observe);
  class PendingAdmissionCompatibilityError extends Error {}
  const error = Object.assign(new PendingAdmissionCompatibilityError('PRIVATE body with https://private.invalid/?secret=TOKEN'), {
    code: 'websocket_receipt_connection_changed', status: 409,
    stack: 'PRIVATE header\n at send (https://private.invalid/src/services/sendersChatMessages.ts?t=PRIVATE:1503:7)\n at private (https://private.invalid/secret:2:3)',
  });
  try {
    mocks.send.mockRejectedValueOnce(error);
    await expect(sendVoiceCallTurn(turn)).rejects.toBe(error);
    expect(events.at(-1)).toMatchObject({reason:'canonical_sending:websocket_receipt_connection_changed',failure:{
      errorClass:'PendingAdmissionCompatibilityError',errorCode:'websocket_receipt_connection_changed',httpStatus:409,
      module:'services/sendersChatMessages.ts',line:1503,
    }});
    expect(JSON.stringify(events)).not.toMatch(/PRIVATE|TOKEN|https?:/);
    events.length = 0;
    const unknown = { name:'PRIVATE',code:'PRIVATE',status:418,stack:'PRIVATE header\n at private (/src/services/private.ts:33:7)' };
    mocks.send.mockRejectedValueOnce(unknown);
    await expect(sendVoiceCallTurn(turn)).rejects.toBe(unknown);
    expect(events.at(-1)).toMatchObject({reason:'canonical_sending:operation_failed',failure:{}});
    expect(JSON.stringify(events)).not.toMatch(/PRIVATE|private\.ts|418/);
    events.length = 0;
    const exception = Object.assign(new TypeError('PRIVATE'), {
      statusCode:503,stack:'TypeError: PRIVATE\n at private (/src/services/private.ts:99:1)\n at send (/src/services/preparedPrivacyForSend.ts:178:2)',
    });
    mocks.send.mockRejectedValueOnce(exception);
    await expect(sendVoiceCallTurn(turn)).rejects.toBe(exception);
    expect(events.at(-1)?.failure).toEqual({errorClass:'TypeError',httpStatus:503,module:'services/preparedPrivacyForSend.ts',line:178});
  } finally { window.removeEventListener('voiceCallTurnDelivery', observe); }
});

// contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.audio.complete-turn-admission
it.each([
  ['Personal privacy receipt does not match this turn', 'privacy_receipt_mismatch'],
  ['Personal privacy scope changed during freshness check', 'privacy_freshness_changed'],
])('identifies the exact fixed privacy guard without exporting exception text: %s', async (message, code) => {
  const events: Array<Record<string, unknown>> = [];
  const observe = (event: Event) => events.push((event as CustomEvent).detail);
  window.addEventListener('voiceCallTurnDelivery', observe);
  try {
    const error = new Error(message);
    mocks.send.mockRejectedValueOnce(error);
    await expect(sendVoiceCallTurn(turn)).rejects.toBe(error);
    expect(events.at(-1)).toMatchObject({ reason: `canonical_sending:${code}`,
      failure: { errorClass: 'Error', errorCode: code } });
    expect(JSON.stringify(events)).not.toContain(message);
    events.length = 0;
    const privateError = new Error(`${message}: PRIVATE data`);
    mocks.send.mockRejectedValueOnce(privateError);
    await expect(sendVoiceCallTurn(turn)).rejects.toBe(privateError);
    expect(events.at(-1)).toMatchObject({ reason: 'canonical_sending:operation_failed' });
    expect((events.at(-1)?.failure as Record<string, unknown>).errorCode).toBeUndefined();
    expect(JSON.stringify(events)).not.toMatch(/PRIVATE|Personal privacy/);
  } finally { window.removeEventListener('voiceCallTurnDelivery', observe); }
});
