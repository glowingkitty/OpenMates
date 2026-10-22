/** Real authenticated STT and ordinary encrypted chat transport in isolated CI.
 * Only external providers use deterministic fixtures; browser sockets, routing,
 * encrypted messages, speech assets and source uploads use their normal owners.
 */
import type { Locator, Page, TestInfo } from '@playwright/test';
import { clickChatTarget, scrollChatHistoryToStart } from './helpers/chat-scroll';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const USER_SPEECH = 'How do I make ramen?';
const ASSISTANT_SPEECH = 'For ramen, simmer the broth and cook the noodles.';
const PASTED_TEXT = 'Please use this pasted recipe: noodles, broth, mushrooms and ginger.';

/** Substitute only the external image bytes; ordinary proxy URLs and embeds stay real. */
async function installVoiceFixtureImageProxy(page: Page): Promise<{ servedRequests: number }> {
  const asset = await page.request.get('/store-examples/generate-1.webp');
  expect(asset.ok()).toBeTruthy();
  const imageBytes = await asset.body();
  expect(imageBytes.subarray(8, 12).toString('ascii')).toBe('WEBP');
  const proxyUrl = new URL('https://preview.openmates.org/api/v1/image');
  proxyUrl.searchParams.set('url', 'https://app.dev.openmates.org/store-examples/generate-1.webp');
  // Chat renderers proxy before mounting the image component, without a size.
  // Its double-proxy guard preserves that exact URL when the component asks
  // for a 520px preview; the component-preview route uses a different URL.
  const observed = { servedRequests: 0 };
  await page.route(url => url.href === proxyUrl.href, async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: 'image/webp', body: imageBytes });
    observed.servedRequests++;
  });
  return observed;
}

interface SocketObservation {
  path: string;
  code?: string;
  stage?: string;
  errorOrigin?: { category: string; function: string; line: number };
  socketId?: number;
  type: string;
  voiceMode?: boolean;
  autoSpeak?: boolean;
  forcedModel?: boolean;
  speaking?: boolean;
  kind?: string;
  speechStatus?: string;
  segmentId?: string;
  heardBoundary?: {assistant_message_id:string;completed_sequences:number[];active_sequence:number|null;active_offset_ms:number};
  language?: string;
  observedAt?: number;
  audioSamples?: number;
  audioBatch?: number;
  audioNonzero?: boolean;
  startupAllowanceMs?: number;
  messageId?: string;
  requestId?: string;
  turnId?: string;
  preflightId?: string;
  chatId?: string;
  callId?: string;
  role?: string;
  assistantMessageId?: string;
  userMessageId?: string;
  taskId?: string;
  taskStatus?: string;
  finalChunk?: boolean;
  awaitingContinuation?: boolean;
  interruptedByRevocation?: boolean;
  interruptedBySoftLimit?: boolean;
  embedId?: string;
  summary?: string;
  ciphertextLength?: number;
  plaintext?: boolean;
  revision?: number;
  inputListening?: boolean;
  processing?: boolean;
  creditsCharged?:number;
  checkpointId?: string;
  coveredCount?: number;
  compressedMessageCount?: number;
  sourceMessageIds?: string[];
  coveredMessageIds?: string[];
  snapshotId?: string;
  boundaryTimestamp?: number;
  createdAt?: number;
  final?: boolean;
  textLength?: number;
  expectedReply?: boolean;
  context?: Array<{ role: string; text: string; message_id?: string; created_at?: number }>;
}
interface TurnDeliveryObservation {
  callId?: string; chatId?: string; turnId?: string; phase: string; reason?: string; observedAt: number;
  failure?: {errorClass?:string;errorCode?:string;httpStatus?:number;module?:string;line?:number};
}
interface CallEvidence {
  turnDelivery?: TurnDeliveryObservation[];
  sent: SocketObservation[];
  received: SocketObservation[];
  tracks: MediaStreamTrack[];
  decryptChatContent?: (value: string, rawKey: ArrayBuffer) => Promise<string>;
  boundCaptureTracks?:MediaStreamTrack[];
  readyHeld?: boolean;
  releaseReady?: () => void;
  mainSocket?: WebSocket;
  mainSocketId?: number;
  reconnectOnText?: boolean;
  reconnectInjected?: boolean;
  hangupOnCommittedAction?: { callId: string; socketId: number };
  committedHangupInjected?: boolean;
  committedHangupReceipt?: SocketObservation;
  heldChatLookupCount?: number;
  holdMetadataCommits?: boolean;
  heldMetadataCommits?: number;
  chatLookupDiagnostics?: {
    selectedConstructors: number;
    omittedConstructors: number;
    promises: Array<{ ordinal: number; resolutionRequests: number; rejectionRequests: number;
      matchedBoundRow: boolean; held: boolean }>;
  };
  releaseChatLookup?: () => void;
  historyDurability?: Array<{ ordinal: number; role: string; localExists: boolean; remoteExists: boolean;
    localRevision: number; remoteRevision: number; pendingOutboxCount: number;
    ciphertextMatches: boolean; plaintextMatches: boolean }>;
}

test.use({
  actionTimeout: 30_000,
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

// Failure evidence keeps bounded transport categories, never message/audio bodies.
test.afterEach(async ({page},testInfo)=>{
  if(testInfo.status===testInfo.expectedStatus)return;
  const diagnostic=await page.evaluate(()=>{
    const browser=window as unknown as {__voiceCallEvidence?:CallEvidence;__nativeVoiceInput?:NativeVoiceInputEvidence};
    const state=browser.__voiceCallEvidence;const native=browser.__nativeVoiceInput;
    const count=(frames:SocketObservation[]|undefined,type:string)=>frames?.filter(frame=>frame.type===type).length??0;
    const id=(value:unknown)=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)?value:undefined;
    const ids=(frame:SocketObservation)=>({type:frame.type,callId:id(frame.callId),chatId:id(frame.chatId),
      messageId:id(frame.messageId),userMessageId:id(frame.userMessageId),assistantMessageId:id(frame.assistantMessageId),
      taskId:id(frame.taskId),turnId:id(frame.turnId),preflightId:id(frame.preflightId),requestId:id(frame.requestId),observedAt:frame.observedAt});
    const serverCodes=new Set(['client_update_required','durable_preflight_failed','immutable_chat_key_mismatch',
      'preflight_expired','preflight_mismatch','preflight_required','recovery_key_mismatch','message_identity_mismatch',
      'team_chat_scope_mismatch','version_conflict','existing_chat_metadata_forbidden','invalid_chat_turn_admission',
      'inference_commitment_mismatch','privacy_receipt_required','privacy_receipt_invalid','privacy_context_changed',
      'inference_temporarily_paused','insufficient_credits','unauthorized','forbidden','websocket_receipt_connection_changed']);
    const status=document.querySelector('[data-testid="voice-call-status"]');
    const statusText=document.querySelector('[data-testid="voice-call-status-text"]')?.textContent;
    const transcriptFailure=statusText==='The transcript could not be saved. The call was stopped.'||
      statusText==='Das Transkript konnte nicht gespeichert werden. Der Anruf wurde beendet.';
    const callUIstatus=transcriptFailure?'transcript_save_failed':status?.getAttribute('role')==='alert'?'error':
      document.querySelector('[data-testid="voice-call-bar"]')?.getAttribute('aria-busy')==='true'?'connecting':status?'active':'inactive';
    return {observed:!!state,starts:count(state?.sent,'start'),ready:count(state?.received,'ready'),
      microphoneFrames:count(state?.sent,'mic_audio'),canonicalSends:count(state?.sent,'chat_message_added'),
      finalUserTranscripts:state?.received.filter(frame=>frame.type==='transcript'&&frame.role==='user'&&frame.final).length??0,
      errors:state?.received.filter(frame=>frame.type==='error').slice(-3).map(frame=>({code:frame.code,stage:frame.stage,path:frame.path}))??[],
      speechStatuses:state?.received.filter(frame=>frame.type==='assistant_speech_status').slice(-8).map(frame=>({kind:frame.kind,status:frame.speechStatus,language:frame.language}))??[],
      historyDurability:state?.historyDurability,callUIstatus,
      turnDelivery:state?.turnDelivery?.slice(-48)??[],
      finalTranscriptTurns:state?.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='transcript'&&frame.role==='user'&&frame.final).slice(-24).map(ids)??[],
      textInputTurns:state?.sent.filter(frame=>frame.type==='text_input').slice(-24).map(ids)??[],
      canonicalTurns:state?.sent.filter(frame=>frame.type==='chat_message_added').slice(-24).map(frame=>({...ids(frame),voiceMode:frame.voiceMode,heardBoundary:!!frame.heardBoundary}))??[],
      interruptionTargets:state?.received.filter(frame=>frame.type==='audio.interrupted').slice(-24).map(ids)??[],
      admissionEvents:[...(state?.sent??[]).map(frame=>({...frame,direction:'sent'})),
        ...(state?.received??[]).map(frame=>({...frame,direction:'received'}))]
        .filter(frame=>['chat_turn_admit','chat_turn_preflight','chat_turn_preflight_ack','chat_turn_context','chat_turn_context_ack',
          'chat_message_confirmed','error'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-48).map(frame=>({...ids(frame),direction:frame.direction,
          status:frame.taskStatus,code:frame.code?(serverCodes.has(frame.code)?frame.code:'other'):undefined})),
      taskEvents:[...(state?.sent??[]),...(state?.received??[])].filter(frame=>['cancel_ai_task','ai_task_initiated','ai_task_cancel_requested','ai_task_ended','ai_task_completed','ai_task_failed','ai_message_ready','ai_response_storage_confirmed','ai_response_storage_failed'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-24).map(frame=>({...ids(frame),status:frame.taskStatus})),
      finalAssistantEvents:state?.received.filter(frame=>frame.type==='ai_message_update'&&frame.finalChunk).slice(-24).map(frame=>({...ids(frame),final:frame.final,awaitingContinuation:frame.awaitingContinuation,
        interruptedByRevocation:frame.interruptedByRevocation,interruptedBySoftLimit:frame.interruptedBySoftLimit}))??[],
      captureRequests:native?.captureRequests??0,detectorReady:native?.detectorReady??0,
      workersCreated:native?.workersCreated??0,workersTerminated:native?.workersTerminated??0};
  }).catch(()=>({captureFailed:true}));
  await testInfo.attach('voice-call-transport-state',{body:JSON.stringify(diagnostic),contentType:'application/json'});
});

async function observeRealTransport(page: Page, deferReady = false): Promise<void> {
  await page.addInitScript(({deferReady}) => {
    let holdReady=deferReady;
    let audioBatch=0;
    let nextAudioBatch=0;
    const evidence={sent:[],received:[],tracks:[]} as CallEvidence;
    evidence.decryptChatContent = async (value, rawKey) => {
      const encrypted = Uint8Array.from(atob(value), char => char.charCodeAt(0));
      // Chat ciphertext uses OM + FNV-1a key fingerprint + IV; legacy starts at IV.
      const header = encrypted[0] === 0x4f && encrypted[1] === 0x4d ? 6 : 0;
      if (header) {
        let fingerprint = 0x811c9dc5;
        for (const byte of new Uint8Array(rawKey)) fingerprint = Math.imul(fingerprint ^ byte, 0x01000193);
        const expected = [fingerprint >>> 24 & 255, fingerprint >>> 16 & 255, fingerprint >>> 8 & 255, fingerprint & 255];
        if (expected.some((byte, index) => byte !== encrypted[index + 2])) throw new Error('Chat ciphertext key fingerprint mismatch');
      }
      const key = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['decrypt']);
      return new TextDecoder().decode(await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: encrypted.slice(header, header + 12) }, key, encrypted.slice(header + 12)));
    };
    Object.assign(window,{__voiceCallEvidence:evidence});
    const phases=new Set(['queued','started','validating','sender_loading','chat_loading','message_saving','chat_refreshing',
      'chat_updating','canonical_sending','receipt_reading','accepted','refused','failed']);
    const reasons=new Set(['invalid_turn','scope_changed','disconnected','personal_chat_unavailable','message_row_unavailable',
      'message_failed','message_waiting_for_connection','predecessor_not_saved','message_identity_conflict','turn_already_settled',
      'immutable_chat_key_mismatch','message_identity_mismatch','preflight_mismatch','recovery_key_mismatch','version_conflict',
      'inference_commitment_mismatch','client_update_required','operation_failed']);
    const errorClasses=new Set(['Error','TypeError','RangeError','SyntaxError','ReferenceError','DOMException','AbortError',
      'OperationError','InvalidStateError','InvalidAccessError','DataError','QuotaExceededError','ConstraintError',
      'TransactionInactiveError','NotFoundError','DataCloneError','NetworkError','PreflightRejectionError','PendingAdmissionCompatibilityError']);
    const errorCodes=new Set(['immutable_chat_key_mismatch','message_identity_mismatch','preflight_mismatch','recovery_key_mismatch',
      'version_conflict','inference_commitment_mismatch','client_update_required','durable_preflight_failed','preflight_expired',
      'preflight_required','team_chat_scope_mismatch','existing_chat_metadata_forbidden','websocket_receipt_connection_changed']);
    for(const code of errorCodes)reasons.add(code);
    const httpStatuses=new Set([400,401,403,404,408,409,413,422,429,500,502,503,504]);
    const errorModules=new Set(['services/voiceCallTurns.ts','services/chatSyncService.ts','services/sendersChatMessages.ts',
      'services/preparedPrivacyForSend.ts','services/preflightAcknowledgement.ts','services/serverCapabilityGate.ts',
      'services/outboundMessageSends.ts','services/personalChatTurnBarrier.ts','services/fastAdmissionJournal.ts',
      'services/fastAdmissionPhaseJournal.ts','services/savedPersonalAdmissionHistory.ts','services/websocketService.ts',
      'services/chatKeyWriteGuard.ts','services/chatKeyConsistency.ts','services/encryption/ChatKeyManager.ts','services/db.ts',
      'services/db/messageOperations.ts','services/db/chatCrudOperations.ts','services/db/messageJournalOperations.ts',
      'utils/chatCompletionRecovery.ts']);
    const safeId=(value:unknown)=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)?value:undefined;
    const taskStatuses=new Set(['queued','initiated','processing','running','streaming','completed','failed','timed_out',
      'cancelled','revocation_sent','revocation_failed','already_completed','already_cancelled','not_found','synced','stored',
      'accepted','rejected','ready','ok','success','error']);
    window.addEventListener('voiceCallTurnDelivery',event=>{
      const detail=(event as CustomEvent).detail;
      if(!detail||!phases.has(detail.phase))return;
      const parts=typeof detail.reason==='string'?detail.reason.split(':'):[];
      const reason=parts.length===1&&reasons.has(parts[0])?parts[0]:parts.length===2&&phases.has(parts[0])&&reasons.has(parts[1])?parts.join(':'):undefined;
      const failure: NonNullable<TurnDeliveryObservation['failure']>={};
      if(detail.phase==='failed'&&detail.failure&&typeof detail.failure==='object') {
        const value=detail.failure;
        if(errorClasses.has(value.errorClass))failure.errorClass=value.errorClass;
        if(errorCodes.has(value.errorCode))failure.errorCode=value.errorCode;
        if(httpStatuses.has(value.httpStatus))failure.httpStatus=value.httpStatus;
        if(errorModules.has(value.module)) {
          failure.module=value.module;
          if(Number.isInteger(value.line)&&value.line>=1&&value.line<=999999)failure.line=value.line;
        }
      }
      const events=evidence.turnDelivery??(evidence.turnDelivery=[]);
      events.push({callId:safeId(detail.callId),chatId:safeId(detail.chatId),turnId:safeId(detail.turnId),
        phase:detail.phase,reason,observedAt:performance.now(),...(Object.keys(failure).length?{failure}:{})});
      if(events.length>48)events.splice(0,events.length-48);
    });
    const NativeWebSocket=window.WebSocket;
    let nextSocketId=0;
    window.WebSocket=new Proxy(NativeWebSocket,{construct(Target,args){
      const socket:WebSocket=Reflect.construct(Target,args);
      const socketId=++nextSocketId;
      const path=new URL(String(args[0]),location.href).pathname;
      if(path==='/v1/ws') { evidence.mainSocket=socket; evidence.mainSocketId=socketId; }
      const observe=(data:unknown,sent:boolean)=>{
        if(typeof data!=='string')return;
        let event;try{event=JSON.parse(data);}catch{return;}
        const payload=event.payload??event;
        const message=payload.message??payload;
        if(!sent&&path==='/v1/voice-call'&&event.type==='ready'&&holdReady)return;
        if(sent&&event.type==='mic_audio'&&!audioBatch){audioBatch=++nextAudioBatch;queueMicrotask(()=>{audioBatch=0;});}
        // Keep identity, bounded counts and booleans only. No PCM, message text,
        // tokens, encryption keys, presigned URLs or decrypted embeds leave here.
        const frame:SocketObservation={path,socketId,type:event.type,observedAt:performance.now(),
          messageId:payload.message_id??message.message_id,chatId:payload.chat_id,callId:payload.call_id,
          turnId:safeId(payload.turn_id),preflightId:safeId(payload.preflight_id),requestId:safeId(payload.request_id),
          role:message.role,assistantMessageId:payload.assistant_message_id,
          userMessageId:payload.user_message_id,taskId:payload.task_id??payload.assistant_task_id,
          taskStatus:taskStatuses.has(payload.status)?payload.status:undefined,
          ...(event.type==='start'?{startupAllowanceMs:payload.startup_audio_allowance_ms}:{}),
          ...(event.type==='error'?{code:typeof payload.code==='string'&&/^[a-z_]{1,64}$/.test(payload.code)?payload.code:'unknown',stage:typeof payload.stage==='string'&&/^[a-z_]{1,64}$/.test(payload.stage)?payload.stage:'unknown'}:{}),
          ...(event.type==='mic_audio'?{audioSamples:atob(payload.data).length/2,audioBatch,audioNonzero:/[^\0]/.test(atob(payload.data))}:{}),
          ...(['chat_message_added','chat_system_message_added','call_message_completed'].includes(event.type)?{
            ciphertextLength:typeof message.encrypted_content==='string'?message.encrypted_content.length:0,
            plaintext:'content' in message||'text' in message,voiceMode:message.voice_mode===true,
            autoSpeak:message.auto_speak_response===true,forcedModel:!!(message.model||message.provider||message.model_id),
            ...(message.voice_heard_boundary?{heardBoundary:message.voice_heard_boundary}:{})}:{}),
          ...(event.type==='billing_activity'?{inputListening:payload.input_listening,processing:payload.processing}:{}),
          ...(event.type==='usage'?{creditsCharged:payload.credits_charged}:{}),
          ...(event.type==='transcript'?{final:payload.final===true,createdAt:payload.created_at}:{}),
          ...(event.type==='ai_message_update'?{userMessageId:payload.user_message_id,
            final:payload.is_final_chunk===true&&!payload.awaiting_async_skill_continuation,
            finalChunk:payload.is_final_chunk===true,awaitingContinuation:payload.awaiting_async_skill_continuation===true,
            interruptedByRevocation:payload.interrupted_by_revocation===true,interruptedBySoftLimit:payload.interrupted_by_soft_limit===true}:{}),
          ...(event.type==='assistant_state'?{speaking:payload.speaking,language:payload.language}:{}),
          ...(event.type==='assistant_speech_status'?{kind:payload.kind,speechStatus:payload.status,language:payload.language,segmentId:payload.segment_id}:{}),
        };
        (sent?evidence.sent:evidence.received).push(frame);
      };
      const originalSend=socket.send.bind(socket);
      socket.send=data=>{observe(data,true);originalSend(data);};
      socket.addEventListener('message',event=>{
        if(typeof event.data!=='string')return;
        try{if(path==='/v1/voice-call'&&JSON.parse(event.data).type==='ready'&&holdReady){
          event.stopImmediatePropagation();evidence.readyHeld=true;evidence.releaseReady=()=>{holdReady=false;evidence.readyHeld=false;socket.dispatchEvent(new MessageEvent('message',{data:event.data}));};return;
        }}catch{return;}
        observe(event.data,false);
      });
      return socket;
    }});
    const capture=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia=async constraints=>{const stream=await capture(constraints);evidence.tracks.push(...stream.getTracks());return stream;};
  },{deferReady});
}

async function evidence(page: Page): Promise<Omit<CallEvidence, 'tracks'>> {
  return page.evaluate(() => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    return { sent: state.sent, received: state.received };
  });
}

/** Wait for this ordinary turn's completed stream, including any app invocation. */
async function waitForCanonicalAssistant(page: Page, userMessageId: string): Promise<void> {
  await expect.poll(async () => (await evidence(page)).received.some(frame =>
    frame.type === 'ai_message_update' && frame.userMessageId === userMessageId && frame.final),
  { timeout: 45_000, message: 'The admitted ordinary turn must finish its canonical assistant response' }).toBe(true);
}

/** Resolve the STT-admitted identity before waiting on its ordinary reply. */
async function waitForSpokenAssistant(page: Page): Promise<void> {
  let userMessageId: string | undefined;
  await expect.poll(async () => {
    userMessageId=(await evidence(page)).received.find(frame => frame.path === '/v1/voice-call' &&
      frame.type === 'transcript' && frame.role === 'user' && frame.final)?.messageId;
    return !!userMessageId;
  }, { timeout: 30_000, message: 'Real speech must produce a final admitted user turn' }).toBe(true);
  await waitForCanonicalAssistant(page,userMessageId!);
}

interface NativeVoiceInputEvidence {
  nativeTracks: MediaStreamTrack[];
  outputTracks: MediaStreamTrack[];
  contexts: AudioContext[];
  localToneStarts: number;
  samples: number;
  sampleRate: number;
  capturedSpeech: boolean;
  capturedQuietSamples: number;
  captureRequests: number;
  speechReady: boolean;
  playing: boolean;
  workersCreated: number;
  workersTerminated: number;
  detectorReady: number;
  readyUploadedSamples: number;
  error: boolean;
  play: (short: boolean) => void;
}

/** Feed the public WAV through a genuine microphone/WebAudio stream at native cadence. */
async function installNativeVoiceInput(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state: NativeVoiceInputEvidence = {
      nativeTracks: [], outputTracks: [], contexts: [], localToneStarts: 0, samples: 0, sampleRate: 0,
      capturedSpeech: false, capturedQuietSamples: 0,
      captureRequests: 0, speechReady: false, playing: false, workersCreated: 0,
      workersTerminated: 0, detectorReady: 0, readyUploadedSamples: 0, error: false, play: () => {},
    };
    Object.assign(window, { __nativeVoiceInput: state });
    const NativeAudioContext = window.AudioContext;
    window.AudioContext = new Proxy(NativeAudioContext, {
      construct(Target, args) {
        const context: AudioContext = Reflect.construct(Target, args);
        state.contexts.push(context);
        // Observe genuine local WebAudio cue output without replacing its sound
        // implementation or exposing product-only diagnostic hooks.
        const createOscillator = context.createOscillator.bind(context);
        context.createOscillator = () => {
          const oscillator = createOscillator();
          const start = oscillator.start.bind(oscillator);
          oscillator.start = (...args: Parameters<OscillatorNode['start']>) => {
            start(...args);
            state.localToneStarts++;
          };
          return oscillator;
        };
        // Observe the production capture processor, not just the fixture source's
        // onended event: its pending input quanta must reach the startup FIFO.
        const createProcessor = context.createScriptProcessor.bind(context);
        context.createScriptProcessor = (...args: Parameters<AudioContext['createScriptProcessor']>) => {
          const processor = createProcessor(...args);
          processor.addEventListener('audioprocess', ({ inputBuffer }) => {
            const samples = inputBuffer.getChannelData(0);
            let lastSpeech = -1;
            for (let index = 0; index < samples.length; index++) {
              if (Math.abs(samples[index]) >= 1 / 32768) lastSpeech = index;
            }
            if (lastSpeech >= 0) {
              state.capturedSpeech = true;
              state.capturedQuietSamples = samples.length - lastSpeech - 1;
            } else if (state.capturedSpeech) state.capturedQuietSamples += samples.length;
          });
          return processor;
        };
        return context;
      },
    });
    const NativeWorker = window.Worker;
    window.Worker = new Proxy(NativeWorker, {
      construct(Target, args) {
        const worker: Worker = Reflect.construct(Target, args);
        if (String(args[0]).includes('voiceCallDetector.worker')) {
          state.workersCreated++;
          let stopped = false;
          const terminate = worker.terminate.bind(worker);
          worker.terminate = () => { if (!stopped) { stopped = true; state.workersTerminated++; } terminate(); };
          worker.addEventListener('message', ({ data }) => {
            if (data?.type !== 'ready') return;
            state.detectorReady++;
            state.readyUploadedSamples = (window as unknown as { __voiceCallEvidence?: CallEvidence })
              .__voiceCallEvidence?.sent.reduce((total, frame) => total + (frame.audioSamples ?? 0), 0) ?? 0;
          });
        }
        return worker;
      },
    });
    const nativeCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      // Camera capture remains the genuine video-only device stream.
      if (!constraints?.audio) return nativeCapture(constraints);
      const microphone = await nativeCapture(constraints);
      state.captureRequests++;
      state.nativeTracks.push(...microphone.getTracks());
      // Keep the fixture meter separate from production capture observations.
      const audio = new NativeAudioContext();
      state.contexts.push(audio);
      await audio.resume();
      state.sampleRate = audio.sampleRate;
      const output = audio.createMediaStreamDestination();
      const source = audio.createMediaStreamSource(microphone);
      const quiet = audio.createGain();
      quiet.gain.value = 0;
      source.connect(quiet);
      quiet.connect(output);
      // Fake Chromium microphones may emit tones. Keep actual native permission,
      // capture and tracks, while the public speech fixture is the audible input.
      const meterSource = audio.createMediaStreamSource(output.stream);
      const meter = audio.createScriptProcessor(2048, 1, 1);
      const silentOutput = audio.createGain();
      silentOutput.gain.value = 0;
      meterSource.connect(meter);
      meter.connect(silentOutput);
      silentOutput.connect(audio.destination);
      meter.onaudioprocess = ({ inputBuffer }) => { state.samples += inputBuffer.length; };
      let speech: AudioBuffer | null = null;
      let player: AudioBufferSourceNode | null = null;
      let stopped = false;
      state.play = (short) => {
        if (!speech || stopped || state.playing) throw new Error('Public voice fixture is not ready');
        player = audio.createBufferSource();
        player.buffer = speech;
        player.connect(output);
        state.playing = true;
        player.onended = () => { player?.disconnect(); player = null; state.playing = false; };
        player.start(0, short ? 0.75 : 0, short ? 0.35 : speech.duration);
      };
      void fetch('/store-examples/transcription-demo-voice-note.wav')
        .then((response) => { if (!response.ok) throw new Error('Fixture unavailable'); return response.arrayBuffer(); })
        .then((bytes) => audio.decodeAudioData(bytes))
        .then((buffer) => { if (!stopped) { speech = buffer; state.speechReady = true; } })
        .catch(() => { if (!stopped) state.error = true; });
      const cleanup = () => {
        if (stopped) return;
        stopped = true;
        meter.onaudioprocess = null;
        meter.disconnect(); meterSource.disconnect(); silentOutput.disconnect();
        source.disconnect(); quiet.disconnect();
        if (player) { player.onended = null; player.stop(); player.disconnect(); player = null; }
        state.playing = false;
        state.speechReady = false;
        microphone.getTracks().forEach((track) => track.stop());
        void audio.close();
      };
      for (const track of output.stream.getTracks()) {
        const stop = track.stop.bind(track);
        track.stop = () => { stop(); cleanup(); };
      }
      state.outputTracks.push(...output.stream.getTracks());
      return output.stream;
    };
  });
}

async function nativeVoiceInput(page: Page) {
  return page.evaluate(() => {
    const state = (window as unknown as { __nativeVoiceInput: NativeVoiceInputEvidence }).__nativeVoiceInput;
    return { samples: state.samples, sampleRate: state.sampleRate, captureRequests: state.captureRequests,
      capturedSpeech: state.capturedSpeech, capturedQuietSamples: state.capturedQuietSamples,
      speechReady: state.speechReady, playing: state.playing, error: state.error,
      contexts: state.contexts.map((context) => context.state), localToneStarts: state.localToneStarts,
      nativeTracks: state.nativeTracks.map((track) => track.readyState),
      outputTracks: state.outputTracks.map((track) => track.readyState),
      workersCreated: state.workersCreated, workersTerminated: state.workersTerminated, detectorReady: state.detectorReady, readyUploadedSamples: state.readyUploadedSamples };
  });
}

async function playNativeVoiceFixture(page: Page, short = true): Promise<void> {
  await expect.poll(async () => (await nativeVoiceInput(page)).speechReady).toBe(true);
  await page.evaluate((short) => (window as unknown as { __nativeVoiceInput: NativeVoiceInputEvidence }).__nativeVoiceInput.play(short), short);
}

const voiceFrames = (transport: Awaited<ReturnType<typeof evidence>>, type: string) =>
  transport.sent.filter((frame) => frame.path === '/v1/voice-call' && frame.type === type);

async function assertVoiceInputCleanup(page: Page): Promise<void> {
  await expect.poll(async () => {
    const state = await nativeVoiceInput(page);
    return state.nativeTracks.length > 0 && state.nativeTracks.every((track) => track === 'ended') &&
      state.outputTracks.every((track) => track === 'ended') && state.contexts.every((context) => context === 'closed') &&
      state.workersCreated === state.workersTerminated;
  }).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
    .__voiceCallEvidence.tracks.every((track) => track.readyState === 'ended'))).toBe(true);
  expect((await nativeVoiceInput(page)).error).toBe(false);
}

async function assertSlimCallSurface(page: Page): Promise<void> {
  await expect(page.getByTestId('voice-call-bar')).toBeVisible();
  await expect(page.getByTestId('voice-call-pricing')).toHaveCount(0);
  await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
  await expect(page.getByTestId('voice-call-usage')).toHaveCount(0);
  await expect(page.getByTestId('voice-call-status')).toHaveCSS('clip','rect(0px, 0px, 0px, 0px)');
  await expect(page.getByTestId('voice-call-waveform').locator('span')).toHaveCount(48);
}

async function activeCallSeconds(page: Page): Promise<number> {
  return (await page.getByTestId('voice-call-timer').textContent() ?? '').split(':').reduce((seconds,value)=>seconds*60+Number(value),0);
}

async function assertActivityCounter(page: Page, active: boolean): Promise<void> {
  await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('data-activity-active',String(active));
  await expect(page.getByTestId('voice-call-timer')).toHaveCSS('opacity',active?'1':'0.48');
}

async function chooseAppsHome(page: Page): Promise<void> {
  const link=page.getByTestId('apps-nav-link');
  if(await link.isVisible()) await link.click();
  else await page.getByTestId('workspace-mobile-select').selectOption('/#apps');
  await expect(page.getByTestId('apps-workspace-home')).toBeVisible();
  await expect.poll(()=>new URL(page.url()).hash.split('&')[0]).toBe('#apps');
  await expect(page.getByTestId('apps-route-header').getByTestId('voice-call-pill')).toHaveAccessibleName('Return to chat');
}

/** Canonical owned ciphertext durability, including events, before any local eviction. */
async function assertCallHistoryDurable(page: Page, chatId: string, callId: string, transcriptIds: string[] = [], expectedTimes?: string[], expectedDuration?:number): Promise<void> {
  const apiUrl=process.env.PLAYWRIGHT_TEST_API_URL;
  expect(apiUrl).toBeTruthy();
  await expect.poll(()=>page.evaluate(async({apiUrl,chatId,callId,transcriptIds,expectedTimes,expectedDuration})=>{
    const eventIds=[`00000000-voice-call-${callId}-started`,`ffffffff-voice-call-${callId}-ended`];
    const ids=[...eventIds,...transcriptIds];
    const open=(name:string)=>new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(name);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    const read=<T>(db:IDBDatabase,store:string,id:string)=>new Promise<T>((resolve,reject)=>{const r=db.transaction(store,'readonly').objectStore(store).get(id);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    const db=await open('chats_db');const keys=await open('openmates_crypto');
    try {
      const local=await Promise.all(ids.map(id=>read<{encrypted_content?:string;content?:string;role:string;chat_id:string;created_at:number;
        queue_revision?:number;call_persistence_v1?:{entries:unknown[]}}|undefined>(db,'messages',id)));
      if(local.some(row=>!row?.encrypted_content||typeof row.content==='string'||row.chat_id!==chatId)) return {durable:0,decryptedEvents:0,privateRows:false,pair:false,times:false,duration:false};
      const remote=new Map<string,{message_id:string;encrypted_content:string;role:string;created_at:number;queue_revision?:number}>();
      const params=new URLSearchParams({direction:'latest',limit:'20',respect_compression_boundary:'false'});
      for(let window=0;window<8;window++) {
        const response=await fetch(`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?${params}`,{credentials:'include'});
        if(!response.ok) return {durable:0,decryptedEvents:0,privateRows:true,pair:false,times:false,duration:false};
        const history=await response.json();
        for(const row of history.messages??[]) remote.set(row.message_id,row);
        if(!history.has_more_before||!history.start_cursor) break;
        params.set('direction','before');params.set('before_timestamp',String(history.start_cursor.created_at));params.set('before_message_id',history.start_cursor.message_id);
      }
      const master=await read<CryptoKey>(keys,'keys','master_key');
      const chat=await read<{encrypted_chat_key:string}>(db,'chats',chatId);
      const bytes=(value:string)=>Uint8Array.from(atob(value),char=>char.charCodeAt(0));
      const wrapped=bytes(chat.encrypted_chat_key);
      const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:wrapped.slice(0,12)},master,wrapped.slice(12));
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      state.historyDurability=await Promise.all(ids.map(async(id,ordinal)=>{
        const own=local[ordinal];const canonical=remote.get(id);
        const ciphertextMatches=!!own?.encrypted_content&&own.encrypted_content===canonical?.encrypted_content;
        let plaintextMatches=ciphertextMatches;
        if(!ciphertextMatches&&own?.encrypted_content&&canonical?.encrypted_content) {
          try { plaintextMatches=await state.decryptChatContent!(own.encrypted_content,raw)===
            await state.decryptChatContent!(canonical.encrypted_content,raw); } catch { /* Boolean only. */ }
        }
        return {ordinal,role:['user','assistant','system'].includes(own?.role??'')?own!.role:'other',
          localExists:!!own,remoteExists:!!canonical,localRevision:own?.queue_revision??0,
          remoteRevision:canonical?.queue_revision??0,pendingOutboxCount:own?.call_persistence_v1?.entries.length??0,
          ciphertextMatches,plaintextMatches};
      }));
      // Ordinary optimistic and canonical rows use independent AES-GCM IVs.
      // Durability requires the same owned row identity and decrypted content,
      // never coincidental ciphertext equality between those encryptions.
      const durable=state.historyDurability.filter((proof,index)=>proof.localExists&&proof.remoteExists&&proof.plaintextMatches&&
        local[index]!.role===remote.get(ids[index])!.role&&local[index]!.created_at===remote.get(ids[index])!.created_at).length;
      const events=[];
      let decryptedEvents=0;
      // Decrypt only inside the browser; diagnostics return counts/booleans.
      for(const row of remote.values()) {
        if(row.role!=='system') continue;
        let event;
        try { event=JSON.parse(await state.decryptChatContent!(row.encrypted_content,raw)); }
        catch { continue; }
        if(eventIds.includes(row.message_id)) decryptedEvents++;
        if(event?.type==='voice_call'&&event.call_id===callId) events.push({event,row});
      }
      const start=events.filter(item=>item.event.action==='started');const end=events.filter(item=>item.event.action==='ended');
      const pair=start.length===1&&end.length===1&&start[0].row.message_id===eventIds[0]&&end[0].row.message_id===eventIds[1]&&
        Number.isSafeInteger(start[0].event.created_at)&&start[0].event.created_at>0&&start[0].event.created_at<=end[0].event.created_at&&
        start[0].event.created_at===start[0].row.created_at&&end[0].event.created_at===end[0].row.created_at&&
        Number.isSafeInteger(end[0].event.active_elapsed_seconds)&&end[0].event.active_elapsed_seconds>=0;
      const times=pair&&(!expectedTimes||[start[0],end[0]].every((item,index)=>new Date(item.event.created_at*1000).toISOString()===expectedTimes[index]));
      return {durable,decryptedEvents,privateRows:true,pair,times,duration:pair&&(expectedDuration===undefined||end[0].event.active_elapsed_seconds===expectedDuration)};
    } finally {db.close();keys.close();}
  },{apiUrl:apiUrl!,chatId,callId,transcriptIds,expectedTimes,expectedDuration}),{timeout:45_000,intervals:[250,500,1000],message:'Owned canonical history must durably contain the encrypted call transcripts and one original-chat lifecycle pair'})
    .toEqual({durable:transcriptIds.length+2,decryptedEvents:2,privateRows:true,pair:true,times:true,duration:true});
}

async function evictOwnedCallRows(page:Page,chatId:string,callId:string,transcriptIds:string[]=[]):Promise<void> {
  await page.evaluate(async({chatId,callId,transcriptIds})=>{
    const ids=[`00000000-voice-call-${callId}-started`,`ffffffff-voice-call-${callId}-ended`,...transcriptIds];
    const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open('chats_db');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    try {
      await new Promise<void>((resolve,reject)=>{
        const tx=db.transaction('messages','readwrite');const store=tx.objectStore('messages');
        for(const id of ids) { const r=store.get(id);r.onsuccess=()=>{if(r.result?.chat_id===chatId) store.delete(id);}; }
        tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);
      });
    } finally {db.close();}
  },{chatId,callId,transcriptIds});
}

function installChatLookupHold({ boundChatId }: {
  boundChatId: string;
}): void {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    const NativePromise = window.Promise;
    let holding = true;
    const resolutions: Array<() => void> = [];
    state.heldChatLookupCount = 0;
    const diagnostics: NonNullable<CallEvidence['chatLookupDiagnostics']> = {
      selectedConstructors: 0, omittedConstructors: 0, promises: [],
    };
    state.chatLookupDiagnostics = diagnostics;
    state.releaseChatLookup = () => {
      holding = false;
      window.Promise = NativePromise;
      for (const resolve of resolutions.splice(0)) resolve();
    };
    // The reader owns an explicit completion Promise. Select only its direct
    // constructor caller; database initialization and native IDB Promises have
    // their own callers and always run, including same-chat draft reads.
    type Executor = (resolve: (value: unknown) => void, reject: (reason?: unknown) => void) => void;
    window.Promise = new Proxy(NativePromise, {
      construct(Target, args, newTarget) {
        const executor = args[0] as Executor;
        // OpenTelemetry's ZoneAwarePromise uses null/undefined executors for
        // internal resolve/then capability promises. Preserve those constructor
        // calls verbatim; only an explicit function executor can be wrapped.
        if (typeof executor !== 'function') return Reflect.construct(Target, args, newTarget);
        const frames = new Error().stack?.split('\n').slice(1) ?? [];
        // Frame0 is this construct trap; frame1 is the direct constructor caller.
        const directCaller = frames[1] ?? '';
        const selectedLookup = /^\s*at (?:[\w$]+\.)?readChatForNavigation\s*\(/.test(directCaller);
        if (!selectedLookup) return Reflect.construct(Target, args, newTarget);
        const diagnostic = selectedLookup ? {
          ordinal: ++diagnostics.selectedConstructors, resolutionRequests: 0, rejectionRequests: 0,
          matchedBoundRow: false, held: false,
        } : undefined;
        if (diagnostic) {
          if (diagnostics.promises.length < 32) diagnostics.promises.push(diagnostic);
          else diagnostics.omittedConstructors++;
        }
        let settlementRequested = false;
        return Reflect.construct(Target, [(resolve: (value: unknown) => void, reject: (reason?: unknown) => void) => {
          const resolveRequested = (value: unknown) => {
            if (diagnostic) diagnostic.resolutionRequests++;
            const chat = value && typeof value === 'object' ? value as Record<string, unknown> : null;
            const matchedBoundRow = chat?.chat_id === boundChatId && typeof chat.encrypted_chat_key === 'string' && chat.encrypted_chat_key.length > 0;
            if (diagnostic && matchedBoundRow) diagnostic.matchedBoundRow = true;
            // Delaying the native resolve must not reopen its first-settlement
            // boundary: duplicate resolves and later rejects remain ignored.
            if (settlementRequested) return;
            settlementRequested = true;
            if (holding && selectedLookup && matchedBoundRow) {
              if (diagnostic) diagnostic.held = true;
              state.heldChatLookupCount = (state.heldChatLookupCount ?? 0) + 1;
              resolutions.push(() => resolve(value));
            } else resolve(value);
          };
          const rejectRequested = (reason?: unknown) => {
            if (diagnostic) diagnostic.rejectionRequests++;
            if (settlementRequested) return;
            settlementRequested = true;
            reject(reason);
          };
          try { executor(resolveRequested, rejectRequested); }
          catch (error) { rejectRequested(error); }
        }], newTarget);
      },
    });
}

async function holdChatLookup(page: Page, chatId: string): Promise<void> {
  await page.evaluate(installChatLookupHold, { boundChatId: chatId });
}

async function expectHeldChatLookup(page: Page, lookupCaller: 'returnToVoiceCallChat' | 'handleChatNavigate'): Promise<void> {
  try {
    await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.heldChatLookupCount ?? 0), {
      message: `The canonical navigation read for ${lookupCaller} must be selected; draft and unrelated reads must remain unheld`,
    }).toBe(1);
  } finally {
    const diagnostics = await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.chatLookupDiagnostics);
    await test.info().attach('voice-navigation-lookup', {
      body: JSON.stringify({ owner: lookupCaller, ...diagnostics }), contentType: 'application/json',
    });
  }
}

async function expectHeaderPointerAccess(page: Page): Promise<void> {
  const profile = await page.getByTestId('profile-picture').boundingBox();
  const github = await page.getByTestId('header-github-link').boundingBox();
  expect(profile, 'The normal Settings profile hit area must be present').not.toBeNull();
  expect(github, 'The adjacent fixed GitHub hit area must be present').not.toBeNull();
  const geometry = [];
  const controls=(await page.getByTestId('voice-call-bar').count()) ? ['voice-call-mute','voice-call-hangup'] : ['voice-call-start','chat-close-button'];
  for (const testId of controls) {
    const button = page.locator(`[data-testid="${testId}"]:visible`);
    await expect(button).toBeVisible();
    const box = await button.boundingBox();
    expect(box).not.toBeNull();
    geometry.push({ testId, ...box! });
  }
  // Capture only public control geometry before assertions, including failures.
  await test.info().attach('voice-mobile-header-hit-areas', {
    body: JSON.stringify({ profile, github, controls: geometry }), contentType: 'application/json',
  });
  for (const box of geometry) {
    const { testId } = box;
    const button = page.locator(`[data-testid="${testId}"]:visible`);
    // Header controls may share an x-column while sitting above the chat row.
    // Reject actual rectangle intersection, then prove native pointer access.
    for (const fixed of [profile!, github!]) {
      const intersects = box.x < fixed.x + fixed.width && box.x + box.width > fixed.x &&
        box.y < fixed.y + fixed.height && box.y + box.height > fixed.y;
      expect(intersects, `${testId} must not intersect a fixed Settings/header target`).toBe(false);
    }
    await expect.poll(() => button.evaluate(element => {
      const rect = element.getBoundingClientRect();
      // Keep corner probes inside circular controls (0.3² + 0.3² < 0.5²).
      return [0.2, 0.5, 0.8].every(x => [0.2, 0.5, 0.8].every(y => {
        const target = document.elementFromPoint(rect.x + rect.width * x, rect.y + rect.height * y);
        return target === element || (target !== null && element.contains(target));
      }));
    }), { message: `${testId} must receive native pointer events beside Settings` }).toBe(true);
  }
}


/** Persist fictional encrypted history through the account's real first-party transport. */
interface CameraCallObservation {
  type: string; observedAt: number; callId?: string; frameId?: string; userMessageId?: string;
  assistantMessageId?: string; embedId?: string; embedType?: string; status?: string;
  appId?: string; skillId?: string; inputEmbedIds?: string[]; model?: string; resolution?: string;
}
interface CameraCallEvidence {
  sent: CameraCallObservation[]; received: CameraCallObservation[];
  wire: Map<string, Promise<{ hash: string; bytes: number; width: number; height: number }>>;
  sources: Map<string, Promise<string>>;
  uploads: Array<{ filename: string; hash: Promise<string>; embedId?: string; savedHash?: string; clean?: boolean }>;
  facing: string[]; beforeFlip?: MediaStreamTrack[];
  openedSource?: { embedId: string; s3Files: Record<string, { s3_key: string; encryption?: string; aes_nonce?: string }>;
    aesKey: string; aesNonce: string };
}

/** Observe genuine camera, upload and encrypted embed traffic without replacing a response. */
async function observeCameraCall(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state: CameraCallEvidence = { sent: [], received: [], wire: new Map(), sources: new Map(), uploads: [], facing: [] };
    Object.assign(window, { __voiceCameraEvidence: state });
    const digest = async (bytes: ArrayBuffer) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
      .map(value => value.toString(16).padStart(2, '0')).join('');
    const decoded = (data: string) => Uint8Array.from(atob(data), value => value.charCodeAt(0));
    const NativeSocket = window.WebSocket;
    window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
      const socket: WebSocket = Reflect.construct(Target, args);
      const path = new URL(String(args[0]), location.href).pathname;
      const originalSend = socket.send.bind(socket);
      socket.send = (data) => {
        if (path === '/v1/voice-call' && typeof data === 'string') {
          const event = JSON.parse(data);
          if (['camera_state', 'camera_frame', 'source_frame_saved', 'source_frame_failed'].includes(event.type)) {
            state.sent.push({ type: event.type, observedAt: performance.now(), callId: event.call_id,
              frameId: event.frame_id, userMessageId: event.user_message_id, embedId: event.embed_reference?.embed_id });
            if (event.type === 'camera_frame') {
              const bytes = decoded(event.data);
              state.wire.set(event.frame_id, (async () => {
                const image = await createImageBitmap(new Blob([bytes], { type: 'image/jpeg' }));
                try { return { hash: await digest(bytes.buffer), bytes: bytes.byteLength, width: image.width, height: image.height }; }
                finally { image.close(); }
              })());
            }
          }
        }
        originalSend(data);
      };
      socket.addEventListener('message', ({ data }) => {
        if (typeof data !== 'string') return;
        const event = JSON.parse(data);
        const payload = event.payload ?? event;
        if (event.type === 'voice_source_frame') {
          state.sources.set(`${event.user_message_id}:${event.frame_id}`, digest(decoded(event.data).buffer));
        }
        if (!['voice_source_frame', 'voice_embed', 'send_embed_data', 'camera_error'].includes(event.type)) return;
        const content = typeof payload.content === 'string' ? payload.content : '';
        const scalar = (name: string) => content.match(new RegExp(`^${name}:\\s*(.+)$`, 'm'))?.[1]?.replace(/^"|"$/g, '');
        const inputs = content.match(/^input_embed_ids(?:\[\d+\])?:\s*(.*)$/m)?.[1] ?? '';
        state.received.push({ type: event.type, observedAt: performance.now(), callId: event.call_id,
          frameId: event.frame_id, userMessageId: event.user_message_id, assistantMessageId: event.assistant_message_id ?? payload.message_id,
          embedId: payload.embed_id, embedType: payload.type, status: payload.status,
          appId: scalar('app_id'), skillId: scalar('skill_id'), inputEmbedIds: inputs.match(/[0-9a-f]{8}-[0-9a-f-]{27}/gi) ?? [],
          model: scalar('model'), resolution: scalar('resolution') });
      });
      return socket;
    } });
    const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      if (constraints?.video) {
        const video = constraints.video;
        const mode = typeof video === 'object' ? video.facingMode : undefined;
        state.facing.push(typeof mode === 'object' && 'ideal' in mode ? String(mode.ideal) : String(mode ?? 'default'));
      }
      return capture(constraints);
    };
    // XHR is the ordinary upload service's transport. Hash only inside the browser;
    // neither image bytes nor response AES keys enter Playwright diagnostics.
    const urls = new WeakMap<XMLHttpRequest, string>();
    XMLHttpRequest.prototype.open = new Proxy(XMLHttpRequest.prototype.open, { apply(Target, xhr, args) {
      urls.set(xhr, String(args[1]));
      return Reflect.apply(Target, xhr, args);
    } });
    XMLHttpRequest.prototype.send = new Proxy(XMLHttpRequest.prototype.send, { apply(Target, xhr, args) {
      const body = args[0];
      const file = body instanceof FormData ? body.get('file') : null;
      if (new URL(urls.get(xhr) ?? '/', location.href).pathname === '/v1/upload/file' && file instanceof File && file.name.startsWith('call-source-')) {
        const upload: CameraCallEvidence['uploads'][number] = { filename: file.name, hash: file.arrayBuffer().then(digest) };
        state.uploads.push(upload);
        xhr.addEventListener('load', () => {
          if (xhr.status < 200 || xhr.status >= 300) return;
          const response = JSON.parse(xhr.responseText);
          upload.embedId = response.embed_id; upload.savedHash = response.content_hash; upload.clean = response.malware_scan === 'clean';
        });
      }
      return Reflect.apply(Target, xhr, args);
    } });
    document.addEventListener('imagefullscreen', (event) => {
      const detail = (event as CustomEvent).detail;
      // ImageRenderer emits media metadata from its owning nodeview; its
      // fullscreen payload does not duplicate the embed identity in the DOM.
      const target = event.target instanceof Element ? event.target : null;
      const owner = target?.closest('[data-embed-id]') ?? target?.querySelector('[data-embed-id]');
      const embedId = detail?.embedId ?? owner?.getAttribute('data-embed-id');
      if (embedId) state.openedSource = { ...detail, embedId };
    });
  });
}

async function cameraCallEvidence(page: Page) {
  return page.evaluate(() => {
    const state = (window as unknown as { __voiceCameraEvidence: CameraCallEvidence }).__voiceCameraEvidence;
    return { sent: state.sent, received: state.received, facing: state.facing };
  });
}

async function sourceFrameProof(page: Page, userMessageId: string) {
  return page.evaluate(async (userMessageId) => {
    const state = (window as unknown as { __voiceCameraEvidence: CameraCallEvidence }).__voiceCameraEvidence;
    const source = state.received.find(event => event.type === 'voice_source_frame' && event.userMessageId === userMessageId);
    const ack = state.sent.find(event => event.type === 'source_frame_saved' && event.userMessageId === userMessageId);
    if (!source?.frameId || !ack?.embedId || ack.frameId !== source.frameId) return null;
    const wire = await state.wire.get(source.frameId);
    const chosen = await state.sources.get(`${userMessageId}:${source.frameId}`);
    const upload = state.uploads.find(upload => upload.filename === `call-source-${source.frameId}.jpg` && upload.embedId === ack.embedId);
    return wire && upload ? { frameId: source.frameId, embedId: ack.embedId, hash: wire.hash,
      exact: wire.hash === chosen && chosen === await upload.hash && upload.savedHash === chosen,
      clean: upload.clean, bounded: wire.bytes <= 256 * 1024 && wire.width <= 1280 && wire.height <= 720 } : null;
  }, userMessageId);
}

async function assertEncryptedSourceAttachment(page: Page, chatId: string, userMessageId: string, sourceId: string, hash: string): Promise<void> {
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL!;
  await expect.poll(() => page.evaluate(async ({ chatId, userMessageId, sourceId, hash, apiUrl }) => {
    const open = (name: string) => new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open(name); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const read = <T>(db: IDBDatabase, store: string, id: string) => new Promise<T>((resolve, reject) => { const r = db.transaction(store).objectStore(store).get(id); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const db = await open('chats_db'); const keys = await open('openmates_crypto');
    try {
      const row = await read<{ encrypted_content?: string; content?: string }>(db, 'messages', userMessageId);
      if (!row?.encrypted_content || row.content !== undefined) return false;
      const chat = await read<{ encrypted_chat_key: string }>(db, 'chats', chatId);
      const master = await read<CryptoKey>(keys, 'keys', 'master_key');
      const bytes = (value: string) => Uint8Array.from(atob(value), char => char.charCodeAt(0));
      const wrapped = bytes(chat.encrypted_chat_key);
      const raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: wrapped.slice(0, 12) }, master, wrapped.slice(12));
      const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
      const text = await state.decryptChatContent!(row.encrypted_content, raw);
      const attached = [...text.matchAll(/```json\s*\n([\s\S]*?)\n```/g)].some(match => {
        const value = JSON.parse(match[1]); return value.type === 'image' && value.embed_id === sourceId;
      });
      const response = await fetch(`${apiUrl}/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(sourceId)}`, { credentials: 'include' });
      if (!response.ok || !attached) return false;
      const embed = (await response.json()).embed;
      if (!embed?.encrypted_content || 'content' in embed) return false;
      const material = await crypto.subtle.importKey('raw', raw, 'HKDF', false, ['deriveBits']);
      const derived = await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: new TextEncoder().encode('openmates-embed-key-v1'), info: new TextEncoder().encode(sourceId) }, material, 256);
      const key = await crypto.subtle.importKey('raw', derived, 'AES-GCM', false, ['decrypt']);
      const payload = bytes(embed.encrypted_content);
      const source = new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: payload.slice(0, 12) }, key, payload.slice(12)));
      return new RegExp(`^content_hash:\\s*"?${hash}"?$`, 'm').test(source);
    } finally { db.close(); keys.close(); }
  }, { chatId, userMessageId, sourceId, hash, apiUrl }), { timeout: 45_000, message: 'The user attachment and owned source metadata must be encrypted and independently decryptable' }).toBe(true);
}

async function assertOpenOriginalSource(page: Page, thumbnail: Locator, sourceId: string, expectedHash: string, testInfo: TestInfo): Promise<void> {
  await expect(thumbnail).toBeEnabled();
  await expect.poll(() => thumbnail.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  // Chat result cards expose their explicit Details action; the card body is a group.
  await clickChatTarget(thumbnail.getByTestId('result-preview-expand'), testInfo);
  await expect(page.getByTestId('image-embed-fullscreen')).toBeVisible();
  await expect.poll(() => page.getByTestId('image-embed-fullscreen').locator('img:not(.preview-placeholder)').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  // Read the original through the normal owner-authorized presigned URL. Keys,
  // ciphertext and plaintext remain within this browser evaluation.
  const originalProof = await page.evaluate(async ({ apiUrl, sourceId, expectedHash }) => {
    const detail = (window as unknown as { __voiceCameraEvidence: CameraCallEvidence }).__voiceCameraEvidence.openedSource;
    if (!detail) return { status: 'missing_source_event' };
    if (detail.embedId !== sourceId) return { status: 'wrong_source_identity', embedId: detail.embedId };
    if (!detail.s3Files?.original) return { status: 'missing_original', embedId: detail.embedId };
    const original = detail.s3Files.original;
    const signed = await fetch(`${apiUrl}/v1/embeds/presigned-url?s3_key=${encodeURIComponent(original.s3_key)}`, { credentials: 'include' });
    if (!signed.ok) return { status: 'presign_failed', httpStatus: signed.status };
    const downloaded = await fetch((await signed.json()).url);
    if (!downloaded.ok) return { status: 'download_failed', httpStatus: downloaded.status };
    const encrypted = await downloaded.arrayBuffer();
    const bytes = (value: string) => Uint8Array.from(atob(value), char => char.charCodeAt(0));
    const noncePrefixed = original.encryption === 'aes-gcm-nonce-prefixed-v1';
    const nonce = noncePrefixed ? new Uint8Array(encrypted.slice(0, 12)) : bytes(original.aes_nonce || detail.aesNonce);
    const key = await crypto.subtle.importKey('raw', bytes(detail.aesKey), 'AES-GCM', false, ['decrypt']);
    const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, key, noncePrefixed ? encrypted.slice(12) : encrypted);
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', plaintext))].map(value => value.toString(16).padStart(2, '0')).join('');
    return { status: digest === expectedHash ? 'matched' : 'hash_mismatch', embedId: detail.embedId,
      expectedHash, actualHash: digest };
  }, { apiUrl: process.env.PLAYWRIGHT_TEST_API_URL!, sourceId, expectedHash });
  expect(originalProof).toMatchObject({ status: 'matched', embedId: sourceId,
    expectedHash, actualHash: expectedHash });
  await page.getByTestId('embed-minimize').click();
  await expect(page.getByTestId('image-embed-fullscreen')).toHaveCount(0);
}

async function sendCameraCallText(page: Page, text: string): Promise<string> {
  const before = voiceFrames(await evidence(page), 'text_input').length;
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
  await editor.click(); await page.keyboard.insertText(text);
  await page.getByTestId('composer-send-button').click();
  await expect.poll(async () => voiceFrames(await evidence(page), 'text_input').length).toBe(before + 1);
  return voiceFrames(await evidence(page), 'text_input').at(-1)!.messageId!;
}

test.describe('Voice mode through ordinary chat', () => {
  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner
  test('requires a saved voice processing acknowledgement before first capture and remembers it after reload', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.setViewportSize({width:390,height:844});
    await installNativeVoiceInput(page);
    await observeRealTransport(page);
    // Observe actual browser boundaries without replacing responses or audio.
    // Only event names leave the browser; no profile payloads, PCM or keys do.
    await page.addInitScript(() => {
      const events: string[] = [];
      Object.assign(window,{__voicePrivacyEvents:events});
      const nativeFetch=window.fetch.bind(window);
      window.fetch=async(input,init)=>{
        const request=input instanceof Request ? input : null;
        const url=new URL(request?.url??String(input),location.href);
        const method=String(init?.method??request?.method??'GET').toUpperCase();
        const acknowledgement=url.pathname==='/v1/settings/voice-processing-ack';
        if(acknowledgement)events.push(method==='POST'?'ack_post':'ack_get');
        const response=await nativeFetch(input,init);
        if(acknowledgement){
          if(method==='POST'){
            const json=response.json.bind(response);
            response.json=async()=>{
              const payload=await json();
              if(response.ok&&payload.version===2&&payload.acknowledged===true&&Number.isSafeInteger(payload.acknowledged_at)&&payload.acknowledged_at>0)events.push('ack_saved');
              return payload;
            };
          }
        }
        return response;
      };
      const microphone=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia=constraints=>{events.push('microphone_requested');return microphone(constraints);};
      const NativeSocket=window.WebSocket;
      window.WebSocket=new Proxy(NativeSocket,{construct(Target,args){
        if(new URL(String(args[0]),location.href).pathname==='/v1/voice-call')events.push('voice_socket');
        return Reflect.construct(Target,args);
      }});
    });
    const events=()=>page.evaluate(()=>(window as unknown as {__voicePrivacyEvents:string[]}).__voicePrivacyEvents);
    const apiUrl=process.env.PLAYWRIGHT_TEST_API_URL;
    expect(apiUrl).toBeTruthy();
    const configure=async(action:'reset'|'fail_next_write')=>{
      const configured=await page.evaluate(async({apiUrl,action})=>{
        const response=await fetch(`${apiUrl}/v1/settings/voice-processing-ack/fixture`,{
          method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),
        });
        return {status:response.status,configured:(await response.json()).configured===true};
      },{apiUrl:apiUrl!,action});
      expect(configured).toEqual({status:200,configured:true});
    };
    const profileAcknowledgement=()=>page.evaluate(async apiUrl=>{
      const response=await fetch(`${apiUrl}/v1/settings/voice-processing-ack`,{credentials:'include'});
      const profile=await response.json();
      return {ok:response.ok,versionValid:profile.version===2,acknowledged:profile.acknowledged===true,
        timestampValid:Number.isSafeInteger(profile.acknowledged_at)&&profile.acknowledged_at>0};
    },apiUrl!);
    const expectNoCall=async()=>{
      const observed=await events();
      expect(observed.filter(event=>event==='microphone_requested'||event==='voice_socket'||event==='ack_saved')).toHaveLength(0);
      expect((await nativeVoiceInput(page)).captureRequests).toBe(0);
      expect(voiceFrames(await evidence(page),'start')).toHaveLength(0);
    };
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await configure('reset');
    expect(await profileAcknowledgement()).toEqual({ok:true,versionValid:true,acknowledged:false,timestampValid:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    const notice=page.getByTestId('notification').filter({hasText:'Before your first voice call'});
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('Mistral processes your microphone audio for transcription and assistant text for speech. Your conversation uses the normal OpenMates AI routing, skills and rich chat messages.');
    await expectNoCall();
    expect((await events()).filter(event=>event==='ack_post')).toHaveLength(0);
    await page.screenshot({path:testInfo.outputPath('voice-call-first-privacy-phone-before-cancel.png')});
    await notice.getByRole('button',{name:'Cancel',exact:true}).click();
    await expect(notice).toHaveCount(0);
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await expectNoCall();
    expect((await events()).filter(event=>event==='ack_post')).toHaveLength(0);
    await expect.poll(async()=>(await nativeVoiceInput(page)).contexts.every(state=>state==='closed')).toBe(true);
    expect(await profileAcknowledgement()).toMatchObject({acknowledged:false,timestampValid:false});

    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(notice).toBeVisible();
    await configure('fail_next_write');
    await notice.getByRole('button',{name:'Continue',exact:true}).click();
    await expect(notice).toContainText('Your acknowledgement could not be saved. Try again to start the call.');
    await expectNoCall();
    expect((await events()).filter(event=>event==='ack_post')).toHaveLength(1);
    expect(await profileAcknowledgement()).toMatchObject({acknowledged:false,timestampValid:false});
    await page.screenshot({path:testInfo.outputPath('voice-call-first-privacy-phone-save-failure.png')});
    await notice.getByRole('button',{name:'Continue',exact:true}).click();
    await expect(notice).toHaveCount(0);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await expect.poll(async()=>voiceFrames(await evidence(page),'mic_audio').length).toBeGreaterThan(0);
    const accepted=await events();
    expect(accepted.filter(event=>event==='ack_post')).toHaveLength(2);
    expect(accepted.filter(event=>event==='ack_saved')).toHaveLength(1);
    expect(accepted.filter(event=>event==='microphone_requested')).toHaveLength(1);
    expect(accepted.filter(event=>event==='voice_socket')).toHaveLength(1);
    expect(accepted.indexOf('ack_saved')).toBeLessThan(accepted.indexOf('microphone_requested'));
    expect(accepted.indexOf('ack_saved')).toBeLessThan(accepted.indexOf('voice_socket'));
    expect(await profileAcknowledgement()).toEqual({ok:true,versionValid:true,acknowledged:true,timestampValid:true});
    const firstReady=(await evidence(page)).received.find(event=>event.type==='ready'&&event.path==='/v1/voice-call');
    expect(firstReady?.callId).toBeTruthy();
    expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
    const firstChatId=voiceFrames(await evidence(page),'start')[0].chatId;
    expect(firstChatId).toBeTruthy();
    await playNativeVoiceFixture(page);
    await waitForSpokenAssistant(page);
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
    const firstTranscriptIds = await page.locator('[data-testid="message-user"],[data-testid="message-assistant"]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-message-id')!).filter(Boolean));
    expect(firstTranscriptIds).toHaveLength(2);
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await assertVoiceInputCleanup(page);
    await expect(page.getByTestId('voice-call-started')).toHaveCount(1);
    await expect(page.getByTestId('voice-call-ended')).toHaveCount(1);
    await assertCallHistoryDurable(page,firstChatId!,firstReady!.callId!,firstTranscriptIds);

    // Use the same authenticated transport/history boundary as the established
    // reload flow before launching from the phone's collapsed composer.
    await page.reload();
    await waitForChatReady(page);
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('voice-call-started')).toHaveCount(1);
    await expect(page.getByTestId('voice-call-ended')).toHaveCount(1);
    await assertCallHistoryDurable(page,firstChatId!,firstReady!.callId!,firstTranscriptIds);
    await expect(page.getByRole('button',{name:'Record audio',exact:true})).toBeEnabled();
    expect(await profileAcknowledgement()).toEqual({ok:true,versionValid:true,acknowledged:true,timestampValid:true});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now',{timeout:45_000});
    await expect(notice).toHaveCount(0);
    await expect.poll(async()=>voiceFrames(await evidence(page),'mic_audio').length).toBeGreaterThan(0);
    expect((await events()).filter(event=>event==='ack_post'||event==='ack_saved')).toHaveLength(0);
    const nextReady=(await evidence(page)).received.find(event=>event.type==='ready'&&event.path==='/v1/voice-call');
    expect(nextReady?.callId).toBeTruthy();expect(nextReady?.callId).not.toBe(firstReady!.callId);
    expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
    await page.screenshot({path:testInfo.outputPath('voice-call-first-privacy-phone-post-reload-call.png')});
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await assertVoiceInputCleanup(page);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.startup-buffer,video-call.audio.background-detection,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  test('flushes genuine pre-ready speech once in capture order with the bounded startup allowance', async ({ page }) => {
    test.setTimeout(100_000);
    await installNativeVoiceInput(page);
    await observeRealTransport(page, true);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.readyHeld),
      { timeout: 30_000 }).toBe(true);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Connecting… Wait to speak.');
    const waiting = await evidence(page);
    const start = voiceFrames(waiting, 'start')[0];
    expect(start.startupAllowanceMs).toBe(10_000);
    expect(voiceFrames(waiting, 'mic_audio')).toHaveLength(0);
    expect(waiting.received.filter((frame) => frame.type === 'ready' && frame.path === '/v1/voice-call')).toHaveLength(0);
    await playNativeVoiceFixture(page);
    await expect.poll(async () => (await nativeVoiceInput(page)).playing).toBe(false);
    await expect.poll(async () => {
      const state = await nativeVoiceInput(page);
      return state.samples / state.sampleRate;
    }).toBeGreaterThan(3);
    expect(voiceFrames(await evidence(page), 'mic_audio')).toHaveLength(0);
    await expect(page.getByTestId('voice-call-timer')).toHaveText('00:00');
    // Source playback completion does not mean its final audio quantum has
    // reached CallAudio. Require speech plus two actual quiet capture quanta.
    await expect.poll(async () => {
      const state = await nativeVoiceInput(page);
      return state.capturedSpeech && state.capturedQuietSamples >= 2 * 2048;
    }, { message: 'Pre-ready capture must contain speech followed by quiet input quanta' }).toBe(true);
    const beforeRelease = await nativeVoiceInput(page);
    await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.releaseReady!());
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await waitForSpokenAssistant(page);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    const flushed = await evidence(page);
    const audio = voiceFrames(flushed, 'mic_audio');
    const startup = audio.filter((frame) => frame.audioBatch === audio[0].audioBatch);
    const startupSamples = startup.reduce((total, frame) => total + (frame.audioSamples ?? 0), 0);
    expect(startupSamples).toBeGreaterThan(16_000 * 2);
    expect(Math.abs(startupSamples - beforeRelease.samples / beforeRelease.sampleRate * 16_000)).toBeLessThan(3200);
    const firstSpeech = startup.findIndex((frame) => frame.audioNonzero);
    const lastSpeech = startup.findLastIndex((frame) => frame.audioNonzero);
    expect(firstSpeech).toBeGreaterThan(0);
    expect(lastSpeech).toBeGreaterThanOrEqual(firstSpeech);
    expect(lastSpeech).toBeLessThan(startup.length - 1);
    expect(audio.every((frame) => frame.socketId === start.socketId)).toBe(true);
    expect(voiceFrames(flushed, 'start')).toHaveLength(1);
    expect(flushed.received.filter((frame) => frame.type === 'ready' && frame.path === '/v1/voice-call')).toHaveLength(1);
    expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await assertVoiceInputCleanup(page);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-detection,video-call.usage.provider-metering,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  test('keeps the authenticated call continuously uploading after the actual model fetch fails', async ({ page, context }) => {
    test.setTimeout(100_000);
    await installNativeVoiceInput(page);
    await observeRealTransport(page);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    let failedModel = false;
    await context.route('**/*silero_vad_v5*', async (route) => {
      if (route.request().resourceType() === 'script') { await route.continue(); return; }
      failedModel = true;
      await route.abort('failed');
    });
    const fallback = page.waitForEvent('console', { predicate: (message) => message.text().includes('Local speech detection unavailable') });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await fallback;
    expect(failedModel).toBe(true);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await playNativeVoiceFixture(page);
    await waitForSpokenAssistant(page);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    const started = await evidence(page);
    const baseline = await nativeVoiceInput(page);
    const fallbackSeconds=await activeCallSeconds(page);
    await expect.poll(async () => {
      const current = await nativeVoiceInput(page);
      return (current.samples - baseline.samples) / current.sampleRate;
    }, { timeout: 15_000 }).toBeGreaterThan(6);
    const continuous = await evidence(page);
    expect(await activeCallSeconds(page)).toBeGreaterThan(fallbackSeconds+4);
    expect(voiceFrames(continuous, 'mic_audio').length).toBeGreaterThan(voiceFrames(started, 'mic_audio').length + 100);
    expect(voiceFrames(continuous, 'audio_stream_end')).toHaveLength(0);
    expect(voiceFrames(continuous, 'start')).toHaveLength(1);
    expect(continuous.received.filter((frame) => frame.type === 'ready' && frame.path === '/v1/voice-call')).toHaveLength(1);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await assertActivityCounter(page,true);
    await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
    expect((await nativeVoiceInput(page)).detectorReady).toBe(0);
    expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await assertVoiceInputCleanup(page);
  });


  // contract-test: direct surface=gui.web assertions=video-call.privacy,video-call.usage.provider-metering
  test('refuses an unauthenticated call before opening speech processing', async ({ page }) => {
    const apiUrl=process.env.PLAYWRIGHT_TEST_API_URL;
    expect(apiUrl).toBeTruthy();
    await page.goto('/');
    const result=await page.evaluate(url=>new Promise<{ready:boolean;closed:boolean}>(resolve=>{
      const socket=new WebSocket(`${url.replace(/^http/,'ws')}/v1/voice-call`);
      let ready=false;
      const timeout=setTimeout(()=>{socket.close();resolve({ready,closed:false});},10_000);
      socket.addEventListener('message',event=>{try{ready ||= JSON.parse(event.data).type==='ready';}catch{/* refusal contains no content */}});
      socket.addEventListener('close',()=>{clearTimeout(timeout);resolve({ready,closed:true});});
    }),apiUrl!);
    expect(result).toEqual({ready:false,closed:true});
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.automatic-idle,video-call.audio.background-detection,video-call.audio.startup-buffer,video-call.chat.activity-status,video-call.usage.provider-metering,video-call.audio.confirmation-sounds,video-call.audio.single-owner
  test('keeps capture live while detection loads, idles on genuine silence and resumes buffered speech on the same call',async({page,context})=>{
    test.setTimeout(150_000);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    let requested=false;let release!:()=>void;
    const held=new Promise<void>(resolve=>{release=resolve;});
    await context.route('**/*silero_vad_v5*',async route=>{
      if(route.request().resourceType()==='script'){await route.continue();return;}
      requested=true;await held;await route.continue();
    });
    try {
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect.poll(()=>requested).toBe(true);
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
      const initial=await evidence(page);const start=voiceFrames(initial,'start')[0];
      const baseline=voiceFrames(initial,'mic_audio').length;
      await expect.poll(async()=>voiceFrames(await evidence(page),'mic_audio').length).toBeGreaterThan(baseline+12);
      expect((await nativeVoiceInput(page)).detectorReady).toBe(0);
      await assertActivityCounter(page,true);
      const seconds=await activeCallSeconds(page);await expect.poll(()=>activeCallSeconds(page)).toBeGreaterThan(seconds);
      const connectedTones=(await nativeVoiceInput(page)).localToneStarts;expect(connectedTones).toBeGreaterThan(0);
      release();await expect.poll(async()=>(await nativeVoiceInput(page)).detectorReady,{timeout:30_000}).toBe(1);
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Speak to resume call.',{timeout:15_000});
      await expect.poll(async()=>(await evidence(page)).received.filter(frame=>frame.type==='billing_activity').at(-1)).toMatchObject({inputListening:false,processing:false});
      const idle=await evidence(page);const idleCount=voiceFrames(idle,'mic_audio').length;
      expect(voiceFrames(idle,'audio_stream_end')).toHaveLength(1);await assertActivityCounter(page,false);
      const timer=await page.getByTestId('voice-call-timer').textContent();
      const sampleCount=(await nativeVoiceInput(page)).samples;
      await expect.poll(async()=>(await nativeVoiceInput(page)).samples).toBeGreaterThan(sampleCount+24_000);
      expect(voiceFrames(await evidence(page),'mic_audio')).toHaveLength(idleCount);
      await expect(page.getByTestId('voice-call-timer')).toHaveText(timer!);
      await playNativeVoiceFixture(page);
      await expect.poll(async()=>voiceFrames(await evidence(page),'mic_audio').length).toBeGreaterThan(idleCount);
      const resumed=await evidence(page);const frames=voiceFrames(resumed,'mic_audio').slice(idleCount);
      const prefix=frames.filter(frame=>frame.audioBatch===frames[0].audioBatch);
      const samples=prefix.reduce((sum,frame)=>sum+(frame.audioSamples??0),0);
      expect(samples).toBeGreaterThanOrEqual(16*300);expect(samples).toBeLessThanOrEqual(16*500);
      expect(prefix.some(frame=>frame.audioNonzero)).toBe(true);
      await waitForSpokenAssistant(page);
      await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
      await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
      expect(voiceFrames(resumed,'start')).toHaveLength(1);
      expect(frames.every(frame=>frame.socketId===start.socketId)).toBe(true);
      expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
      await page.getByTestId('voice-call-mute').click();
      await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed','true');
      const mutedCount=voiceFrames(await evidence(page),'mic_audio').length;
      await expect.poll(async()=>(await nativeVoiceInput(page)).localToneStarts).toBeGreaterThan(connectedTones);
      await expect.poll(async()=>(await nativeVoiceInput(page)).playing).toBe(false);
      await playNativeVoiceFixture(page);await expect.poll(async()=>(await nativeVoiceInput(page)).playing).toBe(false);
      expect(voiceFrames(await evidence(page),'mic_audio')).toHaveLength(mutedCount);
      await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
    } finally {release();}
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.transcripts,video-call.chat.typed-input,video-call.chat.call-events,video-call.audio.complete-turn-admission,video-call.audio.spoken-rich-response,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing,chats.message.identity-idempotent
  test('uses one canonical turn for voice and typed input, preserves rich replies and retains its chat across navigation and reload',async({page},testInfo)=>{
    test.setTimeout(240_000);
    const imageProxyFixture = await installVoiceFixtureImageProxy(page);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await playNativeVoiceFixture(page);
    await waitForSpokenAssistant(page);
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    const first=page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH});
    await expect(first).toHaveCount(1);await expect(first.getByTestId('generated-by')).not.toContainText('Live');
    await assertSlimCallSurface(page);
    const chatId=voiceFrames(await evidence(page),'start')[0].chatId!;
    const ready=(await evidence(page)).received.find(frame=>frame.type==='ready'&&frame.path==='/v1/voice-call')!;
    expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);expect(ready.callId).toBeTruthy();
    await page.getByTestId('voice-call-mute').click();
    await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed','true');
    const typedId=await sendCameraCallText(page,PASTED_TEXT);
    await waitForCanonicalAssistant(page,typedId);
    await expect(page.getByTestId('message-user').filter({hasText:PASTED_TEXT})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:'I received your text: '+PASTED_TEXT})).toHaveCount(1);
    await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]')).toBeEmpty();
    const richId=await sendCameraCallText(page,'Show voice rich results');
    await waitForCanonicalAssistant(page,richId);
    const rich=page.getByTestId('message-assistant').filter({hasText:'Here are the images I found.'});
    await expect(rich).toHaveCount(1);await expect(rich.getByRole('heading',{name:'Results',exact:true})).toBeVisible();
    await expect(rich.getByRole('link',{name:'the source',exact:true})).toHaveAttribute('href','https://app.dev.openmates.org/store-examples/generate-1.webp');
    await expect(rich.locator('[data-testid="embed-preview"]')).not.toHaveCount(0);
    await expect.poll(() => imageProxyFixture.servedRequests, { message: 'The real chat image URL must use the exact upstream byte fixture' }).toBeGreaterThan(0);
    await expect(rich.locator('img').first()).toBeVisible();
    const protocol=await evidence(page);
    const finals=protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='transcript'&&frame.final);
    const sends=protocol.sent.filter(frame=>frame.type==='chat_message_added');
    expect(finals.filter(frame=>frame.messageId===typedId)).toHaveLength(1);
    expect(finals.filter(frame=>frame.messageId===richId)).toHaveLength(1);
    expect(sends.filter(frame=>frame.messageId===typedId)).toHaveLength(1);
    expect(sends.filter(frame=>frame.messageId===richId)).toHaveLength(1);
    expect(sends.every(frame=>frame.autoSpeak===true&&frame.forcedModel===false)).toBe(true);
    expect(protocol.sent.filter(frame=>frame.type==='call_message_completed')).toHaveLength(0);
    expect(protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='audio_chunk')).toHaveLength(0);
    expect(protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='transcript'&&frame.role==='assistant')).toHaveLength(0);
    const messageIds=await page.locator('[data-testid="message-user"],[data-testid="message-assistant"]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-message-id')!).filter(Boolean));
    expect(messageIds).toHaveLength(6);
    await page.screenshot({path:testInfo.outputPath('voice-canonical-rich-laptop.png')});
    const dismiss=page.getByTestId('input-dismiss-button');if(await dismiss.isVisible())await dismiss.click();
    await scrollChatHistoryToStart(page,testInfo);
    const close=page.locator('[data-testid="chat-close-button"]:visible,[data-testid="voice-call-close-chat"]:visible');
    await expect(close).toHaveCount(1);await close.click();await expect(page.getByTestId('voice-call-pill')).toHaveCount(1);
    await chooseAppsHome(page);await holdChatLookup(page,chatId);
    try{await page.getByTestId('apps-route-header').getByTestId('voice-call-pill').click();await expectHeldChatLookup(page,'returnToVoiceCallChat');await expect(page.getByTestId('voice-call-pill')).toHaveCount(1);}
    finally{await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseChatLookup?.());}
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();await expect.poll(()=>new URL(page.url()).hash).toBe(`#chat-id=${chatId}`);
    await page.setViewportSize({width:390,height:844});await expectHeaderPointerAccess(page);
    await page.locator('#settings-menu-toggle').click();await expect(page.getByTestId('voice-call-pill')).toBeVisible();
    await page.getByTestId('voice-call-pill').click();await expect(page.getByTestId('settings-menu')).not.toHaveClass(/visible/);
    await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed','true');
    expect(voiceFrames(await evidence(page),'start')).toHaveLength(1);expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
    await page.screenshot({path:testInfo.outputPath('voice-canonical-rich-phone.png')});
    await page.getByTestId('voice-call-hangup').click();await expect(page.getByTestId('voice-call-ended')).toHaveCount(1);
    await assertVoiceInputCleanup(page);await assertCallHistoryDurable(page,chatId,ready.callId!,messageIds);
    await evictOwnedCallRows(page,chatId,ready.callId!,messageIds);await page.reload();await waitForChatReady(page);
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:'Here are the images I found.'}).getByRole('link',{name:'the source',exact:true})).toHaveAttribute('href','https://app.dev.openmates.org/store-examples/generate-1.webp');
    await assertCallHistoryDurable(page,chatId,ready.callId!,messageIds);
    // Reload restores the compact draft composer. Focus its actual editor to
    // expose the ordinary recording control before checking audio ownership.
    await page.getByTestId('message-editor').click();
    await expect(page.getByTestId('record-audio-button')).toBeEnabled();
  });

  for(const viewport of [{name:'phone',width:390,height:844},{name:'laptop',width:1440,height:900}]) {
    // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.video.source-frame-provenance,video-call.audio.complete-turn-admission,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
    test(`attaches the exact encrypted camera source to the ordinary user request on ${viewport.name}`,async({page,context},testInfo)=>{
      test.setTimeout(180_000);await page.setViewportSize(viewport);await context.grantPermissions(['microphone','camera']);
      await installNativeVoiceInput(page);await observeRealTransport(page);await observeCameraCall(page);
      await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
      await page.locator('[data-testid="voice-call-start"]:visible').click();await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
      await page.getByTestId('voice-call-mute').click();await page.getByTestId('voice-call-video').click();
      await expect.poll(async()=>(await cameraCallEvidence(page)).sent.filter(frame=>frame.type==='camera_frame').length).toBeGreaterThan(0);
      await expect(page.getByTestId('voice-call-video')).toHaveAttribute('aria-pressed','true');
      const userId=await sendCameraCallText(page,PASTED_TEXT);
      // Canonical admission follows this turn's exact source upload/encryption.
      // Check provenance only after the ordinary response confirms that work.
      await waitForCanonicalAssistant(page,userId);
      await expect.poll(()=>sourceFrameProof(page,userId)).toMatchObject({exact:true,clean:true,bounded:true});
      const source=(await sourceFrameProof(page,userId))!;
      const chatId=voiceFrames(await evidence(page),'start')[0].chatId!;
      const user=page.locator(`[data-testid="message-user"][data-message-id="${userId}"]`);
      await expect(user).toHaveCount(1);await assertEncryptedSourceAttachment(page,chatId,userId,source.embedId,source.hash);
      const thumbnail=user.locator(`[data-testid="embed-preview"][data-embed-id="${source.embedId}"]`);
      await assertOpenOriginalSource(page,thumbnail,source.embedId,source.hash,testInfo);
      await expect(page.getByTestId('message-assistant').filter({hasText:'I received your text: '+PASTED_TEXT})).toHaveCount(1);
      await page.getByTestId('voice-call-video').click();await expect(page.getByTestId('voice-call-video')).toHaveAttribute('aria-pressed','false');
      await expect(page.getByTestId('voice-call-bar')).toBeVisible();
      expect((await evidence(page)).sent.filter(frame=>frame.type==='chat_message_added'&&frame.messageId===userId)).toHaveLength(1);
      await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
      await page.reload();await waitForChatReady(page);await expect(user).toHaveCount(1);
      await assertEncryptedSourceAttachment(page,chatId,userId,source.embedId,source.hash);
      await page.screenshot({path:testInfo.outputPath(`voice-source-${viewport.name}-reloaded.png`)});
    });
  }

  // contract-test: direct surface=gui.web assertions=video-call.audio.localized-waiting,video-call.audio.single-owner,video-call.audio.spoken-rich-response
  test('speaks one localized waiting confirmation for a slow German turn without creating a second assistant message',async({page})=>{
    test.setTimeout(150_000);await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await page.getByTestId('voice-call-mute').click();
    const id=await sendCameraCallText(page,'Bitte prüfe das gründlich');
    await expect.poll(async()=>(await evidence(page)).received.filter(frame=>frame.type==='assistant_speech_status'&&frame.kind==='waiting_confirmation'&&frame.speechStatus==='queued'&&frame.language==='de').length,{timeout:30_000}).toBe(1);
    await waitForCanonicalAssistant(page,id);
    const reply=page.getByTestId('message-assistant').filter({hasText:'Ich habe das geprüft. Hier ist das Ergebnis.'});
    await expect(reply).toHaveCount(1);await expect(page.getByTestId('message-assistant')).toHaveCount(1);
    const protocol=await evidence(page);
    expect(protocol.sent.filter(frame=>frame.type==='chat_message_added'&&frame.messageId===id)).toHaveLength(1);
    expect(protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='transcript'&&frame.role==='assistant')).toHaveLength(0);
    await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
  });


  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission,video-call.privacy
  test('carries actual heard-clause progress to the next canonical turn while retaining the complete rich answer',async({page})=>{
    await installVoiceFixtureImageProxy(page);
    test.setTimeout(180_000);
    await page.addInitScript(()=>{
      const audio=new Set<HTMLMediaElement>();
      const held={audio:null as HTMLAudioElement|null,segmentId:null as string|null,offset:0};
      Object.assign(window,{__voiceSpeechPlayback:audio,__voiceSpeechHeld:held});
      const play=HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play=function(...args:Parameters<HTMLMediaElement['play']>){
        if(!audio.has(this)) {
          audio.add(this);
          this.addEventListener('timeupdate',()=>{
            if(held.audio||!(this instanceof HTMLAudioElement)||!this.src.startsWith('blob:')||this.paused||this.ended||this.currentTime<=0)return;
            const active=document.querySelector('[data-testid="assistant-speech-waveform"]')?.getAttribute('data-segment-id');
            const evidence=(window as unknown as {__voiceCallEvidence?:CallEvidence}).__voiceCallEvidence;
            const prose=evidence?.received.some(frame=>frame.type==='assistant_speech_status'&&frame.kind==='voice_prose_clause'&&frame.speechStatus==='ready'&&frame.segmentId===active);
            if(!prose||!active)return;
            // Preserve a real heard offset and the actual clip. Native pause
            // prevents playback finishing while canonical finalization runs.
            held.audio=this;held.segmentId=active;held.offset=this.currentTime;
            this.pause();
          });
        }
        return play.apply(this,args);
      };
    });
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await page.getByTestId('voice-call-mute').click();
    const richTurnId=await sendCameraCallText(page,'Show voice rich results');
    const editor=page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await expect(editor).toBeEmpty();await editor.click();
    const followup='Please continue from the last part I heard.';
    await page.keyboard.insertText(followup);
    await page.waitForFunction(()=>{
      const held=(window as unknown as {__voiceSpeechHeld:{audio:HTMLAudioElement|null;offset:number}}).__voiceSpeechHeld;
      return !!held.audio&&held.audio.paused&&!held.audio.ended&&held.offset>0;
    },undefined,{timeout:60_000,polling:'raf'});
    // The entire produced rich answer must precede interruption. Keep the same
    // genuinely advanced prose clip available across canonical finalization.
    await waitForCanonicalAssistant(page,richTurnId);
    await page.evaluate(async()=>{
      const held=(window as unknown as {__voiceSpeechHeld:{audio:HTMLAudioElement}}).__voiceSpeechHeld;
      await held.audio.play();
    });
    await page.waitForFunction(()=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;
        __voiceSpeechHeld:{audio:HTMLAudioElement;segmentId:string;offset:number}};
      const held=browser.__voiceSpeechHeld;
      const active=document.querySelector('[data-testid="assistant-speech-waveform"]')?.getAttribute('data-segment-id');
      const voice=browser.__voiceCallEvidence.received.some(frame=>frame.type==='assistant_speech_status'&&frame.kind==='voice_prose_clause'&&frame.speechStatus==='ready'&&frame.segmentId===active);
      return voice&&active===held.segmentId&&!held.audio.paused&&!held.audio.ended&&held.audio.currentTime>held.offset;
    },undefined,{timeout:10_000,polling:'raf'});
    const before=voiceFrames(await evidence(page),'text_input').length;
    await page.getByTestId('composer-send-button').click();
    await expect.poll(async()=>voiceFrames(await evidence(page),'text_input').length).toBe(before+1);
    const nextId=voiceFrames(await evidence(page),'text_input').at(-1)!.messageId!;
    await expect.poll(async()=>(await evidence(page)).sent.find(frame=>frame.type==='chat_message_added'&&frame.messageId===nextId)?.heardBoundary,{timeout:45_000}).toBeTruthy();
    const protocol=await evidence(page);
    const boundary=protocol.sent.find(frame=>frame.type==='chat_message_added'&&frame.messageId===nextId)!.heardBoundary!;
    const prior=page.getByTestId('message-assistant').filter({hasText:'Here are the images I found.'});
    await expect(prior).toHaveCount(1);
    expect(boundary.assistant_message_id).toBe(await prior.getAttribute('data-message-id'));
    expect(boundary.completed_sequences.length>0||boundary.active_sequence!==null&&boundary.active_offset_ms>0).toBe(true);
    expect(boundary.completed_sequences.length).toBeLessThanOrEqual(256);
    expect(boundary.active_offset_ms).toBeGreaterThanOrEqual(0);expect(boundary.active_offset_ms).toBeLessThanOrEqual(3_600_000);
    expect(Object.keys(boundary).sort()).toEqual(['active_offset_ms','active_sequence','assistant_message_id','completed_sequences']);
    expect(protocol.received.some(frame=>frame.type==='audio.interrupted'&&frame.assistantMessageId===boundary.assistant_message_id)).toBe(true);
    const privateRow=await page.evaluate(async id=>{
      const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('chats_db');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
      try{return await new Promise<{encrypted:boolean;plaintext:boolean;heardMetadata:boolean}>((resolve,reject)=>{const request=db.transaction('messages','readonly').objectStore('messages').get(id);request.onsuccess=()=>resolve({encrypted:typeof request.result?.encrypted_content==='string',plaintext:typeof request.result?.content==='string',heardMetadata:'voice_heard_boundary' in (request.result??{})});request.onerror=()=>reject(request.error);});}
      finally{db.close();}
    },nextId);
    expect(privateRow).toEqual({encrypted:true,plaintext:false,heardMetadata:false});
    await expect(prior.getByRole('heading',{name:'Results',exact:true})).toBeVisible();
    await expect(prior.getByRole('link',{name:'the source',exact:true})).toHaveAttribute('href','https://app.dev.openmates.org/store-examples/generate-1.webp');
    await expect(prior.locator('[data-testid="embed-preview"]')).not.toHaveCount(0);
    await waitForCanonicalAssistant(page,nextId);
    await expect(page.getByTestId('message-assistant').filter({hasText:'I received your text: '+followup})).toHaveCount(1);
    await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
  });

});
