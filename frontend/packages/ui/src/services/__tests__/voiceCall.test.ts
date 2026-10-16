import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const persistence = vi.hoisted(() => ({
  persist: vi.fn(async (_callId: string, _chatId: string, _id: string, _text: string, _createdAt: number) => {}), rollback: vi.fn(async () => {}),
  lifecycle: vi.fn(async (_event:unknown) => {}), upsert: vi.fn(async () => {}), artifact: vi.fn(async () => {}), prepare: vi.fn(async () => ({ chatId: 'chat-1', history: [] })),
}));
const privacy = vi.hoisted(() => ({ ensure: vi.fn(async (_signal:AbortSignal, _gesture:()=>void) => true) }));
vi.mock('../voiceCallPrivacy', () => ({ ensureVoiceCallPrivacyAcknowledgement: privacy.ensure }));
const cues = vi.hoisted(() => ({ prepare: vi.fn(), play: vi.fn(), stop: vi.fn() }));
vi.mock('../voiceCallCues', () => ({ VoiceCallCuePlayer: class {
  prepare = cues.prepare; play = cues.play; stop = cues.stop;
} }));
const tools = vi.hoisted(() => ({ apply: vi.fn(async () => undefined as string | undefined) }));
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
vi.mock('../voiceCallTools', () => ({ applyVoiceToolEvent: tools.apply, applyVoiceCompression: vi.fn(async () => {}) }));
vi.mock('../voiceCallContext', () => ({ loadVoiceProjectContext: vi.fn(async () => ({ project_focus_candidates: [], client_capabilities: [] })) }));
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
vi.mock('../assistantSpeechController', () => ({ assistantSpeechController: { stop: vi.fn(async () => {}) } }));

import { VoiceCallController, voicePcmEnvelope } from '../voiceCall';
import { VoiceCallAudioGate } from '../voiceCallAudioGate';
import { VoiceCallContextError } from '../voiceCallMessages';

type Harness = {
  update: (state: Record<string, unknown>) => void;
  handleMessage: (message: Record<string, unknown>) => void;
  send: (message: Record<string, unknown>) => boolean;
  socket: { readyState: number; send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> };
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
  const gate = gates.instances.at(-1)!;
  gate.setMuted.mockImplementation((muted: boolean) => { if (muted) gate.callbacks.onAudioEnd(); });
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
    Object.values(cues).forEach(mock => mock.mockClear());
    tools.apply.mockReset().mockResolvedValue(undefined);
    capture.unlock.mockClear();
    privacy.ensure.mockReset().mockResolvedValue(true);
    capture.start.mockReset().mockResolvedValue(undefined);
    capture.stop.mockClear();
    capture.mic.mockClear();
    capture.audioTime=10;
    capture.frames.length = 0;
    capture.playback.length = 0;
    gates.instances.length = 0;
    persistence.prepare.mockReset().mockResolvedValue({ chatId: 'chat-1', history: [] });
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

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
    harness.handleMessage({type:'ready',call_id:'call-1'});
    harness.handleMessage({type:'ready',call_id:'provider-rollover'});
    expect(cues.play.mock.calls).toEqual([['connected']]);
    // Automatic VAD idle/resume and provider activity must remain silent.
    gates.instances.at(-1)!.callbacks.onState({inputIdle:true,userSpeaking:false});
    gates.instances.at(-1)!.callbacks.onState({inputIdle:false,userSpeaking:true});
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
    harness.handleMessage({type:'ready',call_id:'call-1'});
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
    sockets[0].onmessage!({data:JSON.stringify({type:'ready',call_id:'call-1'})});
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
    sockets[1].onmessage!({data:JSON.stringify({type:'ready',call_id:'call-2'})});
    sockets[1].onmessage!({data:JSON.stringify({type:'ready',call_id:'call-2'})});
    controller.hangup();
    controller.hangup();
    expect(persistence.lifecycle.mock.calls.map(([event]) => event)).toEqual([
      expect.objectContaining({type:'started',chatId:'chat-1',callId:'call-2',occurredAt:expect.any(Number)}),
      expect.objectContaining({type:'ended',chatId:'chat-1',callId:'call-2',activeElapsedSeconds:0}),
    ]);
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.activity-status,video-call.audio.single-owner
  it('uses bounded actual PCM envelopes for mic and scheduled playback and cancels waveform work on hangup', async () => {
    let frame:FrameRequestCallback = () => {};
    let now = 100;
    vi.spyOn(performance,'now').mockImplementation(() => now);
    const request = vi.fn((callback:FrameRequestCallback) => { frame=callback;return 42; });
    const cancel = vi.fn();
    vi.stubGlobal('requestAnimationFrame',request);vi.stubGlobal('cancelAnimationFrame',cancel);
    const {controller,sockets} = startingController();
    await controller.start('chat-1');
    sockets[0].onmessage!({data:JSON.stringify({type:'ready',call_id:'call-1'})});
    const pcm = btoa('\0\x10'.repeat(960));
    expect(voicePcmEnvelope(btoa('\0\0'.repeat(960)))).toEqual(Array(16).fill(0));
    expect(voicePcmEnvelope(pcm).every(level => level>0 && level<=1)).toBe(true);
    capture.frames[0](pcm);frame(now);
    expect(get(controller).audioLevels.some(level => level>0)).toBe(true);
    controller.setMuted(true);now+=200;frame(now);
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
    sockets[0].onmessage!({data:JSON.stringify({type:'audio_chunk',data:pcm})});
    now+=30;capture.audioTime+=.03;frame(now);
    expect(get(controller).audioLevels.some(level => level>0)).toBe(true);
    sockets[0].onmessage!({data:JSON.stringify({type:'audio.interrupted'})});
    frame(now);
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
    controller.hangup();
    expect(cancel).toHaveBeenCalled();
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.activity-status,video-call.audio.single-owner
  it('retains suspended playback envelopes until the real audio clock resumes, independent of wall time', async () => {
    let frame:FrameRequestCallback=()=>{};
    let now=100;
    vi.spyOn(performance,'now').mockImplementation(()=>now);
    vi.stubGlobal('requestAnimationFrame',vi.fn((callback:FrameRequestCallback)=>{frame=callback;return 7;}));
    vi.stubGlobal('cancelAnimationFrame',vi.fn());
    const {controller,sockets}=startingController();
    await controller.start('chat-1');
    sockets[0].onmessage!({data:JSON.stringify({type:'ready',call_id:'call-1'})});
    controller.setMuted(true);
    // A real 80 ms chunk: audible first 40 ms, quiet second 40 ms.
    const pcm=btoa('\0\x10'.repeat(960)+'\0\0'.repeat(960));
    sockets[0].onmessage!({data:JSON.stringify({type:'audio_chunk',data:pcm})});
    now+=300_000;frame(now); // OS suspends the output clock before its scheduled start.
    expect(capture.audioTime).toBe(10);
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
    capture.audioTime=10.03;frame(now);
    expect(get(controller).audioLevels.some(level=>level>0)).toBe(true);
    now+=300_000;frame(now); // Suspension during playback retains the same frame.
    expect(get(controller).audioLevels.some(level=>level>0)).toBe(true);
    capture.audioTime=10.07;frame(now);
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
    capture.audioTime=10.11;frame(now);
    expect(get(controller).audioLevels).toEqual(Array(16).fill(0));
    controller.hangup();
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
      type: 'start', chat_id: 'chat-1', startup_audio_allowance_ms: 10_000,
    });
    sockets[0].send.mockClear();
    // A detector may remain cold indefinitely; readiness still completes now.
    gate.start.mockReturnValue(new Promise(() => {}));
    sockets[0].onmessage!({ data: JSON.stringify({ type: 'ready', call_id: 'call-1' }) });
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
    sockets[0].onmessage!({ data: JSON.stringify({ type: 'ready', call_id: 'call-1' }) });
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

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts
  it('merges artifacts into the issued call response without creating a second assistant reply', async () => {
    const { controller, harness } = liveController();
    tools.apply.mockResolvedValue('embed-one');
    harness.handleMessage({ type: 'transcript', role: 'assistant', message_id: 'assistant-one',
      user_message_id: 'user-one', text: 'Found it', final: true });
    await vi.waitFor(() => expect(persistence.upsert).toHaveBeenCalledOnce());
    harness.handleMessage({ type: 'voice_embed', call_id: 'call-1', function_call_id: 'function-one',
      assistant_message_id: 'assistant-one', user_message_id: 'user-one', payload: { embed_id: 'embed-one',
        embed_reference: JSON.stringify({ embed_id: 'embed-one', type: 'app_skill_use', app_id: 'web', skill_id: 'search' }) } });
    await vi.waitFor(() => expect(persistence.artifact).toHaveBeenCalledOnce());
    expect(persistence.artifact).toHaveBeenLastCalledWith(expect.objectContaining({
      messageId: 'assistant-one', embedRefs: ['embed-one'],
    }));
    harness.handleMessage({ type: 'transcript', role: 'assistant', message_id: 'assistant-one',
      user_message_id: 'user-one', text: 'Found the corrected result', final: true });
    await vi.waitFor(() => expect(persistence.upsert).toHaveBeenCalledTimes(2));
    expect(persistence.upsert).toHaveBeenLastCalledWith(expect.objectContaining({
      messageId: 'assistant-one', text: 'Found the corrected result', embedRefs: ['embed-one'],
      embedReferences: [{ embed_id: 'embed-one', type: 'app_skill_use', app_id: 'web', skill_id: 'search' }],
    }));
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.audio.single-owner
  it('buffers microphone and typed frames in order while adopting a durable checkpoint', () => {
    const { controller, harness, socket } = liveController();
    harness.handleMessage({ type: 'voice_context_pause', call_id: 'call-1', checkpoint_id: 'checkpoint-one' });
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({ type: 'voice_context_paused', checkpoint_id: 'checkpoint-one' });
    harness.send({ type: 'mic_audio', data: 'first-audio' });
    harness.send({ type: 'text_input', text: 'queued text' });
    harness.send({ type: 'mic_audio', data: 'second-audio' });
    expect(socket.send).toHaveBeenCalledOnce();
    harness.handleMessage({ type: 'voice_context_resumed', call_id: 'other-call', checkpoint_id: 'checkpoint-one' });
    expect(socket.send).toHaveBeenCalledOnce();
    harness.handleMessage({ type: 'voice_context_resumed', call_id: 'call-1', checkpoint_id: 'checkpoint-one' });
    expect(socket.send.mock.calls.slice(1).map(([frame]) => JSON.parse(frame))).toEqual([
      { type: 'mic_audio', data: 'first-audio' }, { type: 'text_input', text: 'queued text' },
      { type: 'mic_audio', data: 'second-audio' },
    ]);
    controller.hangup();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
  it('stops microphone forwarding before one ordered end marker, including a checkpoint pause', () => {
    const { controller, harness, socket } = liveController();
    harness.audio = { setMicEnabled: vi.fn((enabled: boolean) => {
      if (!enabled) expect(socket.send).toHaveBeenCalledOnce();
    }), stop: vi.fn() };
    harness.handleMessage({ type: 'voice_context_pause', call_id: 'call-1', checkpoint_id: 'checkpoint-one' });
    harness.send({ type: 'mic_audio', data: 'already-queued-audio' });
    controller.setMuted(true);
    controller.setMuted(true);
    expect(harness.audio.setMicEnabled).toHaveBeenCalledExactlyOnceWith(false);
    expect(socket.send).toHaveBeenCalledOnce();
    harness.handleMessage({ type: 'voice_context_resumed', call_id: 'call-1', checkpoint_id: 'checkpoint-one' });
    expect(socket.send.mock.calls.slice(1).map(([frame]) => JSON.parse(frame))).toEqual([
      { type: 'mic_audio', data: 'already-queued-audio' }, { type: 'audio_stream_end' },
    ]);
    harness.audio.setMicEnabled.mockReset();
    controller.setMuted(false);
    expect(harness.audio.setMicEnabled).toHaveBeenCalledExactlyOnceWith(true);
    expect(socket.send).toHaveBeenCalledTimes(3);
    controller.hangup();
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
