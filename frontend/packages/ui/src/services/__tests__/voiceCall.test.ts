import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { notificationStore } from '../../stores/notificationStore';
vi.mock('../../i18n/translations', async () => {
  const { readable } = await import('svelte/store');
  return { text: readable((key: string) => key) };
});

const persistence = vi.hoisted(() => ({
  persist: vi.fn(async (_callId: string, _chatId: string, _id: string, _text: string, _createdAt: number) => {}), rollback: vi.fn(async () => {}),
  lifecycle: vi.fn(async (_event:unknown) => {}), upsert: vi.fn(async () => {}), artifact: vi.fn(async () => {}), prepare: vi.fn(async () => ({ chatId: 'chat-1', history: [] })),
}));
const heard = vi.hoisted(() => ({ value: null as {assistant_message_id:string;completed_sequences:number[];active_sequence:number|null;active_offset_ms:number}|null }));
const canonical = vi.hoisted(() => ({ send: vi.fn(async (_turn: unknown) => true), cancel: vi.fn(async () => {}), tasks: new Map<string,{taskId:string;userMessageId:string}>() }));
vi.mock('../voiceCallTurns', () => ({ sendVoiceCallTurn: canonical.send, reportVoiceCallTurnDelivery: vi.fn() }));
const privacy = vi.hoisted(() => ({ ensure: vi.fn(async (_signal:AbortSignal, _gesture:()=>void) => true) }));
vi.mock('../voiceCallPrivacy', () => ({ ensureVoiceCallPrivacyAcknowledgement: privacy.ensure }));
const streaming = vi.hoisted(() => ({ supported: vi.fn(() => true) }));
vi.mock('../assistantSpeechStream', () => ({ supportsAssistantSpeechStream: streaming.supported }));
const cues = vi.hoisted(() => ({ prepare: vi.fn(), play: vi.fn(), stop: vi.fn() }));
vi.mock('../voiceCallCues', () => ({ VoiceCallCuePlayer: class {
  prepare = cues.prepare; play = cues.play; stop = cues.stop;
} }));
interface CameraCallbacks {
  onFrame: (frame: {frameId:string;data:string;capturedAt:number;width:number;height:number}) => void;
  onStream: (stream:MediaStream|null,facing:'environment'|'user') => void;
  onError: (code:'camera_denied'|'camera_missing'|'camera_failed') => void;
}
const visual = vi.hoisted(() => ({
  cameras: [] as Array<{callbacks:CameraCallbacks; stop:ReturnType<typeof vi.fn>; flip:()=>Promise<void> }>,
  source: vi.fn(), resolve: vi.fn(), destroy: vi.fn(), listeners: new Set<(event:Event) => void>(),
}));
vi.mock('../voiceCallCamera', () => ({ VoiceCallCamera: class {
  stop = vi.fn(() => this.callbacks.onStream(null,'environment'));
  constructor(readonly callbacks:CameraCallbacks) { visual.cameras.push(this); }
  async start() { this.callbacks.onStream({id:'camera'} as MediaStream,'environment'); }
  async flip() { this.callbacks.onStream(null,'user'); this.callbacks.onStream({id:'front'} as MediaStream,'user'); }
} }));
vi.mock('../voiceCallVisuals', () => ({ persistCallSourceFrame: visual.source }));
vi.mock('../voiceCallMedia', () => ({ createVoiceCallMediaResolver: () => ({resolve:visual.resolve,destroy:visual.destroy}) }));
vi.mock('../chatSyncService', () => ({chatSyncService:{
  activeAITasks: canonical.tasks, sendCancelAiTask: canonical.cancel,
  addEventListener: (_name:string,callback:(event:Event)=>void) => visual.listeners.add(callback),
  removeEventListener: (_name:string,callback:(event:Event)=>void) => visual.listeners.delete(callback),
}}));
interface GateCallbacks {
  onAudio: (data: string) => void;
  onAudioEnd: () => void;
  onState: (state: { inputIdle: boolean; userSpeaking: boolean }) => void;
  onError: () => void;
}
const capture = vi.hoisted(() => ({ unlock:vi.fn(), audioTime:10, start: vi.fn(async () => {}), stop: vi.fn(),
  mic: vi.fn(), frames: [] as Array<(data: string) => void>, playback: [] as Array<(user: boolean, assistant: boolean) => void> }));
const gates = vi.hoisted(() => ({ instances: [] as Array<{
  callbacks: GateCallbacks; start: ReturnType<typeof vi.fn>; push: ReturnType<typeof vi.fn>;
  setLive: ReturnType<typeof vi.fn>; setMuted: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>;
}> }));
vi.mock('../voiceCallAudioGate', () => ({ VoiceCallAudioGate: class {
  start = vi.fn();
  push = vi.fn();
  setLive = vi.fn();
  setMuted = vi.fn();
  stop = vi.fn();
  constructor(readonly callbacks: GateCallbacks) { gates.instances.push(this); }
} }));
vi.mock('../../components/videocall/callAudio', () => ({ CallAudio: class {
  constructor(onAudio: (data: string) => void, onState: (user: boolean, assistant: boolean) => void) {
    capture.frames.push(onAudio); capture.playback.push(onState);
  }
  unlock = capture.unlock;
  start = capture.start;
  stop = capture.stop;
  setMicEnabled = capture.mic;
  private nextStart = 0;
  get playbackAudioTime() { return capture.audioTime; }
  playPcm16(data:string,sampleRate=24_000) {
    const startTime=Math.max(capture.audioTime+.025,this.nextStart);
    const duration=atob(data).length/2/sampleRate;
    this.nextStart=startTime+duration;
    return {startTime,duration,sampleRate};
  }
  interrupt() {}
} }));
vi.mock('../voiceCallLifecycle', () => ({ recordCallLifecycle:persistence.lifecycle }));
vi.mock('../voiceCallMessages', () => ({
  VoiceCallContextError: class extends Error {
    constructor(readonly code: string) { super(code); }
  },
  persistTypedCallMessage: persistence.persist,
  markTypedCallMessageFailed: persistence.rollback,
  upsertCallTranscript: persistence.upsert,
  upsertCallArtifact: persistence.artifact,
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
vi.mock('../assistantSpeechController', async () => { const { writable } = await import('svelte/store'); return { assistantSpeechController: {
  get playbackBoundary() { return heard.value; },
  stop: vi.fn(async () => {}), setCallOwner: vi.fn(), primeForAutoplay: vi.fn(),
  activity: writable({ chatId:null as string|null, messageId:null as string|null,text:'',speaking:false,language:'en' }),
} }; });
import { assistantSpeechController } from '../assistantSpeechController';

import { VoiceCallController } from '../voiceCall';
import { VoiceCallAudioGate } from '../voiceCallAudioGate';
import { VoiceCallContextError } from '../voiceCallMessages';

type Harness = {
  update: (state: Record<string, unknown>) => void;
  handleMessage: (message: Record<string, unknown>) => void;
  send: (message: Record<string, unknown>) => boolean;
  socket: { readyState: number; send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> };
  bindCanonicalChat: () => void;
  callTurnIds: Set<string>;
  audioGate: VoiceCallAudioGate;
  audio: { setMicEnabled: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
};

function liveController() {
  const controller = new VoiceCallController();
  const socket = { readyState: 1, send: vi.fn(), close: vi.fn() };
  const harness = controller as unknown as Harness;
  harness.socket = socket;
  harness.update({ status: 'live', chatId: 'chat-1', callId: 'call-1' });
  harness.audioGate = new VoiceCallAudioGate({ onAudio: () => {}, onState: () => {}, onError: () => {},
    onAudioEnd: () => harness.send({ type: 'audio_stream_end' }) });
  const gate = gates.instances[gates.instances.length - 1]!;
  gate.setMuted.mockImplementation((muted: boolean) => { if (muted) gate.callbacks.onAudioEnd(); });
  return { controller, harness, socket };
}

async function submittedId(socket: { send: ReturnType<typeof vi.fn> }): Promise<string> {
  await vi.waitFor(() => expect(socket.send).toHaveBeenCalledOnce());
  const sent = JSON.parse(socket.send.mock.calls[0][0] as string) as { type: string; message_id: string; created_at: number };
  expect(sent.type).toBe('text_input');
  expect(sent.message_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(Number.isInteger(sent.created_at)).toBe(true);
  expect(persistence.persist).not.toHaveBeenCalled();
  return sent.message_id;
}

describe('integrated voice call typed turns', () => {
  beforeEach(() => {
    notificationStore.clearAllNotifications();
    vi.stubGlobal('WebSocket', { OPEN: 1, CLOSING: 2 });
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(0x2a) });
    heard.value=null;
    canonical.send.mockReset().mockResolvedValue(true); canonical.cancel.mockClear(); canonical.tasks.clear();
    assistantSpeechController.activity.set({chatId:null,messageId:null,text:'',speaking:false,language:'en'});
    Object.values(persistence).forEach((mock) => mock.mockClear());
    Object.values(cues).forEach(mock => mock.mockClear());
    capture.unlock.mockClear();
    vi.mocked(assistantSpeechController.primeForAutoplay).mockClear();
    privacy.ensure.mockReset().mockResolvedValue(true);
    streaming.supported.mockReset().mockReturnValue(true);
    capture.start.mockReset().mockResolvedValue(undefined);
    capture.stop.mockClear();
    capture.mic.mockClear();
    capture.audioTime=10;
    capture.frames.length = 0;
    capture.playback.length = 0;
    gates.instances.length = 0;
    visual.cameras.length = 0;
    visual.listeners.clear();
    visual.source.mockReset().mockResolvedValue({type:'image',embed_id:'source-1'});
    visual.resolve.mockReset().mockResolvedValue([]);
    visual.destroy.mockClear();
    persistence.prepare.mockReset().mockResolvedValue({ chatId: 'chat-1', history: [] });
  });
  afterEach(() => { notificationStore.clearAllNotifications(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  function startingController() {
    const sockets: Array<{ readyState: number; send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn>; onopen?: () => void; onmessage?: (event: { data: string }) => void }> = [];
    class Socket {
      static OPEN = 1;
      static CLOSING = 2;
      readyState = 1;
      send = vi.fn();
      close = vi.fn();
      constructor() { sockets.push(this); }
    }
    vi.stubGlobal('WebSocket', Socket);
    return { controller: new VoiceCallController(), sockets };
  }

  // contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.lifecycle.recovery-and-billing,video-call.privacy
  it('rejects unsupported live speech before microphone, socket, context preparation, or canonical work', async () => {
    streaming.supported.mockReturnValue(false);
    const { controller, sockets } = startingController();
    await controller.start('chat-1');
    expect(get(controller)).toMatchObject({ status: 'error', chatId: 'chat-1', error: 'call_unavailable', callId: null });
    expect(capture.start).not.toHaveBeenCalled();
    expect(capture.unlock).not.toHaveBeenCalled();
    expect(capture.frames).toHaveLength(0);
    expect(gates.instances).toHaveLength(0);
    expect(sockets).toHaveLength(0);
    expect(privacy.ensure).not.toHaveBeenCalled();
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(persistence.lifecycle).not.toHaveBeenCalled();
    expect(canonical.send).not.toHaveBeenCalled();
    expect(cues.prepare).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.provider.boundary,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  it.each([undefined, 'full_file_v0', 'mp3_stream_v1'])('rejects a mismatched server output handshake %s before mic upload or live admission', async (transport) => {
    const { controller, sockets } = startingController();
    await controller.start('chat-1');
    const socket = sockets[0];
    const gate = gates.instances[0];
    socket.onopen!();
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({
      type: 'start', speech_output_transport: 'mp3_turn_stream_v2',
    });
    capture.frames[0](btoa('\0\0'.repeat(160)));
    gate.callbacks.onAudio('connecting-audio-must-stay-local');
    socket.onmessage!({ data: JSON.stringify({ type: 'ready', call_id: 'old-server-call', speech_output_transport: transport }) });
    gate.callbacks.onAudio('late-audio-must-not-upload');
    expect(get(controller)).toMatchObject({ status: 'error', error: 'call_unavailable', callId: null });
    expect(gate.setLive).not.toHaveBeenCalled();
    expect(gate.start).not.toHaveBeenCalled();
    expect(gate.stop).toHaveBeenCalledOnce();
    expect(capture.stop).toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalledOnce();
    expect(socket.send.mock.calls.map(([frame]) => JSON.parse(frame).type)).toEqual(['start']);
    expect(canonical.send).not.toHaveBeenCalled();
    expect(persistence.lifecycle).not.toHaveBeenCalled();
    expect(cues.play).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner
  it('waits for the saved first-call acknowledgement before microphone capture or provider socket', async () => {
    let accept!: (accepted:boolean)=>void;
    privacy.ensure.mockImplementationOnce(()=>new Promise<boolean>(resolve=>{accept=resolve;}));
    const {controller,sockets}=startingController();
    const pending=controller.start('chat-1');
    expect(capture.unlock).toHaveBeenCalledOnce();
    expect(capture.start).not.toHaveBeenCalled();
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    await controller.start('another-chat');
    expect(privacy.ensure).toHaveBeenCalledOnce();
    accept(true); await pending;
    expect(capture.start).toHaveBeenCalledOnce();
    expect(sockets).toHaveLength(1);
    controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner,assistant-speech.playback.autoplay-recovery-visible
  it('primes shared speech synchronously in Start and the consent gesture without a deferred duplicate', async () => {
    let accept!: (accepted: boolean) => void;
    privacy.ensure.mockImplementationOnce(() => new Promise<boolean>(resolve => { accept = resolve; }));
    const { controller, sockets } = startingController();
    const pending = controller.start('chat-1');
    const prime = vi.mocked(assistantSpeechController.primeForAutoplay);
    expect(prime).toHaveBeenCalledOnce();
    expect(prime.mock.invocationCallOrder[0]).toBeLessThan(privacy.ensure.mock.invocationCallOrder[0]);
    expect(capture.start).not.toHaveBeenCalled();
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    const consentGesture = privacy.ensure.mock.calls[0][1];
    consentGesture();
    expect(prime).toHaveBeenCalledTimes(2);
    expect(capture.unlock).toHaveBeenCalledTimes(2);
    expect(sockets).toHaveLength(0);
    accept(true);
    await pending;
    expect(prime).toHaveBeenCalledTimes(2);
    expect(sockets).toHaveLength(1);
    controller.hangup();
    consentGesture();
    expect(prime).toHaveBeenCalledTimes(2); // A stale consent callback cannot touch playback.
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.typed-input,video-call.privacy.first-call-warning,video-call.audio.single-owner
  it('unlocks synchronously but waits for the captured draft before chat registration or transport', async () => {
    let saved!: (success: boolean) => void;
    const draftReady = new Promise<boolean>(resolve => { saved = resolve; });
    const { controller, sockets } = startingController();
    const pending = controller.start('project-draft', undefined, draftReady);
    expect(capture.unlock).toHaveBeenCalledOnce();
    await Promise.resolve();
    expect(get(controller).status).toBe('connecting');
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(capture.start).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    saved(true);
    await pending;
    expect(persistence.prepare).toHaveBeenCalledExactlyOnceWith('project-draft', true);
    expect(sockets).toHaveLength(1);
    controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing,video-call.privacy
  it.each(['false', 'rejection'])('fails visibly before registration or transport when draft persistence returns %s during consent', async (failure) => {
    let accept!: (accepted: boolean) => void;
    privacy.ensure.mockImplementationOnce(() => new Promise<boolean>(resolve => { accept = resolve; }));
    const { controller, sockets } = startingController();
    const draftReady = failure === 'false' ? Promise.resolve(false) : Promise.reject(new Error('private draft error'));
    const pending = controller.start('project-draft', undefined, draftReady);
    await new Promise(resolve => setTimeout(resolve, 0)); // Rejection is handled while consent remains pending.
    expect(get(controller).status).toBe('connecting');
    accept(true);
    await pending;
    expect(get(controller)).toMatchObject({ status: 'error', error: 'call_unavailable', chatId: 'project-draft' });
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(capture.start).not.toHaveBeenCalled();
    expect(capture.stop).toHaveBeenCalled();
    expect(gates.instances[0].stop).toHaveBeenCalledOnce();
    expect(sockets).toHaveLength(0);
    expect(canonical.send).not.toHaveBeenCalled();
    expect(cues.play).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing,video-call.privacy
  it('ignores a late saved draft after startup was cancelled', async () => {
    let saved!: (success: boolean) => void;
    const draftReady = new Promise<boolean>(resolve => { saved = resolve; });
    const { controller, sockets } = startingController();
    const pending = controller.start('project-draft', undefined, draftReady);
    await Promise.resolve();
    controller.hangup();
    saved(true);
    await pending;
    expect(get(controller).status).toBe('ended');
    expect(persistence.prepare).not.toHaveBeenCalled();
    expect(capture.start).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('returns to idle on Cancel without microphone, provider, lifecycle or connection cue', async () => {
    privacy.ensure.mockResolvedValueOnce(false);
    const {controller,sockets}=startingController();
    await controller.start('chat-1');
    expect(get(controller).status).toBe('idle');
    expect(capture.start).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    expect(persistence.lifecycle).not.toHaveBeenCalled();
    expect(cues.play).not.toHaveBeenCalled();
    expect(capture.stop).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('aborts pending acknowledgement on hangup and ignores late acceptance', async () => {
    let accept!: (accepted:boolean)=>void;
    privacy.ensure.mockImplementationOnce(()=>new Promise<boolean>(resolve=>{accept=resolve;}));
    const {controller,sockets}=startingController();
    const pending=controller.start('chat-1');
    const signal=privacy.ensure.mock.calls[0][0];
    controller.hangup();
    expect(signal.aborted).toBe(true);
    accept(true); await pending;
    expect(capture.start).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    expect(get(controller).status).toBe('ended');
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('fails closed on an unavailable authoritative acknowledgement', async () => {
    privacy.ensure.mockRejectedValueOnce(new Error('unavailable'));
    const {controller,sockets}=startingController();
    await controller.start('chat-1');
    expect(get(controller).status).toBe('error');
    expect(capture.start).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
    expect(cues.play).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.lifecycle.recovery-and-billing
  it('unlocks silently before admission and cues only successful ready and terminal once', async () => {
    const {controller,sockets}=startingController();
    const pending=controller.start('chat-1');
    expect(cues.prepare).toHaveBeenCalledOnce();
    expect(cues.play).not.toHaveBeenCalled();
    await pending;
    const harness=controller as unknown as Harness;
    harness.handleMessage({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'call-1'});
    harness.handleMessage({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'provider-rollover'});
    expect(cues.play.mock.calls).toEqual([['connected']]);
    // Automatic VAD idle/resume and provider activity must remain silent.
    gates.instances[gates.instances.length - 1]!.callbacks.onState({inputIdle:true,userSpeaking:false});
    gates.instances[gates.instances.length - 1]!.callbacks.onState({inputIdle:false,userSpeaking:true});
    harness.handleMessage({type:'billing_activity',call_id:'call-1',input_listening:false,processing:false});
    expect(cues.play.mock.calls).toEqual([['connected']]);
    const stopsBeforeEnd=cues.stop.mock.calls.length;
    (sockets[0] as unknown as {onclose:()=>void}).onclose();
    harness.handleMessage({type:'ended'});
    controller.hangup();
    expect(cues.play.mock.calls).toEqual([['connected'],['ended']]);
    expect(cues.stop).toHaveBeenCalledTimes(stopsBeforeEnd);
    expect(capture.stop).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it.each(['hangup', 'ended', 'error'])('confirms terminal %s once after a successful connection', async (terminal) => {
    const {controller}=startingController();
    await controller.start('chat-1');
    const harness=controller as unknown as Harness;
    harness.handleMessage({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'call-1'});
    if(terminal==='hangup') controller.hangup();
    else harness.handleMessage({type:terminal});
    harness.handleMessage({type:'ended'});
    expect(cues.play.mock.calls).toEqual([['connected'],['ended']]);
    expect(capture.stop).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.audio.single-owner
  it('cues effective manual mute changes without affecting assistant playback or call activity', () => {
    const {controller,harness}=liveController();
    const playback={setMicEnabled:vi.fn(),stop:vi.fn(),interrupt:vi.fn()};
    harness.audio=playback;
    harness.update({assistantSpeaking:true,audioLevels:Array(16).fill(.4),billingActivity:{inputListening:false,processing:true}});
    controller.setMuted(false);
    controller.setMuted(true);
    controller.setMuted(true);
    controller.setMuted(false);
    controller.setMuted(false);
    expect(cues.play.mock.calls).toEqual([['muted'],['unmuted']]);
    expect(get(controller)).toMatchObject({assistantSpeaking:true,audioLevels:Array(16).fill(.4),billingActivity:{inputListening:false,processing:true}});
    expect(playback.stop).not.toHaveBeenCalled();
    expect(playback.interrupt).not.toHaveBeenCalled();
    expect(playback.setMicEnabled.mock.calls).toEqual([[false],[true]]);
    controller.hangup();
    controller.setMuted(true);
    expect(cues.play.mock.calls).toEqual([['muted'],['unmuted']]);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('closes prepared cue output without confirmations when admission fails', async () => {
    persistence.prepare.mockRejectedValueOnce(new Error('refused'));
    const {controller}=startingController();
    await controller.start('chat-1');
    expect(cues.prepare).toHaveBeenCalledOnce();
    expect(cues.play).not.toHaveBeenCalled();
    expect(cues.stop).toHaveBeenCalledTimes(2);
    controller.hangup();
    expect(cues.play).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.activity-status,video-call.chat.call-strip-layout
  it('counts only active live time, retaining processing time while muted and pausing explicit idle', async () => {
    vi.useFakeTimers({toFake:['setInterval','clearInterval','performance']});
    const {controller,sockets} = startingController();
    await controller.start('chat-1');
    vi.advanceTimersByTime(2000);
    expect(get(controller).activeElapsedSeconds).toBe(0);
    sockets[0].onmessage!({data:JSON.stringify({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'call-1'})});
    vi.advanceTimersByTime(2250);
    expect(get(controller).activeElapsedSeconds).toBe(2);
    const receive = (input_listening:boolean,processing:boolean) => sockets[0].onmessage!({data:JSON.stringify({type:'billing_activity',call_id:'call-1',input_listening,processing})});
    receive(false,false);
    vi.advanceTimersByTime(5000);
    expect(get(controller)).toMatchObject({activeElapsedSeconds:2,elapsedSeconds:7});
    controller.setMuted(true);
    receive(false,true);
    vi.advanceTimersByTime(2000);
    expect(get(controller).activeElapsedSeconds).toBe(4);
    receive(false,false);
    controller.hangup();
    vi.advanceTimersByTime(3000);
    expect(get(controller).activeElapsedSeconds).toBe(4);
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.call-events
  it('records one lifecycle pair for the original ready call and none for refused starts', async () => {
    const {controller,sockets} = startingController();
    await controller.start('chat-1');
    controller.hangup();
    expect(persistence.lifecycle).not.toHaveBeenCalled();
    await controller.start('chat-1');
    sockets[1].onmessage!({data:JSON.stringify({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'call-2'})});
    sockets[1].onmessage!({data:JSON.stringify({type:'ready',speech_output_transport:'mp3_turn_stream_v2',call_id:'call-2'})});
    controller.hangup();
    controller.hangup();
    expect(persistence.lifecycle.mock.calls.map(([event]) => event)).toEqual([
      expect.objectContaining({type:'started',chatId:'chat-1',callId:'call-2',occurredAt:expect.any(Number)}),
      expect.objectContaining({type:'ended',chatId:'chat-1',callId:'call-2',activeElapsedSeconds:0}),
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  it('captures while connecting, routes PCM through the gate and goes live without awaiting VAD', async () => {
    const { controller, sockets } = startingController();
    await controller.start('chat-1');
    const gate = gates.instances[0];
    expect(capture.mic).toHaveBeenCalledWith(true);
    capture.frames[0](btoa('\0\0'.repeat(682)));
    expect(gate.push).toHaveBeenCalledWith(btoa('\0\0'.repeat(682)));
    expect(sockets[0].send).not.toHaveBeenCalled();
    expect(gate.start).not.toHaveBeenCalled();
    sockets[0].onopen!();
    expect(sockets[0].send).toHaveBeenCalledOnce();
    expect(JSON.parse(sockets[0].send.mock.calls[0][0])).toMatchObject({
      type: 'start', chat_id: 'chat-1', startup_audio_allowance_ms: 10_000, speech_output_transport: 'mp3_turn_stream_v2',
    });
    sockets[0].send.mockClear();
    // A detector may remain cold indefinitely; readiness still completes now.
    gate.start.mockReturnValue(new Promise(() => {}));
    sockets[0].onmessage!({ data: JSON.stringify({ type: 'ready', speech_output_transport: 'mp3_turn_stream_v2', call_id: 'call-1' }) });
    expect(get(controller)).toMatchObject({ status: 'live', inputIdle: false, muted: false });
    expect(gate.setLive).toHaveBeenCalledExactlyOnceWith(true);
    expect(gate.start).toHaveBeenCalledOnce();
    gate.callbacks.onAudio('continuous-fallback');
    expect(JSON.parse(sockets[0].send.mock.calls[0][0])).toEqual({ type: 'mic_audio', data: 'continuous-fallback' });
    gate.callbacks.onState({ inputIdle: true, userSpeaking: false });
    gate.callbacks.onAudioEnd();
    gate.callbacks.onState({ inputIdle: false, userSpeaking: true });
    gate.callbacks.onAudio('prefix-and-resumed-pcm');
    expect(get(controller)).toMatchObject({ inputIdle: false, userSpeaking: true });
    expect(sockets[0].send.mock.calls.map(([frame]) => JSON.parse(frame).type)).toEqual(['mic_audio', 'audio_stream_end', 'mic_audio']);
    controller.hangup();
    expect(gate.stop).toHaveBeenCalledOnce();
    expect(get(controller).inputIdle).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  it('keeps manual mute authoritative during connection and ignores callbacks from a previous call', async () => {
    const { controller, sockets } = startingController();
    await controller.start('chat-1');
    const gate = gates.instances[0];
    controller.setMuted(true);
    expect(capture.mic).toHaveBeenLastCalledWith(false);
    expect(gate.setMuted).toHaveBeenCalledExactlyOnceWith(true);
    sockets[0].onmessage!({ data: JSON.stringify({ type: 'ready', speech_output_transport: 'mp3_turn_stream_v2', call_id: 'call-1' }) });
    gate.callbacks.onAudio('must-not-send');
    expect(sockets[0].send).not.toHaveBeenCalled();
    expect(get(controller).muted).toBe(true);
    controller.hangup();
    await controller.start('chat-1');
    const currentState = get(controller);
    gate.callbacks.onAudio('late-frame');
    gate.callbacks.onAudioEnd();
    gate.callbacks.onState({ inputIdle: true, userSpeaking: true });
    gate.callbacks.onError();
    capture.playback[0](true, true);
    expect(get(controller)).toEqual(currentState);
    expect(sockets[1].send).not.toHaveBeenCalled();
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  it('clears startup capture on permission failure and exposes startup overflow as connection_failed', async () => {
    const { controller } = startingController();
    capture.start.mockRejectedValueOnce(Object.assign(new Error('denied'), { name: 'NotAllowedError' }));
    await controller.start('chat-1');
    expect(get(controller)).toMatchObject({ status: 'error', error: 'microphone_denied', inputIdle: false });
    expect(gates.instances[0].stop).toHaveBeenCalledOnce();
    await controller.start('chat-1');
    gates.instances[1].callbacks.onError();
    expect(get(controller)).toMatchObject({ status: 'error', error: 'connection_failed', inputIdle: false });
    expect(gates.instances[1].stop).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.chat.fixed-binding
  it('retains the initiating chat when context preparation fails before a provider socket opens', async () => {
    const Socket = vi.fn();
    Object.assign(Socket, { OPEN: 1, CLOSING: 2 });
    vi.stubGlobal('WebSocket', Socket);
    persistence.prepare.mockRejectedValue(new VoiceCallContextError('context_too_large'));
    const controller = new VoiceCallController();
    const bound = vi.fn();
    const states: Array<{ status: string; chatId: string | null }> = [];
    const unsubscribe = controller.subscribe(({ status, chatId }) => states.push({ status, chatId }));
    await controller.start('chat-with-too-much-history', bound);
    expect(states).toContainEqual({ status: 'connecting', chatId: 'chat-with-too-much-history' });
    expect(get(controller)).toMatchObject({ status: 'error', chatId: 'chat-with-too-much-history', error: 'context_too_large' });
    expect(bound).not.toHaveBeenCalled();
    expect(get(notificationStore).notifications).toMatchObject([{type:'error',message:'voicecall.context_too_large'}]);
    expect(Socket).not.toHaveBeenCalled();
    expect(capture.stop).toHaveBeenCalledOnce();
    unsubscribe();
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context
  it('keeps a new-chat preparation error unbound and dismissible without opening a provider socket', async () => {
    const Socket = vi.fn();
    Object.assign(Socket, { OPEN: 1, CLOSING: 2 });
    vi.stubGlobal('WebSocket', Socket);
    persistence.prepare.mockRejectedValue(new VoiceCallContextError('context_unavailable'));
    const controller = new VoiceCallController();
    await controller.start();
    expect(get(controller)).toMatchObject({ status: 'error', chatId: null, error: 'context_unavailable' });
    expect(Socket).not.toHaveBeenCalled();
    controller.hangup();
    expect(get(controller).status).toBe('ended');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('deduplicates public call errors and never displays arbitrary server error text', () => {
    const { controller, harness } = liveController();
    harness.handleMessage({type:'error',code:'private arbitrary server detail'});
    harness.handleMessage({type:'error',code:'another unknown detail'});
    expect(get(controller)).toMatchObject({status:'error',chatId:'chat-1'});
    expect(get(notificationStore).notifications).toMatchObject([
      {type:'error',message:'voicecall.call_unavailable',dedupeKey:'voice-call-error-call_unavailable'},
    ]);
    expect(get(notificationStore).notifications).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output
  it('notifies repeated camera failures once while preserving the live call', () => {
    const { controller, harness } = liveController();
    harness.update({cameraError:'camera_denied'});
    harness.update({cameraError:'camera_denied'});
    expect(get(controller)).toMatchObject({status:'live',cameraError:'camera_denied'});
    expect(get(notificationStore).notifications).toMatchObject([{type:'error',message:'voicecall.camera_denied'}]);
    expect(get(notificationStore).notifications).toHaveLength(1);
    controller.hangup();
  });

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

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
  it('disables microphone forwarding before sending the live mute end marker once', () => {
    const { controller, harness, socket } = liveController();
    const order: string[] = [];
    harness.audio = { setMicEnabled: vi.fn((enabled: boolean) => order.push(`mic:${enabled}`)), stop: vi.fn() };
    socket.send.mockImplementation((frame: string) => order.push(JSON.parse(frame).type));
    controller.setMuted(true);
    controller.setMuted(true);
    expect(order).toEqual(['mic:false', 'audio_stream_end']);
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
  it('uses only current server billing activity independently of quiet input and queued playback', () => {
    const { controller, harness } = liveController();
    harness.handleMessage({ type: 'billing_activity', call_id: 'other-call', input_listening: false, processing: false });
    harness.handleMessage({ type: 'billing_activity', call_id: 'call-1', input_listening: 'false', processing: false });
    expect(get(controller).billingActivity).toBeNull();
    harness.handleMessage({ type: 'billing_activity', call_id: 'call-1', input_listening: true, processing: false });
    expect(get(controller)).toMatchObject({ userSpeaking: false, billingActivity: { inputListening: true, processing: false } });
    harness.update({ muted: true, assistantSpeaking: true });
    harness.handleMessage({ type: 'billing_activity', call_id: 'call-1', input_listening: false, processing: true });
    expect(get(controller).billingActivity).toEqual({ inputListening: false, processing: true });
    harness.handleMessage({ type: 'billing_activity', call_id: 'call-1', input_listening: false, processing: false });
    expect(get(controller)).toMatchObject({ assistantSpeaking: true, billingActivity: { inputListening: false, processing: false } });
    controller.hangup();
    harness.handleMessage({ type: 'billing_activity', call_id: 'call-1', input_listening: true, processing: true });
    expect(get(controller).billingActivity).toEqual({ inputListening: false, processing: false });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output
  it('enables the camera on the existing socket, shrinks its preview and keeps audio on camera-off', async () => {
    vi.useFakeTimers();
    const {controller,harness,socket}=liveController();
    harness.update({cameraAvailable:true});
    await controller.setCameraEnabled(true);
    expect(get(controller)).toMatchObject({cameraEnabled:true,cameraFacing:'environment',mediaExpanded:true,status:'live'});
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({type:'camera_state',enabled:true,call_id:'call-1'});
    visual.cameras[0].callbacks.onFrame({frameId:'frame-1',data:'jpeg',capturedAt:123,width:640,height:360});
    expect(JSON.parse(socket.send.mock.calls[1][0])).toMatchObject({type:'camera_frame',frame_id:'frame-1',data:'jpeg',captured_at:123});
    await vi.advanceTimersByTimeAsync(2000);
    expect(get(controller).mediaExpanded).toBe(false);
    controller.setMediaExpanded(true);
    await controller.setCameraEnabled(false);
    expect(get(controller)).toMatchObject({cameraEnabled:false,cameraStream:null,status:'live',muted:false});
    expect(socket.close).not.toHaveBeenCalled();
    visual.cameras[0].callbacks.onStream({id:'late'} as MediaStream,'user');
    expect(get(controller).cameraStream).toBeNull();
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output
  it('keeps generated media visible across camera flips and camera permission errors preserve voice', async () => {
    const {controller,harness}=liveController();
    harness.update({cameraAvailable:true});
    await controller.setCameraEnabled(true);
    const result={embedId:'generated',kind:'image' as const,url:'blob:generated'};
    harness.update({displayedMedia:result});
    await controller.flipCamera();
    expect(get(controller)).toMatchObject({cameraFacing:'user',displayedMedia:result});
    visual.cameras[0].callbacks.onError('camera_denied');
    expect(get(controller)).toMatchObject({cameraEnabled:false,cameraError:'camera_denied',status:'live',displayedMedia:result});
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output,video-call.audio.single-owner
  it('keeps an in-flight camera flip owned until cancellation and ignores its late stream', async () => {
    const {controller,harness}=liveController();
    harness.update({cameraAvailable:true});
    await controller.setCameraEnabled(true);
    const camera=visual.cameras[0];
    let finish!:()=>void;
    vi.spyOn(camera,'flip').mockImplementation(()=>{
      camera.callbacks.onStream(null,'user');
      return new Promise<void>(resolve=>{finish=()=>{camera.callbacks.onStream({id:'late-front'} as MediaStream,'user');resolve();};});
    });
    const flipping=controller.flipCamera();
    expect(get(controller).cameraPending).toBe(true);
    await controller.setCameraEnabled(true);
    expect(visual.cameras).toHaveLength(1);
    await controller.setCameraEnabled(false);
    expect(camera.stop).toHaveBeenCalled();
    finish();await flipping;
    expect(get(controller)).toMatchObject({cameraEnabled:false,cameraPending:false,cameraStream:null,status:'live'});
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
  it('acknowledges only the selected saved source frame in the owning live call', async () => {
    const {controller,harness,socket}=liveController();
    const event={type:'voice_source_frame',call_id:'call-1',user_message_id:'user-1',frame_id:'frame-1',data:'/9j/AA==',captured_at:123,created_at:1};
    harness.handleMessage({...event,call_id:'another-call'});
    expect(visual.source).not.toHaveBeenCalled();
    harness.handleMessage(event);
    await vi.waitFor(()=>expect(socket.send).toHaveBeenCalledOnce());
    expect(visual.source).toHaveBeenCalledWith({callId:'call-1',chatId:'chat-1',messageId:'user-1',frameId:'frame-1',data:'/9j/AA==',capturedAt:123,createdAt:1,source:'camera'});
    expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({type:'source_frame_saved',call_id:'call-1',user_message_id:'user-1',frame_id:'frame-1',embed_reference:{type:'image',embed_id:'source-1'}});
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
  it('reports source-save failure without hanging up and fences late source acknowledgements', async () => {
    const {controller,harness,socket}=liveController();
    visual.source.mockRejectedValueOnce(new Error('sync unavailable'));
    const event={type:'voice_source_frame',call_id:'call-1',user_message_id:'user-1',frame_id:'frame-1',data:'/9j/AA==',captured_at:123,created_at:1};
    harness.handleMessage(event);
    await vi.waitFor(()=>expect(get(controller).cameraError).toBe('source_frame_failed'));
    expect(get(controller).status).toBe('live');
    expect(JSON.parse(socket.send.mock.calls[0][0]).type).toBe('source_frame_failed');
    let finish!:(value:unknown)=>void;
    visual.source.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
    harness.handleMessage({...event,frame_id:'frame-2'});
    await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    controller.hangup();
    const before=socket.send.mock.calls.length;
    finish({type:'image',embed_id:'late'});
    await Promise.resolve();await Promise.resolve();
    expect(socket.send.mock.calls.length).toBe(before);
    expect(get(controller).status).toBe('ended');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
  it('attaches and acknowledges the same sampled frame independently for two user turns', async () => {
    const {controller,harness,socket}=liveController();
    let finish!:(reference:unknown)=>void;
    const saving=new Promise(resolve=>{finish=resolve;});
    visual.source.mockReturnValue(saving);
    const event={type:'voice_source_frame',call_id:'call-1',frame_id:'same-frame',data:'/9j/AA==',captured_at:123,created_at:1};
    harness.handleMessage({...event,user_message_id:'first-user'});
    await vi.waitFor(()=>expect(visual.source).toHaveBeenCalledOnce());
    harness.handleMessage({...event,user_message_id:'second-user'});
    await vi.waitFor(()=>expect(visual.source).toHaveBeenCalledTimes(2));
    finish({type:'image',embed_id:'shared-source'});
    await vi.waitFor(()=>expect(socket.send).toHaveBeenCalledTimes(2));
    expect(visual.source.mock.calls.map(call=>call[0].messageId)).toEqual(['first-user','second-user']);
    expect(socket.send.mock.calls.map(call=>JSON.parse(call[0]).user_message_id)).toEqual(['first-user','second-user']);
    controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.chat.typed-input,chats.message.identity-idempotent
  it('admits a final user transcript once through the canonical sender and clears typed input only after admission', async () => {
    const { controller, harness, socket } = liveController();
    let admit!: (accepted:boolean) => void;
    canonical.send.mockImplementationOnce(() => new Promise(resolve => { admit=resolve; }));
    const accepted = controller.submitText('chat-1','Please explain ramen');
    const id = await submittedId(socket);
    const final = {type:'transcript',call_id:'call-1',role:'user',message_id:id,turn_id:id,text:'Please explain ramen',final:true,created_at:1700000000};
    harness.handleMessage({...final, final:false});
    expect(canonical.send).not.toHaveBeenCalled();
    harness.handleMessage(final); harness.handleMessage(final);
    await vi.waitFor(() => expect(canonical.send).toHaveBeenCalledOnce());
    expect(canonical.send).toHaveBeenCalledWith(expect.objectContaining({callId:'call-1',chatId:'chat-1',turnId:id,text:'Please explain ramen'}));
    let resolved=false; void accepted.then(() => {resolved=true;});
    expect(resolved).toBe(false); admit(true);
    expect(await accepted).toBe(true);
    expect(persistence.upsert).not.toHaveBeenCalled(); expect(persistence.persist).not.toHaveBeenCalled();
    harness.handleMessage(final); expect(canonical.send).toHaveBeenCalledOnce(); controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.typed-input,video-call.audio.complete-turn-admission
  it('retains typed draft acceptance on canonical failure, server refusal and connection end', async () => {
    for (const reason of ['canonical','refused','closed']) {
      const {controller,harness,socket}=liveController();
      const pending=controller.submitText('chat-1','Please explain ramen');
      const id=await submittedId(socket);
      if(reason==='canonical') { canonical.send.mockResolvedValueOnce(false); harness.handleMessage({type:'transcript',call_id:'call-1',role:'user',message_id:id,text:'Please explain ramen',final:true}); }
      else if(reason==='refused') harness.handleMessage({type:'text_input_rejected',message_id:id});
      else controller.hangup();
      expect(await pending).toBe(false); controller.hangup();
    }
    expect(persistence.persist).not.toHaveBeenCalled(); expect(persistence.rollback).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.single-owner
  it('keeps listener cues and interim speech from stopping audio, then stops only the confirmed current assistant', async () => {
    const {controller,harness}=liveController(); harness.bindCanonicalChat(); await vi.waitFor(()=>expect(visual.listeners.size).toBeGreaterThan(0));
    harness.callTurnIds.add('user-1');
    canonical.tasks.set('chat-1',{taskId:'task-1',userMessageId:'user-1'});
    for(const listener of visual.listeners)listener(new CustomEvent('aiTypingStarted',{detail:{chat_id:'chat-1',user_message_id:'user-1',task_id:'task-1',message_id:'assistant-1'}}));
    assistantSpeechController.activity.set({chatId:'chat-1',messageId:'assistant-1',text:'Rich answer [source](https://example.org)',speaking:true,language:'en'});
    const baseline=vi.mocked(assistantSpeechController.stop).mock.calls.length;
    for(const text of ['hmm','okay']) harness.handleMessage({type:'transcript',role:'user',call_id:'call-1',message_id:'cue-'+text,text,final:false});
    harness.handleMessage({type:'transcript.discarded',call_id:'call-1',reason:'backchannel'});
    harness.handleMessage({type:'audio.interrupted',call_id:'old-call',assistant_message_id:'assistant-1'});
    harness.handleMessage({type:'audio.interrupted',call_id:'call-1',assistant_message_id:'old-assistant'});
    expect(vi.mocked(assistantSpeechController.stop).mock.calls.length).toBe(baseline);
    expect(canonical.send).not.toHaveBeenCalled();
    harness.handleMessage({type:'audio.interrupted',call_id:'call-1',assistant_message_id:'assistant-1',assistant_task_id:'task-1'});
    await vi.waitFor(() => expect(canonical.cancel).toHaveBeenCalledWith('task-1','chat-1'));
    expect(vi.mocked(assistantSpeechController.stop).mock.calls.length).toBe(baseline+1); controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.single-owner
  it('keeps rich canonical messages authoritative and ignores legacy assistant transcript and audio payloads', async () => {
    const {controller,harness,socket}=liveController(); harness.bindCanonicalChat(); await vi.waitFor(()=>expect(visual.listeners.size).toBeGreaterThan(0));
    harness.handleMessage({type:'transcript',call_id:'call-1',role:'assistant',message_id:'assistant-1',text:'spoken plain text',final:true});
    harness.handleMessage({type:'audio_chunk',data:btoa('\0\0')});
    assistantSpeechController.activity.set({chatId:'chat-1',messageId:'assistant-1',text:'### Rich answer\n[Source](https://example.org)',speaking:true,language:'fr'});
    expect(get(controller).assistantSpeaking).toBe(true);
    expect(socket.send.mock.calls.map(([frame])=>JSON.parse(frame as string))).toContainEqual(expect.objectContaining({type:'assistant_state',assistant_message_id:'assistant-1',speaking:true,language:'fr'}));
    expect(persistence.upsert).not.toHaveBeenCalled(); expect(persistence.artifact).not.toHaveBeenCalled(); expect(canonical.send).not.toHaveBeenCalled();
    assistantSpeechController.activity.set({chatId:'other-chat',messageId:'other',text:'other',speaking:false,language:'en'});
    expect(get(controller).assistantSpeaking).toBe(true); controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.audio.complete-turn-admission
  it('waits for the selected encrypted source before admitting its ordinary user turn', async () => {
    const {controller,harness}=liveController(); let release!: (ref:unknown)=>void;
    visual.source.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    harness.handleMessage({type:'voice_source_frame',call_id:'call-1',user_message_id:'user-1',frame_id:'frame-1',data:'/9j/2Q==',captured_at:1700000000123,created_at:1700000000,source:'screen'});
    harness.handleMessage({type:'transcript',call_id:'call-1',role:'user',message_id:'user-1',text:'Describe this screen',final:true});
    await vi.waitFor(()=>expect(visual.source).toHaveBeenCalledOnce()); expect(canonical.send).not.toHaveBeenCalled();
    release({type:'image',embed_id:'source-1'});
    await vi.waitFor(()=>expect(canonical.send).toHaveBeenCalledWith(expect.objectContaining({turnId:'user-1',embedReferences:[{type:'image',embed_id:'source-1'}]})));
    expect(visual.source).toHaveBeenCalledWith(expect.objectContaining({source:'screen'})); controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.generated-media-stage,video-call.audio.spoken-rich-response,video-call.chat.skill-integration
  it('presents generated media from the ordinary rich assistant response with its routed attribution',async()=>{
    const {controller,harness}=liveController();harness.bindCanonicalChat();
    await vi.waitFor(()=>expect(visual.listeners.size).toBeGreaterThan(0));
    harness.handleMessage({type:'transcript',call_id:'call-1',role:'user',message_id:'user-media',text:'Create a video',final:true});
    await vi.waitFor(()=>expect(canonical.send).toHaveBeenCalledOnce());
    const video={embedId:'generated-video',kind:'video',url:'blob:owned-video'};
    visual.resolve.mockResolvedValueOnce([video]);
    const message={chat_id:'chat-1',message_id:'assistant-media',role:'assistant',user_message_id:'user-media',
      model_name:'automatic-routed-model',category:'technology',sender_name:'Routed Mate',
      content:'### Your video\n\n```json\n{"type":"app_skill_use","embed_id":"generation-group","app_id":"videos","skill_id":"create"}\n```'};
    for(const listener of [...visual.listeners])listener(new CustomEvent('chatUpdated',{detail:{newMessage:message}}));
    await vi.waitFor(()=>expect(get(controller).displayedMedia).toEqual(video));
    expect(visual.resolve).toHaveBeenCalledWith(['generation-group']);
    expect(get(controller)).toMatchObject({modelName:'automatic-routed-model',mateName:'Routed Mate',mediaExpanded:true});
    controller.setMediaExpanded(false);expect(get(controller).mediaExpanded).toBe(false);
    for(const listener of [...visual.listeners])listener(new CustomEvent('chatUpdated',{detail:{newMessage:{...message,chat_id:'other-chat',model_name:'foreign'}}}));
    expect(get(controller).modelName).toBe('automatic-routed-model');
    expect(persistence.upsert).not.toHaveBeenCalled();controller.hangup();expect(visual.destroy).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.complete-turn-admission
  it('binds an early reasoning interruption to its canonical task and fences a newer task',async()=>{
    const {controller,harness,socket}=liveController();harness.bindCanonicalChat();
    await vi.waitFor(()=>expect(visual.listeners.size).toBeGreaterThan(0));
    harness.callTurnIds.add('user-early');canonical.tasks.set('chat-1',{taskId:'task-early',userMessageId:'user-early'});
    for(const listener of visual.listeners)listener(new CustomEvent('aiTaskInitiated',{detail:{chat_id:'chat-1',user_message_id:'user-early',ai_task_id:'task-early'}}));
    expect(socket.send.mock.calls.map(([frame])=>JSON.parse(frame as string))).toContainEqual(expect.objectContaining({
      type:'assistant_state',assistant_message_id:null,assistant_task_id:'task-early',generating:true,speaking:false}));
    harness.handleMessage({type:'audio.interrupted',call_id:'call-1',assistant_message_id:null,assistant_task_id:'task-early'});
    expect(canonical.cancel).toHaveBeenCalledExactlyOnceWith('task-early','chat-1');
    harness.callTurnIds.add('user-new');canonical.tasks.set('chat-1',{taskId:'task-new',userMessageId:'user-new'});
    for(const listener of visual.listeners)listener(new CustomEvent('aiTaskInitiated',{detail:{chat_id:'chat-1',user_message_id:'user-new',ai_task_id:'task-new'}}));
    const stopped=vi.mocked(assistantSpeechController.stop).mock.calls.length;
    harness.handleMessage({type:'audio.interrupted',call_id:'call-1',assistant_message_id:null,assistant_task_id:'task-early'});
    expect(canonical.cancel).toHaveBeenCalledTimes(1);expect(vi.mocked(assistantSpeechController.stop).mock.calls.length).toBe(stopped);
    controller.hangup();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission
  it('captures the heard boundary before pure-stop teardown and sends it only on the next accepted call turn',async()=>{
    const {controller,harness}=liveController();harness.bindCanonicalChat();
    await vi.waitFor(()=>expect(visual.listeners.size).toBeGreaterThan(0));
    harness.callTurnIds.add('user-prior');canonical.tasks.set('chat-1',{taskId:'task-prior',userMessageId:'user-prior'});
    for(const listener of visual.listeners)listener(new CustomEvent('aiTypingStarted',{detail:{chat_id:'chat-1',user_message_id:'user-prior',task_id:'task-prior',message_id:'assistant-prior'}}));
    assistantSpeechController.activity.set({chatId:'chat-1',messageId:'assistant-prior',text:'Full rich answer remains intact.',speaking:true,language:'en'});
    const boundary={assistant_message_id:'assistant-prior',completed_sequences:[0],active_sequence:1,active_offset_ms:1234};
    heard.value=boundary;
    vi.mocked(assistantSpeechController.stop).mockImplementationOnce(async()=>{heard.value=null;});
    harness.handleMessage({type:'audio.interrupted',call_id:'call-1',assistant_message_id:'assistant-prior',assistant_task_id:'task-prior'});
    expect(canonical.send).not.toHaveBeenCalled();expect(heard.value).toBeNull();
    for(const id of ['user-next','user-after'])harness.handleMessage({type:'transcript',call_id:'call-1',role:'user',message_id:id,text:'Continue from where I interrupted',final:true});
    await vi.waitFor(()=>expect(canonical.send).toHaveBeenCalledTimes(2));
    expect(canonical.send.mock.calls[0][0]).toMatchObject({turnId:'user-next',heardBoundary:boundary});
    expect(canonical.send.mock.calls[1][0]).not.toHaveProperty('heardBoundary');
    expect(persistence.upsert).not.toHaveBeenCalled();controller.hangup();
  });

});
